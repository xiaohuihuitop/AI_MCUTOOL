# MCU开发辅助工具

通过Wi-Fi及原生USB，向AI提供五路按键模拟、供电通路选择、充电器插拔模拟、电压电流测量和目标串口交互能力。

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
