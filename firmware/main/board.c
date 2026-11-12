#include "tool_runtime.h"
#include "driver/gpio.h"
#include "esp_timer.h"
#include "esp_mac.h"
#include "esp_random.h"
#include <stdio.h>
#include <string.h>

tool_core_t g_core;
SemaphoreHandle_t g_core_mutex;
char g_device_id[32];
char g_boot_id[33];
bool g_nvs_ready;

typedef struct { uint64_t seq, t_us; char name[32], detail[160]; } event_t;
static event_t events[64];
static uint64_t event_next;
static SemaphoreHandle_t event_mutex;

uint32_t tool_crc32(const uint8_t *data, size_t size)
{
    uint32_t crc = UINT32_MAX;
    for (size_t i = 0; i < size; i++) {
        crc ^= data[i];
        for (int bit = 0; bit < 8; bit++) crc = (crc >> 1) ^ (0xedb88320U & (0U - (crc & 1U)));
    }
    return ~crc;
}

void tool_event(const char *name, const char *detail)
{
    if (!event_mutex) return;
    xSemaphoreTake(event_mutex, portMAX_DELAY);
    uint64_t seq = ++event_next;
    event_t *event = &events[(seq - 1) % 64];
    event->seq = seq;
    event->t_us = esp_timer_get_time();
    snprintf(event->name, sizeof(event->name), "%s", name);
    snprintf(event->detail, sizeof(event->detail), "%s", detail);
    xSemaphoreGive(event_mutex);
}

cJSON *tool_events_read(uint64_t after)
{
    cJSON *out = cJSON_CreateObject(), *items = cJSON_AddArrayToObject(out, "items");
    xSemaphoreTake(event_mutex, portMAX_DELAY);
    uint64_t oldest = event_next > 64 ? event_next - 63 : 1;
    uint64_t start = after + 1 < oldest ? oldest : after + 1;
    cJSON_AddNumberToObject(out, "lost", after + 1 < oldest ? oldest - after - 1 : 0);
    uint64_t next = after;
    for (uint64_t seq = start; seq <= event_next && seq < start + 8; seq++) {
        event_t *event = &events[(seq - 1) % 64];
        cJSON *item = cJSON_CreateObject();
        cJSON_AddNumberToObject(item, "seq", seq);
        cJSON_AddNumberToObject(item, "t_us", event->t_us);
        cJSON_AddStringToObject(item, "name", event->name);
        cJSON_AddStringToObject(item, "detail", event->detail);
        cJSON_AddItemToArray(items, item);
        next = seq;
    }
    cJSON_AddNumberToObject(out, "next", next);
    xSemaphoreGive(event_mutex);
    return out;
}

void tool_board_apply(void)
{
    /* AI:先拉低未选支路再拉高目标，禁止用两个独立外部命令驱动主供电。 */
    if (g_core.power != TOOL_POWER_BATTERY) gpio_set_level(11, 0);
    if (g_core.power != TOOL_POWER_EXTERNAL) gpio_set_level(12, 0);
    gpio_set_level(11, g_core.power == TOOL_POWER_BATTERY);
    gpio_set_level(12, g_core.power == TOOL_POWER_EXTERNAL);
    gpio_set_level(13, g_core.charge);
    for (int i = 0; i < 5; i++) gpio_set_level(4 + i, (g_core.keys >> i) & 1);
}

/** AI:独立推进按键及供电时序，网络处理不会阻塞本任务。@param arg 未使用。@return 不返回。 */
static void control_task(void *arg)
{
    (void)arg;
    TickType_t wake = xTaskGetTickCount();
    int64_t pressed_at = 0;
    bool handled = false;
    while (true) {
        uint64_t now = esp_timer_get_time() / 1000;
        xSemaphoreTake(g_core_mutex, portMAX_DELAY);
        tool_core_tick(&g_core, now);
        tool_board_apply();
        xSemaphoreGive(g_core_mutex);
        if (!gpio_get_level(17)) {
            if (!pressed_at) pressed_at = now;
            if (!handled && now - pressed_at >= 3000) {
                handled = true;
                /* AI:配网启动交由网络任务，控制任务不执行Wi-Fi阻塞操作。 */
                tool_network_provision();
            }
        } else { pressed_at = 0; handled = false; }
        int indicator = tool_network_indicator();
        gpio_set_level(16, indicator == 2 || (now / (indicator == 1 ? 150 : 700)) % 2);
        vTaskDelayUntil(&wake, pdMS_TO_TICKS(1));
    }
}

esp_err_t tool_board_init(void)
{
    g_core_mutex = xSemaphoreCreateMutex();
    event_mutex = xSemaphoreCreateMutex();
    if (!g_core_mutex || !event_mutex) return ESP_ERR_NO_MEM;
    tool_core_init(&g_core);
    uint64_t outputs = TOOL_GPIO_KEYS_MASK | (1ULL << 11) | (1ULL << 12) | (1ULL << 13) | (1ULL << 16);
    for (int pin = 0; pin < 49; pin++) if (outputs & (1ULL << pin)) gpio_set_level(pin, 0);
    gpio_config_t config = {.pin_bit_mask = outputs, .mode = GPIO_MODE_OUTPUT,
        .pull_up_en = GPIO_PULLUP_DISABLE, .pull_down_en = GPIO_PULLDOWN_DISABLE, .intr_type = GPIO_INTR_DISABLE};
    esp_err_t err = gpio_config(&config);
    if (err != ESP_OK) return err;
    gpio_reset_pin(14);
    gpio_set_direction(14, GPIO_MODE_INPUT);
    gpio_set_pull_mode(14, GPIO_FLOATING);
    config.pin_bit_mask = 1ULL << 17;
    config.mode = GPIO_MODE_INPUT;
    config.pull_up_en = GPIO_PULLUP_ENABLE;
    if ((err = gpio_config(&config)) != ESP_OK) return err;
    uint8_t mac[6];
    esp_read_mac(mac, ESP_MAC_WIFI_STA);
    snprintf(g_device_id, sizeof(g_device_id), "MCUTOOL-%02X%02X%02X%02X%02X%02X", mac[0], mac[1], mac[2], mac[3], mac[4], mac[5]);
    snprintf(g_boot_id, sizeof(g_boot_id), "%08lx%08lx%08lx%08lx", (unsigned long)esp_random(), (unsigned long)esp_random(), (unsigned long)esp_random(), (unsigned long)esp_random());
    if (xTaskCreate(control_task, "tool_control", 4096, NULL, 8, NULL) != pdPASS) return ESP_ERR_NO_MEM;
    return ESP_OK;
}

cJSON *tool_board_status(void)
{
    static const char *names[] = {"off", "battery", "external"};
    cJSON *out = cJSON_CreateObject();
    uint64_t now = esp_timer_get_time() / 1000;
    xSemaphoreTake(g_core_mutex, portMAX_DELAY);
    cJSON_AddStringToObject(out, "power", names[g_core.power]);
    cJSON_AddBoolToObject(out, "charge", g_core.charge);
    cJSON_AddNumberToObject(out, "keys_mask", g_core.keys);
    cJSON_AddNumberToObject(out, "revision", g_core.revision);
    cJSON_AddBoolToObject(out, "busy", tool_core_busy(&g_core));
    cJSON_AddBoolToObject(out, "power_switching", g_core.power_slot >= 0);
    char public_owner[9] = {0};
    memcpy(public_owner, g_core.owner, strnlen(g_core.owner, 8));
    cJSON_AddStringToObject(out, "controller", public_owner);
    cJSON_AddBoolToObject(out, "controller_active", g_core.owner[0] && now < g_core.owner_deadline_ms);
    cJSON_AddNumberToObject(out, "power_deadtime_ms", g_core.deadtime_ms);
    cJSON_AddBoolToObject(out, "timing_verified", false);
    cJSON_AddNumberToObject(out, "key_remaining_ms", g_core.key_slot >= 0 && now < g_core.key_deadline_ms ? g_core.key_deadline_ms - now : 0);
    xSemaphoreGive(g_core_mutex);
    cJSON_AddStringToObject(out, "device_id", g_device_id);
    cJSON_AddStringToObject(out, "boot_id", g_boot_id);
    cJSON_AddNumberToObject(out, "uptime_ms", now);
    cJSON_AddBoolToObject(out, "nvs_ready", g_nvs_ready);
    cJSON_AddItemToObject(out, "uart", tool_uart_status());
    cJSON_AddItemToObject(out, "measurement", tool_measure_status());
    cJSON_AddItemToObject(out, "network", tool_network_status(false));
    return out;
}
