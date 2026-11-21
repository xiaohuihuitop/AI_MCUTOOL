"""AI:网页、MCP和命令行共用的设备运行实例。"""
import asyncio
from contextlib import suppress
import hashlib
import os
from pathlib import Path
import re
import time
import uuid
from . import __version__
from .data import History, JobStore, Recorder
from .errors import ToolError
from .firmware_update import FirmwareUpdate, flash_application, usb_port
from .locking import ProcessLock
from .protocol import response_result, validate_telemetry
from .transports import HttpTransport, UsbTransport, normalize_http_address
from .validation import READ_METHODS, RESOURCES, validate

CONNECTION_ERRORS = {"CONNECTION_ERROR", "FRAME_CRC", "FRAME_LIMIT", "FRAME_JSON", "PROTOCOL_MISMATCH", "DEVICE_RESTARTED"}


class Runtime:
    """AI:持有一台工具的连接、公共状态、操作会话与数据。"""

    def __init__(self, data_dir: Path, *, transport_factory=None, test_mode=False):
        """AI:创建未连接后台。@param data_dir 数据目录；transport_factory 测试注入；test_mode 显式测试标识。@return 无。"""
        self.data_dir = data_dir.resolve()
        self.instance_id = uuid.uuid4().hex
        self.controller = uuid.uuid4().hex
        self.test_mode, self.transport_factory = test_mode, transport_factory
        self.transport = None
        self.device_lock = None
        self.connected = self.device_claimed = False
        self.info, self.device_state, self.connection = {}, {}, {}
        self.last_error = None
        self.last_state_at = self.last_data_at = 0.0
        self.sessions = {}
        self.owner = None
        self.control_revision = 0
        self.rpc_lock, self.operation_lock, self.connection_lock = asyncio.Lock(), asyncio.Lock(), asyncio.Lock()
        self.histories = {"measurements": History(6000), "uart": History(2000), "events": History(1000)}
        self.latest = {}
        self.cursors = {"measurement_after": 0, "uart_after": 0, "event_after": 0}
        self.hardware_overflows = 0
        self.jobs = JobStore(self.data_dir / "jobs.sqlite3")
        self.recorder = Recorder(self.data_dir)
        self.active_jobs: dict[str, str] = {}
        self.job_tasks: set[asyncio.Task] = set()
        self.worker = None
        self.stopping = False
        self.closing = False
        self.firmware = FirmwareUpdate(self.data_dir)

    async def start(self):
        """AI:启动独立采集调度。@return 无，不连接设备。"""
        self.worker = asyncio.create_task(self._poll())

    def attach(self, name: str, kind: str) -> dict:
        """AI:建立客户端会话。@param name 名称；kind 入口类型。@return 私有会话令牌及公开标识。"""
        if self.stopping or self.closing:
            raise ToolError("RUNTIME_STOPPING", "后台正在退出，请等待清理完成后重新启动")
        if not name or len(name) > 80 or kind not in ("web", "mcp", "cli", "desktop"):
            raise ToolError("INVALID_PARAMS", "客户端名称或类型不合法")
        token = uuid.uuid4().hex
        public_id = uuid.uuid4().hex[:8]
        self.sessions[token] = {"id": public_id, "name": name, "kind": kind, "deadline": time.monotonic() + 60}
        return {"session_id": token, "client_id": public_id, "ttl_ms": 60000, "instance_id": self.instance_id}

    def session(self, token: str) -> dict:
        """AI:验证会话活性。@param token 私有会话。@return 会话，不自动续约。"""
        if self.stopping or self.closing:
            raise ToolError("RUNTIME_STOPPING", "后台正在退出，不再接受新的客户端操作")
        session = self.sessions.get(token)
        if not session or session["deadline"] <= time.monotonic():
            raise ToolError("SESSION_EXPIRED", "客户端会话已失效，请重新连接后台；已接受动作不会取消")
        return session

    def heartbeat(self, token: str) -> dict:
        """AI:续约当前有效客户端。@param token 私有会话。@return 剩余期限。"""
        self.session(token)["deadline"] = time.monotonic() + 60
        return {"ttl_ms": 60000}

    def detach(self, token: str) -> dict:
        """AI:只退出本客户端。@param token 私有会话。@return 退出结果。"""
        if token in self.sessions:
            self.sessions[token]["deadline"] = 0
        return {"detached": True, "outputs_changed": False}

    def require_owner(self, token: str):
        """AI:所有修改操作检查当前客户端。@param token 会话。@return 无。"""
        self.session(token)
        if self.owner != token:
            raise ToolError("NOT_OWNER", "先取得操作权；其他客户端仍可查看数据")

    def _event(self, name: str, detail: str, **facts):
        """AI:统一保存后台事件。@param name 类型；detail 说明；facts 附加事实。@return 无。"""
        item = self.histories["events"].append({"source": "host", "name": name, "detail": detail,
                                              "received_at": time.time(), **facts})
        self.recorder.emit("events", item)

    async def _rpc(self, method: str, params=None, *, request_id=None, mutation=False) -> dict:
        """AI:一次设备调用，不重放。@param method 方法；params 参数；request_id 编号；mutation 写操作标记。@return 结果。"""
        async with self.rpc_lock:
            if not self.connected or self.transport is None:
                raise ToolError("NOT_CONNECTED", "工具未连接")
            message = {"v": 1, "id": request_id or uuid.uuid4().hex, "method": method, "params": params or {}}
            if mutation:
                message.update(boot_id=self.info["boot_id"], controller=self.controller)
            response = await self.transport.request(message)
            if isinstance(response, dict) and response.get("boot_id") != self.info.get("boot_id"):
                raise ToolError("DEVICE_RESTARTED", "工具已重启，旧动作和缓存不能视为仍有效")
            result, _ = response_result(response, message["id"])
            return result

    async def connect(self, token: str, spec: dict) -> dict:
        """AI:显式连接所选设备。@param token 客户端；spec 连接方式与地址。@return 已验证身份。"""
        self.session(token)
        async with self.operation_lock, self.connection_lock:
            self.session(token)
            self.check_firmware_idle()
            if self.connected:
                raise ToolError("ALREADY_CONNECTED", "已有工具连接，请使用共享状态；更换设备前明确断开")
            if self.active_jobs:
                raise ToolError("BUSY", "任务仍在收尾，不能更换连接")
            return await self._connect_locked(spec)

    async def _connect_locked(self, spec: dict, reserved_lock=None) -> dict:
        """AI:在连接锁内握手并建立新数据段。@param spec 明确选择的连接。@param reserved_lock 升级中的设备锁。@return 已核对的设备状态。"""
        transport = None
        acquired = None
        try:
            if spec["kind"] == "http":
                spec = {**spec, "address": normalize_http_address(spec["address"])}
            if self.transport_factory:
                transport = self.transport_factory(spec)
            elif spec["kind"] == "usb":
                transport = await asyncio.to_thread(UsbTransport, spec["port"])
            elif spec["kind"] == "http":
                transport = HttpTransport(spec["address"], spec["token"])
            else:
                raise ToolError("INVALID_PARAMS", "选择USB或Wi-Fi连接")
            request_id = uuid.uuid4().hex
            response = await transport.request({"v": 1, "id": request_id, "method": "device.info", "params": {}})
            info, boot = response_result(response, request_id)
            if info.get("protocol_version") != 1 or not isinstance(info.get("device_id"), str) or not info["device_id"] or info.get("boot_id") != boot or not isinstance(info.get("capabilities"), list):
                raise ToolError("PROTOCOL_MISMATCH", "所选端口没有返回受支持的工具身份")
            if info.get("test_device") and not self.test_mode:
                raise ToolError("TEST_DEVICE_REFUSED", "生产后台拒绝测试设备，请使用明确的测试环境")
            expected = spec.get("expected_device_id")
            if expected and expected != info["device_id"]:
                raise ToolError("DEVICE_MISMATCH", "连接的设备身份与指定工具不一致")
            if reserved_lock is not None:
                acquired = reserved_lock
            elif not self.test_mode:
                key = hashlib.sha256(info["device_id"].encode()).hexdigest()
                acquired = ProcessLock(Path(os.environ["LOCALAPPDATA"]) / "MCU_TOOL" / "device-locks" / (key + ".lock"))
            previous_info = self.info
            same_boot = previous_info.get("device_id") == info["device_id"] and previous_info.get("boot_id") == boot
            self.transport, self.device_lock, self.info = transport, acquired, info
            self.connected, self.device_claimed = True, False
            self.connection = {k: v for k, v in spec.items() if k in ("kind", "port", "address")}
            if not same_boot:
                self.cursors = {"measurement_after": 0, "uart_after": 0, "event_after": 0}
                self.hardware_overflows = 0
                if previous_info:
                    self._event("device_segment_changed", "设备或启动已变化，旧启动尚未传出的缓存无法确认恢复", previous_device=previous_info.get("device_id"), previous_boot=previous_info.get("boot_id"), device_id=info["device_id"], boot_id=boot)
            self.last_error = None
            self.device_state = await self._rpc("device.status")
            self.last_state_at = time.monotonic()
            self.latest.clear()
            self.owner = None
            self.control_revision += 1
            self._event("connected", "工具已连接，尚未取得操作权", device_id=info["device_id"], boot_id=boot)
            return self.snapshot()
        except BaseException:
            self.connected = False
            self.transport = None
            if transport:
                await transport.close()
            if acquired and acquired is not reserved_lock:
                acquired.close()
            self.device_lock = None
            raise

    async def _lost(self, error: ToolError, transport=None):
        """AI:关闭出现故障的通信。@param error 原错误；transport 轮询失败时对应的连接。@return 无。"""
        async with self.connection_lock:
            if not self.connected or (transport is not None and self.transport is not transport):
                return
            self.connected = self.device_claimed = False
            self.last_error = error.as_dict()
            self.control_revision += 1
            self._event("connection_lost", error.message, error=error.as_dict())
            if self.transport:
                await self.transport.close()
                self.transport = None
            if self.device_lock:
                self.device_lock.close()
                self.device_lock = None

    async def claim(self, token: str, *, takeover=False, expected_revision=None, expected_device_revision=None):
        """AI:取得操作权或显式接管。@param token 客户端；takeover 接管；expected_revision 后台版本；expected_device_revision 设备版本。@return 状态。"""
        self.session(token)
        async with self.operation_lock:
            self.session(token)
            if not self.connected:
                raise ToolError("NOT_CONNECTED", "先连接工具")
            if self.owner == token and self.device_claimed:
                return self.snapshot()
            if self.active_jobs:
                raise ToolError("BUSY", "有在途动作，不能交接操作权")
            if self.owner and not takeover:
                raise ToolError("NOT_OWNER", "操作权仍由原客户端持有，请核对状态后显式接管")
            if takeover:
                if expected_revision != self.control_revision:
                    raise ToolError("STALE_STATE", "后台状态已变化，请刷新后再接管")
                current = await self._rpc("device.status")
                if expected_device_revision != current.get("revision") or current.get("busy"):
                    raise ToolError("STALE_STATE", "设备状态已变化或仍有动作，请重新核对")
            else:
                current = self.device_state
            if not self.device_claimed:
                params = {"takeover": bool(takeover)}
                if takeover:
                    params["expected_revision"] = current["revision"]
                self.device_state = await self._rpc("control.claim", params, mutation=True)
                self.device_claimed = True
                self.last_state_at = time.monotonic()
            self.owner = token
            self.control_revision += 1
            self._event("control_claimed", "操作权已交接", actor=self.sessions[token]["name"])
            return self.snapshot()

    async def release(self, token: str):
        """AI:显式释放操作权，输出保持。@param token 持有会话。@return 状态。"""
        async with self.operation_lock:
            self.require_owner(token)
            if self.active_jobs:
                raise ToolError("BUSY", "等待在途动作结束后再释放操作权")
            if self.device_claimed and self.connected:
                self.device_state = await self._rpc("control.release", mutation=True)
                self.device_claimed = False
            self.owner = None
            self.control_revision += 1
            self._event("control_released", "操作权已释放，输出保持")
            return self.snapshot()

    async def disconnect(self, token: str):
        """AI:明确断开设备通信。@param token 请求会话。@return 状态，不关闭被测设备供电。"""
        async with self.operation_lock:
            self.session(token)
            self.check_firmware_idle()
            if self.owner:
                self.require_owner(token)
            if self.active_jobs:
                raise ToolError("BUSY", "动作正在执行，等待完成后断开")
            async with self.connection_lock:
                if self.connected and self.device_claimed:
                    await self._rpc("control.release", mutation=True)
                self.device_claimed = False
                async with self.rpc_lock:
                    if self.transport:
                        await self.transport.close()
                        self.transport = None
                    self.connected = False
                if self.device_lock:
                    self.device_lock.close()
                    self.device_lock = None
            self.owner = None
            self.control_revision += 1
            self._event("disconnected", "设备通信已断开，板上输出未改变")
            return self.snapshot()

    def check_firmware_idle(self):
        """AI:保护已受理的写入和重连。@return 无，升级占用时拒绝更换设备或退出。"""
        if self.firmware.status["phase"] in ("installing", "reconnecting"):
            raise ToolError("BUSY", "工具板正在升级或重连，请等待结果")

    async def prepare_firmware(self, token: str, retry: bool):
        """AI:为工作台当前设备准备正式包。@param token 会话。@param retry 明确复查。@return 当前阶段。"""
        async with self.operation_lock:
            self.session(token)
            self.check_firmware_idle()
            if not self.connected or self.test_mode or self.info.get("test_device"):
                raise ToolError("NOT_CONNECTED", "请先连接实际工具板")
            self.firmware.prepare(self.info, retry=retry)
            return self.firmware.status

    async def install_firmware(self, token: str, device_id: str, boot_id: str, version: str):
        """AI:验证用户选择并交给独占写入任务。@param token 操作者。@param device_id 板号。@param boot_id 启动编号。@param version 目标版本。@return 已受理的升级状态。"""
        async with self.operation_lock, self.connection_lock:
            self.require_owner(token)
            update = self.firmware
            if self.test_mode or not self.connected or not self.device_claimed or self.connection.get("kind") != "usb":
                raise ToolError("INVALID_CONNECTION", "请通过 USB 连接工具板并取得操作权")
            target = update.status.get("target", {})
            prepared = update.status.get("version") if update.status["phase"] == "ready" else None
            if update.status["phase"] == "failed":
                prepared = update.status.get("cached_version")
            if (not prepared or prepared != version
                    or (self.info["device_id"], self.info["boot_id"]) != (device_id, boot_id)
                    or any(self.info.get(key) != value for key, value in target.items())):
                raise ToolError("STALE_STATE", "设备或固件包已变化，请重新检查")
            if self.active_jobs or self.recorder.state in ("recording", "stopping"):
                raise ToolError("BUSY", "请先结束动作和记录")
            try:
                images = update.images(self.info, version)
            except Exception as exc:
                update.status = {"phase": "failed", "target": target, "message": f"缓存校验失败：{exc}"}
                raise ToolError("INVALID_PACKAGE", update.status["message"]) from exc
            # AI:续约由板端核对当前启动和控制者，返回同次请求的实际输出状态。
            board = await self._renew_control()
            if (board["busy"] or board["power"] != "off" or board["charge"] or board["keys_mask"]
                    or board["uart"]["tx_enabled"] or board["uart"]["tx_draining"]):
                raise ToolError("BUSY", "请先关闭供电、充电、按键和串口发送，再升级")
            self.require_owner(token)
            port = self.connection["port"]
            reserved = self.device_lock
            async with self.rpc_lock:
                await self.transport.close()
                self.transport = self.device_lock = self.owner = None
                self.connected = self.device_claimed = False
            self.control_revision += 1
            update.status = {"phase": "installing", "target": target, "version": version}
            update.task = asyncio.create_task(self._flash_and_reconnect(port, target, version, images, reserved))
            return update.status

    async def _flash_and_reconnect(self, port, target, version, images, reserved):
        """AI:写入一次并等原板重启，独立于页面生命周期。@param port 原 USB 口。@param target 旧身份。@param version 目标版本。@param images 已验证镜像。@param reserved 设备锁。@return 无，终态进入共享快照。"""
        status = self.firmware.status
        try:
            await asyncio.to_thread(flash_application, port, target["device_id"], *images)
            status.update(phase="reconnecting")
            deadline = time.monotonic() + 25
            while True:
                await asyncio.sleep(0.5)
                try:
                    current_port = await asyncio.to_thread(usb_port, target["device_id"])
                    if current_port is None:
                        raise ToolError("PORT_BUSY", "等待原工具板的 USB 端口重新出现")
                    spec = {"kind": "usb", "port": current_port, "expected_device_id": target["device_id"]}
                    async with self.operation_lock, self.connection_lock:
                        await self._connect_locked(spec, reserved)
                    reserved = None
                    break
                except ToolError as exc:
                    if exc.code not in ("PORT_BUSY", "CONNECTION_ERROR") or time.monotonic() >= deadline:
                        raise
            status["new_boot_id"] = self.info["boot_id"]
            if (self.info["boot_id"] == target["boot_id"] or self.info["firmware_version"] != version
                    or self.info["hardware_revision"] != target["hardware_revision"]):
                raise ValueError("回读的启动编号、硬件修订或固件版本不符")
            status.update(phase="succeeded")
            self._event("firmware_updated", "工具板升级完成并已重连", device_id=target["device_id"], version=version)
        except Exception as exc:
            stage = "固件已写入并校验，重连回读失败" if status["phase"] == "reconnecting" else "升级未完成"
            status.update(phase="failed", message=f"{stage}：{exc}")
            self._event("firmware_update_failed", status["message"], device_id=target["device_id"])
        finally:
            if reserved:
                reserved.close()

    async def read_device(self, token: str, method: str, params: dict):
        """AI:执行声明过的只读查询。@param token 客户端；method 方法；params 参数。@return 结果。"""
        self.session(token)
        validate(method, params)
        if method not in READ_METHODS:
            raise ToolError("READ_ONLY", "写操作必须通过任务入口")
        return await self._rpc(method, params)

    async def command(self, token: str, request_id: str, method: str, params: dict) -> dict:
        """AI:先持久化再提交操作。@param token 客户端；request_id 编号；method 方法；params 参数。@return 可追踪任务。"""
        validate(method, params)
        if method not in RESOURCES or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,64}", request_id):
            raise ToolError("INVALID_PARAMS", "写操作名称或请求编号不合法")
        async with self.operation_lock:
            self.require_owner(token)
            if not self.connected or not self.device_claimed:
                raise ToolError("NOT_CONNECTED", "设备未连接或未取得设备操作权")
            fingerprint = self.jobs.fingerprint(method, params, self.info["device_id"])
            existing = self.jobs.existing(request_id, fingerprint)
            if existing:
                return existing
            if method in ("charge.run", "charge.cancel", "outputs.run", "outputs.cancel") and method not in self.info["capabilities"]:
                raise ToolError("METHOD_NOT_FOUND", f"当前固件未提供板上命令 {method}")
            resource = RESOURCES[method]
            if resource != "cancel" and resource in self.active_jobs.values():
                raise ToolError("BUSY", "该功能仍有在途动作，未排队新操作")
            record = self.jobs.accept(request_id, fingerprint, {
                "method": method, "params": {k: ("[已隐藏]" if k == "password" else v) for k, v in params.items()},
                "device_id": self.info["device_id"], "boot_id": self.info["boot_id"],
                "actor": self.sessions[token]["name"], "actor_id": self.sessions[token]["id"], "action_id": None})
            self.active_jobs[request_id] = resource
            self._event("command_accepted", "操作请求已记录", job=record)
            task = asyncio.create_task(self._run_job(request_id, method, params))
            self.job_tasks.add(task)
            task.add_done_callback(self.job_tasks.discard)
            return record

    async def _run_job(self, request_id: str, method: str, params: dict):
        """AI:执行一次请求并追踪板上动作。@param request_id 编号；method 方法；params 参数。@return 无。"""
        confirmed_terminal = False
        try:
            self.jobs.update(request_id, state="running")
            result = await self._rpc(method, params, request_id=request_id, mutation=True)
            if "action_id" in result:
                self.jobs.update(request_id, action_id=result["action_id"], result=result)
                while result.get("state") == "running":
                    await asyncio.sleep(0.05)
                    result = await self._rpc("action.get", {"action_id": result["action_id"]})
                state = "cancelled" if result.get("state") == "cancelled" and RESOURCES[method] != "cancel" else "succeeded"
            else:
                state = "succeeded"
            record = self.jobs.update(request_id, state=state, result=result, finished_at=time.time())
            confirmed_terminal = True
            self._event("command_finished", "操作已取得执行结果", job=record)
        except ToolError as exc:
            unknown = exc.code in CONNECTION_ERRORS | {"NOT_CONNECTED", "NOT_FOUND", "DEVICE_IO", "JOURNAL_ERROR"}
            try:
                record = self.jobs.update(request_id, state="unknown" if unknown else "failed", error=exc.as_dict(), finished_at=time.time())
                self._event("command_error", exc.message, job=record)
            except ToolError as journal_error:
                self.last_error = journal_error.as_dict()
                self._event("journal_error", journal_error.message, request_id=request_id)
            if exc.code in CONNECTION_ERRORS:
                await self._lost(exc)
        except asyncio.CancelledError:
            with suppress(ToolError):
                self.jobs.update(request_id, state="unknown", error={"code": "BACKEND_STOPPED", "message": "后台停止等待，板上动作未被取消"})
            raise
        except Exception as exc:
            self.last_error = {"code": "INTERNAL_ERROR", "message": f"操作处理异常：{type(exc).__name__}"}
            with suppress(ToolError):
                self.jobs.update(request_id, state="unknown", error=self.last_error)
        finally:
            self.active_jobs.pop(request_id, None)
        # AI:后续状态查询不能覆盖已经持久化的执行证据。
        if confirmed_terminal and self.connected:
            try:
                self.device_state = await self._rpc("device.status")
                self.last_state_at = time.monotonic()
            except ToolError as exc:
                self.last_error = exc.as_dict()
                self._event("state_refresh_failed", exc.message)
                if exc.code in CONNECTION_ERRORS:
                    await self._lost(exc)

    async def reconcile(self, token: str, request_id: str):
        """AI:通过既有动作编号核对未知结果，不重发原操作。@param token 会话；request_id 任务。@return 当前证据。"""
        async with self.operation_lock:
            self.session(token)
            job = self.jobs.get(request_id)
            if not job:
                raise ToolError("NOT_FOUND", "任务不存在")
            if not self.connected or job["device_id"] != self.info.get("device_id") or job["boot_id"] != self.info.get("boot_id"):
                raise ToolError("EVIDENCE_UNAVAILABLE", "设备或启动标识不同，不能确认旧动作结果")
            if not job.get("action_id"):
                raise ToolError("EVIDENCE_UNAVAILABLE", "没有已确认的板上动作编号；不能通过重发操作判断结果")
            result = await self._rpc("action.get", {"action_id": job["action_id"]})
            state = result.get("state")
            if state in ("succeeded", "cancelled"):
                terminal = "succeeded" if state == "cancelled" and RESOURCES.get(job["method"]) == "cancel" else state
                return self.jobs.update(request_id, state=terminal, result=result, error=None)
            return {**job, "observed_action": result}

    def _ingest(self, packet: dict):
        """AI:采集源数据并分发给独立缓存及记录器。@param packet 设备数据包。@return 无。"""
        validate_telemetry(packet, self.cursors, self.info["boot_id"])
        received = time.time()
        for source, cursor_key in (("measurements", "measurement_after"), ("events", "event_after")):
            block = packet[source]
            if block.get("lost", 0):
                self._event("device_data_gap", "设备历史缓存发生覆盖", stream=source, lost=block["lost"])
            for item in block["items"]:
                record = self.histories[source].append({**item, "received_at": received, "device_id": self.info["device_id"], "boot_id": self.info["boot_id"]})
                self.recorder.emit(source, record)
                if source == "measurements":
                    self.latest[item["channel"]] = record
            self.cursors[cursor_key] = block["next"]
        uart = packet["uart"]
        if uart.get("lost", 0):
            self._event("device_data_gap", "设备串口缓存发生覆盖", stream="uart", lost=uart["lost"])
        if uart.get("data_hex"):
            record = self.histories["uart"].append({**uart, "received_at": received, "device_id": self.info["device_id"], "boot_id": self.info["boot_id"]})
            self.recorder.emit("uart", record)
        overflows = uart.get("hardware_overflow_events", 0)
        if overflows > self.hardware_overflows:
            self._event("uart_hardware_gap", "UART硬件或驱动丢失数据，字节数量未知", events=overflows - self.hardware_overflows)
        self.hardware_overflows = overflows
        self.cursors["uart_after"] = uart["next"]
        self.last_data_at = received

    async def _renew_control(self):
        """AI:由板端核对持有者并续约。@return 当次板端状态，失去操作权时更新本地标记并抛出原错误。"""
        try:
            return await self._rpc("control.renew", mutation=True)
        except ToolError as exc:
            if exc.code in ("NOT_OWNER", "OWNER_EXPIRED"):
                self.device_claimed = False
                self.control_revision += 1
                self._event("device_control_lost", "设备操作权已失效，请核对状态后显式取得操作权")
            raise

    async def _poll(self):
        """AI:持续采集不依赖网页或单次MCP调用。@return 无。"""
        last_status = last_renew = 0.0
        while not self.stopping:
            transport = self.transport
            try:
                async with self.connection_lock:
                    transport = self.transport
                    if not self.connected:
                        continue
                    now = time.monotonic()
                    if self.device_claimed and now - last_renew >= 15:
                        try:
                            await self._renew_control()
                        except ToolError as exc:
                            if exc.code not in ("NOT_OWNER", "OWNER_EXPIRED"):
                                raise
                        last_renew = now
                    if now - last_status >= 0.5:
                        self.device_state = await self._rpc("device.status")
                        self.last_state_at = now
                        last_status = now
                    self._ingest(await self._rpc("telemetry.read", dict(self.cursors)))
            except ToolError as exc:
                await self._lost(exc, transport)
            except (KeyError, TypeError, ValueError) as exc:
                await self._lost(ToolError("PROTOCOL_MISMATCH", f"设备数据结构不合法：{type(exc).__name__}"), transport)
            except Exception as exc:
                await self._lost(ToolError("INTERNAL_ERROR", f"采集处理异常，已停止设备通信：{type(exc).__name__}"), transport)
            finally:
                await asyncio.sleep(0.04 if self.connected else 0.2)

    def snapshot(self) -> dict:
        """AI:返回公共状态，不暴露令牌或控制秘密。@return 状态快照，未采集值不会补零。"""
        now, wall = time.monotonic(), time.time()
        clients = [{k: v for k, v in session.items() if k != "deadline"} | {"active": session["deadline"] > now}
                   for session in self.sessions.values()]
        owner = self.sessions.get(self.owner)
        latest = {}
        for channel, item in self.latest.items():
            age = max(0, (wall - item["received_at"]) * 1000)
            if "t_us" in item and self.last_state_at:
                age = max(age, self.device_state.get("uptime_ms", 0) + (now - self.last_state_at) * 1000 - item["t_us"] / 1000)
            latest[channel] = {**item, "age_ms": round(age), "stale": not self.connected or age > 3000}
        return {"version": __version__, "instance_id": self.instance_id, "test_mode": self.test_mode, "stopping": self.stopping or self.closing,
                "connected": self.connected, "connection": self.connection, "device": self.info,
                "device_state": self.device_state, "device_state_stale": not self.connected or now - self.last_state_at > 3000 / 1000,
                "control": {"owner": {k: v for k, v in owner.items() if k != "deadline"} if owner else None,
                            "owner_active": bool(owner and owner["deadline"] > now), "revision": self.control_revision, "device_claimed": self.device_claimed},
                "clients": clients, "latest": latest, "last_error": self.last_error, "firmware_update": dict(self.firmware.status),
                "recording": self.recorder.status(), "jobs": self.jobs.recent(30), "last_data_at": self.last_data_at}

    def data(self, token: str, kind: str, after: int, limit: int):
        """AI:读取共享历史。@param token 会话；kind 数据类型；after 游标；limit 条数。@return 带后台身份的记录。"""
        self.session(token)
        if kind not in self.histories:
            raise ToolError("INVALID_PARAMS", "未知数据类型")
        return {**self.histories[kind].read(after, limit), "instance_id": self.instance_id}

    async def recording_start(self, token: str):
        """AI:由当前操作者明确开始记录。@param token 会话。@return 状态。"""
        async with self.operation_lock:
            self.require_owner(token)
            if not self.connected:
                raise ToolError("NOT_CONNECTED", "先连接工具再开始记录")
            calibration = await self._rpc("calibration.get")
            return await self.recorder.start({"device": self.info, "connection": self.connection, "calibration": calibration, "runtime_version": __version__, "test_mode": self.test_mode})

    async def recording_stop(self, token: str, *, takeover=False, expected_revision=None):
        """AI:明确停止本机记录，不取得硬件写权。@param token 会话；takeover 是否明确结束无人记录；expected_revision 观测后台版本。@return 最终状态。"""
        async with self.operation_lock:
            self.session(token)
            if self.owner != token:
                owner = self.sessions.get(self.owner)
                if not takeover or expected_revision != self.control_revision or (owner and owner["deadline"] > time.monotonic()) or self.active_jobs:
                    raise ToolError("NOT_OWNER", "由当前操作者停止记录；原操作者离线后可核对状态并明确结束无人记录")
                self._event("orphan_recording_stop", "客户端明确停止无人持有的本机记录，未接管硬件操作权", actor=self.sessions[token]["name"])
            return await self.recorder.stop()

    async def prepare_shutdown(self, token: str):
        """AI:检查全局退出条件并释放本后台写权。@param token 明确发起退出的客户端。@return 退出确认，不改变输出。"""
        async with self.operation_lock:
            self.session(token)
            self.check_firmware_idle()
            if self.active_jobs or self.recorder.state in ("recording", "stopping"):
                raise ToolError("BUSY", "先等待动作结束并明确停止记录，再退出后台")
            if any(key != token and session["deadline"] > time.monotonic() for key, session in self.sessions.items()):
                raise ToolError("CLIENTS_ACTIVE", "还有其他客户端在使用后台，请先让它们退出会话")
            # AI:等待设备释放期间就关闭客户端准入；失败只恢复入口，不停止采集任务。
            self.closing = True
            try:
                if self.connected and self.device_claimed:
                    await self._rpc("control.release", mutation=True)
                    self.device_claimed = False
            except BaseException:
                self.closing = False
                raise
            self.stopping = True
            self.owner = None
            self.control_revision += 1
            self._event("shutdown", "用户明确请求退出后台，输出保持")
            return {"shutdown_requested": True, "outputs_changed": False}

    async def close(self):
        """AI:结束后台等待，保留未知结果，不向硬件发送复位或关闭输出。@return 无。"""
        if self.firmware.task:
            if self.firmware.status["phase"] not in ("installing", "reconnecting"):
                self.firmware.task.cancel()
            await asyncio.gather(self.firmware.task, return_exceptions=True)
        self.stopping = True
        if self.worker:
            self.worker.cancel()
            with suppress(asyncio.CancelledError):
                await self.worker
        tasks = list(self.job_tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if self.transport:
            await self.transport.close()
        if self.device_lock:
            self.device_lock.close()
        await self.recorder.stop()
        self.jobs.close()
