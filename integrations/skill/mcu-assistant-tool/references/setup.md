# 安装与连接

本 Skill 随 MCU TOOL 交付，可整体复制到支持 Skill 的 AI 客户端。复制 Skill 负责提供使用指引；客户端还需要连接 MCU TOOL 的 MCP 服务，才能读取或操作设备。

## 使用已安装的 Windows 桌面版

取得完整仓库且用户要求安装/接入时，优先运行仓库根目录下的 `scripts/setup-desktop.ps1`，不要默认构建源码。它支持Windows自带PowerShell 5.1，读取 `integrations/desktop-release.json` 中的版本与SHA256：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/setup-desktop.ps1 -ConfigureCodex -Launch
```

仓库为私有时，默认使用Git已有的GitHub凭据；显式 `-Auth Token` 使用环境变量 `GH_TOKEN`，`-Auth Anonymous` 适用于公开访问。下载失败直接报告，不切换协议、镜像或其他版本。已下载发布安装器和同名`.sha256`时，用 `-PackageDirectory <目录>`。

安装器包含后台运行环境及WebView2离线安装程序。脚本复用同版本安装，安装Skill、生成绝对路径 `mcp-config.json`、只读MCP `ping`核对版本与工具。`-ConfigureCodex`调用官方CLI更新`mcutool`条目并备份原配置，不改其他服务；Codex命令未在PATH时传`-CodexCommand <完整路径>`。省略该选项则只生成通用MCP配置，AI按客户端类型合并。Skill沿用已有`.codex/skills/mcu-assistant-tool`，新安装使用`.agents/skills/mcu-assistant-tool`，避免两个位置出现同名副本。

运行中旧版须正常结束任务与记录后升级，脚本不强杀使用者。脚本不会连接工具板、申请操作权或烧录固件。成功输出包括实际程序、数据目录、Skill和MCP配置路径；MCP配置变更后按客户端要求重新载入或重新开始会话。

1. 安装 MCU TOOL，并确认桌面与 MCP 使用相同的软件版本。安装器随附 Python 运行环境，普通使用不要求安装 Python 或 Node.js。
2. 确定安装目录和数据目录。默认安装在 `%LOCALAPPDATA%/MCU TOOL`，默认数据在 `%LOCALAPPDATA%/MCU_TOOL/data`。桌面配置 `%LOCALAPPDATA%/MCU_TOOL/desktop.json` 中的 `data_dir` 可以指定项目目录；MCP 必须使用同一个 `data_dir`。
3. 用户要求配置客户端时，按客户端支持的格式添加该 MCP，保留其他服务配置。项目提供 `integrations/mcp.desktop.example.json`；下面是便于核对的通用结构，路径应替换为本机真实绝对路径，不能把占位文字或环境变量原样写入不支持展开的客户端。

```json
{
  "mcpServers": {
    "mcutool": {
      "command": "C:/实际安装目录/MCU TOOL/runtime/MCUTOOL-service/MCUTOOL-service.exe",
      "args": ["mcp", "--data-dir", "D:/实际数据目录"]
    }
  }
}
```

4. 脚本会安装整个Skill；手动安装时将 `mcu-assistant-tool` 文件夹放进客户端Skill目录，保留`references/`和`agents/`。Codex新安装采用用户`.agents/skills/`，本机已有`.codex/skills/`副本时原地更新。其他客户端使用各自安装方式。
5. MCP 可用后先调用 `ping()`、`runtime_status()`，再 `connect()` 附着。桌面已经连接工具板时复用它；没有连接时只返回未连接状态，不自行选硬件。

软件升级先按桌面流程正常退出旧版及共享后台，再安装新版。版本不一致时先统一软件版本，不绕过版本检查。

## 使用源码工程

源码开发环境为 Windows、Python 3.11 和 Node.js 22；辅助 PowerShell 脚本用 PowerShell 7，依赖以工程锁文件为准。

- 在工程根目录运行 `scripts/install.ps1`，然后双击 `启动工具.cmd` 打开本机网页。
- 项目 `integrations/mcp.example.json` 使用工程 `.venv/Scripts/python.exe`，参数为 `-m mcutool.mcp --data-dir <实际数据目录>`。项目常用 `.mcutool/`，应与桌面或网页启动配置一致。
- 路径均写成实际绝对路径，移动工程后同步修改。不要把另一目录当成故障恢复用的替代后台。

## 接入核对

MCP 命名空间由客户端决定。以可调用工具 schema 核对参数，以 `ping` 核对版本及工具清单，以 `runtime_status` 和 `device_status` 核对共享后台与设备状态。Skill 中的工具短名不能直接当作任意客户端的完整函数名。

`runtime.json` 含本机访问凭据，不写入报告或分享。读取网络状态时可能返回 Wi-Fi 访问令牌，报告仅保留必要的非敏感状态。

首次连接需明确设备。USB 选择工具的原生 USB Serial/JTAG 端口，握手后核对设备身份；已有网页连接可直接 `connect()` 复用。切换 USB/Wi-Fi 需要明确断开及重新连接，不自动换通道。

Wi-Fi 首次配置可在 USB 连接下通过网页“设备设置”保存网络。也可连接工具首次启动或长按 CONFIG 三秒开启的 `MCUTOOL-xxxxxx` 热点，密码 `mcutool-setup`，访问 `http://192.168.4.1/setup`。配置成功后热点关闭；正常网络失联不会自动开热点。设备地址从 USB 网络状态或路由器获得，访问令牌从 USB 状态或配网页面获得；令牌不写入普通操作记录。

已有后台不可达时，先读取本机状态和日志；不另开原始串口、杀掉所有 Python 进程或清空活跃锁文件。任务结果未知时先查询记录。后台不兼容或配置路径错误时明确修正环境，不通过另一套连接实现绕过。
