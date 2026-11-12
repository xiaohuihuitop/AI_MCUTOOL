#include "ina226.h"
#include <assert.h>
#include <math.h>
#include <stdio.h>

/** AI:以手册和20mΩ电路对应的已知物理点验证生产换算函数。@return 断言通过时返回0。 */
int main(void)
{
    const uint8_t positive_3a[] = {0x5d, 0xc0}, negative_3a[] = {0xa2, 0x40};
    const uint8_t negative_80mv[] = {0x83, 0x00}; /* AI:TI手册第24页给出的负80mV补码示例。 */
    const uint8_t positive_lsb[] = {0x00, 0x01}, negative_lsb[] = {0xff, 0xff}, zero[] = {0x00, 0x00};
    const uint8_t battery_4v[] = {0x0c, 0x80}, bus_15v[] = {0x2e, 0xe0};
    assert(fabs(tool_ina226_current(positive_3a) - 3.0) < 1e-12);
    assert(fabs(tool_ina226_current(negative_3a) + 3.0) < 1e-12);
    assert(fabs(tool_ina226_current(negative_80mv) + 4.0) < 1e-12);
    assert(fabs(tool_ina226_current(positive_lsb) - 0.000125) < 1e-12);
    assert(fabs(tool_ina226_current(negative_lsb) + 0.000125) < 1e-12);
    assert(tool_ina226_current(zero) == 0 && tool_ina226_voltage(zero) == 0);
    assert(fabs(tool_ina226_voltage(battery_4v) - 4.0) < 1e-12);
    assert(fabs(tool_ina226_voltage(bus_15v) - 15.0) < 1e-12);
    assert(fabs(tool_ina226_voltage(positive_lsb) - 0.00125) < 1e-12);
    assert(tool_ina226_identity(0x5449, 0x2260) && tool_ina226_identity(0x5449, 0x2261));
    assert(!tool_ina226_identity(0x5449, 0x2280) && !tool_ina226_identity(0x5449, 0x226f));
    assert(!tool_ina226_identity(0xffff, 0x2260));
    puts("INA226 signed current and bus voltage conversion: passed");
    return 0;
}
