#include <assert.h>
#include <stdio.h>
#include "tool_core.h"

/** AI:验证充电循环的实际控制段长、完成次数、独立运行和取消互锁。@return 无，失败由断言终止。 */
static void test_charge_cycle(void)
{
    tool_core_t core;
    uint32_t id, other;
    tool_core_init(&core);
    assert(tool_core_charge_run(&core, 200, 500, 2, 0, &id) == TOOL_INTERLOCK);
    assert(tool_core_claim(&core, "pc", false, 0, 0) == TOOL_OK);
    assert(tool_core_power(&core, TOOL_POWER_BATTERY, 0, &other) == TOOL_OK);
    assert(tool_core_charge_run(&core, 200, 500, 2, 99, &id) == TOOL_BUSY);
    tool_core_tick(&core, 100);
    assert(tool_core_charge_run(&core, 0, 500, 2, 100, &id) == TOOL_INVALID);
    assert(tool_core_charge_run(&core, 200, 500, 1000, 100, &id) == TOOL_INVALID);
    assert(tool_core_charge(&core, true) == TOOL_OK);
    assert(tool_core_charge_run(&core, 200, 500, 2, 100, &id) == TOOL_INTERLOCK);
    assert(tool_core_charge(&core, false) == TOOL_OK);
    assert(tool_core_charge_run(&core, 200, 500, 2, 59900, &id) == TOOL_OK);
    const tool_action_t *a = tool_core_action(&core, id);
    assert(core.charge && a->kind == TOOL_KIND_CHARGE);
    tool_core_tick(&core, 60099);
    assert(core.charge && tool_core_owner(&core, "pc", 60099) == TOOL_OWNER_EXPIRED);
    tool_core_tick(&core, 60103);
    assert(!core.charge && a->cycle.completed == 0 && a->cycle.max_on_ms == 203);
    assert(tool_core_claim(&core, "other", true, core.revision, 60103) == TOOL_BUSY);
    assert(tool_core_charge(&core, true) == TOOL_BUSY);
    assert(tool_core_power(&core, TOOL_POWER_EXTERNAL, 60103, &other) == TOOL_BUSY);
    assert(tool_core_charge_run(&core, 200, 500, 1, 60103, &other) == TOOL_BUSY);
    assert(tool_core_cancel(&core, id, 60103) == TOOL_INVALID);
    tool_core_tick(&core, 60602);
    assert(!core.charge);
    tool_core_tick(&core, 60603);
    assert(core.charge && a->cycle.completed == 1);
    tool_core_tick(&core, 60803);
    tool_core_tick(&core, 61305);
    assert(!core.charge && !tool_core_busy(&core) && a->state == TOOL_ACTION_SUCCEEDED);
    assert(a->cycle.completed == 2 && a->cycle.min_on_ms == 200 && a->cycle.max_on_ms == 203);
    assert(a->cycle.min_off_ms == 500 && a->cycle.max_off_ms == 502);
    assert(tool_core_charge_cancel(&core, other, 61306) == TOOL_INVALID);
    for (int off_phase = 0; off_phase <= 1; off_phase++) {
        uint64_t start = 62000 + off_phase * 1000;
        assert(tool_core_charge_run(&core, 200, 500, 1, start, &other) == TOOL_OK);
        if (off_phase) tool_core_tick(&core, start + 200);
        assert(tool_core_charge_cancel(&core, other, start + 210) == TOOL_OK);
        assert(tool_core_charge_cancel(&core, other, start + 211) == TOOL_OK);
        assert(!core.charge && !tool_core_busy(&core));
        assert(tool_core_action(&core, other)->state == TOOL_ACTION_CANCELLED);
        assert(tool_core_action(&core, other)->cycle.completed == 0);
        tool_core_tick(&core, start + 900);
        assert(!core.charge);
    }
}

/** AI:按实际控制时刻核对三路组合、保护间隔、断线自主执行和指定收尾状态。@return 无。 */
static void test_output_sequence(void)
{
    tool_core_t c;
    uint32_t id, other;
    tool_core_init(&c);
    const tool_output_step_t unsafe[] = {{OUTPUT_BATTERY, 100}, {OUTPUT_OFF, 99}, {OUTPUT_EXTERNAL, 100}};
    assert(tool_outputs_run(&c, unsafe, 3, 1, OUTPUT_OFF, OUTPUT_OFF, 0, &id) == TOOL_INTERLOCK);
    const tool_output_step_t wrap[] = {{OUTPUT_BATTERY, 100}, {OUTPUT_OFF, 100}, {OUTPUT_EXTERNAL, 100}};
    assert(tool_outputs_run(&c, wrap, 3, 2, OUTPUT_OFF, OUTPUT_OFF, 0, &id) == TOOL_INTERLOCK);
    assert(!tool_core_busy(&c) && !c.charge && c.power == TOOL_POWER_OFF && c.next_action == 0);
    const tool_output_step_t steps[] = {{OUTPUT_BATTERY, 50}, {OUTPUT_CHARGING, 200}, {OUTPUT_OFF, 100},
                                         {OUTPUT_EXTERNAL, 75}, {OUTPUT_OFF, 100}};
    assert(tool_outputs_run(&c, steps, 5, 2, OUTPUT_BATTERY, OUTPUT_EXTERNAL, 60000, &id) == TOOL_OK);
    const tool_action_t *a = tool_core_action(&c, id);
    assert(a->sequence.settling);
    assert(tool_core_power(&c, TOOL_POWER_EXTERNAL, 60000, &other) == TOOL_BUSY);
    assert(tool_core_charge(&c, true) == TOOL_BUSY);
    assert(tool_core_charge_run(&c, 200, 500, 1, 60000, &other) == TOOL_BUSY);
    assert(tool_core_cancel(&c, id, 60000) == TOOL_INVALID);
    assert(tool_core_charge_cancel(&c, id, 60000) == TOOL_INVALID);
    tool_core_tick(&c, 60099);
    assert(c.power == TOOL_POWER_OFF);
    uint64_t base = 60100;
    tool_core_tick(&c, base);
    for (unsigned i = 0; i < 2; i++) {
        assert(c.power == TOOL_POWER_BATTERY && !c.charge);
        tool_core_tick(&c, base + 50);
        assert(c.power == TOOL_POWER_BATTERY && c.charge);
        tool_core_tick(&c, base + 249);
        assert(c.charge);
        tool_core_tick(&c, base + 252);
        assert(c.power == TOOL_POWER_OFF && !c.charge);
        tool_core_tick(&c, base + 351);
        assert(c.power == TOOL_POWER_OFF);
        tool_core_tick(&c, base + 352);
        assert(c.power == TOOL_POWER_EXTERNAL && !c.charge);
        tool_core_tick(&c, base + 427);
        assert(c.power == TOOL_POWER_OFF);
        base += 527;
        tool_core_tick(&c, base);
    }
    assert(a->state == TOOL_ACTION_SUCCEEDED && a->sequence.completed == 2 && a->sequence.max_late_ms == 2);
    assert(c.power == TOOL_POWER_BATTERY && !c.charge && !tool_core_busy(&c));
    assert(tool_outputs_run(&c, steps, 5, 1, OUTPUT_OFF, OUTPUT_EXTERNAL, base, &id) == TOOL_OK);
    tool_core_tick(&c, base + 50);
    assert(c.charge);
    assert(tool_outputs_cancel(&c, id, base + 55) == TOOL_OK);
    assert(!c.charge && c.power == TOOL_POWER_OFF && tool_core_busy(&c));
    assert(tool_outputs_cancel(&c, id, base + 100) == TOOL_OK);
    tool_core_tick(&c, base + 154);
    assert(c.power == TOOL_POWER_OFF);
    tool_core_tick(&c, base + 155);
    assert(!tool_core_busy(&c) && c.power == TOOL_POWER_EXTERNAL);
    assert(tool_core_action(&c,id)->state == TOOL_ACTION_CANCELLED);
    assert(tool_outputs_cancel(&c, id, base + 156) == TOOL_OK);
    const tool_output_step_t external[] = {{OUTPUT_EXTERNAL, 50}};
    assert(tool_outputs_run(&c, external, 1, 1, OUTPUT_CHARGING, OUTPUT_OFF, base + 200, &id) == TOOL_OK);
    tool_core_tick(&c, base + 250);
    assert(tool_core_busy(&c) && c.power == TOOL_POWER_OFF && !c.charge);
    tool_core_tick(&c, base + 350);
    assert(!tool_core_busy(&c) && c.power == TOOL_POWER_BATTERY && c.charge);
}

/** AI:验证启动、互锁、取消和失联行为。@return 0 表示全部断言通过。 */
int main(void)
{
    test_charge_cycle();
    test_output_sequence();
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
