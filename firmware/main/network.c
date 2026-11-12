#include "tool_runtime.h"
#include "esp_wifi.h"
#include "esp_event.h"
#include "esp_netif.h"
#include "esp_http_server.h"
#include "esp_random.h"
#include "nvs.h"
#include "lwip/sockets.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static TaskHandle_t network_task_handle;
static SemaphoreHandle_t network_mutex;
static char ssid[33], password[65], api_token[65], ip_address[16];
static bool wifi_ready, connected, provisioning, connecting;
static httpd_handle_t http_server;

/** AI:读取带长度限制的HTTP正文。@param req 请求。@param maximum 最大字节数。@return JSON或NULL。 */
static cJSON *read_body(httpd_req_t *req, size_t maximum)
{
    if (req->content_len < 1 || req->content_len > maximum) return NULL;
    char *body = malloc(req->content_len + 1);
    if (!body) return NULL;
    size_t received = 0;
    while (received < req->content_len) {
        int count = httpd_req_recv(req, body + received, req->content_len - received);
        if (count <= 0) { free(body); return NULL; }
        received += count;
    }
    body[received] = '\0';
    const char *end;
    cJSON *result = cJSON_ParseWithOpts(body, &end, true);
    free(body);
    return result;
}

/** AI:HTTP序列化响应，限制与USB一致。@param req 请求。@param json 响应对象。@return HTTP错误。 */
static esp_err_t send_json(httpd_req_t *req, cJSON *json)
{
    char *body = cJSON_PrintUnformatted(json);
    if (!body) return httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR, "allocation failed");
    httpd_resp_set_type(req, "application/json; charset=utf-8");
    esp_err_t err = strlen(body) <= TOOL_FRAME_MAX ? httpd_resp_send(req, body, HTTPD_RESP_USE_STRLEN) : httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR, "response too large");
    free(body);
    return err;
}

/** AI:设备HTTP命令入口，校验配对令牌。@param req 请求。@return HTTP处理结果。 */
static esp_err_t rpc_handler(httpd_req_t *req)
{
    char authorization[80], expected[80];
    snprintf(expected, sizeof(expected), "Bearer %s", api_token);
    if (httpd_req_get_hdr_value_str(req, "Authorization", authorization, sizeof(authorization)) != ESP_OK || strcmp(expected, authorization)) return httpd_resp_send_err(req, HTTPD_401_UNAUTHORIZED, "device token required");
    cJSON *request = read_body(req, TOOL_FRAME_MAX);
    cJSON *response = tool_rpc(request, false);
    esp_err_t err = send_json(req, response);
    cJSON_Delete(response); cJSON_Delete(request);
    return err;
}

/** AI:配网操作只接受热点网段的人工连接。@param req HTTP请求。@return 是否允许配置。 */
static bool setup_allowed(httpd_req_t *req)
{
    if (!provisioning) return false;
    struct sockaddr_in peer;
    socklen_t length = sizeof(peer);
    if (getpeername(httpd_req_to_sockfd(req), (struct sockaddr *)&peer, &length)) return false;
    return (ntohl(peer.sin_addr.s_addr) & 0xffffff00U) == 0xc0a80400U;
}

/** AI:显示人工配网页面，令牌仅通过物理开启的热点提供。@param req 请求。@return HTTP结果。 */
static esp_err_t setup_page(httpd_req_t *req)
{
    if (!setup_allowed(req)) return httpd_resp_send_err(req, HTTPD_403_FORBIDDEN, "connect to configuration hotspot");
    char *page = malloc(4096);
    if (!page) return ESP_ERR_NO_MEM;
    snprintf(page, 4096,
        "<!doctype html><html lang='zh-CN'><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<title>MCU TOOL 配网</title><style>body{font:16px system-ui;max-width:560px;margin:40px auto;padding:20px;background:#edf2f5;color:#193244}input,button{box-sizing:border-box;width:100%%;padding:12px;margin:8px 0 20px;font:inherit}code{word-break:break-all}button{background:#175b8f;color:white;border:0}</style>"
        "<h1>连接工具到 Wi-Fi</h1><p>设备：%s</p><form><label>Wi-Fi 名称<input id='ssid' maxlength='32' required></label><label>Wi-Fi 密码<input id='password' type='password' maxlength='64'></label><button>保存并连接</button></form>"
        "<p id='status'>连接成功后，配置热点将关闭。连接失败时热点保留，供你检查信息。</p><h2>电脑端访问令牌</h2><p>请保存此令牌，用于电脑端的 Wi-Fi 连接。</p><code>%s</code>"
        "<script>document.querySelector('form').onsubmit=async e=>{e.preventDefault();const b=document.querySelector('button');b.disabled=true;try{const r=await fetch('/setup',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ssid:document.querySelector('#ssid').value,password:document.querySelector('#password').value})});const d=await r.json();document.querySelector('#status').textContent=d.message;}catch(e){document.querySelector('#status').textContent='请求结果未确认，请检查热点和设备状态。';}b.disabled=false;};</script></html>",
        g_device_id, api_token);
    httpd_resp_set_type(req, "text/html; charset=utf-8");
    httpd_resp_set_hdr(req, "Cache-Control", "no-store");
    esp_err_t err = httpd_resp_send(req, page, HTTPD_RESP_USE_STRLEN);
    free(page);
    return err;
}

/** AI:接收人工配置，不自动切换到其他网络。@param req 请求。@return HTTP结果。 */
static esp_err_t setup_submit(httpd_req_t *req)
{
    if (!setup_allowed(req)) return httpd_resp_send_err(req, HTTPD_403_FORBIDDEN, "connect to configuration hotspot");
    cJSON *body = read_body(req, 1024);
    const cJSON *name = cJSON_GetObjectItemCaseSensitive(body, "ssid"), *secret = cJSON_GetObjectItemCaseSensitive(body, "password");
    esp_err_t result = cJSON_IsString(name) && cJSON_IsString(secret) ? tool_network_configure(name->valuestring, secret->valuestring) : ESP_ERR_INVALID_ARG;
    cJSON_Delete(body);
    cJSON *response = cJSON_CreateObject();
    cJSON_AddBoolToObject(response, "ok", result == ESP_OK);
    cJSON_AddStringToObject(response, "message", result == ESP_OK ? "已保存，正在尝试连接。请通过USB或路由器查看设备IP。" : "保存失败，请检查名称、密码长度和设备事件。");
    if (result != ESP_OK) httpd_resp_set_status(req, "400 Bad Request");
    esp_err_t err = send_json(req, response);
    cJSON_Delete(response);
    return err;
}

/** AI:处理网络状态事件，不安排隐式重新连接。@param arg 未使用。@param base 事件组。@param id 事件。@param data 载荷。@return 无。 */
static void wifi_event(void *arg, esp_event_base_t base, int32_t id, void *data)
{
    (void)arg;
    if (base == WIFI_EVENT && id == WIFI_EVENT_STA_DISCONNECTED) {
        xSemaphoreTake(network_mutex, portMAX_DELAY);
        connected = connecting = false;
        ip_address[0] = '\0';
        xSemaphoreGive(network_mutex);
        tool_event("wifi_disconnected", "Wi-Fi已断开，业务输出保持；需要显式重新连接");
    } else if (base == IP_EVENT && id == IP_EVENT_STA_GOT_IP) {
        ip_event_got_ip_t *event = data;
        xSemaphoreTake(network_mutex, portMAX_DELAY);
        snprintf(ip_address, sizeof(ip_address), IPSTR, IP2STR(&event->ip_info.ip));
        connected = true; connecting = false;
        xSemaphoreGive(network_mutex);
        tool_event("wifi_connected", "Wi-Fi连接成功");
        if (network_task_handle) xTaskNotify(network_task_handle, 4, eSetBits);
    }
}

/** AI:在独立任务执行Wi-Fi配置，避免阻塞按键计时。@param arg 未使用。@return 不返回。 */
static void network_task(void *arg)
{
    (void)arg;
    uint32_t flags;
    while (true) {
        xTaskNotifyWait(0, UINT32_MAX, &flags, portMAX_DELAY);
        if (flags & 1) {
            wifi_config_t ap = {0};
            snprintf((char *)ap.ap.ssid, sizeof(ap.ap.ssid), "MCUTOOL-%.6s", g_device_id + strlen(g_device_id) - 6);
            strcpy((char *)ap.ap.password, "mcutool-setup");
            ap.ap.ssid_len = strlen((char *)ap.ap.ssid);
            ap.ap.channel = 1; ap.ap.max_connection = 2; ap.ap.authmode = WIFI_AUTH_WPA2_PSK;
            esp_err_t err = esp_wifi_set_mode(WIFI_MODE_APSTA);
            if (err == ESP_OK) err = esp_wifi_set_config(WIFI_IF_AP, &ap);
            if (err == ESP_OK) { provisioning = true; tool_event("provisioning", "配置热点已开启，请连接后访问192.168.4.1/setup"); }
            else tool_event("network_error", "无法开启配置热点");
        }
        if (flags & 2) {
            vTaskDelay(pdMS_TO_TICKS(300));
            wifi_config_t sta = {0};
            xSemaphoreTake(network_mutex, portMAX_DELAY);
            memcpy(sta.sta.ssid, ssid, strlen(ssid));
            memcpy(sta.sta.password, password, strlen(password));
            xSemaphoreGive(network_mutex);
            esp_wifi_disconnect();
            esp_err_t err = esp_wifi_set_config(WIFI_IF_STA, &sta);
            if (err == ESP_OK) { connecting = true; err = esp_wifi_connect(); }
            if (err != ESP_OK) { connecting = false; tool_event("network_error", "Wi-Fi连接请求失败，请检查配置后显式重试"); }
        }
        if ((flags & 4) && provisioning) {
            if (esp_wifi_set_mode(WIFI_MODE_STA) == ESP_OK) provisioning = false;
            else tool_event("network_error", "连接成功但配置热点关闭失败");
        }
    }
}

esp_err_t tool_network_configure(const char *name, const char *secret)
{
    if (!name || !secret || !name[0] || strlen(name) > 32 || strlen(secret) > 64 || (strlen(secret) > 0 && strlen(secret) < 8)) return ESP_ERR_INVALID_ARG;
    if (!g_nvs_ready || !wifi_ready) return ESP_ERR_INVALID_STATE;
    nvs_handle_t handle;
    esp_err_t err = nvs_open("network", NVS_READWRITE, &handle);
    if (err != ESP_OK) return err;
    err = nvs_set_str(handle, "ssid", name);
    if (err == ESP_OK) err = nvs_set_str(handle, "password", secret);
    if (err == ESP_OK) err = nvs_commit(handle);
    nvs_close(handle);
    if (err != ESP_OK) return err;
    xSemaphoreTake(network_mutex, portMAX_DELAY);
    strcpy(ssid, name); strcpy(password, secret);
    xSemaphoreGive(network_mutex);
    return tool_network_connect();
}

esp_err_t tool_network_connect(void)
{
    if (!wifi_ready || !network_task_handle || !ssid[0]) return ESP_ERR_INVALID_STATE;
    xTaskNotify(network_task_handle, 2, eSetBits);
    return ESP_OK;
}

void tool_network_provision(void)
{
    if (wifi_ready && network_task_handle) xTaskNotify(network_task_handle, 1, eSetBits);
}

int tool_network_indicator(void)
{
    return provisioning ? 1 : connected ? 2 : 0;
}

cJSON *tool_network_status(bool include_token)
{
    cJSON *out = cJSON_CreateObject();
    if (network_mutex) xSemaphoreTake(network_mutex, portMAX_DELAY);
    cJSON_AddBoolToObject(out, "ready", wifi_ready);
    cJSON_AddBoolToObject(out, "connected", connected);
    cJSON_AddBoolToObject(out, "connecting", connecting);
    cJSON_AddBoolToObject(out, "provisioning", provisioning);
    cJSON_AddStringToObject(out, "ssid", ssid);
    cJSON_AddStringToObject(out, "ip", ip_address);
    if (include_token) cJSON_AddStringToObject(out, "api_token", api_token);
    if (network_mutex) xSemaphoreGive(network_mutex);
    return out;
}

esp_err_t tool_network_init(void)
{
    network_mutex = xSemaphoreCreateMutex();
    if (!network_mutex) return ESP_ERR_NO_MEM;
    if (!g_nvs_ready) return ESP_ERR_INVALID_STATE;
    nvs_handle_t handle;
    esp_err_t err = nvs_open("network", NVS_READWRITE, &handle);
    if (err != ESP_OK) return err;
    size_t size = sizeof(ssid);
    err = nvs_get_str(handle, "ssid", ssid, &size);
    if (err != ESP_OK && err != ESP_ERR_NVS_NOT_FOUND) { nvs_close(handle); return err; }
    size = sizeof(password);
    err = nvs_get_str(handle, "password", password, &size);
    if (err != ESP_OK && err != ESP_ERR_NVS_NOT_FOUND) { nvs_close(handle); return err; }
    size = sizeof(api_token);
    err = nvs_get_str(handle, "token", api_token, &size);
    if (err == ESP_ERR_NVS_NOT_FOUND) {
        for (int i = 0; i < 8; i++) snprintf(api_token + i * 8, 9, "%08lx", (unsigned long)esp_random());
        err = nvs_set_str(handle, "token", api_token);
        if (err == ESP_OK) err = nvs_commit(handle);
    }
    nvs_close(handle);
    if (err != ESP_OK || strlen(api_token) != 64) return ESP_ERR_INVALID_STATE;
    if ((err = esp_netif_init()) != ESP_OK) return err;
    if ((err = esp_event_loop_create_default()) != ESP_OK) return err;
    if (!esp_netif_create_default_wifi_sta() || !esp_netif_create_default_wifi_ap()) return ESP_ERR_NO_MEM;
    wifi_init_config_t config = WIFI_INIT_CONFIG_DEFAULT();
    if ((err = esp_wifi_init(&config)) != ESP_OK) return err;
    if ((err = esp_wifi_set_storage(WIFI_STORAGE_RAM)) != ESP_OK) return err;
    if ((err = esp_event_handler_register(WIFI_EVENT, ESP_EVENT_ANY_ID, wifi_event, NULL)) != ESP_OK) return err;
    if ((err = esp_event_handler_register(IP_EVENT, IP_EVENT_STA_GOT_IP, wifi_event, NULL)) != ESP_OK) return err;
    if ((err = esp_wifi_set_mode(WIFI_MODE_STA)) != ESP_OK) return err;
    if ((err = esp_wifi_start()) != ESP_OK) return err;
    /* AI:工具持续运行以维持USB、采集及本地动作，不启用工具自身省电休眠。 */
    esp_wifi_set_ps(WIFI_PS_NONE);
    if (xTaskCreate(network_task, "tool_network", 6144, NULL, 3, &network_task_handle) != pdPASS) return ESP_ERR_NO_MEM;
    httpd_config_t http = HTTPD_DEFAULT_CONFIG();
    http.stack_size = 16384;
    http.recv_wait_timeout = 5;
    if ((err = httpd_start(&http_server, &http)) != ESP_OK) return err;
    httpd_uri_t rpc = {.uri = "/rpc", .method = HTTP_POST, .handler = rpc_handler};
    httpd_uri_t setup_get = {.uri = "/setup", .method = HTTP_GET, .handler = setup_page};
    httpd_uri_t setup_post = {.uri = "/setup", .method = HTTP_POST, .handler = setup_submit};
    httpd_register_uri_handler(http_server, &rpc);
    httpd_register_uri_handler(http_server, &setup_get);
    httpd_register_uri_handler(http_server, &setup_post);
    wifi_ready = true;
    if (ssid[0]) tool_network_connect(); else tool_network_provision();
    return ESP_OK;
}
