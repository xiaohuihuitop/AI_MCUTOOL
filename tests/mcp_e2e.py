"""AI:经真实stdio MCP验证共享后台观察与会话退出，不触碰实物。"""
import asyncio
import json
from pathlib import Path
import sys
from fastmcp import Client


async def verify(data_dir: Path, connection_check=False, charge_check=False):
    """AI:使用协议客户端验证工具调用。@param data_dir 测试后台。@param connection_check 检查连接。@param charge_check 检查充电循环。@return 检查摘要。"""
    config = {"mcpServers": {"mcutool": {"command": sys.executable,
              "args": ["-m", "mcutool.mcp", "--data-dir", str(data_dir)]}}}
    async with Client(config) as client:
        ping = await client.call_tool("ping", {})
        assert ping.data["mode"] == "shared-runtime"
        if connection_check:
            attached = await client.call_tool("connect", {"client_name": "MCP连接流程检查"})
            assert attached.data["connected"] is False
            selected = await client.call_tool("connect", {"kind": "http", "address": " http://127.0.0.1:28767/ ", "token": "fixture"})
            assert selected.data["connected"] is True
            assert selected.data["connection"]["address"] == "http://127.0.0.1:28767"
            reused = await client.call_tool("connect", {"kind": "http", "address": "\thttp://127.0.0.1:28767 "})
            assert reused.data["connected"] is True
            mismatch = await client.call_tool("connect", {"expected_device_id": "wrong-device"})
            assert mismatch.data["error"]["code"] == "DEVICE_MISMATCH"
            assert (await client.call_tool("device_status", {})).data["connected"] is True
            assert (await client.call_tool("disconnect", {})).data["connected"] is False
            await client.call_tool("detach", {})
            return {"attach_then_select": True, "repeated_connect_identity_checked": True}
        if charge_check:
            state = (await client.call_tool("connect", {"client_name": "充电循环离线验证"})).data
            assert state["test_mode"] and state["device"]["test_device"]
            await client.call_tool("claim_control", {})

            async def job(request_id, *, need_id=False):
                """AI:等待动作编号或终态。@param request_id 既有请求。@param need_id 是否只等待板上编号。@return 最新任务。"""
                for _ in range(80):
                    row = (await client.call_tool("job_status", {"request_id": request_id})).data
                    if (need_id and row["action_id"]) or row["state"] not in ("accepted", "running"):
                        return row
                    await asyncio.sleep(.025)
                raise AssertionError("等待充电测试任务超时")

            await client.call_tool("power_select", {"source":"battery", "request_id":"cycle-battery"})
            assert (await job("cycle-battery"))["state"] == "succeeded"
            await client.call_tool("run_charge_cycle", {"on_ms":200,"off_ms":500,"count":2,"request_id":"cycle-end"})
            result = (await job("cycle-end"))["result"]
            assert result["state"] == "succeeded" and result["completed"] == 2 and not result["on"]
            await client.call_tool("run_charge_cycle", {"on_ms":200,"off_ms":500,"count":10,"request_id":"cycle-stop"})
            action_id = (await job("cycle-stop", need_id=True))["action_id"]
            progress = (await client.call_tool("action_status", {"action_id":action_id})).data
            assert progress["state"] == "running" and progress["count"] == 10
            await client.call_tool("cancel_charge_cycle", {"action_id":action_id,"request_id":"cycle-cancel"})
            assert (await job("cycle-cancel"))["state"] == "succeeded"
            assert (await job("cycle-stop"))["state"] == "cancelled"
            assert not (await client.call_tool("device_status", {})).data["device_state"]["charge"]
            await client.call_tool("release_control", {})
            await client.call_tool("detach", {})
            return {"cycle_completed_and_cancelled": True}
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
    print(json.dumps(asyncio.run(verify(Path(sys.argv[1]), "--connection-check" in sys.argv[2:], "--charge-check" in sys.argv[2:])), ensure_ascii=False))
