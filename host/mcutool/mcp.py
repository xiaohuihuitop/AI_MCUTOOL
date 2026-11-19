"""AI:MCU TOOL 的共享MCP入口，不直接打开硬件。"""
import argparse
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
import sys
from typing import Literal
from fastmcp import FastMCP
from pydantic import StrictBool, StrictInt
from serial.tools import list_ports
from . import __version__
from .client import RuntimeClient, query_runtime
from .cli import ensure_runtime
from .errors import ToolError
from .transports import normalize_http_address


def build_server(data_dir: Path) -> FastMCP:
    """AI:创建可复用后台的MCP。@param data_dir 项目数据目录。@return 服务器。"""
    holder: dict[str, RuntimeClient] = {}

    @asynccontextmanager
    async def lifespan(server):
        """AI:退出仅分离本客户端。@param server MCP服务。@return 生命周期。"""
        try:
            yield
        finally:
            client = holder.pop("client", None)
            if client:
                try:
                    await client.close()
                except ToolError:
                    print("MCU TOOL会话退出未确认；不会断开共享设备或重放操作。", file=sys.stderr)

    server = FastMCP("mcu-tool", lifespan=lifespan, instructions="通过共享后台使用MCU工具。先connect查看身份和状态，显式claim_control后操作。保存request_id，任务通过job_status查询，超时不重放。正常收尾detach，不替其他客户端断开设备。")

    async def invoke(method: str, path: str, body=None):
        """AI:调用当前共享会话并保留错误语义。@param method HTTP方法；path 路径；body 参数。@return 结果或明确错误。"""
        client = holder.get("client")
        if client is None:
            return {"ok": False, "error": {"code": "SESSION_REQUIRED", "message": "先调用connect附着共享后台"}}
        if client.heartbeat_error:
            return {"ok": False, "error": client.heartbeat_error}
        try:
            return await client.request(method, path, body)
        except ToolError as exc:
            return {"ok": False, "error": exc.as_dict()}

    async def write(method: str, request_id: str, params: dict):
        """AI:提交有稳定编号的硬件任务。@param method 方法；request_id 编号；params 参数。@return 任务记录。"""
        return await invoke("POST", "/api/commands", {"method": method, "request_id": request_id, "params": params})

    @server.tool()
    async def ping() -> dict:
        """AI:查询MCP版本和工具清单，不连接硬件。@return 版本与可用工具。"""
        return {"version": __version__, "mode": "shared-runtime", "tools": sorted(await server.get_tools()),
                "limits": {"keys": 5, "key_min_step_ms": 10, "key_max_steps": 128, "key_max_sequence_ms": 600000, "uart_write_bytes": 4096}}

    @server.tool()
    async def runtime_status() -> dict:
        """AI:只查询已有后台状态，不启动后台、不附着或连接硬件。@return 当前状态或不可达原因。"""
        try:
            return await query_runtime(data_dir)
        except ToolError as exc:
            return {"ok": False, "error": exc.as_dict()}

    @server.tool()
    async def discover_devices() -> dict:
        """AI:只枚举USB端口，不默认选择、不打开设备。@return 端口身份，ESP候选不等于已验证工具。"""
        return {"ports": [{"port": p.device, "description": p.description, "vid": p.vid, "pid": p.pid,
                           "serial_number": p.serial_number, "esp_candidate": p.vid == 0x303A} for p in list_ports.comports()]}

    @server.tool()
    async def connect(kind: Literal["usb", "http"] | None = None, port: str | None = None,
                      address: str | None = None, token: str | None = None,
                      expected_device_id: str | None = None, client_name: str = "AI") -> dict:
        """AI:附着共享后台；GUI已连接时省略连接参数。@param kind USB或HTTP；port 明确端口；address 设备地址；token 设备令牌；expected_device_id 预期身份；client_name 名称。@return 状态，不接通输出。"""
        client = holder.get("client")
        created = client is None
        try:
            if address is not None:
                address = normalize_http_address(address)
            if client is None:
                await asyncio.to_thread(ensure_runtime, data_dir)
                client = RuntimeClient(data_dir, name=client_name, kind="mcp")
                state = await client.attach()
                holder["client"] = client
            else:
                state = await client.request("GET", "/api/status")
            if state["connected"]:
                if expected_device_id and state["device"].get("device_id") != expected_device_id:
                    raise ToolError("DEVICE_MISMATCH", "共享后台已连接另一设备，不会替换")
                if kind or port or address or token:
                    selected = state.get("connection", {})
                    if (kind and kind != selected.get("kind")) or (port and port != selected.get("port")) or (address and address != selected.get("address")):
                        raise ToolError("DEVICE_MISMATCH", "连接参数与当前共享设备不同，请先明确断开原设备")
                return state
            if kind is None:
                return state
            spec = {k: v for k, v in {"kind": kind, "port": port, "address": address, "token": token, "expected_device_id": expected_device_id}.items() if v is not None}
            return await client.request("POST", "/api/connect", spec)
        except ToolError as exc:
            if client and created:
                holder.pop("client", None)
                try:
                    await client.close()
                except ToolError:
                    pass
            return {"ok": False, "error": exc.as_dict()}

    @server.tool()
    async def detach() -> dict:
        """AI:只退出本AI会话，保留其他客户端、记录和板上已接收动作。@return 退出结果。"""
        client = holder.pop("client", None)
        if not client:
            return {"detached": True}
        try:
            await client.close()
            return {"detached": True, "outputs_changed": False}
        except ToolError as exc:
            return {"ok": False, "error": exc.as_dict()}

    @server.tool()
    async def claim_control(takeover: StrictBool = False, expected_revision: StrictInt | None = None,
                            expected_device_revision: StrictInt | None = None) -> dict:
        """AI:明确申请操作权；接管先读取当前状态并确认原流程允许交接。@param takeover 是否接管；expected_revision 后台版本；expected_device_revision 板上状态版本。@return 结果，有在途动作时拒绝。"""
        return await invoke("POST", "/api/control/claim", {"takeover": takeover, "expected_revision": expected_revision, "expected_device_revision": expected_device_revision})

    @server.tool()
    async def release_control() -> dict:
        """AI:无在途动作时显式释放操作权，不改变供电。@return 状态。"""
        return await invoke("POST", "/api/control/release")

    @server.tool()
    async def disconnect() -> dict:
        """AI:明确断开所有入口共用的设备通信，需持有操作权且无在途动作；正常收尾用detach。@return 状态，不能解释为被测设备已断电。"""
        return await invoke("POST", "/api/disconnect")

    @server.tool()
    async def device_status() -> dict:
        """AI:查询公共控制状态和带时间/质量的测量快照，不改变设备。@return 当前状态。"""
        return await invoke("GET", "/api/status")

    @server.tool()
    async def power_select(source: Literal["off", "battery", "external"], request_id: str) -> dict:
        """AI:选择供电通路，充电开启时先显式关闭充电。@param source 通路；request_id 稳定请求编号。@return 后台任务，后续查job_status。"""
        return await write("power.select", request_id, {"source": source})

    @server.tool()
    async def charge_set(enabled: StrictBool, request_id: str) -> dict:
        """AI:控制独立充电器通路，开启要求真实电池通路。@param enabled 开关；request_id 编号。@return 任务。"""
        return await write("charge.set", request_id, {"enabled": enabled})

    @server.tool()
    async def run_output_sequence(steps: list[dict], repeat: StrictInt,
                                  finish: Literal["off", "battery", "external", "battery_charge"],
                                  cancel: Literal["off", "battery", "external", "battery_charge"], request_id: str) -> dict:
        """AI:一次下发整段三路开关时序。@param steps 每步为 state 和 duration_ms，状态同 finish，换源插入足够时长的 off 步骤。@param repeat 有限次数。@param finish 正常完成的输出。@param cancel 显式取消的输出。@param request_id 稳定编号。@return 后台任务，板上计时，失联继续执行。"""
        return await write("outputs.run", request_id, {"steps": steps, "repeat": repeat, "finish": finish, "cancel": cancel})

    @server.tool()
    async def cancel_output_sequence(action_id: StrictInt, request_id: str) -> dict:
        """AI:停止指定三路时序并转入预先指定的取消状态。@param action_id 本次启动的板上动作号。@param request_id 独立请求号。@return 取消任务，切换供电时等待板上保护间隔。"""
        return await write("outputs.cancel", request_id, {"action_id": action_id})

    @server.tool()
    async def run_charge_cycle(on_ms: StrictInt, off_ms: StrictInt, count: StrictInt, request_id: str) -> dict:
        """AI:启动板上有限充电循环，要求真实电池且充电已断开。@param on_ms 接通毫秒。@param off_ms 断开毫秒。@param count 完整次数。@param request_id 稳定请求编号。@return 后台任务，失联不重放。"""
        return await write("charge.run", request_id, {"on_ms": on_ms, "off_ms": off_ms, "count": count})

    @server.tool()
    async def action_status(action_id: StrictInt) -> dict:
        """AI:读取当前启动保留的板上动作。@param action_id 当前设备本次启动的动作编号。@return 阶段、终态及该动作的进度证据。"""
        return await invoke("POST", "/api/read", {"method": "action.get", "params": {"action_id": action_id}})

    @server.tool()
    async def cancel_charge_cycle(action_id: StrictInt, request_id: str) -> dict:
        """AI:取消指定充电循环并断开充电。@param action_id 本次启动的循环动作编号。@param request_id 独立取消请求编号。@return 可查询取消任务。"""
        return await write("charge.cancel", request_id, {"action_id": action_id})

    @server.tool()
    async def press_keys(keys: list[StrictInt], press_ms: StrictInt, request_id: str,
                         release_ms: StrictInt = 100, count: StrictInt = 1) -> dict:
        """AI:由板上计时执行单击、长按、连击或多键组合。@param keys 1到5的按键；press_ms 按下时长；request_id 编号；release_ms 释放间隔；count 次数。@return 任务。"""
        if not keys or len(set(keys)) != len(keys) or any(k not in range(1, 6) for k in keys):
            return {"ok": False, "error": {"code": "INVALID_PARAMS", "message": "keys必须是互不重复的1到5"}}
        mask = sum(1 << (k - 1) for k in keys)
        return await write("keys.run", request_id, {"steps": [{"mask": mask, "duration_ms": press_ms}, {"mask": 0, "duration_ms": release_ms}], "repeat": count})

    @server.tool()
    async def run_key_sequence(steps: list[dict], repeat: StrictInt, request_id: str) -> dict:
        """AI:执行有限按键序列。@param steps 每步mask与duration_ms；repeat 重复次数；request_id 编号。@return 任务，最长10分钟。"""
        return await write("keys.run", request_id, {"steps": steps, "repeat": repeat})

    @server.tool()
    async def cancel_keys(action_id: StrictInt, request_id: str) -> dict:
        """AI:取消指定按键动作并释放其按键，不改供电或充电。@param action_id 板上动作编号；request_id 取消请求编号。@return 可查询任务。"""
        return await write("action.cancel", request_id, {"action_id": action_id})

    @server.tool()
    async def job_status(request_id: str) -> dict:
        """AI:查询已有任务，超时不表示未执行。@param request_id 提交前保存的编号。@return 任务及板上动作编号。"""
        return await invoke("GET", "/api/jobs/" + request_id)

    @server.tool()
    async def job_reconcile(request_id: str) -> dict:
        """AI:只查询旧任务的板上执行证据，不重放动作。@param request_id 编号。@return 可确认结果或证据不足。"""
        return await invoke("POST", "/api/jobs/" + request_id + "/reconcile")

    @server.tool()
    async def read_data(kind: Literal["measurements", "uart", "events"], after: StrictInt = 0, limit: StrictInt = 200) -> dict:
        """AI:按本客户端游标读取共享缓存，读取不消费别人的数据。@param kind 类型；after 上次next；limit 最多500。@return 数据、next、lost及后台身份。"""
        return await invoke("GET", f"/api/data/{kind}?after={after}&limit={limit}")

    @server.tool()
    async def uart_configure(baudrate: StrictInt, request_id: str) -> dict:
        """AI:配置3.3V TTL UART，固定8N1、无流控，要求TX禁用。@param baudrate 常用波特率；request_id 编号。@return 任务。"""
        return await write("uart.configure", request_id, {"baudrate": baudrate})

    @server.tool()
    async def uart_tx(enabled: StrictBool, request_id: str) -> dict:
        """AI:显式启禁TX；禁用等待在途字节发完，被测设备掉电前先禁用。@param enabled 开关；request_id 编号。@return 任务，未完成不能声称已高阻。"""
        return await write("uart.tx", request_id, {"enabled": enabled})

    @server.tool()
    async def uart_write(data_hex: str, request_id: str) -> dict:
        """AI:发送最多4096个原始字节，不解析设备协议。@param data_hex 十六进制；request_id 编号。@return 任务，发送完成不等于对端处理成功。"""
        return await write("uart.write", request_id, {"data_hex": data_hex})

    @server.tool()
    async def recording(action: Literal["start", "stop", "status"], takeover: StrictBool = False, expected_revision: StrictInt | None = None) -> dict:
        """AI:控制电脑端原始记录，显示暂停和detach不停止记录。@param action 开始/停止/状态；takeover 明确结束无人记录；expected_revision 已核对的后台版本。@return 文件位置及完整性。"""
        if action == "status":
            status = await invoke("GET", "/api/status")
            return status.get("recording", status)
        return await invoke("POST", "/api/recording/" + action, {"takeover": takeover, "expected_revision": expected_revision} if action == "stop" else None)

    @server.tool()
    async def calibration_get() -> dict:
        """AI:读取每通道校准记录，不改变校准。@return 校准状态和参考条件。"""
        return await invoke("POST", "/api/read", {"method": "calibration.get", "params": {}})

    @server.tool()
    async def calibration_set(channel: Literal["battery_v", "battery_i", "ain1", "ain2", "ain3", "ain4"],
                              gain: float, offset: float, min_value: float, max_value: float,
                              reference: str, request_id: str) -> dict:
        """AI:保存有参考仪表依据的线性校准，不能编造系数。@param channel 通道；gain 增益；offset 偏移；min_value/max_value 校准范围；reference 参考条件；request_id 编号。@return 任务，不代表额定精度已验收。"""
        return await write("calibration.set", request_id, {"channel": channel, "gain": gain, "offset": offset, "min_value": min_value, "max_value": max_value, "reference": reference})

    @server.tool()
    async def network_status() -> dict:
        """AI:读取Wi-Fi状态，USB连接下可能含配对令牌，不将令牌写入报告。@return 网络状态。"""
        return await invoke("POST", "/api/read", {"method": "network.status", "params": {}})

    @server.tool()
    async def network_configure(ssid: str, password: str, request_id: str) -> dict:
        """AI:明确保存网络并尝试连接，不自动选择其他网络。@param ssid 网络名；password 密码；request_id 编号。@return 任务，结果中不回传密码。"""
        return await write("network.configure", request_id, {"ssid": ssid, "password": password})

    @server.tool()
    async def network_connect(request_id: str) -> dict:
        """AI:明确尝试连接已保存Wi-Fi。@param request_id 编号。@return 任务，不改变业务输出。"""
        return await write("network.connect", request_id, {})

    @server.tool()
    async def set_switch_timing(power_deadtime_ms: StrictInt, request_id: str) -> dict:
        """AI:依据实物波形设置本次启动的先断后通间隔，10到1000ms。@param power_deadtime_ms 间隔；request_id 编号。@return 任务，初值和配置不等于硬件已验证。"""
        return await write("timing.set", request_id, {"power_deadtime_ms": power_deadtime_ms})

    return server


def main():
    """AI:以stdio提供MCP，业务输出不写stdout。@return 无。"""
    parser = argparse.ArgumentParser(description="MCU TOOL 共享MCP")
    parser.add_argument("--data-dir", type=Path, required=True)
    args = parser.parse_args()
    build_server(args.data_dir.resolve()).run(transport="stdio", show_banner=False)


if __name__ == "__main__":
    main()
