Type: task
Status: resolved

# 发布与AI接入

按照 ../spec.md 完成实施、验证、提交、推送、Release发布及远端回读。

## Answer

用户追加实时跟随修复、紧凑布局和移除图表说明后，发布目标改为0.4.1。功能提交175f574、安装与文档提交0bba896已推送master；注释标签v0.4.1指向0bba8963c65fe557f4a63e48160b8e111554f46c。

已发布 https://github.com/xiaohuihuitop/AI_MCUTOOL/releases/tag/v0.4.1 ，保持原私有仓库可见性。6个发布资产（安装器、同名摘要、AI安装包、Skill、固件、总摘要清单）逐项核对大小和SHA256一致。正式安装脚本以Git凭据从该Release重新下载并校验安装器通过。

本机已用同一脚本升级0.4.1、安装Skill、登记Codex的mcutool并只读ping确认27个工具；安装版连接原COM40，实时缩放持续更新，工作台保持打开。18项前端、41项Python相关测试和11项桌面检查通过。无关嘉立创云端修改继续保留在工作区。
