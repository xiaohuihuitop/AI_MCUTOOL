# MCU开发辅助工具

通过Wi-Fi及原生USB，向AI提供五路按键模拟、供电通路选择、充电器插拔模拟、电压电流测量和目标串口交互能力。

## 软件入口

当前版本0.1.1已按实板INA226调整，首块工具板已完成USB烧录与启动检查。2026-11-12用户实测反馈“效果很好，都正常”，已记录功能使用测试通过；[实板结果及测量限制](docs/INA226实板启动与测量限制.md)。测量精度仍以独立校准和量化验收记录为准。

- 双击 [启动工具.cmd](启动工具.cmd) 打开本机网页；本次工作区已准备Python环境和网页产物。
- [软件使用说明](docs/软件使用说明.md)：连接、操作、记录、配网、校准和后台退出。
- [软件验证报告](docs/软件验证报告.md)：本次构建与离线验证结果，实物待验收项单列。
- `firmware/` 为ESP-IDF固件，`host/` 为共享后台与MCP，`web/` 为Vue网页，`protocol/` 为设备契约。
- [MCP配置示例](integrations/mcp.example.json)与[配套使用Skill](integrations/skill/mcu-assistant-tool/SKILL.md)。不会自动覆盖其他AI客户端配置。
- 本次交付位置由 `release/latest.json` 记录；软件包包含固件、已构建网页、源码、启动和安装脚本及SHA256清单。

复制到其他电脑后先运行 `scripts/install.ps1`。源码验证入口为 `scripts/verify.ps1`，其中测试设备始终明确标识，不能代替工具板电气验收。程序启动不会自动连接设备或开启供电。

## 当前工程与版本

- 当前编辑的主工程：`D:\LCEDA\projects\AI_TOOL\AI_TOOL.eprj3`，使用嘉立创EDA专业版本地客户端。
- [本次保存的原生工程目录](hardware/easyeda-local/project/AI_TOOL/)：供Git保存和恢复的目录镜像，日常编辑仍以上述主工程为准。
- [最新保存点](hardware/easyeda-local/latest-version.json)及[完整版本归档](hardware/versions/版本记录.md)：包含源文件SHA256、完整目录快照和官方工程导出。
- [装配资料](hardware/easyeda-local/assembly/2026-11-10/)：140颗器件、37种采购物料；[物料统一记录](docs/已回板物料统一修改记录.md)。
- [按键光继电器选型调查](docs/按键光继电器替代料手册核验.md)：当前工程仍使用GAQY221S/C7435105，候选料和TLP187尚未替换。

PCB已回板，当前仍需完成样机装配及性能实测。最近一次原生PCB DRC为零；原理图保留Q1～Q5/Q14六处旧焊盘本地映射的库匹配提示，详见物料统一记录。保存版本不等于重新进行电气或硬件验证。

## 资料入口

- [功能规格](.scratch/mcu-assistant/spec.md)、[需求记录](docs/MCU开发辅助工具需求记录.md)、[硬件方案](docs/MCU开发辅助工具硬件方案.md)。
- [本地工程说明](docs/嘉立创本地工程说明.md)与[领域术语](GLOSSARY.md)。
- `hardware/kicad/`及`hardware/easyeda-pro/`保留较早阶段的对比设计，当前装配以本地嘉立创主工程和本批BOM为准。

恢复时将版本归档解压到独立目录，再打开其中`AI_TOOL/AI_TOOL.eprj3`；也可导入归档附带的官方`.epro2`工程。保留完整`sch`、`pcb`、`panel`及工程配置，不能只复制单个索引文件。
