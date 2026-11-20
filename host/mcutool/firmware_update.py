"""AI:核验正式固件、保存已下载的包，并写入已确认身份的 USB 工具板。"""
import asyncio
import base64
import hashlib
import io
import json
from pathlib import Path
import re
import struct
from zipfile import ZipFile

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
import httpx
from packaging.version import Version
from serial.tools import list_ports

from .errors import ToolError


REPOSITORY = "xiaohuihuitop/AI_MCUTOOL"
MANIFEST_URL = f"https://raw.githubusercontent.com/{REPOSITORY}/master/integrations/firmware-update.json"
# AI:当前硬件修订使用固定的 factory 分区，NVS 在应用分区之前。
APP_OFFSET = 0x10000
APP_SIZE = 0x300000
MAX_PACKAGE = 16 * 1024 * 1024


def signed_release(envelope: dict) -> dict:
    """AI:用内置固件公钥验证发布清单。@param envelope 原始载荷及签名。@return 可用于下载的正式版本信息。"""
    payload = base64.b64decode(envelope["payload"], validate=True)
    signature = base64.b64decode(envelope["signature"], validate=True)
    key = serialization.load_pem_public_key(Path(__file__).with_name("firmware-signing.pub").read_bytes())
    if not isinstance(key, Ed25519PublicKey):
        raise ValueError("固件公钥类型不匹配")
    try:
        key.verify(signature, payload)
    except InvalidSignature as exc:
        raise ValueError("固件发布清单签名无效") from exc
    release = json.loads(payload)
    if (release["schema"] != "mcutool-firmware-v1" or release["repository"] != REPOSITORY
            or release["chip"] != "esp32s3" or not re.fullmatch(r"v\d+\.\d+\.\d+", release["release_tag"])
            or not re.fullmatch(r"\d+\.\d+\.\d+", release["firmware_version"])
            or release["asset"] != f"MCUTOOL-Firmware-{release['firmware_version']}.zip"
            or not re.fullmatch(r"[0-9a-f]{64}", release["sha256"]) or not 0 < release["size"] <= MAX_PACKAGE):
        raise ValueError("正式固件清单的版本、板型或包信息不合法")
    return release


def verified_images(package: bytes, release: dict) -> tuple[bytes, bytes]:
    """AI:核验整包和镜像并读取分区布局。@param package ZIP 原始字节。@param release 已验签清单。@return 应用镜像和分区表。"""
    if len(package) != release["size"] or hashlib.sha256(package).hexdigest() != release["sha256"]:
        raise ValueError("固件包长度或 SHA256 不符")
    with ZipFile(io.BytesIO(package)) as archive:
        images = []
        for name, limit in (("ai_mcutool.bin", APP_SIZE), ("partition_table/partition-table.bin", 4096)):
            path = "firmware/build/" + name
            if archive.namelist().count(path) != 1 or not 0 < archive.getinfo(path).file_size <= limit:
                raise ValueError("固件镜像缺失或大小超出分区")
            images.append(archive.read(path))
    image, partition = images
    if (len(image) < 112 or image[0] != 0xE9 or struct.unpack_from("<H", image, 12)[0] != 9
            or struct.unpack_from("<I", image, 32)[0] != 0xABCD5432
            or image[48:80].split(b"\0")[0] != release["firmware_version"].encode("ascii")
            or image[80:112].split(b"\0")[0] != b"ai_mcutool"):
        raise ValueError("镜像项目、芯片或版本与签名清单不符")
    entries = [struct.unpack_from("<HBBII", partition, offset) for offset in range(0, len(partition)-31, 32)]
    if (0x50AA, 0, 0, APP_OFFSET, APP_SIZE) not in entries:
        raise ValueError("固件包与工具板应用分区不匹配")
    return image, partition


def usb_port(device_id: str) -> str | None:
    """AI:从原生 USB 序列号定位指定板。@param device_id 已确认的板号。@return 唯一匹配端口，未枚举时为空。"""
    matches = [port.device for port in list_ports.comports()
               if port.vid == 0x303A and port.pid == 0x1001
               and "MCUTOOL-" + (port.serial_number or "").replace(":", "").upper() == device_id]
    if len(matches) > 1:
        raise ValueError("多个 USB 端口使用同一工具板编号")
    return matches[0] if matches else None


def flash_application(port: str, device_id: str, image: bytes, partition: bytes) -> None:
    """AI:核对 USB、芯片和分区后写入应用，校验并复位。@param port 已选端口。@param device_id 固件报告的板号。@param image 已验签应用。@param partition 同包分区表。@return 无，失败报告实际阶段。"""
    import esptool
    from esptool.targets.esp32s3 import ESP32S3ROM
    if usb_port(device_id) != port:
        raise ValueError("USB 端口的硬件序列号与所选工具板不符")
    # AI:写入与芯片身份检查共用同一串口句柄，换板不能继承之前的核验。
    with ESP32S3ROM(port, baud=115200) as rom:
        rom.connect(mode="default-reset", attempts=3)
        if "MCUTOOL-" + bytes(rom.read_mac()).hex().upper() != device_id:
            raise ValueError("下载模式下读到的芯片身份与所选板不符")
        esp = esptool.run_stub(rom)
        esptool.attach_flash(esp)
        if esptool.read_flash(esp, 0x8000, len(partition), no_progress=True) != partition:
            raise ValueError("板上分区布局与固件包不同，无法原地更新")
        esptool.write_flash(esp, [(APP_OFFSET, image)], no_progress=True)
        esptool.verify_flash(esp, [(APP_OFFSET, image)])
        esptool.reset_chip(esp)


class FirmwareUpdate:
    """AI:为当前连接的设备独立准备升级包，保留经过核验的缓存和进度。"""

    def __init__(self, data_dir: Path):
        """AI:初始化更新状态。@param data_dir 本机数据目录。@return 无。"""
        self.cache = data_dir / "firmware-updates"
        self.status = {"phase": "idle"}
        self.task = None
        self.envelope = None

    def prepare(self, info: dict, *, retry: bool):
        """AI:按板号、启动和旧版本去重检查。@param info 当前设备身份。@param retry 明确重新检查。@return 无。"""
        if self.status["phase"] in ("installing", "reconnecting"):
            raise ToolError("BUSY", "正在升级固件")
        target = {k: info[k] for k in ("device_id", "boot_id", "firmware_version", "hardware_revision")}
        if self.status.get("target") == target and (not retry or self.status["phase"] in ("checking", "downloading")):
            return
        if self.task and not self.task.done():
            self.task.cancel()
        self.envelope = None
        self.status = {"phase": "checking", "target": target}
        self.task = asyncio.create_task(self._download(target))

    async def _download(self, target: dict):
        """AI:获取签名清单，预下载并核验新版本。@param target 本次检查的设备身份。@return 无。"""
        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
                response = await client.get(MANIFEST_URL)
                response.raise_for_status()
                envelope = response.json()
                release = signed_release(envelope)
                if release["hardware_revision"] != target["hardware_revision"]:
                    raise ValueError("正式固件与当前硬件修订不匹配")
                version = release["firmware_version"]
                if Version(version) <= Version(target["firmware_version"]):
                    self.status.update(phase="current")
                    return
                self.cache.mkdir(parents=True, exist_ok=True)
                path = self.cache / (release["sha256"] + ".zip")
                package = path.read_bytes() if path.is_file() and path.stat().st_size == release["size"] else b""
                if hashlib.sha256(package).hexdigest() != release["sha256"]:
                    self.status.update(phase="downloading", version=version, received=0, total=release["size"])
                    url = f"https://github.com/{REPOSITORY}/releases/download/{release['release_tag']}/{release['asset']}"
                    package = bytearray()
                    async with client.stream("GET", url) as response:
                        response.raise_for_status()
                        async for chunk in response.aiter_bytes():
                            package.extend(chunk)
                            if len(package) > release["size"]:
                                raise ValueError("固件下载超过签名清单声明的长度")
                            self.status["received"] = len(package)
                verified_images(package, release)
                if self.status["phase"] == "downloading":
                    temporary = path.with_suffix(".part")
                    temporary.write_bytes(package)
                    temporary.replace(path)
                self.envelope = envelope
                self.status.update(phase="ready", version=version)
        except Exception as exc:
            self.status.update(phase="failed", message=f"固件检查失败：{exc}")

    def images(self, info: dict, version: str) -> tuple[bytes, bytes]:
        """AI:写入前重新验证缓存、当前版本和板型。@param info 最新设备资料。@param version 用户确认的版本。@return 同次验签得到的应用及分区。"""
        release = signed_release(self.envelope)
        if (release["firmware_version"] != version or release["hardware_revision"] != info["hardware_revision"]
                or Version(version) <= Version(info["firmware_version"])):
            raise ValueError("当前工具板与所选升级包不匹配")
        return verified_images((self.cache / (release["sha256"] + ".zip")).read_bytes(), release)
