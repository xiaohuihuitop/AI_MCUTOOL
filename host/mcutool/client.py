"""AI:公共客户端只调用共享后台，不直接打开设备。"""
import asyncio
import json
from pathlib import Path
from urllib.parse import urlsplit
import httpx
from .errors import ToolError


def runtime_info(data_dir: Path) -> dict:
    """AI:读取已启动后台定位信息。@param data_dir 项目数据目录。@return 已校验的本机端点及凭据。"""
    path = data_dir / "runtime.json"
    try:
        info = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ToolError("RUNTIME_UNAVAILABLE", "尚未找到可用后台，请先启动工具") from exc
    parts = urlsplit(info.get("url", ""))
    if parts.scheme != "http" or parts.hostname != "127.0.0.1" or not parts.port or parts.path or parts.username or parts.password or parts.query or parts.fragment or not isinstance(info.get("token"), str) or info.get("protocol") != 1:
        raise ToolError("RUNTIME_MISMATCH", "后台定位信息不合法，不会向其他地址发送凭据")
    return info


class RuntimeClient:
    """AI:网页以外入口的共享会话与活性维护。"""

    def __init__(self, data_dir: Path, name="AI", kind="mcp"):
        """AI:准备公共客户端。@param data_dir 项目数据；name 名称；kind 入口类型。@return 无。"""
        self.data_dir, self.name, self.kind = Path(data_dir), name, kind
        self.http = None
        self.session_id = None
        self.instance_id = None
        self.heartbeat_task = None
        self.heartbeat_error = None

    async def attach(self):
        """AI:复用当前后台并登记本会话。@return 后台状态。"""
        info = runtime_info(self.data_dir)
        self.http = httpx.AsyncClient(base_url=info["url"], headers={"Authorization": "Bearer " + info["token"]}, timeout=12, trust_env=False)
        ping = await self.request("GET", "/api/ping")
        if ping.get("instance_id") != info.get("instance_id") or ping.get("protocol") != 1:
            await self.http.aclose()
            raise ToolError("RUNTIME_MISMATCH", "后台实例或协议已变化，请重新读取状态")
        self.instance_id = ping["instance_id"]
        session = await self.request("POST", "/api/sessions", {"name": self.name, "kind": self.kind})
        self.session_id = session["session_id"]
        self.http.headers["X-Session-ID"] = self.session_id
        self.heartbeat_task = asyncio.create_task(self._heartbeat())
        return await self.request("GET", "/api/status")

    async def request(self, method: str, path: str, body=None):
        """AI:向已验证本机后台发送一次调用。@param method 方法；path 路径；body 参数。@return 结果，不重试。"""
        if self.http is None:
            raise ToolError("SESSION_REQUIRED", "先连接共享后台")
        try:
            response = await self.http.request(method, path, json=body)
            data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ToolError("RUNTIME_UNAVAILABLE", "后台响应未确认，请查询已有任务，勿重放操作") from exc
        if response.is_error:
            error = data.get("error", {"code": "INVALID_PARAMS", "message": str(data.get("detail", "调用失败"))})
            raise ToolError(error.get("code", "RUNTIME_ERROR"), error.get("message", "调用失败"), details=error.get("details"))
        return data

    async def _heartbeat(self):
        """AI:维护本会话，不在失效后自动重新附着。@return 无。"""
        while True:
            await asyncio.sleep(15)
            try:
                await self.request("POST", "/api/sessions/heartbeat")
            except ToolError as exc:
                self.heartbeat_error = exc.as_dict()
                return

    async def close(self):
        """AI:仅退出自己的会话，不停止他人采集或已接受动作。@return 无。"""
        if self.heartbeat_task:
            self.heartbeat_task.cancel()
            try:
                await self.heartbeat_task
            except asyncio.CancelledError:
                pass
        try:
            if self.http and self.session_id:
                await self.request("DELETE", "/api/sessions/current")
        finally:
            self.session_id = None
            if self.http:
                await self.http.aclose()
                self.http = None


async def query_runtime(data_dir: Path) -> dict:
    """AI:只查已存在后台，不创建会话和设备连接。@param data_dir 数据目录。@return 公共运行状态。"""
    info = runtime_info(Path(data_dir))
    async with httpx.AsyncClient(base_url=info["url"], headers={"Authorization": "Bearer " + info["token"]}, timeout=3, trust_env=False) as http:
        try:
            response = await http.get("/api/runtime/status")
            response.raise_for_status()
            result = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ToolError("RUNTIME_UNAVAILABLE", "现有后台不可达，没有创建新设备连接") from exc
        if result.get("instance_id") != info.get("instance_id"):
            raise ToolError("RUNTIME_MISMATCH", "后台实例已变化")
        return result
