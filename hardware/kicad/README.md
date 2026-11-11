# KiCad 硬件工程

2026-10-24 PCB布局初稿：已建立[可编辑PCB](AI_MCUTOOL.kicad_pcb)，90×90mm、四层、164颗器件；包含完整网络及原理图关联，尚未布线。查看[布局预览PNG](preview/PCB布局初稿.png)、[可放大SVG](preview/PCB布局初稿.svg)及[布局说明](../../docs/PCB布局初稿说明.md)。华秋CLI布局违规0、原理图一致性问题0；仍有336项未连接，不能直接投板。板框、天线伸出和外壳净空还需共同收敛到100mm整机上限。

2026-10-24：按功能电路重新绘制，使用本机 KiCad 10.0.6 完成解析、网表导出、ERC、BOM 和 PDF 导出。当前为原理图审阅版，封装和样机能力尚未定版。

2026-10-24封装修复：已校正6个迁移封装的Y轴方向，MOS的Courtyard改为3.8×4.15mm；MOS和VOM补充已核本体轮廓，迁移封装补充1脚标记。新增独立几何检查，旧镜像封装会被拒绝。[修复预览](preview/封装修复预览.png)及 [几何检查结果](verification/footprint-geometry.json)可直接查看。原理图连接与图面没有重画，因此此次变化主要在封装编辑器中查看。

2026-10-24继续核定：SHUNT4按Vishay推荐图修正两个感测铜盘为1.70×0.76mm，外侧与大电流铜盘齐平，并增加本体轮廓和尺寸校验，见[核定依据](../../docs/四端分流器封装尺寸核定.md)。新增[PCB导入准备检查](verification/pcb-import.json)，通过华秋原生pcbnew逐器件载入实际封装，比较全部编号铜盘与网表脚号；尚未创建PCB。

J2已绑定项目专用 `USB_C_HRO_TYPE_C_31_M_12`，按HRO 2020-12-08 Rev A图重建12个电气铜盘、4个外壳金属化槽孔和2个定位孔，保持原理图连接。封装的Dwgs.User板边线为布局参考，不是实际板框。见[连接器核定](../../docs/电源连接器封装核定.md)和[铜盘预览](preview/连接器与分流器核定.png)。采购必须匹配已核图版。

J1已选定华秋商城常见国产件XKB `DC-005-5A-2.0`，绑定项目专用 `DC_XKB_DC005_5A_2_0`。按厂家Rev A0底视图转换为元件面坐标，1脚槽孔采用1×3.5mm；1中心正、2外套筒地、3切换NC保持原连接。合作库存页面当次单件价约1.39元，见[采购页](https://item.hqchip.com/1026633819.html)；价格及库存会变化。当前164颗器件全部绑定，已具备完整PCB导入所需的封装和引脚映射条件。

## 打开和审阅

用 KiCad 项目管理器打开 [AI_MCUTOOL.kicad_pro](AI_MCUTOOL.kicad_pro)，再打开同名原理图或PCB。保留整个目录；子图页、项目符号库和项目封装库都通过相对路径关联。

- [9 页原理图 PDF](AI_MCUTOOL-原理图.pdf)：总览及八个功能页。
- [逐器件 BOM](AI_MCUTOOL-BOM.csv)：制造商料号与封装状态分别保留。
- [校验报告](verification/check.json)、[KiCad ERC](verification/erc.json)、[独立 XML 网表](verification/netlist.xml)。
- [SVG 预览目录](preview/)：矢量图可放大查看。
- 华秋封装编辑器中打开项目库 `AI_MCUTOOL`，重点查看 `N_FET`、`P_FET`、`PHOTO_PV`；已打开的旧封装视图需要重新载入库文件。

原理图包含可编辑的器件、导线、接点、网络标签和明确的 NC 标记。标准符号已复制到项目局部库；标准封装通过 KiCad 10 自带库查找，专用封装在 `AI_MCUTOOL.pretty`。

2026-10-24后续核验：用户已在客户端打开工程，辅助功能层次树确认总览及八个功能图页均已载入；通过当前华秋gRPC运行时读取的实时整板网表也与已确认电路一致，见 [实时校验报告](verification/live-runtime-check.json)及 [接口连接核验](../../docs/KiCad接口连接核验.md)。桌面截图仍然超时，未验证鼠标操作或交互编辑后重存。CLI实际解析与导出、PDF逐页检查已经完成。

## 图页与绘图约定

| 页码 | 内容 |
| --- | --- |
| 1 | 系统总览与图页索引 |
| 2 | 工具 5V 双入口隔离及 3.3V LDO |
| 3 | ESP32-S3-WROOM-1-N16R8、复位、启动、下载及总线 |
| 4 | 五套完整按键模拟电路 |
| 5 | 真实电池与外部电源的两套背靠背 N-MOS 开关 |
| 6 | 独立充电器输入及背靠背 P-MOS 开关 |
| 7 | 四端分流、INA228 和 Kelvin 采样 |
| 8 | 四路高阻分压、缓冲、ADC 及负轨电荷泵 |
| 9 | 3.3V UART、独立 TX 高阻控制及持续 RX |

器件引脚和导线使用 1.27mm 网格；信号优先从左到右，同一功能电路直接连线。跨页接口使用全局标签，四路 ADC 的同页连接使用局部标签。重复通道保持同样布局，位号和值水平阅读，电源和地使用统一图形，未使用引脚明确标 NC。

U14 使用四个运放单元和一个电源单元，BOM 仍为一颗。MOS 堆叠引脚隐藏重复图形但保留实际脚号；N-MOS 的 9 脚属于 D，P-MOS 的 9 脚属于 S。LDO 散热片用库脚号 4，与输出脚 2 同网。

KiCad 的公开文本格式、标准库和命令行检查便于自动化，但不会自动保证图面可读或电路正确。本工程同时检查布局、ERC 和原方案连接等价性。

## 实际校验结果

| 项目 | 结果 |
| --- | --- |
| 实体器件 / BOM 数量 | 164 / 164 |
| 实体符号单元 | 168，含 U14 的 5 个单元 |
| 物理引脚 | 508，全部存在且无重复归网 |
| 连接引脚 / 网络 | 484 / 124 |
| NC 引脚 | 24，集合及网表 NC 标记一致 |
| 与原连接依据逐网络端点集合比较 | 0 差异 |
| ERC | 0 错误、0 警告、0 排除违规 |
| 已绑定封装的脚号覆盖 | 164 颗全部覆盖，华秋原生pcbnew加载及铜盘映射通过 |
| 未绑定封装 | 0 |

连接回归依据为本目录的 `connectivity-baseline.json`。原嘉立创源数据目录已缺失，该文件从修复前通过审查的 `verification/check.json` 网络端点及原XML的NC集合恢复，保留原binding哈希及原理图哈希；不会根据当前输出自动改写基准。验证脚本读取华秋KiCad独立导出的XML，并执行封装几何检查。

ERC 使用 KiCad 默认启用规则，没有添加违规排除。KiCad 默认忽略的 `single_global_label`、`four_way_junction`、`simulation_model_issue`、`footprint_filter` 如实保留在报告中；`--severity-all` 不等于启用这些默认关闭的规则。

### LM66100 专用符号模型

沿用已核方案：U1/U2 的 ST 固定接地，NC 接地，CE 接本路 VOUT。依据见 [五伏双入口隔离器件核验](../../docs/五伏双入口隔离器件核验.md)，TI 允许未使用的 ST 接地。

项目符号将 ST 命名为 `ST_GND`、类型设为 passive；生成器强制检查 5 脚必须接 `COMMON_GND`。该符号只适用于本项目固定接地方式，不能直接复用作状态输出。VOUT 为理想二极管汇合端，使用 passive，并在输入电源及汇合节点放置 PWR_FLAG 声明供电。这些模型处理避免将合法的 ST 接地和理想二极管汇合误判为输出端冲突，没有改变实物连接。

## 后续工程边界

J1/J2均使用已核图版的专用封装，没有套用本机尺寸不同的通用标准库。迁移封装的编号方向已修正，钢网和实际采购型号仍需制造审查。[封装来源记录](footprint-provenance.json)、固定的 `footprint-source.json`、`typec-footprint-source.json` 及 `dc-footprint-source.json` 保留恢复依据、厂家尺寸与来源哈希；四端分流器保持WSK2512R0200BEA、20mΩ、0.1%，其四个铜盘已按厂家第2页对应阻值档核定并修正。来源JSON通过独立manufacturerReview字段记录此次厂家图修订，不从输出封装反向更新。

用户授权开始后，已采用90×90mm、四层板制作可调整布局初稿，外壳及固定孔尚未定版。`pcb-import.json` 的 `readyForCompleteImport` 为true；[PCB实际检查](verification/pcb-layout-check.json)进一步核对了164颗器件、508个逻辑端子、520个有编号铜盘、四铜层及天线禁布规则。布局和原理图一致性检查通过，尚未布线。

LDO散热与反流、MOS动作及互锁、测量精度和校准仍需布线与样机验证。当前没有制造文件，不能据此直接投板；U4项目封装仅将跨主板边缘的丝印轮廓移到Fab，保留标准铜盘、接地孔及全层天线禁布区。

## 维护与复现

日常可直接在华秋KiCad编辑。当前可独立运行封装重建和检查；整个原理图的历史生成器仍引用已缺失的嘉立创数据，暂不可复现整图重建。不要通过运行历史生成器覆盖GUI修改。工程ZIP用于直接打开审阅，维护脚本在仓库 `hardware/tools/` 中运行。

PCB可直接在编辑器内调整。`build_pcb_layout.py`默认拒绝覆盖现有文件，只有显式`--replace-draft`且哈希仍与自动生成结果一致时才能重建；修改过的GUI布局会受到保护。PCB检查使用`kicad-cli pcb drc --schematic-parity`和`hardware/tools/verify_pcb_layout.py`，完整命令见布局说明。

在仓库根目录执行检查，不会重新绘图：

```powershell
& 'D:\Application\kicad\install\bin\python.exe' hardware/tools/verify_kicad_schematic.py
& 'D:\Application\kicad\install\bin\python.exe' hardware/tools/verify_pcb_import.py
```

只重建封装并核对，命令不会重画原理图：

```powershell
& 'D:\Application\kicad\install\bin\python.exe' hardware/tools/kicad_project_footprints.py
& 'D:\Application\kicad\install\bin\python.exe' hardware/tools/verify_kicad_footprints.py --output hardware/kicad/verification/footprint-geometry.json
& 'D:\Application\kicad\install\bin\python.exe' hardware/tools/verify_kicad_schematic.py
```

历史布局与线路在 `../tools/kicad_circuit_pages.py`；封装生成在 `../tools/kicad_project_footprints.py`，独立几何检查在 `../tools/verify_kicad_footprints.py`。未来授权改电路时，回归依据应随经过审查的设计更新，不能忽略差异或自动接受新网表。
