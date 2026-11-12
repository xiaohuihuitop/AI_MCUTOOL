"""AI:设备协议与 USB 有界消息帧。"""
import json
import struct
import zlib
import math
import re
from .errors import ToolError

VERSION = 1
MAX_PAYLOAD = 32768  # AI:与固件共用的单帧上限，避免损坏长度导致无界分配。
MAGIC = b"AMCU"


def encode_frame(message: dict) -> bytes:
    """AI:编码完整 USB 帧。@param message JSON 信封。@return 带长度和 CRC32 的字节。"""
    payload = json.dumps(message, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()
    if not 1 <= len(payload) <= MAX_PAYLOAD:
        raise ToolError("FRAME_LIMIT", "消息超过设备协议长度限制")
    return MAGIC + struct.pack("<I", len(payload)) + payload + struct.pack("<I", zlib.crc32(payload))


class FrameDecoder:
    """AI:保留不完整尾部并隔离 ROM 文本，校验错误明确抛出。"""

    def __init__(self):
        """AI:建立空解码缓存。@return 无。"""
        self.buffer = bytearray()

    def feed(self, chunk: bytes) -> list[dict]:
        """AI:消费任意分段。@param chunk 新字节。@return 完整信封列表，损坏帧抛错。"""
        self.buffer.extend(chunk)
        messages = []
        while self.buffer:
            start = self.buffer.find(MAGIC)
            if start < 0:
                self.buffer[:] = self.buffer[-3:]
                break
            if start:
                del self.buffer[:start]
            if len(self.buffer) < 8:
                break
            size = struct.unpack_from("<I", self.buffer, 4)[0]
            if not 1 <= size <= MAX_PAYLOAD:
                self.buffer.clear()
                raise ToolError("FRAME_LIMIT", "USB 消息长度不合法")
            if len(self.buffer) < size + 12:
                break
            payload = bytes(self.buffer[8:8 + size])
            crc = struct.unpack_from("<I", self.buffer, 8 + size)[0]
            del self.buffer[:size + 12]
            if zlib.crc32(payload) != crc:
                raise ToolError("FRAME_CRC", "USB 消息校验失败，未接受响应")
            try:
                result = json.loads(payload)
            except (UnicodeError, ValueError) as exc:
                raise ToolError("FRAME_JSON", "USB 消息不是有效 JSON") from exc
            if not isinstance(result, dict):
                raise ToolError("FRAME_JSON", "USB 消息信封必须是对象")
            messages.append(result)
        return messages


def response_result(response: dict, request_id: str) -> tuple[dict, str]:
    """AI:校验响应信封。@param response 设备响应；request_id 原请求。@return 结果及启动标识。"""
    if (not isinstance(response, dict) or type(response.get("v")) is not int or response.get("v") != VERSION
            or response.get("id") != request_id or not isinstance(response.get("boot_id"), str) or not response["boot_id"]
            or type(response.get("ok")) is not bool):
        raise ToolError("PROTOCOL_MISMATCH", "设备响应版本或请求标识不匹配")
    if not response["ok"]:
        error = response.get("error")
        if not isinstance(error, dict) or not isinstance(error.get("code"), str) or not error["code"] or not isinstance(error.get("message"), str) or not isinstance(error.get("details", {}), dict):
            raise ToolError("PROTOCOL_MISMATCH", "设备错误响应结构不合法")
        raise ToolError(error["code"], error["message"], details=error.get("details", {}))
    if not isinstance(response.get("result"), dict):
        raise ToolError("PROTOCOL_MISMATCH", "设备响应缺少结果对象")
    return response["result"], response["boot_id"]


def validate_telemetry(packet: dict, cursors: dict, boot_id: str):
    """AI:进入缓存前验证整包结构及连续性。@param packet 数据包；cursors 已读位置；boot_id 启动标识。@return 无，非法时明确拒绝整包。"""
    def integer(value):
        """AI:判断协议安全整数。@param value 输入。@return 是否有效。"""
        return type(value) is int and 0 <= value <= 9007199254740991

    def fail():
        """AI:终止不可信数据包。@return 抛出协议错误。"""
        raise ToolError("PROTOCOL_MISMATCH", "设备采集数据结构、序号或类型不合法")

    if not isinstance(packet, dict):
        fail()
    for source, cursor_key, limit in (("measurements", "measurement_after", 12), ("events", "event_after", 8)):
        block = packet.get(source)
        if not isinstance(block, dict) or not isinstance(block.get("items"), list) or len(block["items"]) > limit or not integer(block.get("next")) or not integer(block.get("lost")):
            fail()
        previous = cursors[cursor_key] + block["lost"]
        for item in block["items"]:
            if not isinstance(item, dict) or not integer(item.get("seq")) or item["seq"] != previous + 1:
                fail()
            previous = item["seq"]
            if source == "measurements":
                channel = item.get("channel")
                if channel not in ("battery_v", "battery_i", "ain1", "ain2", "ain3", "ain4") or item.get("boot_id") != boot_id or item.get("unit") != ("A" if channel == "battery_i" else "V") or not isinstance(item.get("quality"), str) or not integer(item.get("t_us")) or not integer(item.get("window_start_us")) or item["window_start_us"] > item["t_us"]:
                    fail()
                for key in ("value", "nominal"):
                    value = item.get(key)
                    if key not in item or (value is not None and (type(value) not in (int, float) or not math.isfinite(value))):
                        fail()
            elif not isinstance(item.get("name"), str) or not isinstance(item.get("detail"), str) or not integer(item.get("t_us")):
                fail()
        if block["next"] != previous:
            fail()
    uart = packet.get("uart")
    if not isinstance(uart, dict) or any(not integer(uart.get(key)) for key in ("start", "next", "lost", "hardware_overflow_events")):
        fail()
    data = uart.get("data_hex")
    if not isinstance(data, str) or len(data) > 16384 or len(data) % 2 or not re.fullmatch("[0-9a-fA-F]*", data):
        fail()
    if uart["start"] != cursors["uart_after"] + uart["lost"] or uart["next"] != uart["start"] + len(data) // 2:
        fail()
