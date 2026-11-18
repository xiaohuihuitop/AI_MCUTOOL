#ifndef TOOL_CORE_H
#define TOOL_CORE_H

#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>

#define TOOL_MAX_STEPS 128       /**< AI:单段按键序列最大步数。 */
#define TOOL_MAX_ACTIONS 32      /**< AI:保留的动作记录数量，不覆盖正在执行的记录。 */
#define TOOL_OWNER_TTL_MS 60000  /**< AI:写入会话活性期限，失效不改变输出。 */
#define TOOL_MAX_SEQUENCE_MS 600000 /**< AI:整段序列最长十分钟。 */

typedef enum { TOOL_OK, TOOL_INVALID, TOOL_BUSY, TOOL_INTERLOCK, TOOL_NOT_OWNER,
               TOOL_OWNER_EXPIRED, TOOL_STALE_STATE, TOOL_NOT_FOUND } tool_result_t;
typedef enum { TOOL_POWER_OFF, TOOL_POWER_BATTERY, TOOL_POWER_EXTERNAL } tool_power_t;
typedef enum { TOOL_ACTION_RUNNING, TOOL_ACTION_SUCCEEDED, TOOL_ACTION_CANCELLED } tool_action_state_t;
typedef enum { TOOL_KIND_POWER, TOOL_KIND_KEYS, TOOL_KIND_CHARGE, TOOL_KIND_OUTPUTS } tool_action_kind_t;
typedef enum { OUTPUT_OFF, OUTPUT_BATTERY, OUTPUT_EXTERNAL, OUTPUT_CHARGING } tool_output_t;
typedef struct { tool_output_t output; uint32_t duration_ms; } tool_output_step_t;
typedef struct {
    uint32_t index, completed, repeat, step_count, max_late_ms;
    tool_output_t output; /**< AI:当前实际命令状态，换源保护期间为全断。 */
    bool settling; /**< AI:正在等待换源保护间隔，此时尚未开始计算下一步时长。 */
} tool_output_progress_t;
typedef struct {
    uint32_t on_ms, off_ms, count, completed; /**< AI:目标时长、目标次数及已走完断开段的次数。 */
    uint32_t min_on_ms, max_on_ms, min_off_ms, max_off_ms; /**< AI:完整控制段实耗范围，零表示尚未记录。 */
    uint64_t phase_start_ms; /**< AI:当前段起始控制时刻，单位毫秒。 */
    bool on; /**< AI:当前段是否接通，结束时为假。 */
} tool_charge_cycle_t;
typedef struct { uint8_t mask; uint32_t duration_ms; } tool_key_step_t;
typedef struct {
    uint32_t id;
    tool_action_kind_t kind;
    tool_action_state_t state;
    uint64_t started_ms;
    uint64_t finished_ms;
    tool_charge_cycle_t cycle;
    tool_output_progress_t sequence;
} tool_action_t;

typedef struct {
    tool_power_t power;
    tool_power_t pending_power;
    bool charge;
    uint8_t keys;
    uint32_t revision;
    uint32_t deadtime_ms;
    char owner[65];
    uint64_t owner_deadline_ms;
    tool_action_t actions[TOOL_MAX_ACTIONS];
    uint32_t next_action;
    int key_slot;
    int power_slot;
    int charge_slot; /**< AI:占用充电和主供电的循环槽位，空闲为负一。 */
    int output_slot; /**< AI:三路通断序列共用一个槽位，避免两个动作写同一输出。 */
    tool_output_step_t output_steps[TOOL_MAX_STEPS];
    tool_output_t output_finish, output_cancel, output_target;
    tool_action_state_t output_goal; /**< AI:保护等待结束后进入运行、完成或取消状态。 */
    uint64_t output_due_ms, output_off_since_ms;
    uint64_t key_deadline_ms;
    uint64_t power_deadline_ms;
    tool_key_step_t steps[TOOL_MAX_STEPS];
    size_t step_count;
    size_t step_index;
    uint32_t repeats_left;
} tool_core_t;

/** AI:一次接收三路开关的完整时序。@param c 控制实例。@param steps 步骤。@param n 步数。@param repeat 有限次数。@param finish 完成后状态。@param cancel 取消后状态。@param now 板端单调毫秒。@param id 返回动作编号。@return 受理或拒绝原因。 */
tool_result_t tool_outputs_run(tool_core_t *c, const tool_output_step_t *steps, size_t n, uint32_t repeat, tool_output_t finish, tool_output_t cancel, uint64_t now, uint32_t *id);
/** AI:按预定取消状态收尾，必要时先断后通。@param c 控制实例。@param id 动作编号。@param now 板端单调毫秒。@return 请求结果。 */
tool_result_t tool_outputs_cancel(tool_core_t *c, uint32_t id, uint64_t now);

/** AI:初始化安全控制状态。@param core 执行模块实例。@return 无。 */
void tool_core_init(tool_core_t *core);
/** AI:推进本地时序，外层负责互斥及应用GPIO。@param core 实例。@param now_ms 单调毫秒。@return 无。 */
void tool_core_tick(tool_core_t *core, uint64_t now_ms);
/** AI:申请或显式接管写权。@param core 实例。@param owner 会话身份。@param takeover 是否接管。@param revision 调用者观测版本。@param now_ms 单调毫秒。@return 结果代码。 */
tool_result_t tool_core_claim(tool_core_t *core, const char *owner, bool takeover, uint32_t revision, uint64_t now_ms);
/** AI:检查写权及活性。@param core 实例。@param owner 会话身份。@param now_ms 当前时刻。@return 结果代码。 */
tool_result_t tool_core_owner(const tool_core_t *core, const char *owner, uint64_t now_ms);
/** AI:续约已有有效写权。@param core 实例。@param owner 会话身份。@param now_ms 当前时刻。@return 结果代码。 */
tool_result_t tool_core_renew(tool_core_t *core, const char *owner, uint64_t now_ms);
/** AI:无在途动作时释放写权，输出保持。@param core 实例。@param owner 会话身份。@param now_ms 当前时刻。@return 结果代码。 */
tool_result_t tool_core_release(tool_core_t *core, const char *owner, uint64_t now_ms);
/** AI:以先断后通切换主供电。@param core 实例。@param source 目标支路。@param now_ms 当前时刻。@param action_id 返回动作编号。@return 结果代码。 */
tool_result_t tool_core_power(tool_core_t *core, tool_power_t source, uint64_t now_ms, uint32_t *action_id);
/** AI:控制独立充电通路并校验真实电池互锁。@param core 实例。@param enabled 是否接通。@return 结果代码。 */
tool_result_t tool_core_charge(tool_core_t *core, bool enabled);
/** AI:从断开状态启动板上有限充电循环。@param core 实例。@param on_ms 接通毫秒。@param off_ms 断开毫秒。@param count 完整循环次数。@param now_ms 单调毫秒。@param action_id 返回动作编号。@return 参数、互锁、占用或成功状态。 */
tool_result_t tool_core_charge_run(tool_core_t *core, uint32_t on_ms, uint32_t off_ms, uint32_t count, uint64_t now_ms, uint32_t *action_id);
/** AI:取消指定充电循环并断开充电。@param core 实例。@param action_id 充电动作编号。@param now_ms 单调毫秒。@return 动作类型、存在性或成功状态。 */
tool_result_t tool_core_charge_cancel(tool_core_t *core, uint32_t action_id, uint64_t now_ms);
/** AI:启动有限按键序列。@param core 实例。@param steps 步骤。@param count 步数。@param repeat 重复次数。@param now_ms 当前时刻。@param action_id 返回编号。@return 结果代码。 */
tool_result_t tool_core_keys(tool_core_t *core, const tool_key_step_t *steps, size_t count, uint32_t repeat, uint64_t now_ms, uint32_t *action_id);
/** AI:取消按键动作并释放触点。@param core 实例。@param action_id 编号。@param now_ms 当前时刻。@return 结果代码。 */
tool_result_t tool_core_cancel(tool_core_t *core, uint32_t action_id, uint64_t now_ms);
/** AI:查询保留动作。@param core 实例。@param action_id 编号。@return 只读记录，未找到为NULL。 */
const tool_action_t *tool_core_action(const tool_core_t *core, uint32_t action_id);
/** AI:查询是否仍有动作执行。@param core 实例。@return 有动作时为true。 */
bool tool_core_busy(const tool_core_t *core);

#endif
