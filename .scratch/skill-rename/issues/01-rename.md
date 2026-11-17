Type: task
Status: resolved

# 统一Skill名称与引用

按../spec.md实施并核对本机全局Skill可用路径。

## 验证

仓库和本机已安装Skill均更名为`xhh-mcu-tool`，名称、显示名称、默认提示及安装文档同步修改；README、AGENTS、软件说明、安装/打包脚本和既有测试引用全部更新。

两个目录各5个文件逐字节一致，Skill格式校验均通过；引用、UTF-8无BOM和旧目录消除检查通过；3个PowerShell脚本语法检查通过；`tests/test_setup_desktop.py`的3项既有测试全部通过，包含复用已安装运行环境执行只读MCP探测、向隔离目录安装完整Skill。未修改MCP服务配置或操作硬件。

仓库位置：`integrations/skill/xhh-mcu-tool/`。本机位置：`C:/Users/admin/.codex/skills/xhh-mcu-tool/`。在其他项目的新会话中可显式使用`$xhh-mcu-tool`。
