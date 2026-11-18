#include "tool_runtime.h"
#include "ina226.h"
#include "driver/usb_serial_jtag.h"
#include "esp_timer.h"
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static SemaphoreHandle_t rpc_mutex;
typedef struct { char id[65], method[32], controller[65]; cJSON *params, *response; } cached_request_t;
static cached_request_t request_cache[64];
static unsigned cache_next;

/** AI:取得字符串字段。@param json 对象。@param name 字段。@return 字符串或NULL。 */
static const char *string_field(const cJSON *json, const char *name)
{
    const cJSON *item = cJSON_GetObjectItemCaseSensitive(json, name);
    return cJSON_IsString(item) ? item->valuestring : NULL;
}

/** AI:读取有界非负整数。@param json 对象。@param key 字段。@param max 上限。@param value 输出。@return 是否有效。 */
static bool integer_field(const cJSON *json, const char *key, uint64_t max, uint64_t *value)
{
    const cJSON *item = cJSON_GetObjectItemCaseSensitive(json, key);
    if (!cJSON_IsNumber(item) || !isfinite(item->valuedouble) || item->valuedouble < 0 || item->valuedouble > (double)max || floor(item->valuedouble) != item->valuedouble) return false;
    *value = (uint64_t)item->valuedouble;
    return true;
}

/** AI:生成公共错误。@param response 响应。@param code 稳定代码。@param message 说明。@return 无。 */
static void error_response(cJSON *response, const char *code, const char *message)
{
    cJSON_AddBoolToObject(response, "ok", false);
    cJSON *error = cJSON_AddObjectToObject(response, "error");
    cJSON_AddStringToObject(error, "code", code);
    cJSON_AddStringToObject(error, "message", message);
    cJSON_AddObjectToObject(error, "details");
}

/** AI:将核心结果映射为公共错误。@param response 响应。@param result 核心结果。@return 是否成功。 */
static bool core_result(cJSON *response, tool_result_t result)
{
    const char *codes[] = {"OK", "INVALID_PARAMS", "BUSY", "INTERLOCK", "NOT_OWNER", "OWNER_EXPIRED", "STALE_STATE", "NOT_FOUND"};
    const char *messages[] = {"成功", "参数不合法", "有在途动作，请等待结束", "充电互锁冲突，请先关闭充电并核对真实电池通路", "操作权属于其他控制者", "操作会话已失效，请查询状态后显式接管", "状态已变化，请重新查询", "记录不存在或已经过期"};
    if (result == TOOL_OK) return true;
    error_response(response, codes[result], messages[result]);
    return false;
}

/** AI:打包动作控制记录。@param id 动作编号。@return JSON或NULL。 */
static cJSON *action_json(uint32_t id)
{
    cJSON *out = NULL;
    xSemaphoreTake(g_core_mutex, portMAX_DELAY);
    const tool_action_t *action = tool_core_action(&g_core, id);
    if (action) {
        out = cJSON_CreateObject();
        cJSON_AddNumberToObject(out, "action_id", action->id);
        const char *kind = action->kind == TOOL_KIND_CHARGE ? "charge" : action->kind == TOOL_KIND_KEYS ? "keys" : "power";
        cJSON_AddStringToObject(out, "kind", kind);
        cJSON_AddStringToObject(out, "state", action->state == TOOL_ACTION_RUNNING ? "running" : action->state == TOOL_ACTION_CANCELLED ? "cancelled" : "succeeded");
        cJSON_AddNumberToObject(out, "started_ms", action->started_ms);
        cJSON_AddNumberToObject(out, "finished_ms", action->finished_ms);
        if (action->kind == TOOL_KIND_CHARGE) {
            const tool_charge_cycle_t *cycle = &action->cycle;
            cJSON_AddBoolToObject(out, "on", cycle->on);
            cJSON_AddNumberToObject(out, "phase_start_ms", cycle->phase_start_ms);
            cJSON_AddNumberToObject(out, "on_ms", cycle->on_ms);
            cJSON_AddNumberToObject(out, "off_ms", cycle->off_ms);
            cJSON_AddNumberToObject(out, "count", cycle->count);
            cJSON_AddNumberToObject(out, "completed", cycle->completed);
            cJSON_AddNumberToObject(out, "min_on_ms", cycle->min_on_ms);
            cJSON_AddNumberToObject(out, "max_on_ms", cycle->max_on_ms);
            cJSON_AddNumberToObject(out, "min_off_ms", cycle->min_off_ms);
            cJSON_AddNumberToObject(out, "max_off_ms", cycle->max_off_ms);
        }
    }
    xSemaphoreGive(g_core_mutex);
    return out;
}

/** AI:构建设备能力。@return 调用者释放的JSON。 */
static cJSON *device_info(void)
{
    cJSON *out = cJSON_CreateObject();
    cJSON_AddStringToObject(out, "device_id", g_device_id);
    cJSON_AddStringToObject(out, "boot_id", g_boot_id);
    cJSON_AddStringToObject(out, "firmware_version", "0.1.3");
    cJSON_AddStringToObject(out, "hardware_revision", "2026-11-10");
    cJSON_AddNumberToObject(out, "protocol_version", 1);
    cJSON_AddBoolToObject(out, "test_device", false);
    cJSON *measurement = cJSON_AddObjectToObject(out, "measurement");
    cJSON_AddStringToObject(measurement, "battery_sensor", "INA226");
    cJSON_AddNumberToObject(measurement, "shunt_ohms", TOOL_INA226_SHUNT_OHMS);
    cJSON_AddNumberToObject(measurement, "current_lsb_a", TOOL_INA226_CURRENT_LSB_A);
    cJSON_AddNumberToObject(measurement, "battery_voltage_lsb_v", TOOL_INA226_BUS_LSB_V);
    cJSON_AddNumberToObject(measurement, "averaging_samples", 16);
    cJSON_AddNumberToObject(measurement, "conversion_time_us", 2116);
    cJSON_AddNumberToObject(measurement, "nominal_cycle_us", 67712);
    cJSON_AddNumberToObject(measurement, "sample_rate_hz", 10);
    cJSON_AddBoolToObject(measurement, "accuracy_verified", false);
    const char *methods[] = {"device.info", "device.status", "control.claim", "control.renew", "control.release", "power.select", "charge.set", "charge.run", "charge.cancel", "keys.run", "action.get", "action.cancel", "uart.configure", "uart.tx", "uart.write", "telemetry.read", "calibration.get", "calibration.set", "timing.set", "network.status", "network.configure", "network.connect"};
    cJSON *capabilities = cJSON_AddArrayToObject(out, "capabilities");
    for (size_t i = 0; i < sizeof(methods)/sizeof(methods[0]); i++) cJSON_AddItemToArray(capabilities, cJSON_CreateString(methods[i]));
    cJSON *limits = cJSON_AddObjectToObject(out, "limits");
    cJSON_AddNumberToObject(limits, "keys", 5);
    cJSON_AddNumberToObject(limits, "max_steps", TOOL_MAX_STEPS);
    cJSON_AddNumberToObject(limits, "max_sequence_ms", TOOL_MAX_SEQUENCE_MS);
    cJSON_AddNumberToObject(limits, "min_step_ms", 10);
    cJSON_AddNumberToObject(limits, "max_step_ms", 60000);
    cJSON_AddNumberToObject(limits, "owner_ttl_ms", TOOL_OWNER_TTL_MS);
    cJSON_AddNumberToObject(limits, "uart_write_bytes", 4096);
    cJSON_AddNumberToObject(limits, "uart_buffer_bytes", TOOL_UART_CAPACITY);
    cJSON_AddNumberToObject(limits, "measurement_records", TOOL_SAMPLE_CAPACITY);
    cJSON_AddNumberToObject(limits, "dedup_records", 64);
    cJSON_AddNumberToObject(limits, "action_records", TOOL_MAX_ACTIONS);
    cJSON_AddNumberToObject(limits, "power_min_v", 2.8);
    cJSON_AddNumberToObject(limits, "power_max_v", 12);
    cJSON_AddNumberToObject(limits, "current_max_a", 3);
    cJSON_AddNumberToObject(limits, "measurement_max_v", 15);
    cJSON_AddNumberToObject(limits, "charge_v", 5);
    cJSON_AddNumberToObject(limits, "charge_max_a", 2);
    cJSON_AddNumberToObject(limits, "key_max_v", 6);
    cJSON_AddNumberToObject(limits, "key_max_ma", 20);
    cJSON_AddBoolToObject(limits, "hardware_verified", false);
    return out;
}

cJSON *tool_rpc(const cJSON *request, bool usb)
{
    const char *id = string_field(request, "id"), *method = string_field(request, "method");
    const char *controller = string_field(request, "controller"), *boot = string_field(request, "boot_id");
    const cJSON *params = cJSON_GetObjectItemCaseSensitive(request, "params");
    cJSON *response = cJSON_CreateObject(), *result = NULL;
    cJSON_AddNumberToObject(response, "v", 1);
    cJSON_AddStringToObject(response, "id", id ? id : "");
    cJSON_AddStringToObject(response, "boot_id", g_boot_id);
    uint64_t version;
    if (!id || !id[0] || strlen(id) > 64 || !method || strlen(method) > 31 || !cJSON_IsObject(params) || !integer_field(request, "v", 1, &version) || version != 1) {
        error_response(response, "INVALID_REQUEST", "请求信封不合法"); return response;
    }
    bool read_only = !strcmp(method, "device.info") || !strcmp(method, "device.status") || !strcmp(method, "action.get") || !strcmp(method, "telemetry.read") || !strcmp(method, "calibration.get") || !strcmp(method, "network.status");
    bool renew = !strcmp(method, "control.renew");
    bool cacheable = !read_only && !renew;
    xSemaphoreTake(rpc_mutex, portMAX_DELAY);
    if (!read_only && (!boot || strcmp(boot, g_boot_id))) { error_response(response, "DEVICE_RESTARTED", "启动标识不匹配，必须重新查询设备"); goto done; }
    if (!read_only && (!controller || !controller[0] || strlen(controller) > 64)) { error_response(response, "NOT_OWNER", "需要有效控制者标识"); goto done; }
    if (cacheable) {
        for (size_t i = 0; i < 64; i++) if (request_cache[i].response && !strcmp(request_cache[i].id, id)) {
            cached_request_t *cached = &request_cache[i];
            if (strcmp(cached->method, method) || strcmp(cached->controller, controller) || !cJSON_Compare(cached->params, params, true)) error_response(response, "REQUEST_CONFLICT", "相同请求编号不能用于不同内容");
            else { cJSON_Delete(response); response = cJSON_Duplicate(cached->response, true); }
            goto done;
        }
    }
    uint64_t now = esp_timer_get_time() / 1000;
    if (!read_only && strcmp(method, "control.claim")) {
        xSemaphoreTake(g_core_mutex, portMAX_DELAY);
        tool_result_t check = tool_core_owner(&g_core, controller, now);
        xSemaphoreGive(g_core_mutex);
        if (!core_result(response, check)) goto done;
    }
    if (!strcmp(method, "device.info")) result = device_info();
    else if (!strcmp(method, "device.status")) result = tool_board_status();
    else if (!strcmp(method, "network.status")) result = tool_network_status(usb);
    else if (!strcmp(method, "calibration.get")) result = tool_calibration_get();
    else if (!strcmp(method, "telemetry.read")) {
        uint64_t measurement_after, uart_after, event_after;
        if (!integer_field(params, "measurement_after", 9007199254740991ULL, &measurement_after) || !integer_field(params, "uart_after", 9007199254740991ULL, &uart_after) || !integer_field(params, "event_after", 9007199254740991ULL, &event_after)) goto invalid;
        result = cJSON_CreateObject();
        cJSON_AddItemToObject(result, "measurements", tool_measure_read(measurement_after));
        cJSON_AddItemToObject(result, "uart", tool_uart_read(uart_after));
        cJSON_AddItemToObject(result, "events", tool_events_read(event_after));
    } else if (!strncmp(method, "control.", 8)) {
        tool_result_t code;
        uint64_t expected = 0;
        const cJSON *takeover = cJSON_GetObjectItemCaseSensitive(params, "takeover");
        if (takeover && !cJSON_IsBool(takeover)) goto invalid;
        if (cJSON_IsTrue(takeover) && !integer_field(params, "expected_revision", UINT32_MAX, &expected)) goto invalid;
        xSemaphoreTake(g_core_mutex, portMAX_DELAY);
        if (!strcmp(method, "control.claim")) code = tool_core_claim(&g_core, controller, cJSON_IsTrue(takeover), expected, now);
        else if (renew) code = tool_core_renew(&g_core, controller, now);
        else if (!strcmp(method, "control.release")) code = tool_core_release(&g_core, controller, now);
        else code = TOOL_INVALID;
        xSemaphoreGive(g_core_mutex);
        if (core_result(response, code)) result = tool_board_status();
    } else if (!strcmp(method, "power.select")) {
        const char *source = string_field(params, "source");
        if (!source) goto invalid;
        tool_power_t selected;
        if (!strcmp(source, "off")) selected = TOOL_POWER_OFF;
        else if (!strcmp(source, "battery")) selected = TOOL_POWER_BATTERY;
        else if (!strcmp(source, "external")) selected = TOOL_POWER_EXTERNAL;
        else goto invalid;
        uint32_t action;
        xSemaphoreTake(g_core_mutex, portMAX_DELAY);
        tool_result_t code = tool_core_power(&g_core, selected, now, &action);
        tool_board_apply();
        xSemaphoreGive(g_core_mutex);
        if (core_result(response, code)) result = action_json(action);
    } else if (!strcmp(method, "charge.set")) {
        const cJSON *enabled = cJSON_GetObjectItemCaseSensitive(params, "enabled");
        if (!cJSON_IsBool(enabled)) goto invalid;
        xSemaphoreTake(g_core_mutex, portMAX_DELAY);
        tool_result_t code = tool_core_charge(&g_core, cJSON_IsTrue(enabled));
        tool_board_apply();
        xSemaphoreGive(g_core_mutex);
        if (core_result(response, code)) result = tool_board_status();
    } else if (!strcmp(method, "charge.run")) {
        uint64_t on_ms, off_ms, count;
        if (!integer_field(params, "on_ms", 60000, &on_ms) || !integer_field(params, "off_ms", 60000, &off_ms) ||
            !integer_field(params, "count", 1000, &count)) goto invalid;
        uint32_t action;
        xSemaphoreTake(g_core_mutex, portMAX_DELAY);
        tool_result_t code = tool_core_charge_run(&g_core, on_ms, off_ms, count, esp_timer_get_time() / 1000, &action);
        tool_board_apply();
        xSemaphoreGive(g_core_mutex);
        if (core_result(response, code)) result = action_json(action);
    } else if (!strcmp(method, "keys.run")) {
        const cJSON *steps = cJSON_GetObjectItemCaseSensitive(params, "steps");
        uint64_t repeat;
        int count = cJSON_GetArraySize(steps);
        if (!cJSON_IsArray(steps) || count < 1 || count > TOOL_MAX_STEPS || !integer_field(params, "repeat", 1000, &repeat) || !repeat) goto invalid;
        tool_key_step_t sequence[TOOL_MAX_STEPS];
        for (int i = 0; i < count; i++) {
            const cJSON *step = cJSON_GetArrayItem(steps, i);
            uint64_t mask, duration;
            if (!integer_field(step, "mask", 31, &mask) || !integer_field(step, "duration_ms", 60000, &duration)) goto invalid;
            sequence[i] = (tool_key_step_t){mask, duration};
        }
        uint32_t action;
        xSemaphoreTake(g_core_mutex, portMAX_DELAY);
        tool_result_t code = tool_core_keys(&g_core, sequence, count, repeat, now, &action);
        tool_board_apply();
        xSemaphoreGive(g_core_mutex);
        if (core_result(response, code)) result = action_json(action);
    } else if (!strcmp(method, "action.get") || !strcmp(method, "action.cancel") || !strcmp(method, "charge.cancel")) {
        uint64_t action;
        if (!integer_field(params, "action_id", UINT32_MAX, &action) || !action) goto invalid;
        if (strcmp(method, "action.get")) {
            xSemaphoreTake(g_core_mutex, portMAX_DELAY);
            tool_result_t code = !strcmp(method, "charge.cancel") ? tool_core_charge_cancel(&g_core, action, esp_timer_get_time() / 1000) : tool_core_cancel(&g_core, action, now);
            tool_board_apply();
            xSemaphoreGive(g_core_mutex);
            if (!core_result(response, code)) goto save;
        }
        result = action_json(action);
        if (!result) error_response(response, "NOT_FOUND", "动作记录不存在或已经过期");
    } else if (!strcmp(method, "timing.set")) {
        uint64_t deadtime;
        if (!integer_field(params, "power_deadtime_ms", 1000, &deadtime) || deadtime < 10) goto invalid;
        xSemaphoreTake(g_core_mutex, portMAX_DELAY);
        if (tool_core_busy(&g_core)) error_response(response, "BUSY", "动作执行中不能修改时序");
        else { g_core.deadtime_ms = deadtime; g_core.revision++; result = cJSON_CreateObject(); cJSON_AddNumberToObject(result, "power_deadtime_ms", deadtime); }
        xSemaphoreGive(g_core_mutex);
    } else {
        esp_err_t err = ESP_ERR_NOT_SUPPORTED;
        if (!strcmp(method, "uart.configure")) {
            uint64_t baud;
            if (!integer_field(params, "baudrate", 921600, &baud)) goto invalid;
            err = tool_uart_configure(baud);
        } else if (!strcmp(method, "uart.tx")) {
            const cJSON *enabled = cJSON_GetObjectItemCaseSensitive(params, "enabled");
            if (!cJSON_IsBool(enabled)) goto invalid;
            err = tool_uart_tx(cJSON_IsTrue(enabled));
        } else if (!strcmp(method, "uart.write")) err = tool_uart_write(string_field(params, "data_hex"));
        else if (!strcmp(method, "calibration.set")) err = tool_calibration_set(params);
        else if (!strcmp(method, "network.configure")) err = tool_network_configure(string_field(params, "ssid"), string_field(params, "password"));
        else if (!strcmp(method, "network.connect")) err = tool_network_connect();
        if (err == ESP_OK) {
            result = cJSON_CreateObject();
            cJSON_AddBoolToObject(result, "completed", true);
            if (!strncmp(method, "uart.", 5)) cJSON_AddItemToObject(result, "uart", tool_uart_status());
        } else if (err == ESP_ERR_NOT_SUPPORTED) error_response(response, "METHOD_NOT_FOUND", "设备不支持此方法");
        else if (err == ESP_ERR_INVALID_ARG) goto invalid;
        else if (err == ESP_ERR_TIMEOUT && !strcmp(method, "uart.tx")) error_response(response, "TX_NOT_DISABLED", "等待发送结束超时，尚未确认TX高阻");
        else error_response(response, err == ESP_ERR_INVALID_STATE ? "INVALID_STATE" : "DEVICE_IO", "设备操作未完成，请查询状态和事件记录");
    }
    goto save;
invalid:
    error_response(response, "INVALID_PARAMS", "参数类型或范围不合法");
save:
    if (result) { cJSON_AddBoolToObject(response, "ok", true); cJSON_AddItemToObject(response, "result", result); }
    if (cacheable) {
        cached_request_t *cached = &request_cache[cache_next++ % 64];
        cJSON_Delete(cached->params); cJSON_Delete(cached->response);
        snprintf(cached->id, sizeof(cached->id), "%s", id);
        snprintf(cached->method, sizeof(cached->method), "%s", method);
        snprintf(cached->controller, sizeof(cached->controller), "%s", controller);
        cached->params = cJSON_Duplicate(params, true);
        cached->response = cJSON_Duplicate(response, true);
        tool_event(method, cJSON_IsTrue(cJSON_GetObjectItemCaseSensitive(response, "ok")) ? "命令已执行，电气结果需测量确认" : "命令被拒绝或执行失败");
    }
done:
    xSemaphoreGive(rpc_mutex);
    return response;
}

/** AI:USB发送完整帧，调用者串行。@param response JSON响应。@return 无。 */
static void usb_response(cJSON *response)
{
    char *json = cJSON_PrintUnformatted(response);
    if (!json) return;
    uint32_t size = strlen(json), crc = tool_crc32((const uint8_t *)json, size);
    if (size <= TOOL_FRAME_MAX) {
        uint8_t header[8] = {'A','M','C','U', size & 255, (size >> 8) & 255, (size >> 16) & 255, (size >> 24) & 255};
        uint8_t trailer[4] = {crc & 255, (crc >> 8) & 255, (crc >> 16) & 255, (crc >> 24) & 255};
        usb_serial_jtag_write_bytes(header, sizeof(header), pdMS_TO_TICKS(1000));
        usb_serial_jtag_write_bytes(json, size, pdMS_TO_TICKS(1000));
        usb_serial_jtag_write_bytes(trailer, sizeof(trailer), pdMS_TO_TICKS(1000));
    }
    free(json);
}

/** AI:接收有界帧并校验，超时清除不完整消息。@param arg 未使用。@return 不返回。 */
static void usb_task(void *arg)
{
    (void)arg;
    uint8_t *buffer = malloc(TOOL_FRAME_MAX + 12);
    if (!buffer) { tool_event("usb", "USB接收缓存分配失败"); vTaskDelete(NULL); return; }
    size_t used = 0;
    int64_t last = esp_timer_get_time();
    while (true) {
        int count = usb_serial_jtag_read_bytes(buffer + used, TOOL_FRAME_MAX + 12 - used, pdMS_TO_TICKS(50));
        if (count > 0) { used += count; last = esp_timer_get_time(); }
        if (used && esp_timer_get_time() - last > 2000000) { used = 0; tool_event("usb", "不完整USB帧超时，未执行"); }
        while (used >= 8) {
            if (memcmp(buffer, "AMCU", 4)) { memmove(buffer, buffer + 1, --used); continue; }
            uint32_t size = (uint32_t)buffer[4] | ((uint32_t)buffer[5] << 8) | ((uint32_t)buffer[6] << 16) | ((uint32_t)buffer[7] << 24);
            if (!size || size > TOOL_FRAME_MAX) { used = 0; tool_event("usb", "USB帧长度不合法，未执行"); break; }
            if (used < size + 12) break;
            uint8_t *tail = buffer + size + 8;
            uint32_t crc = (uint32_t)tail[0] | ((uint32_t)tail[1] << 8) | ((uint32_t)tail[2] << 16) | ((uint32_t)tail[3] << 24);
            if (crc == tool_crc32(buffer + 8, size)) {
                cJSON *request = cJSON_ParseWithLength((const char *)buffer + 8, size);
                cJSON *response = tool_rpc(request, true);
                usb_response(response);
                cJSON_Delete(response); cJSON_Delete(request);
            } else tool_event("usb", "USB校验失败，未执行");
            used -= size + 12;
            memmove(buffer, buffer + size + 12, used);
        }
    }
}

esp_err_t tool_rpc_init(void)
{
    rpc_mutex = xSemaphoreCreateMutex();
    if (!rpc_mutex) return ESP_ERR_NO_MEM;
    usb_serial_jtag_driver_config_t config = {.tx_buffer_size = 8192, .rx_buffer_size = TOOL_FRAME_MAX + 12};
    esp_err_t err = usb_serial_jtag_driver_install(&config);
    if (err != ESP_OK) return err;
    return xTaskCreate(usb_task, "tool_usb", 12288, NULL, 4, NULL) == pdPASS ? ESP_OK : ESP_ERR_NO_MEM;
}
