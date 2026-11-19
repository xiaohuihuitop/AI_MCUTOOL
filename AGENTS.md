## Agent skills

### 安装与操作工具板

用户要求安装、接入AI或使用工具板时，先读 `README.md` 的“AI自动安装与接入”，再读 `integrations/skill/xhh-mcu-tool/SKILL.md`。默认使用正式桌面安装器及随附运行环境；安装入口是 `scripts/setup-desktop.ps1`。把安装接入和实际硬件操作区分，按用户已授权的测试范围执行。

### Issue tracker

任务和规格使用本地 Markdown 跟踪。读写前查阅 `docs/agents/issue-tracker.md`。

### Triage labels

使用默认五种 triage 状态。分类前查阅 `docs/agents/triage-labels.md`。

### Domain docs

采用 single-context 布局。探索代码前查阅 `docs/agents/domain.md`。

### 发版主线

桌面正式版和候选版都从已合并并验证的 `master` 提交打标签。准备发版时同步远端，核对上一个正式版和最近候选版的提交均已进入本次发布提交，再用该提交的完整 SHA 创建 Release 草稿并在 `master` 运行签名工作流。功能分支用于开发和评审，版本修复先回到主线。发布说明写明本次覆盖的功能、仍待实测的指标，以及旧客户端进入新版的方式。
