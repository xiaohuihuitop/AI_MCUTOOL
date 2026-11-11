# 立创EDA插件实测与重排阻塞

日期：2026-10-24。用户要求使用已安装的easyeda-agent，改善当前原理图并与华秋KiCad比较。

## 最新进展

原始快照契约及合法多单元的连接/位号读取已修复，本地开发版为 `1.14.1-dev.2`。电源页已重排并保存重载验证；J18 已按用户授权替换 C2937625 正式模型，三根网络及 PCB 关联 ID 保持不变。全工程原理图原生 DRC 当前为 0 错误、0 告警。

PCB1 已生成 90×90mm 四层布局比较稿并完成全部位号重排，164 器件、508 逻辑脚与 KiCad 基准一致。两轮结构化数据一致；2026-10-25 已补齐第二轮原生截图并确认布局未漂移，两轮图面核对完成，机械边界问题仍未闭合。PCB 未布线，470 项原生连接错误仍存在；不能称 DRC 通过或制造版。

本轮还发现宿主忽略采购元数据空字符串而插件报告成功，已改为明确的所属属性写入及回读验证。J18 替换第一次因旧自定义属性与新模型默认属性不完全一致回滚；核对回滚后，采用新模型原生属性替换，再恢复原 AI 设计备注，纠正库绑定备注。全部操作经 typed 接口完成，没有删除或放松电气检查。

连接器 typecheck、build、1189 项测试及 Skill 包检查通过。Go 定向测试通过，全量 Go 尚有 Windows 路径、权限、时间精度等失败；未发布、提交或推送。U14 多单元整页 compose/preserve 写入仍未完全支持，其余七页原理图也尚未整理完成。

详见[阶段对比](立创EDA与华秋KiCad阶段对比.md)及[两轮数据核验](../hardware/easyeda-pro/verification/plugin-fix/pcb-two-round-review-complete.json)。下文为初次调查记录，其中“未重排/未生成 PCB”是当时状态。

## 已完成

- 从用户指定仓库的v1.14.0 Release取得Windows CLI和同版Skill，按该Release的checksums.txt核验SHA-256。运行时位于`docs/temp/easyeda-agent-runtime/`，未修改系统PATH或全局Skill。
- 后台daemon监听127.0.0.1:60832；连接器1.14.0，宿主专业版4.1.78。实际工程为`AI-MCUTOOL-RevA`，UUID为`57a0364c842149baada4fb3ca7ccf03f`，8页。
- 通过官方接口保存原始epro2及逐页器件/引脚快照。原始证据位于`hardware/easyeda-pro/verification/before/`，没有覆盖它们来迎合布局候选。
- 从8页原始引脚数据独立聚合得到164颗器件、508个物理引脚、124个连接网和24个NC，与KiCad固定连接基准完全一致。立创为167个符号实例，KiCad为168个符号单元，属于多单元表达差异，不是缺失芯片。详见[连接对账](../hardware/easyeda-pro/verification/kicad-connectivity-comparison.json)。
- 电源页13颗器件通过typed modify添加`EasyEDA Agent Component ID`，保留原生uniqueId、属性、位置及接线。保存返回严格布尔`saved:true`，并重新读取身份。未执行图面重排、清页或PCB写入。

## 当前原理图的表达问题

电源页实际是分散器件加44个网络端口，输入连接器、芯片和各自去耦/泄放/CC电阻分离。应重新组织为功能电路并用真实导线表达专属外围关系，跨功能边界再使用网络端口。

已准备电源页连接不变的布局源与离线候选，位于`hardware/easyeda-pro/planning/`。紧凑求解在Type-C模块的地线命名处耗尽有界预算；展开布线求解完成，但它只是离线候选，不是已经写入或已达到最终可读性的图纸。

## 阻塞1：同版CLI与连接器的图元清单契约不一致

复现：

```text
sch list --include-bbox --include-pins --include-wires
  --include-page-primitives --include-device-identity
sch compose --from ... --before ... --replace --preserve-instances
```

实际返回：

```text
preserve-instances: before snapshot pagePrimitives has incomplete class inventory
```

新鲜快照有11类：arcs、attributes、buses、circles、components、objects、pins、polygons、rectangles、texts、wires。CLI字段表只有10类，不包含pins。**额外的pins类被固定长度检查误判**，并不是工程缺失图元。

源码依据：[v1.14.0 sch_compose_source_guard.go](https://github.com/zhoushoujianwork/easyeda-agent/blob/v1.14.0/internal/app/sch_compose_source_guard.go)，`schComposeProtectedPage()`的字段表没有`pins`，却执行`len(page) != len(fields)`。因此完整快照也会被拒绝。原始返回和非零退出码保存在[重排阻塞证据](../hardware/easyeda-pro/verification/compose-blocker.json)。

正确修复方向：把pins的身份及所属组件纳入同一数据契约，核对真实原生引脚及其属性归属，区分嵌入引脚与可删除图元；完善清图/保留器件的写前和写后检查。不能删除原始快照的pins字段或取消长度/类别校验来绕过保护。

## 阻塞2：多单元U14被误判成重复器件

第七页OPA4391含多个原生符号单元，同属U14；原始`sch list`可读到各单元及全部物理脚。

```text
sch connectivity: duplicate component cmp-U14
sch designator-geometry:
  Could not measure every current-page Designator.
  missing/duplicate part designator: U14
```

源码依据：[v1.14.0 connectivity/snapshot.go](https://github.com/zhoushoujianwork/easyeda-agent/blob/v1.14.0/internal/connectivity/snapshot.go)，默认以`cmp-`加位号构造Component ID。当前路径未正确区分一颗物理器件与它的多个符号实例，位号几何读取也按单个位号唯一处理。

正确修复方向：引入明确的物理器件—符号单元关联，以原生实例/子单元身份进行几何及写入，以物理位号和完整引脚进行连接/BOM对账。真正重复的独立器件仍需拒绝。不能把U14改成多颗不同位号或删除单元来迎合校验。

## 修复验证计划

1. 在隔离的插件源码中重现这两个失败，不修改工程来使测试通过。
2. 保留额外/缺失/重复图元的负例，验证pins归属及清理范围；保留正常单元、合法多单元和真正重复位号三类测试。
3. 用原始工程快照验证规划及保留实例队列，确认uniqueId、物理引脚、NC及其他属性不变。
4. 插件修复后先完成电源页落图，执行连接、几何、bridge、官方DRC及`save → reload → fresh readback`；通过后继续其余图页及PCB比较。

修改第三方插件代码属于新增工具维护范围，用户已授权实施，正在本地修复及现场验证。现阶段没有完成立创原理图重排，也没有生成立创PCB布局；不能把离线候选、已保存的ID属性或原始图截图称为设计交付。
