#include "tool_runtime.h"
#include "nvs_flash.h"

/** AI:按安全输出、存储、采集、命令及网络的顺序启动工具。@return 无。 */
void app_main(void)
{
    if (tool_board_init() != ESP_OK) return;
    /* AI:NVS损坏时保留数据并报告，不擦除校准和配网记录作为兜底。 */
    g_nvs_ready = nvs_flash_init() == ESP_OK;
    if (!g_nvs_ready) tool_event("storage_error", "NVS不可用，未擦除已有记录；校准和网络写入不可用");
    if (tool_measure_init() != ESP_OK) tool_event("measurement_error", "测量模块初始化未完成");
    if (tool_uart_init() != ESP_OK) tool_event("uart_error", "目标UART初始化未完成，TX保持高阻");
    if (tool_rpc_init() != ESP_OK) { tool_event("usb_error", "USB命令入口初始化失败"); return; }
    if (tool_network_init() != ESP_OK) tool_event("network_error", "网络模块初始化未完成，请通过USB查看状态");
    tool_event("boot", "工具已启动，业务输出关闭，UART发送禁用");
}
