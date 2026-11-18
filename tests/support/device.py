"""AI:显式测试设备，用于电脑端协议验证，不代表真实硬件。"""
import copy
import time
import uuid
from mcutool.errors import ToolError
from mcutool.validation import validate


class TestDevice:
    """AI:可控制断线、重启与采样的协议对端。"""
    __test__ = False

    def __init__(self):
        """AI:建立已标记的测试工具。@return 无。"""
        self.boot = uuid.uuid4().hex
        self.started = time.monotonic()
        self.device_id = "TEST-MCUTOOL-001"
        self.state = {"power": "off", "charge": False, "keys_mask": 0, "revision": 0, "busy": False,
                      "power_switching": False, "controller": "", "controller_active": False, "power_deadtime_ms": 100,
                      "timing_verified": False, "uart": {"ready": True, "tx_enabled": False, "tx_draining": False, "baudrate": 115200},
                      "measurement": {"ina226_ready": True, "ads1115_ready": True, "hardware_accuracy_verified": False},
                      "network": {"ready": True, "connected": True, "ssid": "TEST", "ip": "127.0.0.1", "provisioning": False}}
        self.owner = None
        self.actions = {}
        self.requests = []
        self.cache = {}
        self.samples = []
        self.rx = bytearray()
        self.sample_time = -1
        self.fail_next = None
        self.drop_response_for = None
        self.closed = False
        self.calibration = {c: {"channel": c, "state": "uncalibrated"} for c in ("battery_v", "battery_i", "ain1", "ain2", "ain3", "ain4")}

    def tick(self):
        """AI:推进测试动作与预定输入样本。@return 无。"""
        now = time.monotonic()
        for action in self.actions.values():
            if action["state"] == "running" and now >= action["deadline"]:
                action.update(state="succeeded", finished_ms=int((now - self.started) * 1000))
                if action["kind"] == "keys":
                    self.state["keys_mask"] = 0
                else:
                    self.state.update(power=action["source"], power_switching=False)
                self.state["revision"] += 1
        self.state["busy"] = any(a["state"] == "running" for a in self.actions.values())
        self.state["uptime_ms"] = int((now - self.started) * 1000)
        # AI:按固定100ms生成测试样本，调用疏密不改变被测采样频率。
        for tick in range(self.sample_time + 1, int((now - self.started) * 10) + 1):
            self.sample_time = tick
            for channel, value, unit in (("battery_v", 3.9, "V"), ("battery_i", .012, "A"), ("ain1", 3.3, "V"), ("ain2", 1.8, "V"), ("ain3", 5.0, "V"), ("ain4", 0.003, "V")):
                self.samples.append({"seq": len(self.samples) + 1, "boot_id": self.boot, "channel": channel,
                                     "value": value, "nominal": value, "unit": unit, "quality": "uncalibrated",
                                     "t_us": tick * 100000, "window_start_us": max(0, tick * 100000 - 149000),
                                     "window_estimated": True, "calibration_revision": 0})

    async def request(self, request: dict) -> dict:
        """AI:处理测试信封。@param request 请求。@return 明确测试响应。"""
        if self.fail_next:
            error, self.fail_next = self.fail_next, None
            raise ToolError(error, "测试注入的通信故障")
        self.closed = False
        self.tick()
        self.requests.append(copy.deepcopy(request))
        method, params, request_id = request["method"], request["params"], request["id"]
        response = {"v": 1, "id": request_id, "boot_id": self.boot}
        try:
            if request_id in self.cache:
                previous, result = self.cache[request_id]
                if previous != request:
                    raise ToolError("REQUEST_CONFLICT", "重复编号内容不同")
                return copy.deepcopy(result)
            read_only = method in ("device.info", "device.status", "network.status", "calibration.get", "action.get", "telemetry.read")
            if not read_only and request.get("boot_id") != self.boot:
                raise ToolError("DEVICE_RESTARTED", "启动标识不匹配")
            if not read_only and method != "control.claim" and self.owner != request.get("controller"):
                raise ToolError("NOT_OWNER", "未取得设备写权")
            result = self.execute(method, params, request.get("controller"))
            response.update(ok=True, result=copy.deepcopy(result))
        except ToolError as error:
            response.update(ok=False, error=error.as_dict())
        if method not in ("device.info", "device.status", "network.status", "calibration.get", "action.get", "telemetry.read", "control.renew"):
            self.cache[request_id] = (copy.deepcopy(request), copy.deepcopy(response))
        if method == self.drop_response_for:
            self.drop_response_for = None
            raise ToolError("CONNECTION_ERROR", "测试设备已执行，但响应丢失")
        return response

    def execute(self, method, params, controller):
        """AI:执行测试对端公开动作。@param method 方法；params 参数；controller 控制者。@return 结果。"""
        if method == "device.info":
            return {"device_id": self.device_id, "boot_id": self.boot, "protocol_version": 1, "firmware_version": "test-0.1.2",
                    "measurement": {"sample_rate_hz": 10, "battery_sensor": "INA226", "shunt_ohms": 0.02, "current_lsb_a": 0.000125, "battery_voltage_lsb_v": 0.00125},
                    "test_device": True, "capabilities": ["power.select", "keys.run", "charge.set", "telemetry.read", "uart.write"],
                    "limits": {"keys": 5, "max_steps": 128, "max_sequence_ms": 600000, "hardware_verified": False}}
        if method == "device.status":
            return {**self.state, "boot_id": self.boot, "device_id": self.device_id}
        if method == "control.claim":
            if self.owner and self.owner != controller and not params.get("takeover"):
                raise ToolError("NOT_OWNER", "已有控制者")
            self.owner = controller
            self.state.update(controller=controller[:8], controller_active=True)
            self.state["revision"] += 1
            return self.state
        if method == "control.renew":
            return self.state
        if method == "control.release":
            if self.state["busy"]:
                raise ToolError("BUSY", "动作执行中")
            self.owner = None
            self.state.update(controller="", controller_active=False)
            return self.state
        if method == "telemetry.read":
            rows = [r for r in self.samples if r["seq"] > params["measurement_after"]][:12]
            offset = params["uart_after"]
            return {"measurements": {"items": rows, "next": rows[-1]["seq"] if rows else params["measurement_after"], "lost": 0},
                    "events": {"items": [], "next": params["event_after"], "lost": 0},
                    "uart": {"data_hex": self.rx[offset:offset + 8192].hex(), "start": offset, "next": min(len(self.rx), offset + 8192), "lost": 0, "hardware_overflow_events": 0}}
        validate(method, params)
        if method in ("power.select", "keys.run"):
            if method == "power.select" and self.state["charge"] and params["source"] != "battery":
                raise ToolError("INTERLOCK", "请先关闭充电")
            kind = "keys" if method == "keys.run" else "power"
            if any(a["kind"] == kind and a["state"] == "running" for a in self.actions.values()):
                raise ToolError("BUSY", "动作执行中")
            duration = sum(s["duration_ms"] for s in params["steps"]) * params["repeat"] / 1000 if kind == "keys" else .1
            action_id = len(self.actions) + 1
            action = {"action_id": action_id, "kind": kind, "state": "running", "started_ms": self.state["uptime_ms"], "finished_ms": 0, "deadline": time.monotonic() + duration}
            if kind == "keys":
                self.state["keys_mask"] = params["steps"][0]["mask"]
            else:
                action["source"] = params["source"]
                self.state.update(power="off", power_switching=True)
            self.state["revision"] += 1
            self.state["busy"] = True
            self.actions[action_id] = action
            return action
        if method in ("action.get", "action.cancel"):
            action = self.actions.get(params["action_id"])
            if not action:
                raise ToolError("NOT_FOUND", "动作记录不存在")
            if method == "action.cancel":
                if action["kind"] != "keys":
                    raise ToolError("INVALID_PARAMS", "只能取消按键")
                action["state"] = "cancelled"
                self.state["keys_mask"] = 0
            return action
        if method == "charge.set":
            if params["enabled"] and (self.state["power"] != "battery" or self.state["power_switching"]):
                raise ToolError("INTERLOCK", "仅真实电池通路允许充电")
            self.state["charge"] = params["enabled"]
        elif method == "uart.configure":
            if self.state["uart"]["tx_enabled"]:
                raise ToolError("INVALID_STATE", "先禁用TX")
            self.state["uart"]["baudrate"] = params["baudrate"]
        elif method == "uart.tx":
            self.state["uart"]["tx_enabled"] = params["enabled"]
        elif method == "uart.write":
            if not self.state["uart"]["tx_enabled"]:
                raise ToolError("INVALID_STATE", "TX未启用")
            self.rx.extend(bytes.fromhex(params["data_hex"]))
        elif method == "calibration.get":
            return {"channels": list(self.calibration.values())}
        elif method == "calibration.set":
            self.calibration[params["channel"]] = {**params, "state": "calibrated", "revision": 1}
        elif method == "network.status":
            return {**self.state["network"], "api_token": "TEST-ONLY-TOKEN"}
        elif method == "network.configure":
            self.state["network"]["ssid"] = params["ssid"]
        elif method == "timing.set":
            self.state["power_deadtime_ms"] = params["power_deadtime_ms"]
        self.state["revision"] += 1
        return {"completed": True, "uart": self.state["uart"]}

    async def close(self):
        """AI:只关闭测试连接，不取消测试动作。@return 无。"""
        self.closed = True
