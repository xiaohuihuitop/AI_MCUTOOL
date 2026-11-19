"""AI:核对受保护工作流签名和正式固件包，生成可整体发布的固件更新清单。"""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import struct
import tempfile
from zipfile import ZipFile

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


ROOT = Path(__file__).resolve().parents[1]
MAX_IMAGE_SIZE = 16 * 1024 * 1024  # AI:当前 ESP32-S3 板载 Flash 容量。


def prepare(signature_path: Path, package_path: Path) -> None:
    """AI:验证后原子替换正式清单。@param signature_path 工作流产物；package_path 正式 ZIP。@return 无，任一检查失败时终止。"""
    manifest = (ROOT / "integrations/firmware-release.json").read_bytes()
    key = serialization.load_pem_public_key((ROOT / "host/mcutool/firmware-signing.pub").read_bytes())
    if not isinstance(key, Ed25519PublicKey):
        raise ValueError("固件公钥算法不符")
    signature = base64.b64decode(signature_path.read_bytes().strip(), validate=True)
    key.verify(signature, manifest)
    release = json.loads(manifest)
    if package_path.name != release["asset"] or package_path.stat().st_size != release["size"]:
        raise ValueError("固件包名称或长度与签名清单不符")
    with package_path.open("rb") as package:
        if hashlib.file_digest(package, "sha256").hexdigest() != release["sha256"]:
            raise ValueError("固件包 SHA256 与签名清单不符")
        with ZipFile(package) as archive:
            image_name = "firmware/build/ai_mcutool.bin"
            if archive.namelist().count(image_name) != 1 or archive.getinfo(image_name).file_size > MAX_IMAGE_SIZE:
                raise ValueError("固件包须包含唯一的工具板应用镜像")
            with archive.open(image_name) as stream:
                header = stream.read(112)
    # AI:ESP 镜像头内 12 处是芯片 ID；首段应用描述内含 magic、版本和项目名。
    if (len(header) != 112 or header[0] != 0xE9 or release["chip"] != "esp32s3"
            or struct.unpack_from("<H", header, 12)[0] != 9
            or struct.unpack_from("<I", header, 32)[0] != 0xABCD5432
            or header[48:80].split(b"\0")[0].decode("ascii") != release["firmware_version"]
            or header[80:112].split(b"\0")[0] != b"ai_mcutool"):
        raise ValueError("应用镜像的项目、芯片或版本与签名清单不符")
    envelope = {"payload": base64.b64encode(manifest).decode("ascii"),
                "signature": base64.b64encode(signature).decode("ascii")}
    destination = ROOT / "integrations/firmware-update.json"
    with tempfile.NamedTemporaryFile(dir=destination.parent, mode="w", encoding="utf-8", newline="\n",
                                     delete=False) as output:
        output.write(json.dumps(envelope, indent=2) + "\n")
    Path(output.name).replace(destination)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("signature", type=Path)
    parser.add_argument("package", type=Path)
    args = parser.parse_args()
    prepare(args.signature, args.package)
