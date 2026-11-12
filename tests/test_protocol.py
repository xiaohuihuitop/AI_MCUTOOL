"""AI:通过公开帧接口验证损坏数据与业务响应隔离。"""
import pytest

from mcutool.protocol import FrameDecoder, encode_frame, response_result, validate_telemetry
from mcutool.errors import ToolError


def test_fragmented_usb_frames_ignore_boot_text_and_reject_corruption():
    """AI:分段输入必须重组，损坏帧不能被作为有效命令。@return 无。"""
    decoder = FrameDecoder()
    message = {"v": 1, "id": "a", "ok": True, "result": {"value": "中文"}}
    encoded = encode_frame(message)
    assert decoder.feed(b"ESP-ROM boot\r\n" + encoded[:9]) == []
    assert decoder.feed(encoded[9:]) == [message]
    broken = bytearray(encoded)
    broken[-1] ^= 1
    with pytest.raises(ToolError, match="校验"):
        decoder.feed(broken)


@pytest.mark.parametrize("error", [None, [], "bad", {"code": None, "message": 3}])
def test_malformed_device_error_is_explicit_protocol_failure(error):
    """AI:不合规范错误体不能让后台采集静默退出。@param error 畸形错误。@return 无。"""
    with pytest.raises(ToolError) as caught:
        response_result({"v": 1, "id": "a", "boot_id": "boot", "ok": False, "error": error}, "a")
    assert caught.value.code == "PROTOCOL_MISMATCH"


@pytest.mark.parametrize("packet", [None, [], {"measurements": None}, {"measurements": {"items": None}}])
def test_malformed_telemetry_is_rejected_before_cache_changes(packet):
    """AI:畸形采集块统一作为协议错误。@param packet 畸形数据。@return 无。"""
    with pytest.raises(ToolError) as caught:
        validate_telemetry(packet, {"measurement_after": 0, "uart_after": 0, "event_after": 0}, "boot")
    assert caught.value.code == "PROTOCOL_MISMATCH"
