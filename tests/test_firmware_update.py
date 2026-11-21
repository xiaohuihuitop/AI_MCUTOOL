"""AI:验证固件升级的签名、实板准入和重连判定。"""
import asyncio
import base64
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, Mock

import httpx
import pytest

from mcutool.errors import ToolError
from mcutool.firmware_update import FirmwareUpdate, flash_application, signed_release, verified_images
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


@pytest.mark.parametrize("case", ["wrong_boot", "busy", "recording", "power", "wifi", "wrong_readback",
                                 "NOT_OWNER", "OWNER_EXPIRED", "concurrent", "offline", "success"])
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
        if case in ("NOT_OWNER", "OWNER_EXPIRED"):
            runtime._rpc.side_effect = ToolError(case, "板端拒绝续约")
        if case == "recording":
            runtime.recorder.state = "recording"
        runtime.firmware.status = {"phase": "ready", "target": target, "version": "0.1.4"}
        if case == "offline":
            runtime.firmware.status = {"phase": "failed", "target": target, "cached_version": "0.1.4"}
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
            if case in ("wrong_readback", "success", "concurrent", "offline"):
                closing, proceed = asyncio.Event(), asyncio.Event()
                async def close_usb():
                    """AI:在释放串口时暂停以重现第二客户端同时检查。@return 无。"""
                    closing.set()
                    await proceed.wait()
                old_transport.close.side_effect = close_usb
                install = asyncio.create_task(runtime.install_firmware(token, target["device_id"], "old", "0.1.4"))
                await asyncio.wait_for(closing.wait(), 2)
                if case == "concurrent":
                    viewer = runtime.attach("另一工作台", "web")["session_id"]
                    check = asyncio.create_task(runtime.prepare_firmware(viewer, True))
                    await asyncio.sleep(0)
                    assert not check.done()
                proceed.set()
                await install
                if case == "concurrent":
                    with pytest.raises(ToolError) as caught:
                        await check
                    assert caught.value.code == "BUSY"
                await runtime.firmware.task
                assert runtime.firmware.status["phase"] == ("failed" if case == "wrong_readback" else "succeeded")
                write.assert_called_once()
                old_transport.close.assert_awaited_once()
                runtime._rpc.assert_awaited_once_with("control.renew", mutation=True)
            else:
                with pytest.raises(ToolError):
                    await runtime.install_firmware(token, target["device_id"], "wrong" if case == "wrong_boot" else "old", "0.1.4")
                old_transport.close.assert_not_awaited()
                write.assert_not_called()
                if case in ("NOT_OWNER", "OWNER_EXPIRED"):
                    runtime._rpc.assert_awaited_once_with("control.renew", mutation=True)
                    assert runtime.connected and not runtime.device_claimed
        finally:
            runtime.jobs.close()

    asyncio.run(exercise())


@pytest.mark.parametrize(("stage", "message"), [("partition", "旧固件完整"), ("write", "完整性未确认"),
                                               ("verify", "完整性未确认"), ("reset", "新固件已写入并校验")])
def test_flash_failure_stage(monkeypatch, stage, message):
    """AI:在下载模式核对失败与写入各阶段保留对应恢复说明。@param monkeypatch 替代串口。@param stage 故障点。@param message 提示。@return 无。"""
    import esptool
    context = MagicMock()
    context.__enter__.return_value.read_mac.return_value = bytes.fromhex("001122334455")
    monkeypatch.setattr("mcutool.firmware_update.usb_port", lambda _: "COM1")
    monkeypatch.setattr("esptool.targets.esp32s3.ESP32S3ROM", Mock(return_value=context))
    for method in ("run_stub", "attach_flash", "write_flash", "verify_flash", "reset_chip"):
        monkeypatch.setattr(esptool, method, Mock())
    monkeypatch.setattr(esptool, "read_flash", Mock(return_value=b"wrong" if stage == "partition" else b"valid"))
    if stage != "partition":
        method = {"write": "write_flash", "verify": "verify_flash", "reset": "reset_chip"}[stage]
        getattr(esptool, method).side_effect = OSError("USB")
    with pytest.raises(ValueError, match=message):
        flash_application("COM1", "MCUTOOL-001122334455", b"app", b"valid")
    assert esptool.write_flash.call_count == int(stage != "partition")
    assert esptool.reset_chip.call_count == int(stage == "reset")


def test_offline_cache_after_restart(tmp_path, monkeypatch):
    """AI:经下载入口保存清单，重启后独立核验缓存。@param tmp_path 缓存目录。@param monkeypatch 隔离网络与镜像测试数据。@return 无。"""
    import hashlib
    from mcutool import firmware_update as fw
    package = b"test image"
    release = dict(sha256=hashlib.sha256(package).hexdigest(), size=len(package), firmware_version="0.1.4",
                   hardware_revision="rev", release_tag="v1.0.0", asset="firmware.zip")
    envelope = {"signed": "test"}
    def verify(envelope_read):
        """AI:只接受本例的签名样本。@param envelope_read 重读的封装。@return 测试清单。"""
        assert envelope_read == envelope
        return release
    def images(raw, manifest):
        """AI:要求与已签名大小和摘要一致。@param raw 包字节。@param manifest 清单。@return 测试镜像。"""
        assert hashlib.sha256(raw).hexdigest() == manifest["sha256"]
        return raw, b"partition"
    monkeypatch.setattr(fw, "signed_release", verify)
    monkeypatch.setattr(fw, "verified_images", images)
    client = httpx.AsyncClient
    online = True
    def respond(request):
        """AI:切换线上下载和离线连接。@param request 地址。@return 本例响应。"""
        if not online:
            raise httpx.ConnectError("offline", request=request)
        return httpx.Response(200, json=envelope) if str(request.url) == fw.MANIFEST_URL else httpx.Response(200, content=package)
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: client(transport=httpx.MockTransport(respond), **kw))
    target = dict(device_id="board", boot_id="boot", firmware_version="0.1.3", hardware_revision="rev")
    async def prepare():
        """AI:构造全新后台对象并等待准备结束。@return 本次实例。"""
        update = FirmwareUpdate(tmp_path)
        update.prepare(target, retry=False)
        await update.task
        return update
    assert asyncio.run(prepare()).status["phase"] == "ready"
    online = False
    restarted = asyncio.run(prepare())
    assert restarted.status["cached_version"] == "0.1.4"
    assert restarted.images(target, "0.1.4")[0] == package
    with pytest.raises(ValueError, match="不匹配"):
        restarted.images(dict(target, hardware_revision="other"), "0.1.4")
    (restarted.cache / (release["sha256"] + ".zip")).write_bytes(b"x" * len(package))
    assert "cached_version" not in asyncio.run(prepare()).status
