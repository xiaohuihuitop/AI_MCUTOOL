"""AI:共享后台公共接口的行为验证。"""
import time
from fastapi.testclient import TestClient
from mcutool.app import create_app
from tests.support.device import TestDevice


def test_observers_share_data_and_cannot_change_operator_outputs(tmp_path):
    """AI:观察者读取不消费数据，未持有操作权时不能写输出。@param tmp_path 隔离目录。@return 无。"""
    device = TestDevice()
    app = create_app(tmp_path, token="test-runtime-token", transport_factory=lambda _: device, test_mode=True)
    with TestClient(app) as client:
        headers = {"Authorization": "Bearer test-runtime-token"}
        a = client.post("/api/sessions", headers=headers, json={"name": "操作者", "kind": "web"}).json()["session_id"]
        b = client.post("/api/sessions", headers=headers, json={"name": "AI观察者", "kind": "mcp"}).json()["session_id"]
        h_a, h_b = {**headers, "X-Session-ID": a}, {**headers, "X-Session-ID": b}
        assert client.post("/api/connect", headers=h_a, json={"kind": "http", "address": "http://test", "token": "fixture"}).status_code == 200
        assert client.post("/api/control/claim", headers=h_a, json={}).status_code == 200
        denied = client.post("/api/commands", headers=h_b, json={"request_id": "deny", "method": "charge.set", "params": {"enabled": True}})
        assert denied.status_code == 409
        assert denied.json()["error"]["code"] == "NOT_OWNER"
        first = client.get("/api/data/measurements?after=0", headers=h_a).json()
        second = client.get("/api/data/measurements?after=0", headers=h_b).json()
        assert first["items"] == second["items"]
        assert client.delete("/api/sessions/current", headers=h_b).status_code == 200
        assert client.get("/api/status", headers=h_a).json()["connected"]


def test_disconnect_stops_polling_and_allows_the_next_connection(tmp_path):
    """AI:断开释放通信，观察者同步状态并可重连同一设备。@param tmp_path 隔离目录。@return 无。"""
    device = TestDevice()
    app = create_app(tmp_path, token="fixture", transport_factory=lambda _: device, test_mode=True)
    with TestClient(app) as client:
        headers = {"Authorization": "Bearer fixture"}
        def session(name):
            """AI:登记一个本机客户端。@param name 会话显示名。@return 请求头。"""
            identity = client.post("/api/sessions", headers=headers, json={"name": name, "kind": "web"}).json()
            return {**headers, "X-Session-ID": identity["session_id"]}
        owner, observer = session("操作"), session("观察")
        spec = {"kind": "http", "address": "http://test", "token": "fixture"}
        assert client.post("/api/connect", headers=owner, json=spec).is_success
        assert client.post("/api/control/claim", headers=owner, json={}).is_success
        assert client.post("/api/disconnect", headers=observer).json()["error"]["code"] == "NOT_OWNER"
        before = {key: device.state[key] for key in ("power", "charge", "keys_mask")}
        result = client.post("/api/disconnect", headers=owner)
        assert result.is_success and result.json()["control"]["owner"] is None
        assert device.closed and not client.get("/api/status", headers=observer).json()["connected"]
        count = len(device.requests)
        time.sleep(.5)
        assert len(device.requests) == count
        assert all(device.state[key] == value for key, value in before.items())
        assert client.post("/api/connect", headers=observer, json=spec).json()["device"]["device_id"] == device.device_id
