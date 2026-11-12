#include "tool_runtime.h"
#include "driver/uart.h"
#include "driver/gpio.h"
#include "esp_rom_gpio.h"
#include "soc/gpio_sig_map.h"
#include "esp_heap_caps.h"
#include "esp_timer.h"
#include <string.h>
#include <stdlib.h>

static SemaphoreHandle_t uart_mutex;
static QueueHandle_t uart_events;
static uint8_t *rx_bytes;
static uint64_t rx_end, overflow_events;
static bool uart_ready, tx_enabled, tx_draining;
static int baudrate = 115200;
typedef struct { uint64_t start, end, t_us; } rx_stamp_t;
static rx_stamp_t stamps[512];
static uint64_t stamp_count;

/** AI:解除发送外设连接并保持GPIO输入浮空。@return 无。 */
static void tx_high_impedance(void)
{
    esp_rom_gpio_connect_out_signal(14, SIG_GPIO_OUT_IDX, false, false);
    gpio_set_direction(14, GPIO_MODE_INPUT);
    gpio_set_pull_mode(14, GPIO_FLOATING);
}

/** AI:收取原始串口字节并记录覆盖范围。@param arg 未使用。@return 不返回。 */
static void receive_task(void *arg)
{
    (void)arg;
    uint8_t chunk[512];
    uart_event_t event;
    while (true) {
        if (!xQueueReceive(uart_events, &event, pdMS_TO_TICKS(20))) continue;
        if (event.type == UART_FIFO_OVF || event.type == UART_BUFFER_FULL) {
            xSemaphoreTake(uart_mutex, portMAX_DELAY);
            overflow_events++;
            xSemaphoreGive(uart_mutex);
            /* AI:驱动溢出后无法精确知道丢失字节，公开事件而不编造数量。 */
            uart_flush_input(UART_NUM_1);
            tool_event("uart_overflow", "UART硬件或驱动缓存溢出，丢失字节数量未知");
        } else if (event.type == UART_DATA) {
            size_t remaining = event.size;
            while (remaining) {
                int count = uart_read_bytes(UART_NUM_1, chunk, remaining > sizeof(chunk) ? sizeof(chunk) : remaining, pdMS_TO_TICKS(10));
                if (count <= 0) break;
                xSemaphoreTake(uart_mutex, portMAX_DELAY);
                uint64_t start = rx_end;
                for (int i = 0; i < count; i++) rx_bytes[rx_end++ % TOOL_UART_CAPACITY] = chunk[i];
                stamps[stamp_count++ % 512] = (rx_stamp_t){start, rx_end, esp_timer_get_time()};
                xSemaphoreGive(uart_mutex);
                remaining -= count;
            }
        }
    }
}

esp_err_t tool_uart_init(void)
{
    uart_mutex = xSemaphoreCreateMutex();
    if (!uart_mutex) return ESP_ERR_NO_MEM;
    rx_bytes = heap_caps_malloc(TOOL_UART_CAPACITY, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    if (!rx_bytes) return ESP_ERR_NO_MEM;
    uart_config_t config = {.baud_rate = baudrate, .data_bits = UART_DATA_8_BITS,
        .parity = UART_PARITY_DISABLE, .stop_bits = UART_STOP_BITS_1,
        .flow_ctrl = UART_HW_FLOWCTRL_DISABLE, .source_clk = UART_SCLK_DEFAULT};
    esp_err_t err = uart_param_config(UART_NUM_1, &config);
    if (err == ESP_OK) err = uart_set_pin(UART_NUM_1, UART_PIN_NO_CHANGE, 15, UART_PIN_NO_CHANGE, UART_PIN_NO_CHANGE);
    if (err == ESP_OK) err = uart_driver_install(UART_NUM_1, 8192, 0, 32, &uart_events, 0);
    tx_high_impedance();
    if (err == ESP_OK && xTaskCreate(receive_task, "tool_uart", 4096, NULL, 5, NULL) != pdPASS) return ESP_ERR_NO_MEM;
    uart_ready = err == ESP_OK;
    return err;
}

esp_err_t tool_uart_configure(int baud)
{
    static const int allowed[] = {9600, 19200, 38400, 57600, 115200, 230400, 460800, 921600};
    bool valid = false;
    for (size_t i = 0; i < sizeof(allowed) / sizeof(allowed[0]); i++) if (allowed[i] == baud) valid = true;
    if (!valid) return ESP_ERR_INVALID_ARG;
    if (!uart_ready || tx_enabled || tx_draining) return ESP_ERR_INVALID_STATE;
    esp_err_t err = uart_set_baudrate(UART_NUM_1, baud);
    if (err == ESP_OK) baudrate = baud;
    return err;
}

esp_err_t tool_uart_tx(bool enabled)
{
    if (!uart_ready) return ESP_ERR_INVALID_STATE;
    if (enabled) {
        if (tx_draining) return ESP_ERR_INVALID_STATE;
        esp_err_t err = uart_set_pin(UART_NUM_1, 14, 15, UART_PIN_NO_CHANGE, UART_PIN_NO_CHANGE);
        if (err == ESP_OK) { gpio_set_pull_mode(14, GPIO_FLOATING); tx_enabled = true; }
        return err;
    }
    tx_draining = true;
    esp_err_t err = uart_wait_tx_done(UART_NUM_1, pdMS_TO_TICKS(5000));
    if (err == ESP_OK) { tx_high_impedance(); tx_enabled = false; }
    tx_draining = false;
    return err;
}

/** AI:解码十六进制单字符。@param ch 字符。@return 0到15，非法为-1。 */
static int hex_digit(char ch)
{
    if (ch >= '0' && ch <= '9') return ch - '0';
    if (ch >= 'a' && ch <= 'f') return ch - 'a' + 10;
    if (ch >= 'A' && ch <= 'F') return ch - 'A' + 10;
    return -1;
}

esp_err_t tool_uart_write(const char *hex)
{
    if (!uart_ready || !tx_enabled || tx_draining) return ESP_ERR_INVALID_STATE;
    if (!hex) return ESP_ERR_INVALID_ARG;
    size_t size = strlen(hex);
    if (!size || size % 2 || size > 8192) return ESP_ERR_INVALID_ARG;
    uint8_t *bytes = malloc(size / 2);
    if (!bytes) return ESP_ERR_NO_MEM;
    for (size_t i = 0; i < size; i += 2) {
        int hi = hex_digit(hex[i]), lo = hex_digit(hex[i + 1]);
        if (hi < 0 || lo < 0) { free(bytes); return ESP_ERR_INVALID_ARG; }
        bytes[i / 2] = (hi << 4) | lo;
    }
    int written = uart_write_bytes(UART_NUM_1, bytes, size / 2);
    free(bytes);
    if (written != (int)(size / 2)) return ESP_FAIL;
    return uart_wait_tx_done(UART_NUM_1, pdMS_TO_TICKS(5000));
}

cJSON *tool_uart_status(void)
{
    cJSON *out = cJSON_CreateObject();
    cJSON_AddBoolToObject(out, "ready", uart_ready);
    cJSON_AddBoolToObject(out, "tx_enabled", tx_enabled);
    cJSON_AddBoolToObject(out, "tx_draining", tx_draining);
    cJSON_AddNumberToObject(out, "baudrate", baudrate);
    cJSON_AddStringToObject(out, "format", "8N1");
    if (uart_mutex) xSemaphoreTake(uart_mutex, portMAX_DELAY);
    cJSON_AddNumberToObject(out, "received_bytes", rx_end);
    cJSON_AddNumberToObject(out, "hardware_overflow_events", overflow_events);
    if (uart_mutex) xSemaphoreGive(uart_mutex);
    return out;
}

cJSON *tool_uart_read(uint64_t after)
{
    cJSON *out = cJSON_CreateObject();
    if (!uart_mutex || !rx_bytes) {
        cJSON_AddStringToObject(out, "data_hex", ""); cJSON_AddNumberToObject(out, "start", after); cJSON_AddNumberToObject(out, "next", after); cJSON_AddNumberToObject(out, "lost", 0);
        cJSON_AddNumberToObject(out, "hardware_overflow_events", 0);
        cJSON_AddBoolToObject(out, "available", false);
        return out;
    }
    xSemaphoreTake(uart_mutex, portMAX_DELAY);
    uint64_t oldest = rx_end > TOOL_UART_CAPACITY ? rx_end - TOOL_UART_CAPACITY : 0;
    uint64_t start = after < oldest ? oldest : after;
    if (start > rx_end) start = rx_end;
    size_t count = rx_end - start > 8192 ? 8192 : rx_end - start;
    char *hex = malloc(count * 2 + 1);
    if (!hex) { xSemaphoreGive(uart_mutex); cJSON_Delete(out); return NULL; }
    const char digits[] = "0123456789abcdef";
    for (size_t i = 0; i < count; i++) { uint8_t value = rx_bytes[(start + i) % TOOL_UART_CAPACITY]; hex[i * 2] = digits[value >> 4]; hex[i * 2 + 1] = digits[value & 15]; }
    hex[count * 2] = '\0';
    cJSON_AddStringToObject(out, "data_hex", hex);
    free(hex);
    cJSON_AddNumberToObject(out, "start", start);
    cJSON_AddNumberToObject(out, "next", start + count);
    cJSON_AddNumberToObject(out, "lost", after < oldest ? oldest - after : 0);
    cJSON_AddNumberToObject(out, "hardware_overflow_events", overflow_events);
    uint64_t first = 0, last = 0;
    for (uint64_t i = stamp_count > 512 ? stamp_count - 512 : 0; i < stamp_count; i++) {
        rx_stamp_t *stamp = &stamps[i % 512];
        if (count && stamp->start <= start && stamp->end > start) first = stamp->t_us;
        if (count && stamp->start < start + count && stamp->end >= start + count) last = stamp->t_us;
    }
    if (first && last) { cJSON_AddNumberToObject(out, "start_t_us", first); cJSON_AddNumberToObject(out, "end_t_us", last); }
    else { cJSON_AddNullToObject(out, "start_t_us"); cJSON_AddNullToObject(out, "end_t_us"); }
    cJSON_AddNumberToObject(out, "read_t_us", esp_timer_get_time());
    xSemaphoreGive(uart_mutex);
    return out;
}
