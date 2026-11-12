#include "tool_runtime.h"
#include "ina226.h"
#include "driver/i2c.h"
#include "esp_timer.h"
#include "esp_heap_caps.h"
#include "nvs.h"
#include <math.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>

typedef struct {
    uint32_t magic, version, revision;
    double gain, offset, min_value, max_value;
    char reference[96];
    uint32_t crc;
} calibration_t;
typedef struct {
    uint64_t seq, t_us, window_start_us;
    double nominal, value;
    uint32_t calibration_revision;
    uint8_t channel;
    bool valid;
    char quality[32];
} sample_t;

static const char *channel_names[] = {"battery_v", "battery_i", "ain1", "ain2", "ain3", "ain4"};
static sample_t *samples;
static uint64_t sample_next;
static calibration_t calibration[6];
static int cal_state[6]; /* AI:0未校准、1有效记录、-1记录损坏，禁止静默套用旧系数。 */
static SemaphoreHandle_t measure_mutex;
static bool i2c_ready, ina_ready, ads_ready;

/** AI:读取指定I2C寄存器。@param address 地址。@param reg 寄存器。@param data 输出。@param size 字节数。@return 总线错误。 */
static esp_err_t read_register(uint8_t address, uint8_t reg, uint8_t *data, size_t size)
{
    return i2c_master_write_read_device(I2C_NUM_0, address, &reg, 1, data, size, pdMS_TO_TICKS(30));
}

/** AI:写大端16位寄存器。@param address 地址。@param reg 寄存器。@param value 值。@return 总线错误。 */
static esp_err_t write_register(uint8_t address, uint8_t reg, uint16_t value)
{
    uint8_t data[] = {reg, value >> 8, value & 0xff};
    return i2c_master_write_to_device(I2C_NUM_0, address, data, sizeof(data), pdMS_TO_TICKS(30));
}

/** AI:读取严格有限数值。@param json 参数对象。@param key 字段。@param value 输出。@return 是否有效。 */
static bool finite_number(const cJSON *json, const char *key, double *value)
{
    const cJSON *item = cJSON_GetObjectItemCaseSensitive(json, key);
    if (!cJSON_IsNumber(item) || !isfinite(item->valuedouble)) return false;
    *value = item->valuedouble;
    return true;
}

/** AI:保存一份采样并应用明确的校准质量。@param channel 通道。@param nominal 名义值。@param valid 是否读取成功。@param t 完成时刻。@param window 窗口起始估计。@return 无。 */
static void publish(int channel, double nominal, bool valid, uint64_t t, uint64_t window)
{
    if (!samples) return;
    xSemaphoreTake(measure_mutex, portMAX_DELAY);
    sample_t *sample = &samples[sample_next % TOOL_SAMPLE_CAPACITY];
    memset(sample, 0, sizeof(*sample));
    sample->seq = ++sample_next;
    sample->channel = channel;
    sample->nominal = nominal;
    sample->value = nominal;
    sample->valid = valid;
    sample->t_us = t;
    sample->window_start_us = window;
    const char *quality = "sensor_error";
    if (valid) {
        quality = "uncalibrated";
        if (cal_state[channel] < 0) quality = "invalid_calibration";
        if (cal_state[channel] == 1) {
            calibration_t *cal = &calibration[channel];
            sample->value = nominal * cal->gain + cal->offset;
            sample->calibration_revision = cal->revision;
            quality = sample->value >= cal->min_value && sample->value <= cal->max_value ? "calibrated" : "outside_calibrated_range";
        }
        if ((channel == 1 && fabs(nominal) > 3.0) || (channel != 1 && (nominal < 0 || nominal > 15.0))) quality = "out_of_range";
    }
    snprintf(sample->quality, sizeof(sample->quality), "%s", quality);
    xSemaphoreGive(measure_mutex);
}

/** AI:获取通道校准记录版本。@param channel 通道编号。@return 电池通道为INA226版本2，ADS1115仍为版本1。 */
static uint32_t calibration_format_version(int channel)
{
    return channel < 2 ? 2 : 1;
}

/** AI:初始化固定量程INA226，型号不匹配不解释其寄存器。@return 身份与配置回读均匹配时为真。 */
static bool configure_ina(void)
{
    uint8_t vendor[2], device[2], config[2];
    if (read_register(TOOL_INA226_ADDRESS, TOOL_INA226_REG_MANUFACTURER, vendor, 2) != ESP_OK ||
        read_register(TOOL_INA226_ADDRESS, TOOL_INA226_REG_DIE, device, 2) != ESP_OK) return false;
    if (!tool_ina226_identity(((uint16_t)vendor[0] << 8) | vendor[1], ((uint16_t)device[0] << 8) | device[1])) {
        char detail[96];
        snprintf(detail, sizeof(detail), "INA226型号不匹配，厂商=%02X%02X，芯片=%02X%02X", vendor[0], vendor[1], device[0], device[1]);
        tool_event("measurement", detail);
        return false;
    }
    /* AI:直接用SHUNT原始码换算电流，无需写芯片CAL寄存器；校准仍由六路系数管理。 */
    return write_register(TOOL_INA226_ADDRESS, TOOL_INA226_REG_CONFIG, TOOL_INA226_CONFIG) == ESP_OK &&
        read_register(TOOL_INA226_ADDRESS, TOOL_INA226_REG_CONFIG, config, 2) == ESP_OK &&
        (((uint16_t)config[0] << 8) | config[1]) == TOOL_INA226_CONFIG;
}

/** AI:按固定周期采样，转换等待不阻塞控制任务。@param arg 未使用。@return 不返回。 */
static void measurement_task(void *arg)
{
    (void)arg;
    vTaskDelay(pdMS_TO_TICKS(1200));
    while (true) {
        int64_t cycle_start = esp_timer_get_time();
        uint8_t bus[2], shunt[2];
        bool ina_ok = i2c_ready && ina_ready &&
            read_register(TOOL_INA226_ADDRESS, TOOL_INA226_REG_BUS, bus, 2) == ESP_OK &&
            read_register(TOOL_INA226_ADDRESS, TOOL_INA226_REG_SHUNT, shunt, 2) == ESP_OK;
        uint64_t t = esp_timer_get_time();
        double voltage = 0, current = 0;
        if (ina_ok) {
            voltage = tool_ina226_voltage(bus);
            current = tool_ina226_current(shunt);
        }
        /* AI:平均结果可能来自上一转换，按手册最大转换时间覆盖两轮并标明估计。 */
        uint64_t window = t > TOOL_INA226_WINDOW_US ? t - TOOL_INA226_WINDOW_US : 0;
        publish(0, voltage, ina_ok, t, window);
        publish(1, current, ina_ok, t, window);
        bool ads_cycle_ok = true;
        for (int channel = 0; channel < 4; channel++) {
            uint64_t start = esp_timer_get_time();
            uint16_t config = 0x8503 | ((4 + channel) << 12);
            bool ok = i2c_ready && write_register(0x48, 0x01, config) == ESP_OK;
            bool ready = false;
            uint8_t data[2];
            while (ok && esp_timer_get_time() - (int64_t)start < 220000) {
                vTaskDelay(pdMS_TO_TICKS(5));
                ok = read_register(0x48, 0x01, data, 2) == ESP_OK;
                if (ok && (data[0] & 0x80)) { ready = true; break; }
            }
            ok = ok && ready && read_register(0x48, 0x00, data, 2) == ESP_OK;
            double value = ok ? (int16_t)(((uint16_t)data[0] << 8) | data[1]) * 0.0006875 : 0;
            publish(channel + 2, value, ok, esp_timer_get_time(), start);
            ads_cycle_ok = ads_cycle_ok && ok;
        }
        ads_ready = ads_cycle_ok;
        int64_t remaining = 1000000 - (esp_timer_get_time() - cycle_start);
        if (remaining > 0) vTaskDelay(pdMS_TO_TICKS((remaining + 999) / 1000));
    }
}

esp_err_t tool_measure_init(void)
{
    measure_mutex = xSemaphoreCreateMutex();
    if (!measure_mutex) return ESP_ERR_NO_MEM;
    samples = heap_caps_calloc(TOOL_SAMPLE_CAPACITY, sizeof(sample_t), MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    if (!samples) return ESP_ERR_NO_MEM;
    nvs_handle_t handle;
    esp_err_t cal_open = g_nvs_ready ? nvs_open("calibration", NVS_READONLY, &handle) : ESP_ERR_INVALID_STATE;
    if (cal_open == ESP_OK) {
        for (int i = 0; i < 6; i++) {
            char key[8]; snprintf(key, sizeof(key), "ch%d", i);
            size_t size = sizeof(calibration_t);
            esp_err_t err = nvs_get_blob(handle, key, &calibration[i], &size);
            if (err == ESP_ERR_NVS_NOT_FOUND) continue;
            calibration_t *cal = &calibration[i];
            cal_state[i] = err == ESP_OK && size == sizeof(*cal) && cal->magic == 0x43414c31 && cal->version == calibration_format_version(i) && isfinite(cal->gain) && cal->gain > 0 && cal->gain <= 10 && isfinite(cal->offset) && isfinite(cal->min_value) && isfinite(cal->max_value) && cal->min_value <= cal->max_value && cal->reference[95] == '\0' && cal->crc == tool_crc32((const uint8_t *)cal, offsetof(calibration_t, crc)) ? 1 : -1;
        }
        nvs_close(handle);
    } else if (cal_open != ESP_ERR_NVS_NOT_FOUND) {
        for (int i = 0; i < 6; i++) cal_state[i] = -1;
        tool_event("calibration_error", "校准记录读取失败，不能解释为尚未校准");
    }
    i2c_config_t config = {.mode = I2C_MODE_MASTER, .sda_io_num = 9, .scl_io_num = 10,
        .sda_pullup_en = GPIO_PULLUP_ENABLE, .scl_pullup_en = GPIO_PULLUP_ENABLE, .master.clk_speed = 100000};
    esp_err_t err = i2c_param_config(I2C_NUM_0, &config);
    if (err == ESP_OK) err = i2c_driver_install(I2C_NUM_0, I2C_MODE_MASTER, 0, 0, 0);
    i2c_ready = err == ESP_OK;
    ina_ready = i2c_ready && configure_ina();
    if (!ina_ready) tool_event("measurement", "INA226初始化失败，读数标记无效");
    if (xTaskCreate(measurement_task, "tool_measure", 6144, NULL, 3, NULL) != pdPASS) return ESP_ERR_NO_MEM;
    return err;
}

cJSON *tool_measure_status(void)
{
    cJSON *out = cJSON_CreateObject();
    cJSON_AddBoolToObject(out, "i2c_ready", i2c_ready);
    cJSON_AddBoolToObject(out, "ina226_ready", ina_ready);
    cJSON_AddBoolToObject(out, "ads1115_ready", ads_ready);
    cJSON_AddBoolToObject(out, "hardware_accuracy_verified", false);
    return out;
}

cJSON *tool_measure_read(uint64_t after)
{
    cJSON *out = cJSON_CreateObject(), *items = cJSON_AddArrayToObject(out, "items");
    if (!samples || !measure_mutex) { cJSON_AddNumberToObject(out, "next", 0); cJSON_AddNumberToObject(out, "lost", 0); return out; }
    xSemaphoreTake(measure_mutex, portMAX_DELAY);
    uint64_t oldest = sample_next > TOOL_SAMPLE_CAPACITY ? sample_next - TOOL_SAMPLE_CAPACITY + 1 : 1;
    uint64_t start = after + 1 < oldest ? oldest : after + 1, next = after;
    cJSON_AddNumberToObject(out, "lost", after + 1 < oldest ? oldest - after - 1 : 0);
    for (uint64_t seq = start; seq <= sample_next && seq < start + 12; seq++) {
        sample_t *sample = &samples[(seq - 1) % TOOL_SAMPLE_CAPACITY];
        cJSON *item = cJSON_CreateObject();
        cJSON_AddNumberToObject(item, "seq", seq);
        cJSON_AddStringToObject(item, "boot_id", g_boot_id);
        cJSON_AddStringToObject(item, "channel", channel_names[sample->channel]);
        cJSON_AddStringToObject(item, "unit", sample->channel == 1 ? "A" : "V");
        if (sample->valid) {
            cJSON_AddNumberToObject(item, "value", sample->value);
            cJSON_AddNumberToObject(item, "nominal", sample->nominal);
        } else { cJSON_AddNullToObject(item, "value"); cJSON_AddNullToObject(item, "nominal"); }
        cJSON_AddNumberToObject(item, "t_us", sample->t_us);
        cJSON_AddNumberToObject(item, "window_start_us", sample->window_start_us);
        cJSON_AddBoolToObject(item, "window_estimated", sample->channel < 2);
        cJSON_AddStringToObject(item, "quality", sample->quality);
        cJSON_AddNumberToObject(item, "calibration_revision", sample->calibration_revision);
        cJSON_AddItemToArray(items, item);
        next = seq;
    }
    cJSON_AddNumberToObject(out, "next", next);
    xSemaphoreGive(measure_mutex);
    return out;
}

cJSON *tool_calibration_get(void)
{
    cJSON *out = cJSON_CreateObject(), *channels = cJSON_AddArrayToObject(out, "channels");
    if (!measure_mutex) return out;
    xSemaphoreTake(measure_mutex, portMAX_DELAY);
    for (int i = 0; i < 6; i++) {
        cJSON *item = cJSON_CreateObject();
        cJSON_AddStringToObject(item, "channel", channel_names[i]);
        cJSON_AddStringToObject(item, "state", cal_state[i] == 1 ? "calibrated" : cal_state[i] < 0 ? "invalid" : "uncalibrated");
        if (cal_state[i] == 1) {
            calibration_t *cal = &calibration[i];
            cJSON_AddNumberToObject(item, "gain", cal->gain);
            cJSON_AddNumberToObject(item, "offset", cal->offset);
            cJSON_AddNumberToObject(item, "min_value", cal->min_value);
            cJSON_AddNumberToObject(item, "max_value", cal->max_value);
            cJSON_AddNumberToObject(item, "revision", cal->revision);
            cJSON_AddStringToObject(item, "reference", cal->reference);
        }
        cJSON_AddItemToArray(channels, item);
    }
    xSemaphoreGive(measure_mutex);
    return out;
}

esp_err_t tool_calibration_set(const cJSON *params)
{
    const cJSON *channel = cJSON_GetObjectItemCaseSensitive(params, "channel");
    const cJSON *reference = cJSON_GetObjectItemCaseSensitive(params, "reference");
    if (!cJSON_IsString(channel) || !cJSON_IsString(reference) || !reference->valuestring[0] || strlen(reference->valuestring) > 95 || !measure_mutex) return ESP_ERR_INVALID_ARG;
    int index = -1;
    for (int i = 0; i < 6; i++) if (!strcmp(channel->valuestring, channel_names[i])) index = i;
    calibration_t cal = {.magic = 0x43414c31, .version = 1};
    if (index < 0 || !finite_number(params, "gain", &cal.gain) || !finite_number(params, "offset", &cal.offset) || !finite_number(params, "min_value", &cal.min_value) || !finite_number(params, "max_value", &cal.max_value) || cal.gain <= 0 || cal.gain > 10 || fabs(cal.offset) > 20 || cal.min_value > cal.max_value || cal.min_value < (index == 1 ? -3 : 0) || cal.max_value > (index == 1 ? 3 : 15)) return ESP_ERR_INVALID_ARG;
    cal.version = calibration_format_version(index);
    if (!g_nvs_ready) return ESP_ERR_INVALID_STATE;
    snprintf(cal.reference, sizeof(cal.reference), "%s", reference->valuestring);
    xSemaphoreTake(measure_mutex, portMAX_DELAY);
    cal.revision = cal_state[index] == 1 ? calibration[index].revision + 1 : 1;
    cal.crc = tool_crc32((const uint8_t *)&cal, offsetof(calibration_t, crc));
    nvs_handle_t handle;
    esp_err_t err = nvs_open("calibration", NVS_READWRITE, &handle);
    if (err == ESP_OK) {
        char key[] = "ch0";
        key[2] = (char)('0' + index);
        err = nvs_set_blob(handle, key, &cal, sizeof(cal));
        if (err == ESP_OK) err = nvs_commit(handle);
        nvs_close(handle);
    }
    if (err == ESP_OK) { calibration[index] = cal; cal_state[index] = 1; }
    xSemaphoreGive(measure_mutex);
    return err;
}
