# 原生USB接口改版核验

日期：2026-11-04。用户确认删除五针UART0下载排针，使用现有Type-C承担工具供电、固件下载、日志及双向命令交互。仅修改嘉立创本地工程第1、2页原理图，PCB最后统一同步。

## 当前接线

| 信号 | Type-C J2 | 静电保护D5 | MCU侧串阻 | ESP32-S3模组U4 |
| --- | --- | --- | --- | --- |
| USB D− | A7、B7并入USB_DM | 1、6脚 | R85，22Ω | 13脚GPIO19 |
| USB D+ | A6、B6并入USB_DP | 3、4脚 | R86，22Ω | 14脚GPIO20 |
| 公共地 | 原GND及外壳连接保持 | 2脚 | — | 原公共地 |
| 接口5V | 原TYPEC_IN_5V保持 | 5脚 | — | 经原SS34和LDO生成3.3V，不直接接GPIO |

D5采用友台USBLC6-2SC6（C2687116，SOT-23-6）正式模型，1/6、3/4分别为两路内部相通的I/O。本图将对应脚明确接在同一网络上。R85/R86采用厚声0603WAF220JT5E（C23345，22Ω±1%、0603）正式模型。新器件Unique ID全工程唯一。

J2的四个数据引脚采用短跨页网名表示正反插配对，避免与已有电源竖线新增交叉；保护器件内部配对及MCU侧采用直接导线。删除上述六个原未连接标记，释放UART0模组36/37脚并添加未连接标记。原J3、其五条引线及两条UART0引脚引线移除，BOOT/RESET/CONFIG及上拉、复位RC保持。

## 使用与固件约定

- 使用ESP32-S3内置USB Serial/JTAG，不增加USB转串口芯片。USB口可用于烧录及双向CDC串口，JTAG也由此控制器支持。
- 正常情况下下载工具可自动进入下载模式；必要时按住BOOT，按下并释放RESET，再释放BOOT。USB引脚被固件复用或控制器被关闭时，可用这一操作重新进入ROM下载模式。
- 日志和命令接收需要后续固件启用USB Serial/JTAG控制台及命令处理。只开启次级USB日志输出不等于具备输入能力；日志与命令响应的区分留待固件协议实现。本轮没有创建或编译固件。
- Wi-Fi能力保持；USB与Wi-Fi的命令格式、并发处理由后续固件设计，不增加通信自动回退或切换策略。被测设备的业务UART仍使用GPIO14/15，原收发电路不改。
- 沿用人工二选一供电：USB接电脑时不接DC，DC供电时通过Wi-Fi使用。电脑USB口不自动视为5V/2A适配器，端口供电能力、启动和Wi-Fi瞬态须样机核验。Type-C仍不做PD升压协商。
- 工具USB在深睡时会断开，轻睡也可能影响连接；本轮不增加休眠或自动恢复机制。被测设备的低功耗测试不要求工具自身进入休眠。

## 验证与后续PCB事项

两页均经用户客户端保存、关闭、重开，再由全新后台会话明确读取磁盘本地工程。当前140颗器件、415个逻辑引脚，原理图DRC为零。逐脚确认Type-C正反插配对、D+/D−极性、D5地和VBUS、两颗串阻及释放的UART0脚。批准变更以外的全部网络分组、保留网名、器件身份、属性与几何不变；其他六页及PCB文件摘要不变，新增引线无异网交叉。机器结果为`hardware/easyeda-local/native-usb-check.json`。

原生图面检查并调整了Type-C旧说明、USB短网名、串阻位号与阻值的位置。预览为`hardware/easyeda-local/preview/01.png`和`02.png`。

PCB尚未更新，不能直接投板。统一修改时删除J3，放置D5及R85/R86，D5靠近接口，串阻靠近模组，按USB差分布线要求处理正反插汇合、回流与参考地。没有进行USB枚举、下载、日志收发、命令交互、ESD或供电实测；DRC不替代这些测试。

## 来源

- [乐鑫USB Serial/JTAG控制台](https://docs.espressif.com/projects/esp-idf/en/stable/esp32s3/api-guides/usb-serial-jtag-console.html)：GPIO19/20、双向控制台、自动下载、控制台配置及休眠限制。
- [乐鑫ESP32-S3硬件设计指南USB部分](https://docs.espressif.com/projects/esp-hardware-design-guidelines/en/latest/esp32s3/schematic-checklist.html#usb)：建议预留22/33Ω串阻并靠近芯片。本图初装22Ω，最终信号质量待验证。
- [友台USBLC6-2SC6厂家手册](https://atta.szlcsc.com/upload/public/pdf/source/20250624/893D59A24F8E7586285A0E18B354F560.pdf)，Nov.2024，第1页脚号和第3页低电容参数；已核对准确C2687116模型。
