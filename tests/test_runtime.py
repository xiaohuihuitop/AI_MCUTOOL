"""AI:共享后台公共接口的行为验证。"""
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
