# MCU开发辅助工具

通过Wi-Fi及原生USB，向AI提供五路按键模拟、供电通路选择、充电器插拔模拟、电压电流测量和目标串口交互能力。

## 版本与下载

**桌面／后台／MCP：0.5.1；工具板固件：0.1.3。** [下载正式版本](https://github.com/xiaohuihuitop/AI_MCUTOOL/releases/tag/v0.5.1) · [版本列表](https://github.com/xiaohuihuitop/AI_MCUTOOL/releases)。正式安装器可匿名下载。0.5.0 用户首次手动升级至 0.5.1，之后可通过托盘“检查更新”获取新正式版；选择“更新并重启”后，桌面会验证签名并检查后台占用。

六路固定每路每秒10次。电池电压、电流共用双轴图；四路电压另有独立页面，支持每路比例、偏移、颜色和曲线显隐。两组分别开始/暂停、清空、导出CSV，保留最近4小时完整采样；电池图支持A/B游标、极值、时间加权平均与区间净电量。详细规则见[图表使用说明](docs/上位机界面与图表使用说明.md)。

0.5.0 增加板上充电插拔循环。选择真实电池并关闭充电后，通过 MCP 的 `run_charge_cycle` 一次指定接通毫秒、断开毫秒和有限次数。电脑失联后板子继续执行，最后断开充电。[协议和验收口径](protocol/设备协议.md)

## AI自动安装与接入

把本仓库交给AI，并说明：

> 请按README安装MCU TOOL正式桌面版和配套Skill，接入我正在使用的AI客户端，完成只读MCP自检。先不要执行按键、供电、充电或串口发送；连接工具板时核对我指定的设备。

**Windows 10/11 x64** 下，在仓库根目录运行以下命令。使用Windows自带的PowerShell 5.1即可，PowerShell 7也支持：

```powershell
# Codex：安装桌面、运行环境、Skill，登记MCP并打开工作台
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/setup-desktop.ps1 -Auth Anonymous -ConfigureCodex -Launch
```

安装脚本会依次完成：

1. 按[固定发布描述](integrations/desktop-release.json)下载**与当前仓库版本匹配**的安装器；同时核对仓库内SHA256与随包校验文件，失败立即停止。
2. 安装到当前用户目录。安装器随附Python后台、所需库、编译好的网页、桌面程序及WebView2离线安装程序；日常使用**不用另装Python、Node.js、Rust或ESP-IDF**。
3. 已安装同版本时直接复用。需要升级且程序仍运行时明确报错，先按正常流程退出，不强杀进程、不删除原始记录。
4. 读取已有桌面数据目录，生成包含本机绝对路径的MCP配置；安装完整配套Skill，更新已有副本前备份。
5. 启动随附MCP执行`initialize`和`ping`，核对版本与工具清单。此自检不连接硬件，也不改变输出。
6. 使用`-ConfigureCodex`时，通过官方`codex mcp add`登记`mcutool`并回读检查；更新前备份Codex配置，其他MCP服务保持。`-Launch`打开桌面窗口。

Codex CLI未在PATH中时，AI应定位已安装客户端的`codex.exe`，通过`-CodexCommand "完整路径"`指定。MCP配置变更后，按客户端要求重新加载工具或开始新会话，再实际调用`ping`确认已可见；不能把“配置文件写完”当作当前AI已能操作。

**其他AI客户端**使用同一个安装入口，省略`-ConfigureCodex`：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/setup-desktop.ps1 -Auth Anonymous -Launch
```

脚本输出桌面程序、数据目录、Skill和`mcp-config.json`的实际位置。AI将其中`mcutool`条目合并到该客户端支持的MCP配置，保留已有服务；手动配置格式见[安装版MCP示例](integrations/mcp.desktop.example.json)。Skill提供使用规则，MCP提供实际执行接口，两者都要接好。

### 下载权限与离线安装

默认`-Auth Git`使用Git已有的GitHub凭据，不打印或保存令牌。使用SSH克隆但没有HTTPS凭据时，可明确选择`-Auth Token`，由环境变量`GH_TOKEN`提供有仓库读取权限的令牌；不要把令牌放进命令参数或聊天。公开访问才使用`-Auth Anonymous`。下载失败不会自动换源或改装其他版本。

已从Release下载安装器和同名`.sha256`文件时，两者放在同一目录：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/setup-desktop.ps1 -PackageDirectory "D:\Downloads\MCUTOOL" -ConfigureCodex -Launch
```

`-DownloadOnly`仅下载并校验。需要自定义安装位置可传`-InstallDirectory`；脚本输出和生成的MCP配置会使用该实际位置。

### 安装后在哪里

| 内容 | 默认位置／规则 |
| --- | --- |
| 桌面程序 | `%LOCALAPPDATA%/MCU TOOL/mcutool-desktop.exe`，同时创建快捷方式 |
| MCP程序 | 同安装目录下`runtime/MCUTOOL-service/MCUTOOL-service.exe` |
| 数据与原始记录 | `%LOCALAPPDATA%/MCU_TOOL/data/`；存在`desktop.json`时沿用其`data_dir` |
| 桌面配置 | `%LOCALAPPDATA%/MCU_TOOL/desktop.json` |
| 接入配置、下载与备份 | `%LOCALAPPDATA%/MCU_TOOL/setup/` |
| Codex Skill | 新安装使用`~/.agents/skills/xhh-mcu-tool/`；已有`~/.codex/skills/`同名副本时原地更新 |

桌面与MCP必须使用**同一数据目录**。本开发机的绝对路径不适用于其他电脑，安装脚本会按目标电脑生成配置。

## AI如何操作工具

安装后先读[配套Skill](integrations/skill/xhh-mcu-tool/SKILL.md)，按具体任务读取[操作参数与异常处理](integrations/skill/xhh-mcu-tool/references/operations.md)或[测量与区间分析](integrations/skill/xhh-mcu-tool/references/measurements.md)。工具名以当前客户端显示的命名空间和schema为准。

| 步骤 | 接口与完成依据 |
| --- | --- |
| 确认入口 | `ping()`、`runtime_status()`核对版本和现有后台 |
| 连接工具板 | 桌面已连接时`connect()`复用。未连接时枚举端口，按用户指定的USB端口或Wi-Fi地址连接，核对`device_id`和`boot_id`；不选“第一个候选设备” |
| 只读观察 | `device_status()`看最新值和质量；`read_data(kind="measurements", after=上次next, limit=...)`持续读取，无需操作权 |
| 执行已授权操作 | `claim_control()`取得操作权，为每次写操作生成独立UUID `request_id`，再调用对应接口 |
| 核对结果 | 用`job_status(request_id)`查任务终态，结合读数或串口判断被测设备响应。超时不代表未执行，结果未知时查询证据，不重发动作 |
| 收尾 | 按测试意图结束自己开启的记录、释放自己的操作权并`detach()`；普通退出不调用会影响所有客户端的`disconnect()` |

例如用户已授权“按K1十次，每秒一次，每次按下100ms，同时记录电流变化”：

```text
recording(action="start")                         # 已连接且持有操作权
press_keys(keys=[1], press_ms=100, release_ms=900,
           count=10, request_id="本次新生成的UUID")
read_data(kind="measurements", after=测量游标)     # 循环增量读取并保存next
job_status(request_id="同一个UUID")                # 查询到终态
recording(action="stop")                          # 核对completed及文件位置
```

按键序列由工具板计时；执行期间后台继续采集和记录，AI可以交替查询任务与新增数据。测量、串口、事件各用自己的游标，检查`lost`及设备启动变化。不要用AI调用之间的等待实现按下/释放的精确定时；同一功能忙碌时不会自动排队新动作。

常用操作：`press_keys`单击/长按/连击/多键组合、`run_key_sequence`有限按键序列、`cancel_keys`取消指定动作、`power_select`选择供电通路、`charge_set`充电通路、`uart_configure`/`uart_tx`/`uart_write`串口交互。已有其他操作者时需明确交接，不能擅自抢占。一次授权的完整流程内无需逐个按键重复询问。

测量原始电流单位是**A**，图表显示为**mA**；电量是指定区间的带符号积分，单位**mAh**，不是电池剩余容量。六路10Hz不等于严格同时采样，不能拿来保证捕获瞬时尖峰。波形暂停/清空只作用于对应图表；要长期保存，提前开启后台持续记录。完整边界见Skill。

## 工具板与运行条件

桌面安装不会烧录工具板。固定 10 Hz 采样需要固件 0.1.2 或以上，板上充电循环需要固件 0.1.3。连接后在“设备设置”或设备信息里核对。需要升级时使用 Release 的固件包及[固件下载说明](docs/软件使用说明.md#2-工具固件)，先确认目标工具身份、实际接线和重启时机。重启会关闭主供电、充电、按键输出并使 TX 高阻。

工具USB与工具DC供电人工二选一。按键触点目标≤6V/20mA；UART为3.3V；主通路目标2.8～12V、双向3A；四路电压输入0～15V。`power_select`只选通路，不调外部电源电压。本工具不承担目标MCU烧录/SWD调试。实装INA226的步进、校准与精度限制见[实板测量说明](docs/INA226实板启动与测量限制.md)。

## 软件资料与开发

- [桌面版使用说明](docs/桌面版使用说明.md)：窗口、托盘、共享后台、升级和卸载。
- [图表说明](docs/上位机界面与图表使用说明.md)、[完整软件说明](docs/软件使用说明.md)、[0.4.1验证报告](docs/固定10Hz与长时间波形验证报告.md)。
- `firmware/`为ESP-IDF固件，`host/`为共享后台与MCP，`web/`为Vue网页，`desktop/`为Tauri桌面，`protocol/`为设备契约。
- **只有修改源码才需要开发工具链**：Python 3.11、Node.js 22、PowerShell 7；桌面构建另需Rust和VS C++工具，固件构建需ESP-IDF。准备后运行`scripts/install.ps1`，验证用`scripts/verify.ps1`。普通安装使用前述`setup-desktop.ps1`。
- `release/`是开发机生成产物，不随Git克隆。其他电脑从GitHub Release下载，不依赖本机的`release/latest-desktop.json`。

Codex配置方式参考[官方MCP文档](https://developers.openai.com/codex/mcp/)与[官方Skill文档](https://developers.openai.com/codex/skills/)。

## 当前工程与版本

- 当前编辑的主工程已于2026-11-12切换为嘉立创EDA专业版全在线模式的云端`AI_TOOL`；官方CLI读取、DRC、截图及导出已实测，见[云端操作记录](docs/嘉立创云端AI_TOOL操作实测.md)。
- `D:\LCEDA\projects\AI_TOOL\AI_TOOL.eprj3`及[已保存的原生工程目录](hardware/easyeda-local/project/AI_TOOL/)保留为切换前本地保存点，不与云端自动同步；当前云端工程标识见[接入信息](hardware/easyeda-cloud/connection.json)。
- [最新保存点](hardware/easyeda-local/latest-version.json)及[完整版本归档](hardware/versions/版本记录.md)：包含源文件SHA256、完整目录快照和官方工程导出。
- [装配资料](hardware/easyeda-local/assembly/2026-11-10/)：140颗器件、37种采购物料；[物料统一记录](docs/已回板物料统一修改记录.md)。
- [按键光继电器选型调查](docs/按键光继电器替代料手册核验.md)：当前工程仍使用GAQY221S/C7435105，候选料和TLP187尚未替换。

PCB已回板，当前仍需完成样机装配及性能实测。最近一次原生PCB DRC为零；原理图保留Q1～Q5/Q14六处旧焊盘本地映射的库匹配提示，详见物料统一记录。保存版本不等于重新进行电气或硬件验证。

## 资料入口

- [功能规格](.scratch/mcu-assistant/spec.md)、[需求记录](docs/MCU开发辅助工具需求记录.md)、[硬件方案](docs/MCU开发辅助工具硬件方案.md)。
- [本地工程说明](docs/嘉立创本地工程说明.md)与[领域术语](GLOSSARY.md)。
- `hardware/kicad/`及`hardware/easyeda-pro/`保留较早阶段的对比设计，当前装配以本地嘉立创主工程和本批BOM为准。

恢复时将版本归档解压到独立目录，再打开其中`AI_TOOL/AI_TOOL.eprj3`；也可导入归档附带的官方`.epro2`工程。保留完整`sch`、`pcb`、`panel`及工程配置，不能只复制单个索引文件。
