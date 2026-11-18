#include "tool_core.h"
#include <string.h>

/** AI:分配动作记录。@param c 实例。@param kind 动作类型。@param now 开始时刻。@return 记录下标。 */
static int allocate_action(tool_core_t *c, tool_action_kind_t kind, uint64_t now)
{
    int slot = -1;
    uint32_t oldest = UINT32_MAX;
    for (int i = 0; i < TOOL_MAX_ACTIONS; i++) {
        if (i != c->key_slot && i != c->power_slot && i != c->charge_slot && c->actions[i].id < oldest) {
            oldest = c->actions[i].id;
            slot = i;
        }
    }
    if (slot >= 0) {
        c->actions[slot] = (tool_action_t){.id = ++c->next_action, .kind = kind,
            .state = TOOL_ACTION_RUNNING, .started_ms = now};
    }
    return slot;
}

void tool_core_init(tool_core_t *c)
{
    memset(c, 0, sizeof(*c));
    c->key_slot = c->power_slot = c->charge_slot = -1;
    c->deadtime_ms = 100; /* AI:工程初值，必须通过实际MOS关断波形确认。 */
}

bool tool_core_busy(const tool_core_t *c)
{
    return c->key_slot >= 0 || c->power_slot >= 0 || c->charge_slot >= 0;
}

tool_result_t tool_core_owner(const tool_core_t *c, const char *owner, uint64_t now)
{
    if (!owner || !owner[0] || strcmp(c->owner, owner)) return TOOL_NOT_OWNER;
    return now >= c->owner_deadline_ms ? TOOL_OWNER_EXPIRED : TOOL_OK;
}

tool_result_t tool_core_claim(tool_core_t *c, const char *owner, bool takeover, uint32_t revision, uint64_t now)
{
    if (!owner || !owner[0] || strlen(owner) > 64) return TOOL_INVALID;
    if (c->owner[0]) {
        if (!strcmp(c->owner, owner) && now < c->owner_deadline_ms) {
            c->owner_deadline_ms = now + TOOL_OWNER_TTL_MS;
            return TOOL_OK;
        }
        if (!takeover) return TOOL_NOT_OWNER;
        if (tool_core_busy(c)) return TOOL_BUSY;
        if (revision != c->revision) return TOOL_STALE_STATE;
    }
    strcpy(c->owner, owner);
    c->owner_deadline_ms = now + TOOL_OWNER_TTL_MS;
    c->revision++;
    return TOOL_OK;
}

tool_result_t tool_core_renew(tool_core_t *c, const char *owner, uint64_t now)
{
    tool_result_t result = tool_core_owner(c, owner, now);
    if (result == TOOL_OK) c->owner_deadline_ms = now + TOOL_OWNER_TTL_MS;
    return result;
}

tool_result_t tool_core_release(tool_core_t *c, const char *owner, uint64_t now)
{
    tool_result_t result = tool_core_owner(c, owner, now);
    if (result != TOOL_OK) return result;
    if (tool_core_busy(c)) return TOOL_BUSY;
    c->owner[0] = '\0';
    c->owner_deadline_ms = 0;
    c->revision++;
    return TOOL_OK;
}

tool_result_t tool_core_power(tool_core_t *c, tool_power_t source, uint64_t now, uint32_t *id)
{
    if (source < TOOL_POWER_OFF || source > TOOL_POWER_EXTERNAL || !id) return TOOL_INVALID;
    if (c->power_slot >= 0 || c->charge_slot >= 0) return TOOL_BUSY;
    if (c->charge && source != TOOL_POWER_BATTERY) return TOOL_INTERLOCK;
    int slot = allocate_action(c, TOOL_KIND_POWER, now);
    if (slot < 0) return TOOL_BUSY;
    *id = c->actions[slot].id;
    if (c->power == source) {
        c->actions[slot].state = TOOL_ACTION_SUCCEEDED;
        c->actions[slot].finished_ms = now;
        return TOOL_OK;
    }
    c->power = TOOL_POWER_OFF;
    c->pending_power = source;
    c->revision++;
    if (source == TOOL_POWER_OFF) {
        c->actions[slot].state = TOOL_ACTION_SUCCEEDED;
        c->actions[slot].finished_ms = now;
    } else {
        c->power_slot = slot;
        c->power_deadline_ms = now + c->deadtime_ms;
    }
    return TOOL_OK;
}

tool_result_t tool_core_charge(tool_core_t *c, bool enabled)
{
    if (c->charge_slot >= 0) return TOOL_BUSY;
    if (enabled && (c->power != TOOL_POWER_BATTERY || c->power_slot >= 0)) return TOOL_INTERLOCK;
    if (c->charge != enabled) c->revision++;
    c->charge = enabled;
    return TOOL_OK;
}

tool_result_t tool_core_charge_run(tool_core_t *c, uint32_t on_ms, uint32_t off_ms, uint32_t count, uint64_t now, uint32_t *id)
{
    if (!id || on_ms < 10 || on_ms > 60000 || off_ms < 10 || off_ms > 60000 || !count || count > 1000 ||
        (uint64_t)(on_ms + off_ms) * count > TOOL_MAX_SEQUENCE_MS) return TOOL_INVALID;
    if (c->charge_slot >= 0 || c->power_slot >= 0) return TOOL_BUSY;
    if (c->power != TOOL_POWER_BATTERY || c->charge) return TOOL_INTERLOCK;
    int slot = allocate_action(c, TOOL_KIND_CHARGE, now);
    if (slot < 0) return TOOL_BUSY;
    c->actions[slot].cycle = (tool_charge_cycle_t){.on_ms = on_ms, .off_ms = off_ms, .count = count,
        .phase_start_ms = now, .on = true};
    c->charge_slot = slot;
    c->charge = true;
    c->revision++;
    *id = c->actions[slot].id;
    return TOOL_OK;
}

tool_result_t tool_core_charge_cancel(tool_core_t *c, uint32_t id, uint64_t now)
{
    const tool_action_t *action = tool_core_action(c, id);
    if (!action) return TOOL_NOT_FOUND;
    if (action->kind != TOOL_KIND_CHARGE) return TOOL_INVALID;
    if (action->state != TOOL_ACTION_RUNNING) return TOOL_OK;
    tool_action_t *active = &c->actions[c->charge_slot];
    active->state = TOOL_ACTION_CANCELLED;
    active->finished_ms = now;
    active->cycle.on = false;
    c->charge = false;
    c->charge_slot = -1;
    c->revision++;
    return TOOL_OK;
}

/** AI:每次最多执行一次真实切换，调度延迟不压缩下一段。@param c 实例。@param now 锁内读取的单调毫秒。@return 无。 */
static void tick_charge(tool_core_t *c, uint64_t now)
{
    if (c->charge_slot < 0) return;
    tool_action_t *action = &c->actions[c->charge_slot];
    tool_charge_cycle_t *cycle = &action->cycle;
    uint32_t target = cycle->on ? cycle->on_ms : cycle->off_ms;
    if (now < cycle->phase_start_ms + target) return;
    uint32_t elapsed = (uint32_t)(now - cycle->phase_start_ms);
    uint32_t *min_ms = cycle->on ? &cycle->min_on_ms : &cycle->min_off_ms;
    uint32_t *max_ms = cycle->on ? &cycle->max_on_ms : &cycle->max_off_ms;
    if (!*min_ms || elapsed < *min_ms) *min_ms = elapsed;
    if (elapsed > *max_ms) *max_ms = elapsed;
    if (!cycle->on) cycle->completed++;
    if (cycle->completed == cycle->count) {
        action->state = TOOL_ACTION_SUCCEEDED;
        action->finished_ms = now;
        c->charge_slot = -1;
    } else {
        cycle->on = !cycle->on;
        cycle->phase_start_ms = now;
        c->charge = cycle->on;
    }
    c->revision++;
}

tool_result_t tool_core_keys(tool_core_t *c, const tool_key_step_t *steps, size_t count, uint32_t repeat, uint64_t now, uint32_t *id)
{
    if (!steps || !id || !count || count > TOOL_MAX_STEPS || !repeat || repeat > 1000) return TOOL_INVALID;
    if (c->key_slot >= 0) return TOOL_BUSY;
    uint64_t duration = 0;
    for (size_t i = 0; i < count; i++) {
        if (steps[i].mask > 31 || steps[i].duration_ms < 10 || steps[i].duration_ms > 60000) return TOOL_INVALID;
        duration += steps[i].duration_ms;
    }
    if (duration * repeat > TOOL_MAX_SEQUENCE_MS) return TOOL_INVALID;
    int slot = allocate_action(c, TOOL_KIND_KEYS, now);
    if (slot < 0) return TOOL_BUSY;
    memcpy(c->steps, steps, count * sizeof(*steps));
    c->step_count = count;
    c->step_index = 0;
    c->repeats_left = repeat;
    c->key_slot = slot;
    c->keys = steps[0].mask;
    c->key_deadline_ms = now + steps[0].duration_ms;
    c->revision++;
    *id = c->actions[slot].id;
    return TOOL_OK;
}

void tool_core_tick(tool_core_t *c, uint64_t now)
{
    tick_charge(c, now);
    if (c->power_slot >= 0 && now >= c->power_deadline_ms) {
        c->power = c->pending_power;
        c->actions[c->power_slot].state = TOOL_ACTION_SUCCEEDED;
        c->actions[c->power_slot].finished_ms = now;
        c->power_slot = -1;
        c->revision++;
    }
    if (c->key_slot < 0 || now < c->key_deadline_ms) return;
    c->step_index++;
    if (c->step_index == c->step_count) {
        c->step_index = 0;
        c->repeats_left--;
    }
    if (!c->repeats_left) {
        c->keys = 0;
        c->actions[c->key_slot].state = TOOL_ACTION_SUCCEEDED;
        c->actions[c->key_slot].finished_ms = now;
        c->key_slot = -1;
    } else {
        c->keys = c->steps[c->step_index].mask;
        /* AI:调度延迟时延后后续步骤，不压缩下一步形成过短实体按键。 */
        c->key_deadline_ms = now + c->steps[c->step_index].duration_ms;
    }
    c->revision++;
}

const tool_action_t *tool_core_action(const tool_core_t *c, uint32_t id)
{
    for (int i = 0; i < TOOL_MAX_ACTIONS; i++) if (id && c->actions[i].id == id) return &c->actions[i];
    return NULL;
}

tool_result_t tool_core_cancel(tool_core_t *c, uint32_t id, uint64_t now)
{
    const tool_action_t *action = tool_core_action(c, id);
    if (!action) return TOOL_NOT_FOUND;
    if (action->kind != TOOL_KIND_KEYS) return TOOL_INVALID;
    if (action->state != TOOL_ACTION_RUNNING) return TOOL_OK;
    c->actions[c->key_slot].state = TOOL_ACTION_CANCELLED;
    c->actions[c->key_slot].finished_ms = now;
    c->key_slot = -1;
    c->keys = 0;
    c->revision++;
    return TOOL_OK;
}
