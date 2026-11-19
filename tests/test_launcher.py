"""AI:真实Windows虚拟环境子进程的启动、复用和退出回归。"""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import pytest
from mcutool.cli import configured_port, ensure_runtime
from mcutool.client import runtime_info
from mcutool.errors import ToolError


def test_virtual_environment_launcher_matches_runtime_identity_not_pid(tmp_path):
    """AI:venv启动器与实际Python可有不同PID，仍应准确识别同一后台。@param tmp_path 隔离目录。@return 无。"""
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    root = Path(__file__).resolve().parents[1]
    base = [sys.executable, "-m", "mcutool.cli"]
    args = ["--data-dir", str(tmp_path), "--port", str(port), "--no-browser"]
    try:
        first = subprocess.run(base + ["start"] + args, cwd=root, capture_output=True, text=True, timeout=35)
        assert first.returncode == 0, first.stderr
        info = json.loads(first.stdout)
        second = subprocess.run(base + ["start"] + args, cwd=root, capture_output=True, text=True, timeout=10)
        assert second.returncode == 0, second.stderr
        assert json.loads(second.stdout)["instance_id"] == info["instance_id"]
        status = subprocess.run(base + ["status", "--data-dir", str(tmp_path)], cwd=root, capture_output=True, text=True, timeout=10)
        assert status.returncode == 0, status.stderr
        assert json.loads(status.stdout)["connected"] is False
    finally:
        stopped = subprocess.run(base + ["stop", "--data-dir", str(tmp_path)], cwd=root, capture_output=True, text=True, timeout=12)
    assert stopped.returncode == 0, stopped.stderr
    assert json.loads(stopped.stdout)["shutdown_requested"] is True


def test_port_conflict_does_not_publish_credentials_and_can_restart(tmp_path, monkeypatch):
    """AI:占用、改端口、同目录复用以及冲突解除都经过真实监听。@param tmp_path 隔离目录；monkeypatch 隔离配置。@return 无。"""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    data = tmp_path / "records"
    assert configured_port(data) == 5210
    with socket.socket() as owner:
        owner.bind(("127.0.0.1", 0))
        owner.listen()
        occupied = owner.getsockname()[1]
        with pytest.raises(ToolError) as error:
            ensure_runtime(data, port=occupied)
        assert error.value.code == "PORT_IN_USE"
        assert f"127.0.0.1:{occupied}" in error.value.message
        assert str(os.getpid()) in error.value.message
        failed = json.loads((data / "runtime.json").read_text(encoding="utf-8"))
        assert failed["state"] == "failed" and "token" not in failed
        with pytest.raises(ToolError, match="已被占用"):
            runtime_info(data)
        with socket.socket() as free:
            free.bind(("127.0.0.1", 0))
            explicit = free.getsockname()[1]
        config = tmp_path / "MCU_TOOL" / "desktop.json"
        config.parent.mkdir()
        config.write_text(json.dumps({"port": explicit, "data_dir": str(data)}), encoding="utf-8")
        info = ensure_runtime(data)
        try:
            assert info["url"] == f"http://127.0.0.1:{explicit}"
            assert ensure_runtime(data, port=explicit)["instance_id"] == info["instance_id"]
            with pytest.raises(ToolError) as mismatch:
                ensure_runtime(data, port=occupied)
            assert mismatch.value.code == "PORT_MISMATCH"
        finally:
            subprocess.run([sys.executable, "-m", "mcutool.cli", "stop", "--data-dir", str(data)], check=True, capture_output=True)
    # AI:新目录排除上一后台异步退出时间的影响，直接在刚释放的地址验证可启动。
    retry_data = tmp_path / "retry"
    assert ensure_runtime(retry_data, port=occupied)["state"] == "ready"
    subprocess.run([sys.executable, "-m", "mcutool.cli", "stop", "--data-dir", str(retry_data)], check=True, capture_output=True)
