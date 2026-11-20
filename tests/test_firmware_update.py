"""AI:验证固件升级的签名、实板准入和重连判定。"""
import asyncio
import base64
import json
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest

from mcutool.errors import ToolError
from mcutool.firmware_update import signed_release, verified_images
from mcutool.runtime import Runtime


def test_published_signature_and_corrupt_cache():
    """AI:使用实际发布签名验证篡改拒绝。@return 无。"""
    root = Path(__file__).resolve().parents[1]
    envelope = json.loads((root / "integrations/firmware-update.json").read_bytes())
    release = signed_release(envelope)
    with pytest.raises(ValueError, match="SHA256"):
        verified_images(b"bad", release)
    envelope["payload"] = base64.b64encode(base64.b64decode(envelope["payload"]) + b" ").decode()
    with pytest.raises(ValueError, match="签名"):
        signed_release(envelope)


@pytest.mark.parametrize("case", ["wrong_boot", "busy", "recording", "power", "wifi", "wrong_readback", "success"])
def test_install_checks_before_reset_and_requires_new_boot(tmp_path, monkeypatch, case):
    """AI:升级前的拒绝保留连接，写后须核对同板新启动。@param tmp_path 测试目录。@param monkeypatch 模拟烧录与设备握手。@param case 场景。@return 无。"""
    async def exercise():
        """AI:经共享后台入口完成单个场景。@return 无。"""
        runtime = Runtime(tmp_path)
        token = runtime.attach("固件验收", "web")["session_id"]
        target = dict(device_id="MCUTOOL-TEST", boot_id="old", hardware_revision="rev", firmware_version="0.1.3")
        runtime.info = {**target, "capabilities": []}
        runtime.connected = runtime.device_claimed = True
        runtime.owner = token
        runtime.connection = {"kind": "http" if case == "wifi" else "usb", "port": "COM1"}
        old_transport = AsyncMock()
        runtime.transport = old_transport
        runtime.device_state = {"busy": case == "busy", "power": "battery" if case == "power" else "off",
                                "charge": False, "keys_mask": 0, "uart": {"tx_enabled": False, "tx_draining": False}}
        monkeypatch.setattr(runtime, "_rpc", AsyncMock(return_value=runtime.device_state))
        if case == "recording":
            runtime.recorder.state = "recording"
        runtime.firmware.status = {"phase": "ready", "target": target, "version": "0.1.4"}
        monkeypatch.setattr(runtime.firmware, "images", Mock(return_value=(b"app", b"part")))
        write = Mock()
        monkeypatch.setattr("mcutool.runtime.flash_application", write)
        monkeypatch.setattr("mcutool.runtime.usb_port", lambda _: "COM2")

        async def reconnect(spec, reserved):
            """AI:模拟重启后回读。@param spec 期望板号及端口。@param reserved 原设备锁。@return 无。"""
            assert spec == {"port": "COM2", "kind": "usb", "expected_device_id": target["device_id"]}
            runtime.connected = True
            runtime.info = {**runtime.info, "firmware_version": "0.1.4", "boot_id": "old" if case == "wrong_readback" else "new"}

        monkeypatch.setattr(runtime, "_connect_locked", reconnect)
        try:
            if case in ("wrong_readback", "success"):
                await runtime.install_firmware(token, target["device_id"], "old", "0.1.4")
                await runtime.firmware.task
                assert runtime.firmware.status["phase"] == ("succeeded" if case == "success" else "failed")
                write.assert_called_once()
                old_transport.close.assert_awaited_once()
            else:
                with pytest.raises(ToolError):
                    await runtime.install_firmware(token, target["device_id"], "wrong" if case == "wrong_boot" else "old", "0.1.4")
                old_transport.close.assert_not_awaited()
                write.assert_not_called()
        finally:
            runtime.jobs.close()

    asyncio.run(exercise())
