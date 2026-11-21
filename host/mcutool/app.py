"""AI:共享后台HTTP与WebSocket入口，网页和MCP使用同一运行实例。"""
import asyncio
from contextlib import asynccontextmanager
import hmac
import json
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit
import uuid
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, model_validator
from starlette.middleware.trustedhost import TrustedHostMiddleware
from serial.tools import list_ports
from .errors import ToolError
from .runtime import Runtime
from . import __version__
from .diagnostics import diagnostic_archive
from .paths import web_dist


class Input(BaseModel):
    """AI:所有入口拒绝未声明字段。"""
    model_config = ConfigDict(extra="forbid", strict=True)


class SessionInput(Input):
    """AI:客户端登记参数。"""
    name: str = Field(min_length=1, max_length=80)
    kind: Literal["web", "mcp", "cli", "desktop"]


class ConnectInput(Input):
    """AI:明确选择一种设备连接，不能自动换通道。"""
    kind: Literal["usb", "http"]
    port: str | None = None
    address: str | None = None
    token: str | None = None
    expected_device_id: str | None = None

    @model_validator(mode="after")
    def check_selection(self):
        """AI:校验连接选择。@return 自身，缺少地址时失败。"""
        if self.kind == "usb" and (not self.port or self.address or self.token):
            raise ValueError("USB连接需要明确端口，不接受网络参数")
        if self.kind == "http" and (not self.address or not self.token or self.port):
            raise ValueError("Wi-Fi连接需要设备地址和访问令牌")
        return self


class ClaimInput(Input):
    """AI:接管必须基于用户已观察的状态版本。"""
    takeover: StrictBool = False
    expected_revision: StrictInt | None = None
    expected_device_revision: StrictInt | None = None


class CommandInput(Input):
    """AI:稳定请求编号与受限方法参数。"""
    request_id: str = Field(min_length=1, max_length=64)
    method: str
    params: dict


class RecordingStopInput(Input):
    """AI:无人记录只能在明确操作和最新后台状态下结束。"""
    takeover: StrictBool = False
    expected_revision: StrictInt | None = None


class ReadInput(Input):
    """AI:受限只读设备查询。"""
    method: str
    params: dict = Field(default_factory=dict)


class FirmwareInstallInput(Input):
    """AI:用户在升级提示中确认的设备、启动和目标版本。"""
    device_id: str
    boot_id: str
    version: str


def create_app(data_dir: Path, *, token: str | None = None, transport_factory=None, test_mode=False) -> FastAPI:
    """AI:创建本地应用。@param data_dir 数据目录；token 后台凭据；transport_factory 测试注入；test_mode 测试模式。@return 应用。"""
    runtime_token = token or uuid.uuid4().hex + uuid.uuid4().hex
    runtime = Runtime(Path(data_dir), transport_factory=transport_factory, test_mode=test_mode)

    @asynccontextmanager
    async def lifespan(app):
        """AI:管理运行实例生命周期。@param app 应用。@return 异步生命周期。"""
        await runtime.start()
        try:
            yield
        finally:
            await runtime.close()

    app = FastAPI(title="MCU TOOL", version=__version__, lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.runtime, app.state.token = runtime, runtime_token
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"] + (["testserver"] if test_mode else []))

    @app.middleware("http")
    async def authenticate(request: Request, call_next):
        """AI:只允许本地同源页面及持有凭据的调用。@param request 请求；call_next 下一处理。@return 响应。"""
        origin = request.headers.get("origin")
        if origin and urlsplit(origin).netloc != request.headers.get("host"):
            return JSONResponse({"error": {"code": "ORIGIN_REJECTED", "message": "请求来源与后台不一致"}}, status_code=403)
        if request.url.path.startswith("/api/"):
            supplied = request.headers.get("authorization", "")
            if not hmac.compare_digest(supplied, "Bearer " + runtime_token):
                return JSONResponse({"error": {"code": "AUTH_REQUIRED", "message": "后台授权已失效，请重新打开启动入口"}}, status_code=401)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.exception_handler(ToolError)
    async def tool_error(request: Request, error: ToolError):
        """AI:统一错误结果。@param request 请求；error 工具错误。@return 明确失败响应。"""
        status = 400 if error.code.startswith("INVALID") else 503 if error.code in ("NOT_CONNECTED", "CONNECTION_ERROR") else 409
        return JSONResponse({"ok": False, "error": error.as_dict()}, status_code=status)

    def session_id(request: Request) -> str:
        """AI:验证请求附着会话。@param request 请求。@return 私有会话标识。"""
        value = request.headers.get("x-session-id", "")
        runtime.session(value)
        return value

    @app.get("/api/ping")
    async def ping():
        """AI:只查询后台身份，不连接设备。@return 版本及后台标识。"""
        return {"version": __version__, "protocol": 1, "desktop_protocol": 1, "instance_id": runtime.instance_id, "test_mode": test_mode}

    @app.post("/api/sessions")
    async def attach(body: SessionInput):
        """AI:登记客户端。@param body 登记参数。@return 会话。"""
        return runtime.attach(body.name, body.kind)

    @app.get("/api/runtime/status")
    async def runtime_status():
        """AI:仅查看已存在后台，不登记会话、不连接硬件。@return 公共状态。"""
        return runtime.snapshot()

    @app.post("/api/sessions/heartbeat")
    async def heartbeat(request: Request):
        """AI:续约本客户端。@param request 请求。@return 活性期限。"""
        return runtime.heartbeat(session_id(request))

    @app.delete("/api/sessions/current")
    async def detach(request: Request):
        """AI:退出本会话，保持共享工作。@param request 请求。@return 退出结果。"""
        return runtime.detach(session_id(request))

    @app.get("/api/status")
    async def status(request: Request):
        """AI:查看公共缓存状态。@param request 请求。@return 状态。"""
        session_id(request)
        return runtime.snapshot()

    @app.get("/api/ports")
    async def ports(request: Request):
        """AI:只枚举USB身份，不打开串口。@param request 请求。@return 端口列表。"""
        session_id(request)
        return {"ports": [{"port": p.device, "description": p.description, "vid": p.vid, "pid": p.pid,
                           "serial_number": p.serial_number, "esp_candidate": p.vid == 0x303A} for p in list_ports.comports()]}

    @app.post("/api/connect")
    async def connect(request: Request, body: ConnectInput):
        """AI:显式连接工具。@param request 请求；body 连接参数。@return 状态。"""
        return await runtime.connect(session_id(request), body.model_dump(exclude_none=True))

    @app.post("/api/disconnect")
    async def disconnect(request: Request):
        """AI:显式断开通信。@param request 请求。@return 状态。"""
        return await runtime.disconnect(session_id(request))

    @app.post("/api/firmware/prepare")
    async def prepare_firmware(request: Request, retry: bool = False):
        """AI:预下载所连板的正式固件。@param request 当前会话。@param retry 是否手动复查。@return 检查阶段。"""
        return await runtime.prepare_firmware(session_id(request), retry)

    @app.post("/api/firmware/install")
    async def install_firmware(request: Request, body: FirmwareInstallInput):
        """AI:明确确认后升级所选板。@param request 当前会话。@param body 界面选中的目标。@return 受理状态。"""
        return await runtime.install_firmware(session_id(request), **body.model_dump())

    @app.post("/api/control/claim")
    async def claim(request: Request, body: ClaimInput):
        """AI:申请或明确交接操作权。@param request 请求；body 状态前提。@return 状态。"""
        return await runtime.claim(session_id(request), **body.model_dump())

    @app.post("/api/control/release")
    async def release(request: Request):
        """AI:释放操作权，输出保持。@param request 请求。@return 状态。"""
        return await runtime.release(session_id(request))

    @app.post("/api/read")
    async def read(request: Request, body: ReadInput):
        """AI:读取设备声明的只读能力。@param request 请求；body 查询参数。@return 结果。"""
        return await runtime.read_device(session_id(request), body.method, body.params)

    @app.post("/api/commands")
    async def command(request: Request, body: CommandInput):
        """AI:提交可追踪操作。@param request 请求；body 操作。@return 任务记录。"""
        return await runtime.command(session_id(request), body.request_id, body.method, body.params)

    @app.get("/api/jobs/{request_id}")
    async def job(request: Request, request_id: str):
        """AI:查询任务且不访问硬件。@param request 请求；request_id 编号。@return 任务。"""
        session_id(request)
        record = runtime.jobs.get(request_id)
        if record is None:
            raise ToolError("NOT_FOUND", "任务不存在，不能据此认定未执行")
        return record

    @app.post("/api/jobs/{request_id}/reconcile")
    async def reconcile(request: Request, request_id: str):
        """AI:仅查询板上执行证据。@param request 请求；request_id 编号。@return 核对结果。"""
        return await runtime.reconcile(session_id(request), request_id)

    @app.get("/api/data/{kind}")
    async def data(request: Request, kind: str, after: int = 0, limit: int = 200):
        """AI:增量读取共享数据。@param request 请求；kind 类型；after 游标；limit 条数。@return 历史。"""
        return runtime.data(session_id(request), kind, after, limit)

    @app.post("/api/recording/start")
    async def recording_start(request: Request):
        """AI:开始持续记录。@param request 请求。@return 记录状态。"""
        return await runtime.recording_start(session_id(request))

    @app.post("/api/recording/stop")
    async def recording_stop(request: Request, body: RecordingStopInput | None = None):
        """AI:完成记录落盘。@param request 请求。@return 记录终态。"""
        return await runtime.recording_stop(session_id(request), **(body.model_dump() if body else {}))

    @app.post("/api/runtime/shutdown")
    async def shutdown(request: Request, update: bool = False, confirmation: str = ""):
        """AI:明确请求退出后台，检查其他使用者和在途工作。@param request 请求。@return 退出请求结果。"""
        callback = getattr(app.state, "shutdown_callback", None)
        if callback is None:
            raise ToolError("SHUTDOWN_UNAVAILABLE", "当前运行方式不提供后台退出入口")
        result = await runtime.prepare_shutdown(session_id(request), update=update, confirmation=confirmation)
        if result.get("shutdown_requested"):
            callback()
        return result

    @app.get("/api/diagnostics")
    async def diagnostics(request: Request):
        """AI:导出脱敏诊断信息。@param request 有效本机会话。@return ZIP，不访问硬件或修改记录。"""
        session_id(request)
        return Response(diagnostic_archive(runtime, runtime_token), media_type="application/zip",
                        headers={"Content-Disposition": 'attachment; filename="MCUTOOL-diagnostics.zip"'})

    @app.get("/api/recordings")
    async def recordings(request: Request):
        """AI:列出本项目已有记录。@param request 请求。@return 文件列表。"""
        session_id(request)
        rows = []
        if runtime.recorder.root.exists():
            for directory in sorted(runtime.recorder.root.iterdir(), reverse=True)[:100]:
                if directory.is_dir() and not directory.is_symlink():
                    rows.append({"id": directory.name, "files": [p.name for p in directory.iterdir() if p.is_file() and not p.is_symlink()]})
        return {"recordings": rows}

    @app.get("/api/recordings/{record_id}/{filename}")
    async def download(request: Request, record_id: str, filename: str):
        """AI:导出记录根目录内的文件。@param request 请求；record_id 记录目录；filename 文件。@return 文件。"""
        session_id(request)
        root = runtime.recorder.root.resolve()
        path = (root / record_id / filename).resolve()
        if not path.is_relative_to(root) or not path.is_file() or path.parent.parent != root:
            raise ToolError("NOT_FOUND", "记录文件不存在")
        return FileResponse(path, filename=path.name)

    @app.websocket("/ws")
    async def websocket(ws: WebSocket):
        """AI:向独立订阅者推送显示数据，断开不停止采集。@param ws 连接。@return 无。"""
        if ws.headers.get("origin") and urlsplit(ws.headers["origin"]).netloc != ws.headers.get("host"):
            await ws.close(code=1008)
            return
        await ws.accept()
        try:
            hello = await asyncio.wait_for(ws.receive_json(), timeout=5)
            if not isinstance(hello, dict) or not hmac.compare_digest(str(hello.get("token", "")), runtime_token):
                await ws.close(code=1008)
                return
            client = str(hello.get("session_id", ""))
            runtime.session(client)
            cursors = {kind: max(0, history.sequence - (100 if kind == "events" else 300)) for kind, history in runtime.histories.items()}
            while True:
                frame = {"status": runtime.snapshot(), "data": {}}
                for kind in cursors:
                    block = runtime.data(client, kind, cursors[kind], 200)
                    cursors[kind] = block["next"]
                    frame["data"][kind] = block
                await asyncio.wait_for(ws.send_json(frame), timeout=3)
                try:
                    message = await asyncio.wait_for(ws.receive_json(), timeout=0.25)
                    if message == {"type": "heartbeat"}:
                        runtime.heartbeat(client)
                    else:
                        raise ToolError("INVALID_PARAMS", "WebSocket仅接受活性消息")
                except asyncio.TimeoutError:
                    pass
        except (WebSocketDisconnect, ToolError, ValueError, asyncio.TimeoutError):
            with suppress_websocket():
                await ws.close(code=1008)

    dist = web_dist()

    @app.get("/", response_class=HTMLResponse)
    async def index():
        """AI:提供已构建网页与本机授权。@return 页面或明确构建错误。"""
        index_path = dist / "index.html"
        if not index_path.is_file():
            return HTMLResponse("<html lang='zh-CN'><meta charset='utf-8'><h1>网页尚未构建</h1><p>请运行项目安装脚本后重新打开。</p></html>", status_code=503)
        return HTMLResponse(index_path.read_text(encoding="utf-8").replace("__MCUTOOL_TOKEN__", runtime_token))

    if (dist / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")
    return app


class suppress_websocket:
    """AI:关闭已断开的连接时忽略重复关闭错误，不改变业务结果。"""
    def __enter__(self):
        """AI:开始清理范围。@return 自身。"""
        return self

    def __exit__(self, exc_type, exc, tb):
        """AI:仅处理WebSocket重复关闭。@param exc_type 异常类型；exc 异常；tb 调用栈。@return 是否已处理。"""
        return exc_type is not None and issubclass(exc_type, (RuntimeError, WebSocketDisconnect))
