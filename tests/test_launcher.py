"""AI:真实Windows虚拟环境子进程的启动、复用和退出回归。"""
import json
from pathlib import Path
import socket
import subprocess
import sys


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
