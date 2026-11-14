#ifndef TOOL_INA226_H
#define TOOL_INA226_H

#include <stdbool.h>
#include <stdint.h>

/* AI:按TI SBOS547C第22～24页，当前实板固定使用INA226和20mΩ分流器。 */
#define TOOL_INA226_ADDRESS 0x40
#define TOOL_INA226_REG_CONFIG 0x00
#define TOOL_INA226_REG_SHUNT 0x01
#define TOOL_INA226_REG_BUS 0x02
#define TOOL_INA226_REG_MANUFACTURER 0xfe
#define TOOL_INA226_REG_DIE 0xff
#define TOOL_INA226_CONFIG 0x456f /**< AI:保留位=100、16次平均、双通道各2116µs，最长74.496ms内产生新结果。 */
#define TOOL_INA226_SHUNT_OHMS 0.020 /**< AI:原板20mΩ分流器，不通过软件换档。 */
#define TOOL_INA226_CURRENT_LSB_A 0.000125 /**< AI:2.5µV除以20mΩ，125µA/码，不代表准确度。 */
#define TOOL_INA226_BUS_LSB_V 0.00125 /**< AI:VBUS寄存器1.25mV/码，不代表准确度。 */
#define TOOL_INA226_WINDOW_US 149000ULL /**< AI:读取连续平均寄存器时覆盖两轮，按单次最大2328µs估计结果最早来源。 */

/** AI:检查官方支持的芯片身份。@param vendor 厂商标识。@param die 芯片标识。@return 仅INA226的2260/2261为真。 */
static inline bool tool_ina226_identity(uint16_t vendor, uint16_t die)
{
    return vendor == 0x5449 && (die == 0x2260 || die == 0x2261);
}

/** AI:换算大端VBUS原始码。@param data 寄存器的两个字节。@return 未校准名义电压，单位V。 */
static inline double tool_ina226_voltage(const uint8_t data[2])
{
    return (((uint16_t)data[0] << 8) | data[1]) * TOOL_INA226_BUS_LSB_V;
}

/** AI:按补码换算双向分流电流。@param data SHUNT寄存器的两个字节。@return 未校准名义电流，单位A，正值向设备供电。 */
static inline double tool_ina226_current(const uint8_t data[2])
{
    uint16_t raw = ((uint16_t)data[0] << 8) | data[1];
    int32_t signed_raw = raw & 0x8000 ? (int32_t)raw - 65536 : raw;
    return signed_raw * TOOL_INA226_CURRENT_LSB_A;
}

#endif
