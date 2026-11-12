"""AI:统一可序列化的工具错误。"""

class ToolError(Exception):
    """AI:跨通信入口传递明确的错误代码和说明。"""

    def __init__(self, code: str, message: str, *, details: dict | None = None):
        """AI:初始化错误。@param code 稳定代码；message 中文说明；details 附加事实。@return 无。"""
        super().__init__(message)
        self.code, self.message, self.details = code, message, details or {}

    def as_dict(self) -> dict:
        """AI:转换为公共错误结构。@return 错误代码、说明和附加事实。"""
        return {"code": self.code, "message": self.message, "details": self.details}
