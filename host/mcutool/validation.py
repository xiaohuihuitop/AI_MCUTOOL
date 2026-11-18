"""AI:所有调用入口共用严格参数与资源契约。"""
import math
import re
from .errors import ToolError

READ_METHODS = {"device.info", "device.status", "network.status", "calibration.get", "action.get"}
RESOURCES = {"power.select": "power", "charge.set": "power", "charge.run": "power", "charge.cancel": "cancel", "timing.set": "power",
             "outputs.run": "power", "outputs.cancel": "cancel",
             "keys.run": "keys", "action.cancel": "cancel", "uart.configure": "uart", "uart.tx": "uart",
             "uart.write": "uart", "calibration.set": "measurement", "network.configure": "network", "network.connect": "network"}
BAUDRATES = (9600, 19200, 38400, 57600, 115200, 230400, 460800, 921600)
CHANNELS = ("battery_v", "battery_i", "ain1", "ain2", "ain3", "ain4")


def integer(value, minimum, maximum):
    """AI:拒绝布尔及浮点替代整数。@param value 输入；minimum/maximum 范围。@return 是否有效。"""
    return type(value) is int and minimum <= value <= maximum


def validate(method: str, params: dict) -> None:
    """AI:校验操作参数及未知字段。@param method 方法；params 参数。@return 无，非法时抛错。"""
    if not isinstance(params, dict):
        raise ToolError("INVALID_PARAMS", "参数必须是对象")
    valid, fields = False, set()
    if method in {"device.info", "device.status", "network.status", "calibration.get", "network.connect"}:
        valid = True
    elif method == "power.select":
        fields = {"source"}
        valid = params.get("source") in ("off", "battery", "external")
    elif method in ("charge.set", "uart.tx"):
        fields = {"enabled"}
        valid = type(params.get("enabled")) is bool
    elif method == "keys.run":
        fields = {"steps", "repeat"}
        steps, repeat = params.get("steps"), params.get("repeat")
        valid = isinstance(steps, list) and 1 <= len(steps) <= 128 and integer(repeat, 1, 1000)
        if valid:
            valid = all(isinstance(s, dict) and set(s) == {"mask", "duration_ms"} and integer(s["mask"], 0, 31) and integer(s["duration_ms"], 10, 60000) for s in steps)
        if valid:
            valid = sum(s["duration_ms"] for s in steps) * repeat <= 600000
    elif method == "charge.run":
        fields = {"on_ms", "off_ms", "count"}
        on_ms, off_ms, count = (params.get(key) for key in ("on_ms", "off_ms", "count"))
        valid = (integer(on_ms, 10, 60000) and integer(off_ms, 10, 60000) and integer(count, 1, 1000)
                 and (on_ms + off_ms) * count <= 600000)
    elif method == "outputs.run":
        fields = {"steps", "repeat", "finish", "cancel"}
        states = ("off", "battery", "external", "battery_charge")
        steps, repeat = params.get("steps"), params.get("repeat")
        valid = (params.get("finish") in states and params.get("cancel") in states and integer(repeat, 1, 1000)
                 and isinstance(steps, list) and 1 <= len(steps) <= 128
                 and all(isinstance(step, dict) and set(step) == {"state", "duration_ms"}
                         and step["state"] in states and integer(step["duration_ms"], 10, 60000) for step in steps))
        if valid:
            valid = sum(step["duration_ms"] for step in steps) * repeat <= 600000
    elif method in ("action.get", "action.cancel", "charge.cancel", "outputs.cancel"):
        fields = {"action_id"}
        valid = integer(params.get("action_id"), 1, 2**32 - 1)
    elif method == "uart.configure":
        fields = {"baudrate"}
        valid = type(params.get("baudrate")) is int and params["baudrate"] in BAUDRATES
    elif method == "uart.write":
        fields = {"data_hex"}
        value = params.get("data_hex")
        valid = isinstance(value, str) and 2 <= len(value) <= 8192 and len(value) % 2 == 0 and re.fullmatch("[0-9a-fA-F]+", value) is not None
    elif method == "timing.set":
        fields = {"power_deadtime_ms"}
        valid = integer(params.get("power_deadtime_ms"), 10, 1000)
    elif method == "network.configure":
        fields = {"ssid", "password"}
        name, secret = params.get("ssid"), params.get("password")
        valid = isinstance(name, str) and 1 <= len(name.encode()) <= 32 and "\0" not in name and isinstance(secret, str) and (len(secret.encode()) == 0 or 8 <= len(secret.encode()) <= 64) and "\0" not in secret
    elif method == "calibration.set":
        fields = {"channel", "gain", "offset", "min_value", "max_value", "reference"}
        values = [params.get(k) for k in ("gain", "offset", "min_value", "max_value")]
        valid = params.get("channel") in CHANNELS and all(type(v) in (int, float) and math.isfinite(v) for v in values)
        if valid:
            gain, offset, low, high = values
            valid = 0 < gain <= 10 and abs(offset) <= 20 and low <= high and low >= (-3 if params["channel"] == "battery_i" else 0) and high <= (3 if params["channel"] == "battery_i" else 15)
        reference = params.get("reference")
        valid = valid and isinstance(reference, str) and 1 <= len(reference.encode()) <= 95 and "\0" not in reference
    else:
        raise ToolError("METHOD_NOT_FOUND", "没有此公共操作")
    if not valid or set(params) != fields:
        raise ToolError("INVALID_PARAMS", "参数类型、字段或范围不合法", details={"method": method})
