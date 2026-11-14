# 补齐 0.3.0 配套 Skill

Status: ready-for-human
Progress: completed

2026-11-13 用户提出让 AI 快速使用配套 Skill，并要求先提交界面改版。界面已提交为 `b05b4ed`，随后开始本任务。

## 范围

- 更新现有 `integrations/skill/mcu-assistant-tool`，复用共享 MCP，保持原有设备操作约束。
- 补齐桌面版接入、任务入口、原始测量单位与区间统计说明，明确图表显示设置和设备校准的区别。
- 校验工具 schema、Skill 格式及本地引用，安装本机 Skill 副本并提供可复制的配套包。
- 不调整其他 AI 客户端配置，不运行真实设备写操作；本轮 Skill 改动单独保留，不包含在先前界面提交中。

## Comments

现有 MCP 已提供所需控制和原始数据能力，本任务不新增后端 API 或修改安装器二进制。

已更新 Skill 的任务入口、桌面安装说明和测量分析参考，新增自动发现元数据。格式及 5 处引用、12 组真实工具 schema 校验通过；内存 MCP 只读 ping 返回 0.3.0 / 27 个工具。未连接硬件，未执行硬件写操作。

已安装到 `C:/Users/admin/.codex/skills/mcu-assistant-tool`，并将 5 个文件打包为交付目录内的 `MCUTOOL-Skill-0.3.0.zip`，源码、安装副本及压缩包逐文件一致。安装器二进制保持原 SHA256。验证详情见 `../skill-validation.json`。本轮 Skill 改动尚未提交 Git。
