# KiCad 接口连接核验

日期：2026-10-24。对象：`D:\Application\kicad\install` 中正在运行的 KiCad 10.0.6，以及当前 AI_MCUTOOL 原理图。

## 结论

已经通过当前华秋运行时的本机 gRPC 接口，读取编辑器内的整板网表并与已确认电路比较通过。该读取链路不依赖桌面截图。

安装目录附带的 `kicad-mcp 0.1.6` 使用旧 NNG/JSON SDK 协议；当前进程没有开放它预期的端点，实测连接被拒绝。不能将“附带 MCP 源码”当成“当前 MCP 已接通”，也不能把 gRPC 直读称为已安装并配置好的 MCP 服务。

## 实测结果

| 检查 | 结果 |
| --- | --- |
| 标准 KiCad IPC | 版本、心跳和已打开原理图查询通过 |
| 当前原理图 | `AI_MCUTOOL.kicad_sch` |
| 客户端层次树 | 总览和八个功能图页均已载入 |
| 旧 SDK 地址 | `ipc://kicad_sdk_pair-309336-schematic`，ConnectionRefused |
| 当前运行时 | 进程实际监听 `127.0.0.1:2643`，gRPC 反射查询通过 |
| 主机识别 | KiCad，版本 10.0.6，安装目录匹配 |
| 实时整板读取 | `hq.ir.schematic.v1.NetListService/GetProjectNetList` 成功 |
| 实体器件 / 物理引脚 | 164 / 508，与连接依据一致 |
| 连接网络 / NC | 124 / 24，逐端点集合一致 |
| 文件变化 | 九个原理图文件 SHA-256 与此前交付一致 |

进程号与端口仅代表本次运行，重启后必须重新发现并识别目标，不能固定写死为永久配置。实际服务通过 gRPC 反射获得；只调用了主机信息、能力查询和整板网表读取，没有调用认证、写入、布局或保存接口。

证据保存在 [运行时校验报告](../hardware/kicad/verification/live-runtime-check.json)、[实时网表](../hardware/kicad/verification/live-netlist.json)、[反射服务目录](../hardware/kicad/verification/runtime-services.json)。基准仍为 `hardware/easyeda-pro/rev-a/binding.json`。

## 能力及限制

主机明确报告支持原理图、网表、选中对象网表、BOM 和放置能力。运行时服务目录还声明了工程管理、命令校验/执行、PCB 放置与布线结果应用等接口；这些接口的存在不代表写入已经验证，也不代表自带可直接使用的自动布局算法。本轮没有 PCB 工程，不测试 PCB 写入。

旧 MCP 的 `KiCadClient.get_netlist()` 在返回前会删除 XML 的 `nets` 节点，故其所谓“完整工程读取”不能用于连接等价验证；部分按键接口的脚号也被声明为整数，不应未经检查用于包含字母脚号的 Type-C 连接器。

桌面窗口和辅助功能文字可读，截图依然超时。因此客户端载入和实时连线已确认，但不能宣称截图、鼠标操作或编辑后重存已验证。

## 后续接入建议

如果需要正式向 AI 暴露 MCP 工具，应为当前 gRPC 运行时建立明确的适配层，先提供已验证的只读能力；写入需在独立测试工程验证事务、撤销、保存和连接完整性后再开放。不要直接配置安装包中的旧 MCP 并假定它兼容。

本次只建立诊断脚本和隔离的临时 Python 环境于 `docs/temp/`，未修改安装目录、全局 Python 环境或 Codex MCP 配置。继续开发正式适配器属于后续范围。
