"""AI:独立审查发现的并发、重连和证据保持场景。"""
import asyncio
import time
import httpx
from fastapi.testclient import TestClient
from mcutool.app import create_app
from mcutool.errors import ToolError
from tests.support.device import TestDevice
from tests.test_runtime_actions import submit, wait_job


class GatedDevice(TestDevice):
    """AI:仅让测试对端延迟状态响应，复现交接期间的真实等待。"""

    def __init__(self):
        """AI:建立状态响应门。@return 无。"""
        super().__init__()
        self.gate = False
        self.gate_method = "device.status"
        self.entered = asyncio.Event()
        self.resume = asyncio.Event()

    async def request(self, request):
        """AI:受控延迟一份状态响应。@param request 协议请求。@return 响应。"""
        if self.gate and request["method"] == self.gate_method:
            self.gate = False
            self.entered.set()
            await self.resume.wait()
        return await super().request(request)


def test_old_operator_request_queued_during_takeover_is_rejected(tmp_path):
    """AI:取得操作锁之后必须复核权限。@param tmp_path 数据目录。@return 无。"""
    async def scenario():
        """AI:从公共HTTP并发执行交接和旧请求。@return 无。"""
        device = GatedDevice()
        app = create_app(tmp_path, token="test", test_mode=True, transport_factory=lambda _: device)
        async with app.router.lifespan_context(app), httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as http:
            base = {"Authorization": "Bearer test"}
            a = (await http.post("/api/sessions", headers=base, json={"name": "A", "kind": "web"})).json()
            b = (await http.post("/api/sessions", headers=base, json={"name": "B", "kind": "mcp"})).json()
            ha, hb = {**base, "X-Session-ID": a["session_id"]}, {**base, "X-Session-ID": b["session_id"]}
            await http.post("/api/connect", headers=ha, json={"kind": "http", "address": "http://test", "token": "fixture"})
            state = (await http.post("/api/control/claim", headers=ha, json={})).json()
            device.gate = True
            takeover = asyncio.create_task(http.post("/api/control/claim", headers=hb, json={"takeover": True, "expected_revision": state["control"]["revision"], "expected_device_revision": state["device_state"]["revision"]}))
            await asyncio.wait_for(device.entered.wait(), 2)
            old_request = asyncio.create_task(http.post("/api/commands", headers=ha, json={"request_id": "queued-old", "method": "charge.set", "params": {"enabled": False}}))
            await asyncio.sleep(.02)
            device.resume.set()
            assert (await takeover).status_code == 200
            rejected = await old_request
            assert rejected.status_code == 409
            assert rejected.json()["error"]["code"] == "NOT_OWNER"
            assert not any(r["method"] == "charge.set" for r in device.requests)
    asyncio.run(scenario())


def test_shutdown_closes_admission_before_waiting_for_device(tmp_path):
    """AI:退出释放设备期间不能新建会话或排队旧写操作。@param tmp_path 数据目录。@return 无。"""
    async def scenario():
        """AI:在HTTP退出等待期间验证准入门。@return 无。"""
        device = GatedDevice()
        app = create_app(tmp_path, token="test", test_mode=True, transport_factory=lambda _: device)
        acknowledged = []
        app.state.shutdown_callback = lambda: acknowledged.append(True)
        async with app.router.lifespan_context(app), httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as http:
            base = {"Authorization": "Bearer test"}
            session = (await http.post("/api/sessions", headers=base, json={"name": "A", "kind": "web"})).json()
            headers = {**base, "X-Session-ID": session["session_id"]}
            await http.post("/api/connect", headers=headers, json={"kind": "http", "address": "http://test", "token": "fixture"})
            await http.post("/api/control/claim", headers=headers, json={})
            device.gate_method, device.gate = "control.release", True
            shutdown = asyncio.create_task(http.post("/api/runtime/shutdown", headers=headers))
            await asyncio.wait_for(device.entered.wait(), 2)
            rejected = await http.post("/api/sessions", headers=base, json={"name": "B", "kind": "web"})
            assert rejected.json()["error"]["code"] == "RUNTIME_STOPPING"
            device.resume.set()
            assert (await shutdown).json()["shutdown_requested"] is True
            assert (await http.post("/api/control/claim", headers=headers, json={})).json()["error"]["code"] == "RUNTIME_STOPPING"
            assert acknowledged == [True]
    asyncio.run(scenario())


class StatusFailsAfterWrite(TestDevice):
    """AI:写入已确认，随后的状态查询独立失败。"""

    def __init__(self):
        """AI:配置一次状态故障。@return 无。"""
        super().__init__()
        self.fail_status = False

    async def request(self, request):
        """AI:模拟操作完成后的通信中断。@param request 请求。@return 响应。"""
        if request["method"] == "device.status" and self.fail_status:
            self.fail_status = False
            raise ToolError("CONNECTION_ERROR", "测试状态刷新失败")
        result = await super().request(request)
        if request["method"] == "charge.set":
            self.fail_status = True
        return result


def attach_operator(http):
    """AI:建立公共测试会话并取得操作权。@param http 客户端。@return 会话头。"""
    headers = {"Authorization": "Bearer test"}
    session = http.post("/api/sessions", headers=headers, json={"name": "测试操作者", "kind": "web"}).json()
    headers["X-Session-ID"] = session["session_id"]
    assert http.post("/api/connect", headers=headers, json={"kind": "http", "address": "http://test", "token": "fixture"}).status_code == 200
    assert http.post("/api/control/claim", headers=headers, json={}).status_code == 200
    return headers


def test_confirmed_success_survives_later_status_query_failure(tmp_path):
    """AI:后续读失败不能否定已收到的执行证据。@param tmp_path 数据目录。@return 无。"""
    app = create_app(tmp_path, token="test", test_mode=True, transport_factory=lambda _: StatusFailsAfterWrite())
    with TestClient(app) as http:
        headers = attach_operator(http)
        submit(http, headers, "completed-write", "charge.set", {"enabled": False})
        result = wait_job(http, headers, "completed-write")
        assert result["state"] == "succeeded"
        assert result["result"]["completed"] is True


def test_same_boot_reconnection_does_not_duplicate_measurements_or_uart(tmp_path):
    """AI:人工重连同一启动延续游标，原始记录不能重复。@param tmp_path 数据目录。@return 无。"""
    device = TestDevice()
    app = create_app(tmp_path, token="test", test_mode=True, transport_factory=lambda _: device)
    with TestClient(app) as http:
        headers = attach_operator(http)
        http.post("/api/recording/start", headers=headers)
        submit(http, headers, "tx", "uart.tx", {"enabled": True}); wait_job(http, headers, "tx")
        submit(http, headers, "abc", "uart.write", {"data_hex": "414243"}); wait_job(http, headers, "abc")
        deadline = time.monotonic() + 2
        while not http.get("/api/data/uart", headers=headers).json()["items"] and time.monotonic() < deadline:
            time.sleep(.02)
        assert http.post("/api/disconnect", headers=headers).status_code == 200
        assert http.post("/api/connect", headers=headers, json={"kind": "http", "address": "http://test", "token": "fixture"}).status_code == 200
        http.post("/api/control/claim", headers=headers, json={})
        submit(http, headers, "def", "uart.write", {"data_hex": "444546"}); wait_job(http, headers, "def")
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            chunks = http.get("/api/data/uart", headers=headers).json()["items"]
            if chunks and chunks[-1]["next"] == 6:
                break
            time.sleep(.02)
        assert http.post("/api/recording/stop", headers=headers).json()["state"] == "completed"
        serial_file = next((tmp_path / "recordings").glob("*/串口.bin"))
        assert serial_file.read_bytes() == b"ABCDEF"
        samples = http.get("/api/data/measurements", headers=headers).json()["items"]
        assert len({(s["boot_id"], s["seq"]) for s in samples}) == len(samples)
