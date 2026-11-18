"""AI:任务去重、互锁、交接和记录的公共HTTP场景。"""
import json
import time
from fastapi.testclient import TestClient
import pytest
from mcutool.app import create_app
from tests.support.device import TestDevice


@pytest.fixture
def connected(tmp_path):
    """AI:准备显式测试设备及两个客户端。@param tmp_path 数据目录。@return 公共客户端和测试对端。"""
    device = TestDevice()
    app = create_app(tmp_path, token="test-token", transport_factory=lambda _: device, test_mode=True)
    with TestClient(app) as http:
        base = {"Authorization": "Bearer test-token"}
        one = http.post("/api/sessions", headers=base, json={"name": "操作者", "kind": "web"}).json()
        two = http.post("/api/sessions", headers=base, json={"name": "观察者", "kind": "mcp"}).json()
        a, b = {**base, "X-Session-ID": one["session_id"]}, {**base, "X-Session-ID": two["session_id"]}
        assert http.post("/api/connect", headers=a, json={"kind": "http", "address": "http://test", "token": "fixture"}).status_code == 200
        assert http.post("/api/control/claim", headers=a, json={}).status_code == 200
        yield http, a, b, device, tmp_path


def wait_job(http, headers, request_id):
    """AI:查询任务终态而不重放命令。@param http 客户端；headers 会话；request_id 编号。@return 任务。"""
    deadline = time.monotonic() + 4
    while time.monotonic() < deadline:
        response = http.get("/api/jobs/" + request_id, headers=headers)
        assert response.status_code == 200
        result = response.json()
        if result["state"] not in ("accepted", "running"):
            return result
        time.sleep(.02)
    raise AssertionError("任务未按预期完成")


def submit(http, headers, request_id, method, params):
    """AI:提交一次公共写请求。@param http 客户端；headers 会话；request_id 编号；method 方法；params 参数。@return HTTP响应。"""
    return http.post("/api/commands", headers=headers, json={"request_id": request_id, "method": method, "params": params})


def test_update_shutdown_leaves_recording_and_active_action_running(tmp_path):
    """AI:安装前的退出检查保护录制及在途动作。@param tmp_path 测试目录。@return 无。"""
    device = TestDevice()
    app = create_app(tmp_path, token="update-test", transport_factory=lambda _: device, test_mode=True)
    acknowledged = []
    app.state.shutdown_callback = lambda: acknowledged.append(True)
    with TestClient(app) as http:
        auth = {"Authorization": "Bearer update-test"}
        session = http.post("/api/sessions", headers=auth, json={"name":"升级测试","kind":"desktop"}).json()
        headers = {**auth, "X-Session-ID": session["session_id"]}
        assert http.post("/api/connect", headers=headers, json={"kind":"http","address":"http://test","token":"fixture"}).is_success
        assert http.post("/api/control/claim", headers=headers, json={}).is_success
        assert http.post("/api/recording/start", headers=headers, json={}).is_success
        assert http.post("/api/runtime/shutdown", headers=headers).json()["error"]["code"] == "BUSY"
        assert http.get("/api/status", headers=headers).json()["recording"]["state"] == "recording"
        assert http.post("/api/recording/stop", headers=headers, json={}).is_success
        assert submit(http, headers, "held", "keys.run", {"steps":[{"mask":1,"duration_ms":500}], "repeat":1}).is_success
        assert http.post("/api/runtime/shutdown", headers=headers).json()["error"]["code"] == "BUSY"
        assert not acknowledged and wait_job(http, headers, "held")["state"] == "succeeded"
        assert http.post("/api/runtime/shutdown", headers=headers).json()["shutdown_requested"]
        assert acknowledged == [True]


def test_request_id_deduplicates_and_conflicting_content_is_rejected(connected):
    """AI:重复请求不能产生第二次实体动作。@param connected 已连接夹具。@return 无。"""
    http, a, _, device, _ = connected
    params = {"steps": [{"mask": 3, "duration_ms": 100}, {"mask": 0, "duration_ms": 10}], "repeat": 1}
    assert submit(http, a, "once", "keys.run", params).status_code == 200
    assert submit(http, a, "once", "keys.run", params).status_code == 200
    assert wait_job(http, a, "once")["state"] == "succeeded"
    assert sum(r["method"] == "keys.run" for r in device.requests) == 1
    changed = {**params, "repeat": 2}
    assert submit(http, a, "once", "keys.run", changed).json()["error"]["code"] == "REQUEST_CONFLICT"


def test_charging_interlock_keeps_previous_control_state(connected):
    """AI:被拒绝操作不能先关闭充电或改变供电。@param connected 夹具。@return 无。"""
    http, a, _, _, _ = connected
    submit(http, a, "bat", "power.select", {"source": "battery"})
    assert wait_job(http, a, "bat")["state"] == "succeeded"
    submit(http, a, "chg", "charge.set", {"enabled": True})
    assert wait_job(http, a, "chg")["state"] == "succeeded"
    for source in ("off", "external"):
        submit(http, a, source, "power.select", {"source": source})
        failed = wait_job(http, a, source)
        assert failed["state"] == "failed" and failed["error"]["code"] == "INTERLOCK"
    state = http.post("/api/read", headers=a, json={"method": "device.status", "params": {}}).json()
    assert state["power"] == "battery" and state["charge"] is True


def test_cancel_finishes_cancellation_but_marks_original_keys_cancelled(connected):
    """AI:取消请求成功与原动作被取消是两个结果。@param connected 夹具。@return 无。"""
    http, a, b, _, _ = connected
    submit(http, a, "hold", "keys.run", {"steps": [{"mask": 31, "duration_ms": 3000}], "repeat": 1})
    deadline = time.monotonic() + 2
    action_id = None
    while not action_id and time.monotonic() < deadline:
        action_id = http.get("/api/jobs/hold", headers=a).json()["action_id"]
        time.sleep(.01)
    assert action_id
    state = http.get("/api/status", headers=b).json()
    takeover = http.post("/api/control/claim", headers=b, json={"takeover": True, "expected_revision": state["control"]["revision"], "expected_device_revision": state["device_state"]["revision"]})
    assert takeover.json()["error"]["code"] == "BUSY"
    submit(http, a, "cancel", "action.cancel", {"action_id": action_id})
    assert wait_job(http, a, "cancel")["state"] == "succeeded"
    assert wait_job(http, a, "hold")["state"] == "cancelled"
    assert http.post("/api/read", headers=a, json={"method": "device.status", "params": {}}).json()["keys_mask"] == 0


def test_unknown_result_is_not_replayed_on_manual_reconnection(connected):
    """AI:已执行但回复丢失的命令保持未知，重连不重新点击。@param connected 夹具。@return 无。"""
    http, a, _, device, _ = connected
    device.drop_response_for = "keys.run"
    params = {"steps": [{"mask": 1, "duration_ms": 100}], "repeat": 1}
    submit(http, a, "lost", "keys.run", params)
    assert wait_job(http, a, "lost")["state"] == "unknown"
    deadline = time.monotonic() + 2
    while http.get("/api/status", headers=a).json()["connected"] and time.monotonic() < deadline:
        time.sleep(.02)
    assert not http.get("/api/status", headers=a).json()["connected"]
    assert http.post("/api/connect", headers=a, json={"kind": "http", "address": "http://test", "token": "fixture"}).status_code == 200
    assert http.post("/api/control/claim", headers=a, json={}).status_code == 200
    assert submit(http, a, "lost", "keys.run", params).json()["state"] == "unknown"
    assert sum(r["method"] == "keys.run" for r in device.requests) == 1


def test_charge_cycle_reconciles_after_connection_loss_without_replay(connected):
    """AI:动作已受理且随后失联，同一次启动可查回终态。@param connected 隔离的共享后台和模拟设备。@return 无。"""
    http, a, _, device, _ = connected
    submit(http, a, "bat-cycle", "power.select", {"source": "battery"})
    assert wait_job(http, a, "bat-cycle")["state"] == "succeeded"
    params = {"on_ms": 200, "off_ms": 500, "count": 1}
    device.drop_response_for = "action.get"
    submit(http, a, "lost-cycle", "charge.run", params)
    row = wait_job(http, a, "lost-cycle")
    assert row["state"] == "unknown" and row["action_id"]
    device.drop_response_for = None
    assert http.post("/api/connect", headers=a, json={"kind": "http", "address": "http://test", "token": "fixture"}).status_code == 200
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        row = http.post("/api/jobs/lost-cycle/reconcile", headers=a).json()
        if row["state"] == "succeeded":
            break
        time.sleep(.02)
    assert row["state"] == "succeeded" and row["result"]["completed"] == 1 and not row["result"]["on"]
    assert sum(request["method"] == "charge.run" for request in device.requests) == 1


def test_older_firmware_receives_no_charge_cycle_command(tmp_path):
    """AI:旧固件缺少循环能力时，后台直接拒绝。@param tmp_path 隔离目录。@return 无。"""
    device = TestDevice()
    app = create_app(tmp_path, token="old-fw", transport_factory=lambda _: device, test_mode=True)
    with TestClient(app) as http:
        base = {"Authorization": "Bearer old-fw"}
        session = http.post("/api/sessions", headers=base, json={"name":"旧固件测试", "kind":"mcp"}).json()
        headers = {**base, "X-Session-ID": session["session_id"]}
        original = device.execute

        def old_info(method, params, controller):
            """AI:提供旧版真实能力集合中的充电命令。@param method 方法。@param params 参数。@param controller 操作者。@return 设备响应。"""
            result = original(method, params, controller)
            if method == "device.info":
                result["capabilities"] = ["charge.set", "power.select"]
            return result

        device.execute = old_info
        assert http.post("/api/connect", headers=headers, json={"kind":"http", "address":"http://test", "token":"fixture"}).status_code == 200
        assert http.post("/api/control/claim", headers=headers, json={}).status_code == 200
        rejected = submit(http, headers, "old-cycle", "charge.run", {"on_ms":200, "off_ms":500, "count":1})
        assert rejected.json()["error"]["code"] == "METHOD_NOT_FOUND"
        assert not any(request["method"] in ("charge.run", "charge.set") for request in device.requests)


def test_observer_detach_and_page_absence_do_not_stop_recording(connected):
    """AI:原始记录由后台持续保存，观察者退出不停止记录。@param connected 夹具。@return 无。"""
    http, a, b, _, root = connected
    assert http.post("/api/recording/start", headers=a).status_code == 200
    assert http.delete("/api/sessions/current", headers=b).status_code == 200
    submit(http, a, "tx-on", "uart.tx", {"enabled": True})
    wait_job(http, a, "tx-on")
    submit(http, a, "binary", "uart.write", {"data_hex": "0001ff4142"})
    wait_job(http, a, "binary")
    deadline = time.monotonic() + 2
    while not http.get("/api/data/uart?after=0", headers=a).json()["items"] and time.monotonic() < deadline:
        time.sleep(.02)
    result = http.post("/api/recording/stop", headers=a).json()
    assert result["state"] == "completed"
    paths = list((root / "recordings").glob("*/串口.bin"))
    assert len(paths) == 1 and paths[0].read_bytes() == b"\x00\x01\xffAB"
    metadata = json.loads((paths[0].parent / "会话.json").read_text(encoding="utf-8"))
    assert metadata["state"] == "completed" and metadata["test_mode"] is True


def test_takeover_requires_observed_revision_and_blocks_old_operator(connected):
    """AI:显式交接校验版本并撤销原操作者写入。@param connected 夹具。@return 无。"""
    http, a, b, _, _ = connected
    assert http.post("/api/control/claim", headers=b, json={}).json()["error"]["code"] == "NOT_OWNER"
    state = http.get("/api/status", headers=b).json()
    body = {"takeover": True, "expected_revision": state["control"]["revision"], "expected_device_revision": state["device_state"]["revision"]}
    assert http.post("/api/control/claim", headers=b, json={**body, "expected_revision": -1}).json()["error"]["code"] == "STALE_STATE"
    assert http.post("/api/control/claim", headers=b, json=body).status_code == 200
    assert submit(http, a, "old", "power.select", {"source": "off"}).json()["error"]["code"] == "NOT_OWNER"


def test_validation_rejects_bool_integer_and_password_is_not_journaled(connected):
    """AI:严格参数避免隐式转换；Wi-Fi密码不进入任务日志。@param connected 夹具。@return 无。"""
    http, a, _, _, root = connected
    rejected = submit(http, a, "bad", "keys.run", {"steps": [{"mask": True, "duration_ms": 100}], "repeat": 1})
    assert rejected.status_code == 400
    submit(http, a, "wifi", "network.configure", {"ssid": "test", "password": "private-secret-123"})
    job = wait_job(http, a, "wifi")
    assert job["params"]["password"] == "[已隐藏]"
    assert b"private-secret-123" not in (root / "jobs.sqlite3").read_bytes()


def test_recording_directory_failure_is_reported_without_changing_outputs(connected):
    """AI:写盘目录不可用时明确失败，不覆盖文件或改变设备。@param connected 夹具。@return 无。"""
    http, a, _, _, root = connected
    (root / "recordings").write_text("preserve", encoding="utf-8")
    response = http.post("/api/recording/start", headers=a)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "RECORDING_IO"
    assert (root / "recordings").read_text() == "preserve"
    assert http.get("/api/status", headers=a).json()["device_state"]["power"] == "off"


def test_orphan_recording_can_be_stopped_explicitly_without_taking_hardware(connected):
    """AI:失联操作者留下的本机记录可明确结束，不要求重连或接管硬件。@param connected 夹具。@return 无。"""
    http, a, b, device, _ = connected
    assert http.post("/api/recording/start", headers=a).status_code == 200
    device.fail_next = "CONNECTION_ERROR"
    deadline = time.monotonic() + 2
    while http.get("/api/status", headers=a).json()["connected"] and time.monotonic() < deadline:
        time.sleep(.02)
    http.delete("/api/sessions/current", headers=a)
    assert http.post("/api/recording/stop", headers=b).status_code == 409
    state = http.get("/api/status", headers=b).json()
    result = http.post("/api/recording/stop", headers=b, json={"takeover": True, "expected_revision": state["control"]["revision"]})
    assert result.json()["state"] == "completed"
    assert http.get("/api/status", headers=b).json()["control"]["owner"]["name"] == "操作者"
