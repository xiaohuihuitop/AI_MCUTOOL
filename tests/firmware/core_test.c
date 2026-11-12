#include <assert.h>
#include <stdio.h>
#include "tool_core.h"

/** AI:验证启动、互锁、取消和失联行为。@return 0 表示全部断言通过。 */
int main(void)
{
    tool_core_t core;
    tool_core_init(&core);
    assert(core.power == TOOL_POWER_OFF && !core.charge && core.keys == 0);
    assert(tool_core_claim(&core, "pc-a", false, 0, 0) == TOOL_OK);
    uint32_t action = 0;
    assert(tool_core_power(&core, TOOL_POWER_BATTERY, 0, &action) == TOOL_OK);
    assert(core.power == TOOL_POWER_OFF);
    tool_core_tick(&core, 99);
    assert(core.power == TOOL_POWER_OFF);
    tool_core_tick(&core, 100);
    assert(core.power == TOOL_POWER_BATTERY);
    assert(tool_core_charge(&core, true) == TOOL_OK);
    assert(tool_core_power(&core, TOOL_POWER_EXTERNAL, 101, &action) == TOOL_INTERLOCK);
    assert(tool_core_power(&core, TOOL_POWER_OFF, 101, &action) == TOOL_INTERLOCK);
    assert(core.power == TOOL_POWER_BATTERY && core.charge);
    assert(tool_core_charge(&core, false) == TOOL_OK);
    tool_key_step_t steps[] = {{3, 20}, {0, 10}, {16, 30}};
    assert(tool_core_keys(&core, steps, 3, 2, 200, &action) == TOOL_OK);
    assert(core.keys == 3);
    tool_core_tick(&core, 219);
    assert(core.keys == 3);
    tool_core_tick(&core, 220);
    assert(core.keys == 0);
    tool_core_tick(&core, 230);
    assert(core.keys == 16);
    assert(tool_core_cancel(&core, action, 231) == TOOL_OK);
    assert(core.keys == 0 && core.power == TOOL_POWER_BATTERY);
    assert(tool_core_action(&core, action)->state == TOOL_ACTION_CANCELLED);
    tool_key_step_t long_step = {1, 5000};
    assert(tool_core_keys(&core, &long_step, 1, 1, 59000, &action) == TOOL_OK);
    tool_core_tick(&core, 60001);
    assert(tool_core_owner(&core, "pc-a", 60001) == TOOL_OWNER_EXPIRED);
    assert(core.keys == 1 && core.power == TOOL_POWER_BATTERY);
    assert(tool_core_claim(&core, "pc-b", true, core.revision, 60001) == TOOL_BUSY);
    tool_core_tick(&core, 64000);
    assert(core.keys == 0);
    assert(tool_core_claim(&core, "pc-b", true, core.revision - 1, 64001) == TOOL_STALE_STATE);
    assert(tool_core_claim(&core, "pc-b", true, core.revision, 64001) == TOOL_OK);
    assert(tool_core_owner(&core, "pc-a", 64001) == TOOL_NOT_OWNER);
    assert(tool_core_power(&core, TOOL_POWER_EXTERNAL, 65000, &action) == TOOL_OK);
    assert(core.power == TOOL_POWER_OFF);
    assert(tool_core_charge(&core, true) == TOOL_INTERLOCK);
    tool_core_tick(&core, 65100);
    assert(core.power == TOOL_POWER_EXTERNAL);
    assert(tool_core_charge(&core, true) == TOOL_INTERLOCK);
    puts("core: all behavior checks passed");
    return 0;
}
