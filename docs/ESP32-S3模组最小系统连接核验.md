# ESP32-S3 模组最小系统连接核验

> 2026-11-04更新：用户确认现有Type-C接入GPIO19/20原生USB，支持下载、日志与命令交互；删除J3五针UART0下载排针，GPIO43/44预留未连接，BOOT/RESET保持。本文原下载接口讨论保留为历史；当前以[原生USB接口改版核验](原生USB接口改版核验.md)为准。

> 2026-11-04实施更新：RESET、BOOT、CONFIG三颗实体按键已按用户指定统一为TS-1009S-03826（C455243），原上拉、复位RC及触发逻辑保持。当前依据见[板载按键替换核验](板载按键C455243替换核验.md)，PCB最后统一更新。

核验日期：2026-10-22。对象为 **ESP32-S3-WROOM-1-N16R8** 模组直接上板。已实际读取乐鑫官方模组手册 v1.8、硬件设计指南及下载指南，并渲染核对手册第 39、41 页原理图。本文是画图依据与工程建议，尚无本项目原理图、PCB、实物或验证结果。

用户已确认独立 2.54mm 下载排针、BOOT/RESET/配网三个按键、电源/状态两颗普通 LED。本轮不改变业务 GPIO 分配，不增加 USB 数据接口或自动下载电路。

## 可直接用于绘图的模组引脚表

以下是**模组焊盘号**，不是裸 ESP32-S3 芯片脚号，也不是下载排针编号。[S1 §3.2，表 3-1，第 11～12 页]

| 模组信号 | 模组焊盘号 | 本项目连接 |
| --- | ---: | --- |
| 3V3 | 2 | 工具内部稳压 3.3V，近端去耦 |
| GND | 1、40 | 主板公共地，连接地平面 |
| EPAD | 41 | 底部接地焊盘；推荐按官方 land pattern 接地并合理焊接，见下方说明 |
| EN | 3 | 复位 RC、RESET 按键及下载口 EN |
| IO0 / GPIO0 | 27 | BOOT 按键、外部上拉及下载口 BOOT |
| TXD0 / GPIO43 | 37 | 下载口 TX0，连接外接串口工具 RX |
| RXD0 / GPIO44 | 36 | 下载口 RX0，连接外接串口工具 TX |
| IO16 / GPIO16 | 9 | 状态 LED，沿用既有分配 |
| IO17 / GPIO17 | 10 | 独立配网按键，沿用既有分配 |
| IO46 / GPIO46 | 16 | 下载启动绑带，复位采样时保持低电平 |
| IO45 / GPIO45 | 26 | 存储电压相关绑带，保留不用 |
| IO3 / GPIO3 | 15 | JTAG 来源相关绑带，保留不用；建议外部下拉定义电平 |

N16R8 的 IO35、IO36、IO37（模组焊盘 28、29、30）已连接 Octal PSRAM，不得作为业务引脚。模组内已集成 40MHz 晶振、Flash 及射频/天线电路，不在主板重复添加裸芯片外围。[S1 §1.1、表 3-1 注 b、§8]

## 最小连接与初始器件值

| 部分 | 连接及建议值 | 依据与状态 |
| --- | --- | --- |
| 模组供电 | 稳压 3.3V → 模组 2 脚；1、40 脚 → GND | 推荐工作范围 3.0～3.6V，模组外部供电能力至少 0.5A；不是持续耗电为 0.5A。[S1 §6.2] 工具其他负载另计 |
| 模组入口去耦 | 模组 2 脚附近，3V3 对地 **22µF＋0.1µF** | 模组外设参考图的 C1/C3，而非照抄裸芯片电源脚电容。[S1 图 9-1，第 41 页] 电容介质、耐压、有效容量和封装待 BOM 选择 |
| EN 复位 | 3V3 → **10kΩ** → EN；EN → **1µF** → GND；RESET 常开按键接 EN 与 GND | 官方模组说明给出的常用 RC 起点，需按实际稳压启动/关断波形核验。[S1 §9；S2 Chip Power-up and Reset Timing] |
| BOOT | GPIO0 → **10kΩ 上拉至 3V3**；BOOT 常开按键接 GPIO0 与 GND；同节点引到下载口 | 官方推荐 GPIO0 外部上拉；10kΩ 为本次工程初始值。不要给 GPIO0 加大容量去抖电容，以免上电误入下载。[S2 Strapping Pins] |
| GPIO46 | 保持复位采样时低；建议 **10kΩ 下拉至 GND**，不接其他外部驱动 | 芯片已有弱下拉，外部 10kΩ 为工程建议，用于明确 UART 下载条件。[S1 §4.1] |
| GPIO3 | 建议 **10kΩ 下拉至 GND**，不接业务外设 | 无内部拉电阻。默认 eFuse 配置下 GPIO3 被 JTAG 选择逻辑忽略；若启用 strap 选择，电平不得浮空。[S1 §4.4、表 4-5] 外部下拉为工程建议，不修改 eFuse |
| GPIO45 | 保留不用，不外部上拉到高电平 | 默认弱下拉；带 PSRAM 模组的 VDD_SPI 由出厂 eFuse 固定，不能据裸芯片绑带表擅自修改存储电压。[S1 §4.2、§8] |
| 配网按键 | GPIO17 → **10kΩ 上拉至 3V3**；常开按键接 GPIO17 与 GND | 工程初始值，独立于 BOOT。长按时间及消抖属于后续固件定义 |
| 电源 LED | 3V3 → 限流电阻 → LED → GND | 表示工具 3.3V 电源存在，不代表被测设备供电已开启。阻值随 LED 的正向压降和亮度需求确定 |
| 状态 LED | GPIO16 → 限流电阻 → LED → GND，高电平点亮 | 工程连接建议，普通低电流 LED；电阻随 LED 参数和 GPIO 带载电压核算，闪烁规则后续定义 |

LED 可先以约 1～2mA 为亮度/功耗设计起点，但本轮不指定颜色、具体料号或未经核算的阻值。上表 BOOT、GPIO46、GPIO3、配网的 10kΩ 是工程建议，不冒充官方全部指定阻值。

**模组内部已存在 UART0 TX 串联电阻。** 官方模组原理图第 39 页可见 U0TXD 路径的 R3＝499Ω；硬件指南面向芯片所述“U0TXD 串 499Ω”已经体现在该模组内。主板不能机械地再串一个 499Ω。[S1 图 8-1；S2 UART] 本项目仍需按最终线长和连接器验证 UART 波形与下载可靠性。

EN 的 10kΩ×1µF 约 10ms 只是 RC 时间常数，不能当成精确复位释放时间。参考图另外画有 RESET 按键旁的 0.1µF，不要求在 EN 的 1µF 之外重复增加；若调整总电容，须统一按同一 EN 网络核算。

## 复位、启动与手动下载

官方时序要求：[S1 §4，表 4-2/4-6；S2]

- 电源稳定后，EN 拉高前预留的 `tSTBL` 最少 50µs。
- EN 保持在复位低电平范围内的 `tRST` 最少 50µs。
- EN 上升后，GPIO0/GPIO46 等绑带电平保持时间 `tH` 最少 3ms。
- 正常 SPI 启动：GPIO0＝1；UART 下载所处 Joint Download Boot：**GPIO0＝0 且 GPIO46＝0**。

下载排针只包含 **TX0、RX0、GND、BOOT、EN** 五个信号，编号顺序由主板布局定义。与官方参考图带 3V3 的 UART 接口不同，本项目不通过下载排针供电。BOOT 是 GPIO0 节点，EN 是模组使能/复位节点；外接工具不能输出 5V 逻辑。

手动操作顺序：[S1 §4.1；S3，按已确认按键连接实施]

1. 工具从自身电源口供电；外接串口工具 TX → RX0、RX → TX0、GND → GND，使用 3.3V 逻辑。
2. 按住 BOOT，按下并释放 RESET；在 EN 上升后的绑带保持时间结束后再释放 BOOT。人工按键通常远长于 3ms，仍以电气时序验证为准。
3. UART0 出现 `waiting for download` 后进行串口烧录；同一个 COM 口不要同时被日志终端与烧录程序占用。
4. 烧录完成后释放 BOOT，使 GPIO0 被上拉；再按一次 RESET，进入正常 SPI 启动。

本项目不加入 DTR/RTS 自动复位电路。下载器若只用 TX/RX/GND，BOOT/EN 可不接，由板上按键操作；若使用外部控制，须遵守相同电平、时序和复位节点负载要求。

## 主板布局边界

- 按模组官方 footprint 建立封装，不能将 GPIO 编号当焊盘号。EPAD＝41、GND＝1/40；**官方明确 EPAD 焊到主板地不是强制要求**，但可改善热性能。选择焊接时按推荐 land pattern、钢网和焊膏量处理，过多焊膏可能将模组顶起。[S1 §9、§11.1]
- 22µF/0.1µF 靠近模组 3V3 入口，EN RC 靠近 EN，EN 走线短；电源/地回路需支撑 Wi-Fi 瞬态，不以适配器标称额定替代板上电源验证。[S1 §9；S2]
- WROOM-1 板载天线靠主板边缘，优先伸出主板；无法伸出时按官方图形留空，不在天线附近布电源、排针或线缆。终端外壳内天线各方向建议至少 15mm 净空，最终整机验证通信。[S4 模组定位章节]
- 主板不重复设计 40MHz 晶振、Flash/PSRAM、RF 匹配。可选的 32.768kHz 外晶振不纳入当前最小系统，尤其不能占用已用于业务的 GPIO15/16。[S1 §1.1、图 9-1]
- 本轮不增加监控复位芯片；先对实际独立稳压供电验证 EN RC 时序。官方提醒慢升降电源或频繁通断时 RC 可能不够，出现这些实测问题再按根因调整电源/复位方案，不宣称 10kΩ/1µF 已覆盖一切波形。[S2]

## 官方证据

2026-10-22 通过 HTTPS 实际读取以下资料。PDF 在内存中解析；第 39、41 页另在内存中渲染目视检查，没有写入资料下载文件。

- **S1**：[ESP32-S3-WROOM-1 & WROOM-1U Datasheet v1.8](https://documentation.espressif.com/esp32-s3-wroom-1_wroom-1u_datasheet_en.pdf)：§3.2/表 3-1（第 11～12 页），§4（第 13～16 页），§6.2（第 27 页），§8/图 8-1（第 39 页，模组内部含 TX 499Ω），§9/图 9-1（第 41 页，模组外设电路、去耦及 EN RC），§11.1（官方封装依据）。
- **S2**：[ESP Hardware Design Guidelines — ESP32-S3 Schematic Checklist](https://docs.espressif.com/projects/esp-hardware-design-guidelines/en/latest/esp32s3/schematic-checklist.html)：本次读取 `latest` 在线版的 Power Supply、Chip Power-up and Reset Timing、UART、Strapping Pins；网页没有在这些章节给出独立固定版号。
- **S3**：[ESP Hardware Design Guidelines — ESP32-S3 Download Guidelines](https://docs.espressif.com/projects/esp-hardware-design-guidelines/en/latest/esp32s3/download-guidelines.html)：本次读取 `latest` 在线版 UART 下载步骤与 `waiting for download` 要求。
- **S4**：[ESP Hardware Design Guidelines — ESP32-S3 PCB Layout Design](https://docs.espressif.com/projects/esp-hardware-design-guidelines/en/latest/esp32s3/pcb-layout-design.html)：本次读取 `latest` 在线版 General Principles of PCB Layout for Modules (Positioning a Module on a Base Board)、UART。

已核实的是器件资料和最小连接方向；供电波形、复位可靠性、LED 亮度、下载成功率、射频和默认关闭仍需在实际原理图及样机上验证。
