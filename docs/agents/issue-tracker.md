# 问题跟踪：本地 Markdown

任务和规格保存在项目根目录的 `.scratch/` 下。

## 文件约定

- 每个功能使用独立目录：`.scratch/<feature-slug>/`。
- 规格保存为 `spec.md`。
- 每个实施任务独立保存为 `issues/<NN>-<slug>.md`，从 `01` 编号。
- 任务文件顶部通过 `Status:` 记录 triage 状态，取值见 `triage-labels.md`。
- 评论和讨论追加在文件底部的 `## Comments` 下。

## 发布与读取

技能要求“发布到问题跟踪器”时，按上述约定创建文件及所需目录。
技能要求“读取相关任务”时，读取用户指定路径；仅提供编号时，
在对应功能目录解析，存在歧义时先确认。

## Wayfinder 工作流

- 工作地图：`.scratch/<effort>/map.md`，记录笔记、已确认决策和待澄清问题。
- 子任务：`.scratch/<effort>/issues/<NN>-<slug>.md`，正文记录问题。
- 类型：顶部 `Type:` 使用 `research`、`prototype`、`grilling` 或 `task`。
- 工作状态：使用独立的 `Status:` 值 `open`、`claimed`、`resolved`。
- 依赖：顶部 `Blocked by: NN, NN`；所有依赖均为 `resolved` 后解除阻塞。
- 选择任务：从 `open`、未阻塞的任务中按编号选择最小项。
- 认领：开始工作前保存 `Status: claimed`。
- 完成：在 `## Answer` 下追加答案，保存 `Status: resolved`，
  并向地图的已确认决策中追加摘要和文件链接。
