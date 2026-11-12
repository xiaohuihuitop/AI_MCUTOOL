"""AI:经真实stdio MCP验证共享后台观察与会话退出，不触碰实物。"""
import asyncio
import json
from pathlib import Path
import sys
from fastmcp import Client


async def verify(data_dir: Path, connection_check=False):
    """AI:使用协议客户端验证工具调用。@param data_dir 显式测试后台目录。@return 检查摘要。"""
    config = {"mcpServers": {"mcutool": {"command": sys.executable,
              "args": ["-m", "mcutool.mcp", "--data-dir", str(data_dir)]}}}
    async with Client(config) as client:
        ping = await client.call_tool("ping", {})
        assert ping.data["mode"] == "shared-runtime"
        if connection_check:
            attached = await client.call_tool("connect", {"client_name": "MCP连接流程检查"})
            assert attached.data["connected"] is False
            selected = await client.call_tool("connect", {"kind": "http", "address": "http://127.0.0.1:28767", "token": "fixture"})
            assert selected.data["connected"] is True
            mismatch = await client.call_tool("connect", {"expected_device_id": "wrong-device"})
            assert mismatch.data["error"]["code"] == "DEVICE_MISMATCH"
            assert (await client.call_tool("device_status", {})).data["connected"] is True
            assert (await client.call_tool("disconnect", {})).data["connected"] is False
            await client.call_tool("detach", {})
            return {"attach_then_select": True, "repeated_connect_identity_checked": True}
        connected = await client.call_tool("connect", {"client_name": "MCP端到端观察者"})
        assert connected.data["test_mode"] is True and connected.data["connected"] is True
        measurements = await client.call_tool("read_data", {"kind": "measurements", "after": 0, "limit": 20})
        assert measurements.data["items"]
        rejected = await client.call_tool("power_select", {"source": "off", "request_id": "mcp-observer-must-not-write"})
        assert rejected.data["error"]["code"] == "NOT_OWNER"
        detached = await client.call_tool("detach", {})
        assert detached.data["detached"] is True
        status = await client.call_tool("runtime_status", {})
        assert status.data["connected"] is True
        assert status.data["recording"]["state"] == "recording"
        return {"tools": len(ping.data["tools"]), "shared_device": connected.data["device"]["device_id"],
                "observer_write_rejected": True, "detach_kept_recording": True}


if __name__ == "__main__":
    print(json.dumps(asyncio.run(verify(Path(sys.argv[1]), len(sys.argv) > 2 and sys.argv[2] == "--connection-check")), ensure_ascii=False))
