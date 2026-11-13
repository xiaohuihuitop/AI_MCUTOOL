"""AI:本地后台启动及共享命令行入口。"""
import argparse
import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid
import webbrowser
import httpx
from .app import create_app
from .client import RuntimeClient, query_runtime, runtime_info
from .data import json_text
from .errors import ToolError
from .locking import ProcessLock
from . import __version__
from .paths import default_data_dir, runtime_command, web_dist


def ensure_runtime(data_dir: Path, *, port=8766, browser=False) -> dict:
    """AI:复用后台或显式启动一个无设备连接的实例。@param data_dir 目录；port 本地端口；browser 是否展示。@return 端点元数据。"""
    data_dir = data_dir.resolve()
    if not (web_dist() / "index.html").is_file():
        raise ToolError("WEB_ASSETS_MISSING", "网页产物缺失，请先运行安装或网页构建脚本")
    data_dir.mkdir(parents=True, exist_ok=True)
    startup_lock = ProcessLock(data_dir / "startup.lock")
    try:
        info = None
        if (data_dir / "runtime.json").is_file():
            previous = runtime_info(data_dir)
            try:
                response = httpx.get(previous["url"] + "/api/ping", headers={"Authorization": "Bearer " + previous["token"]}, timeout=2, trust_env=False)
                if response.status_code == 200 and response.json().get("instance_id") == previous.get("instance_id"):
                    if response.json().get('version') != __version__ or response.json().get('protocol') != 1:
                        raise ToolError('RUNTIME_MISMATCH', '已有后台版本不同，请先在原窗口正常退出后台，再启动当前版本')
                    info = previous
            except (httpx.HTTPError, ValueError):
                # AI:只检查启动定位；后续系统锁会拒绝仍在运行的其他后台。
                pass
        if info is None:
            probe_lock = ProcessLock(data_dir / "runtime.lock")
            probe_lock.close()
            startup_id = uuid.uuid4().hex
            log = (data_dir / "runtime.log").open("ab")
            try:
                process = subprocess.Popen(runtime_command() + ["serve", "--data-dir", str(data_dir), "--port", str(port), "--startup-id", startup_id],
                                           stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                           creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            finally:
                log.close()
            deadline = time.monotonic() + 25
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise ToolError("START_FAILED", f"后台启动失败，请查看 {data_dir / 'runtime.log'}")
                if (data_dir / "runtime.json").is_file():
                    candidate = runtime_info(data_dir)
                    # AI:Windows虚拟环境启动器PID不等于实际Python进程，用本次随机启动标识核对。
                    if candidate.get("startup_id") == startup_id:
                        try:
                            response = httpx.get(candidate["url"] + "/api/ping", headers={"Authorization": "Bearer " + candidate["token"]}, timeout=.5, trust_env=False)
                            if response.status_code == 200 and response.json().get("instance_id") == candidate["instance_id"]:
                                info = candidate
                                break
                        except (httpx.HTTPError, ValueError):
                            pass
                time.sleep(.2)
            if info is None:
                process.terminate()
                raise ToolError("START_TIMEOUT", "新后台未在25秒内就绪，已停止本次启动；查看启动日志")
        if browser:
            webbrowser.open(info["url"])
        return info
    finally:
        startup_lock.close()


def serve(data_dir: Path, port: int, test_mode=False, startup_id=None):
    """AI:运行当前项目唯一后台，固定回环监听。@param data_dir 目录；port 端口；test_mode 显式测试；startup_id 启动器核对标识。@return 退出时无。"""
    import uvicorn
    data_dir = data_dir.resolve()
    lock = ProcessLock(data_dir / "runtime.lock")
    try:
        app = create_app(data_dir, test_mode=test_mode)
        info = {"url": f"http://127.0.0.1:{port}", "token": app.state.token, "protocol": 1, "version": __version__,
                "pid": os.getpid(), "instance_id": app.state.runtime.instance_id, "data_dir": str(data_dir), "test_mode": test_mode, "startup_id": startup_id}
        temporary = data_dir / "runtime.json.tmp"
        temporary.write_text(json_text(info), encoding="utf-8")
        temporary.replace(data_dir / "runtime.json")
        server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, access_log=False, log_level="warning", timeout_graceful_shutdown=10))
        app.state.shutdown_callback = lambda: setattr(server, "should_exit", True)
        server.run()
    finally:
        lock.close()


async def cli_call(args):
    """AI:通过共享客户端执行CLI请求。@param args 已解析命令行。@return JSON结果。"""
    if args.action == "status":
        return await query_runtime(args.data_dir)
    client = RuntimeClient(args.data_dir, name="命令行", kind="cli")
    try:
        await client.attach()
        if args.action == "read":
            return await client.request("POST", "/api/read", {"method": args.method, "params": json.loads(args.params)})
        if args.action == "job":
            return await client.request("GET", "/api/jobs/" + args.request_id)
        if args.action == "stop":
            result = await client.request("POST", "/api/runtime/shutdown")
            client.session_id = None
            return result
        raise ToolError("INVALID_PARAMS", "不支持的命令")
    finally:
        await client.close()


def main():
    """AI:解析启动和只读命令行。@return 进程退出码由异常决定。"""
    parser = argparse.ArgumentParser(description="MCU TOOL 共享后台")
    parser.add_argument("action", choices=("start", "serve", "status", "read", "job", "stop", "desktop-start", "can-uninstall"))
    parser.add_argument("--data-dir", type=Path, default=default_data_dir())
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--test-mode", action="store_true", help="明确允许测试设备，页面持续显示测试标识")
    parser.add_argument("--method", default="device.status")
    parser.add_argument("--params", default="{}")
    parser.add_argument("--request-id", default="")
    parser.add_argument("--startup-id", default=None, help=argparse.SUPPRESS)
    args = parser.parse_args()
    try:
        if not 1024 <= args.port <= 65535:
            raise ToolError("INVALID_PARAMS", "后台端口须为1024到65535")
        if args.action == "serve":
            serve(args.data_dir, args.port, args.test_mode, args.startup_id)
        elif args.action == "can-uninstall":
            from .desktop import check_uninstall
            check_uninstall()
        elif args.action == "desktop-start":
            from .desktop import desktop_start
            print(json_text(desktop_start(args.data_dir, args.port, args.test_mode)))
        elif args.action == "start":
            if args.test_mode:
                raise ToolError("INVALID_PARAMS", "测试环境请显式使用serve --test-mode，不复用生产启动入口")
            info = ensure_runtime(args.data_dir, port=args.port, browser=not args.no_browser)
            print(json_text({"url": info["url"], "instance_id": info["instance_id"]}))
        else:
            print(json_text(asyncio.run(cli_call(args))))
    except (ToolError, ValueError) as exc:
        print(json_text({"error": exc.as_dict() if isinstance(exc, ToolError) else {"message": str(exc)}}), file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
