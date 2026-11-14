#ifndef TOOL_RUNTIME_H
#define TOOL_RUNTIME_H

#include "tool_core.h"
#include "cJSON.h"
#include "esp_err.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"

#define TOOL_GPIO_KEYS_MASK ((1ULL<<4)|(1ULL<<5)|(1ULL<<6)|(1ULL<<7)|(1ULL<<8)) /**< AI:五路触点驱动，高有效。 */
#define TOOL_FRAME_MAX 32768 /**< AI:USB与HTTP共用的JSON最大字节数。 */
#define TOOL_UART_CAPACITY 262144 /**< AI:目标串口原始接收环形缓存容量。 */
#define TOOL_SAMPLE_CAPACITY 8192 /**< AI:六路10Hz共享约136秒的通信缓存，完整长时间记录由电脑保存。 */

extern tool_core_t g_core;
extern SemaphoreHandle_t g_core_mutex;
extern char g_device_id[32];
extern char g_boot_id[33];
extern bool g_nvs_ready;

/** AI:计算协议IEEE CRC32。@param data 字节。@param size 长度。@return CRC32。 */
uint32_t tool_crc32(const uint8_t *data, size_t size);

/** AI:设置业务GPIO默认状态并启动本地时序。@return 初始化错误代码。 */
esp_err_t tool_board_init(void);
/** AI:将当前控制状态应用于GPIO，调用前持有核心锁。@return 无。 */
void tool_board_apply(void);
/** AI:构建控制状态快照。@return 调用者释放的JSON。 */
cJSON *tool_board_status(void);
/** AI:保存有限事件。@param name 事件类型。@param detail 中文说明。@return 无。 */
void tool_event(const char *name, const char *detail);
/** AI:读取事件历史。@param after 最后已读序号。@return 调用者释放的JSON。 */
cJSON *tool_events_read(uint64_t after);
/** AI:初始化测量与校准模块。@return 初始化错误，不影响业务输出。 */
esp_err_t tool_measure_init(void);
/** AI:读取测量历史。@param after 最后已读序号。@return 有数据和缺失信息的JSON。 */
cJSON *tool_measure_read(uint64_t after);
/** AI:获取传感器健康状态。@return 调用者释放的JSON。 */
cJSON *tool_measure_status(void);
/** AI:读取全部校准记录。@return 调用者释放的JSON。 */
cJSON *tool_calibration_get(void);
/** AI:保存一个通道校准。@param params 参数。@return 成功ESP_OK，参数或存储错误不修改已有记录。 */
esp_err_t tool_calibration_set(const cJSON *params);
/** AI:初始化目标串口，TX保持高阻。@return 初始化错误代码。 */
esp_err_t tool_uart_init(void);
/** AI:改变目标串口速率，要求TX禁用。@param baud 波特率。@return 错误代码。 */
esp_err_t tool_uart_configure(int baud);
/** AI:显式启禁TX。@param enabled 是否启用。@return 禁用等待超时返回ESP_ERR_TIMEOUT。 */
esp_err_t tool_uart_tx(bool enabled);
/** AI:发送目标原始字节并等待硬件发送完毕。@param hex 十六进制字节。@return 错误代码，不表示对端处理结果。 */
esp_err_t tool_uart_write(const char *hex);
/** AI:获取目标串口状态。@return 调用者释放的JSON。 */
cJSON *tool_uart_status(void);
/** AI:读取目标串口字节历史。@param after 已读字节位置。@return 字节块与缺失信息JSON。 */
cJSON *tool_uart_read(uint64_t after);
/** AI:初始化Wi-Fi及HTTP命令入口。@return 初始化错误代码。 */
esp_err_t tool_network_init(void);
/** AI:进入人工配网热点。@return 无，错误记录到事件。 */
void tool_network_provision(void);
/** AI:读取网络状态。@param include_token 是否允许物理USB读取配对令牌。@return JSON。 */
cJSON *tool_network_status(bool include_token);
/** AI:保存Wi-Fi并安排一次连接。@param ssid 网络名称。@param password 密码。@return 错误代码。 */
esp_err_t tool_network_configure(const char *ssid, const char *password);
/** AI:显式连接已保存网络。@return 错误代码。 */
esp_err_t tool_network_connect(void);
/** AI:查询联网状态用于指示灯。@return 配网为1，联网为2，其他为0。 */
int tool_network_indicator(void);
/** AI:处理完整RPC，USB与HTTP共用。@param request 输入JSON。@param usb 是否物理USB入口。@return 响应JSON。 */
cJSON *tool_rpc(const cJSON *request, bool usb);
/** AI:初始化命令互斥和USB串口任务。@return 初始化错误。 */
esp_err_t tool_rpc_init(void);

#endif
