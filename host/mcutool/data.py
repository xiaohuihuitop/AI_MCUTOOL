"""AI:独立读取缓存、持久任务与后台记录器。"""
import asyncio
from collections import deque
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import time
import uuid
from .errors import ToolError


def json_text(value) -> str:
    """AI:严格编码记录。@param value JSON数据。@return UTF-8可用文本，不允许NaN。"""
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=True)


class History:
    """AI:读取不会消费的有界历史，所有客户端使用独立游标。"""

    def __init__(self, capacity=4000, byte_limit=4 * 1024 * 1024):
        """AI:设置缓存预算。@param capacity 最大条目；byte_limit 估算编码字节。@return 无。"""
        self.capacity, self.byte_limit = capacity, byte_limit
        self.items, self.sizes = deque(), deque()
        self.total_bytes = self.sequence = 0

    def append(self, record: dict) -> dict:
        """AI:写入一条记录并淘汰最旧数据。@param record 原始记录。@return 带公共游标的记录。"""
        self.sequence += 1
        item = {**record, "cursor": self.sequence}
        size = len(json_text(item).encode())
        self.items.append(item)
        self.sizes.append(size)
        self.total_bytes += size
        while len(self.items) > self.capacity or self.total_bytes > self.byte_limit:
            self.items.popleft()
            self.total_bytes -= self.sizes.popleft()
        return item

    def read(self, after=0, limit=200) -> dict:
        """AI:按游标读取且明确覆盖量。@param after 最后游标；limit 最大条数。@return 数据、下一位置、缺失数。"""
        if type(after) is not int or after < 0 or type(limit) is not int or not 1 <= limit <= 500:
            raise ToolError("INVALID_PARAMS", "读取游标或条数不合法")
        if after > self.sequence:
            raise ToolError("CURSOR_RESET", "游标不属于当前后台，请核对后台标识后重新读取")
        oldest = self.items[0]["cursor"] if self.items else self.sequence + 1
        rows = [item for item in self.items if item["cursor"] > after][:limit]
        return {"items": rows, "next": rows[-1]["cursor"] if rows else max(after, oldest - 1),
                "lost": max(0, oldest - after - 1)}


class JobStore:
    """AI:执行前落盘的任务日志，重启不重放未确认操作。"""

    def __init__(self, path: Path):
        """AI:打开本项目任务库。@param path 数据库路径。@return 无。"""
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, body TEXT NOT NULL, created REAL NOT NULL)")
        for row in self.db.execute("SELECT id,body FROM jobs").fetchall():
            body = json.loads(row[1])
            if body["state"] in ("accepted", "running"):
                body.update(state="unknown", error={"code": "BACKEND_RESTARTED", "message": "后台中断，请查询设备动作结果；未重放操作"})
                self.db.execute("UPDATE jobs SET body=? WHERE id=?", (json_text(body), row[0]))
        self.db.commit()

    def get(self, request_id: str) -> dict | None:
        """AI:查询既有请求。@param request_id 编号。@return 任务或空。"""
        row = self.db.execute("SELECT body FROM jobs WHERE id=?", (request_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def fingerprint(self, method: str, params: dict, device_id: str) -> str:
        """AI:绑定请求内容与设备身份。@param method 方法；params 参数；device_id 设备。@return 摘要。"""
        return hashlib.sha256(json_text([method, params, device_id]).encode()).hexdigest()

    def existing(self, request_id: str, fingerprint: str) -> dict | None:
        """AI:拒绝编号复用到不同内容。@param request_id 编号；fingerprint 摘要。@return 已有记录。"""
        row = self.db.execute("SELECT fingerprint,body FROM jobs WHERE id=?", (request_id,)).fetchone()
        if row and row[0] != fingerprint:
            raise ToolError("REQUEST_CONFLICT", "此请求编号已用于不同设备或内容")
        return json.loads(row[1]) if row else None

    def accept(self, request_id: str, fingerprint: str, body: dict) -> dict:
        """AI:先可靠记录接受，调用方之后才能发送硬件命令。@param request_id 编号；fingerprint 摘要；body 任务。@return 记录。"""
        record = {**body, "request_id": request_id, "state": "accepted", "created_at": time.time(), "result": None, "error": None}
        try:
            self.db.execute("INSERT INTO jobs VALUES (?,?,?,?)", (request_id, fingerprint, json_text(record), record["created_at"]))
            self.db.commit()
        except sqlite3.Error as exc:
            self.db.rollback()
            raise ToolError("JOURNAL_ERROR", "任务未成功记录，没有向设备发送操作") from exc
        return record

    def update(self, request_id: str, **changes) -> dict:
        """AI:更新执行证据。@param request_id 编号；changes 修改字段。@return 新记录。"""
        record = self.get(request_id)
        if record is None:
            raise ToolError("NOT_FOUND", "任务记录不存在")
        record.update(changes, updated_at=time.time())
        try:
            self.db.execute("UPDATE jobs SET body=? WHERE id=?", (json_text(record), request_id))
            self.db.commit()
        except sqlite3.Error as exc:
            self.db.rollback()
            raise ToolError("JOURNAL_ERROR", "任务结果写盘失败，执行结果需另行核对") from exc
        return record

    def recent(self, limit=100) -> list[dict]:
        """AI:查询最近任务。@param limit 数量。@return 从新到旧的记录。"""
        return [json.loads(row[0]) for row in self.db.execute("SELECT body FROM jobs ORDER BY created DESC LIMIT ?", (limit,)).fetchall()]

    def close(self):
        """AI:关闭任务库。@return 无。"""
        self.db.close()


class Recorder:
    """AI:网页显示之外的原始数据记录器，队列溢出不报告完整保存。"""

    def __init__(self, root: Path):
        """AI:配置记录根目录。@param root 项目数据目录。@return 无。"""
        self.root = root / "recordings"
        self.state = "idle"
        self.path: Path | None = None
        self.error: str | None = None
        self.queue: asyncio.Queue = asyncio.Queue(maxsize=2048)
        self.worker: asyncio.Task | None = None
        self.files = {}
        self.metadata = {}
        self.written = 0
        self.uart_offset = 0

    async def start(self, metadata: dict):
        """AI:明确开始一次记录。@param metadata 设备与版本信息。@return 状态。"""
        if self.worker and not self.worker.done():
            raise ToolError("RECORDING_ACTIVE", "已有记录正在进行")
        self.error, self.written, self.uart_offset = None, 0, 0
        self.path = None
        self.files = {}
        self.queue = asyncio.Queue(maxsize=2048)
        self.metadata = {**metadata, "started_at": datetime.now(timezone.utc).isoformat(), "state": "recording"}
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            self.path = self.root / (datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:8])
            self.path.mkdir()
            # AI:逐个登记文件句柄，后续创建失败时也能关闭已打开的文件。
            for name, filename in {"measurements": "测量.jsonl", "events": "事件.jsonl", "uart_index": "串口索引.jsonl", "uart": "串口.bin"}.items():
                self.files[name] = (self.path / filename).open("xb")
            (self.path / "会话.json").write_text(json_text(self.metadata), encoding="utf-8")
        except OSError as exc:
            self.state, self.error = "failed", str(exc)
            for stream in self.files.values():
                stream.close()
            raise ToolError("RECORDING_IO", "无法创建记录文件，没有开始记录") from exc
        self.state = "recording"
        self.worker = asyncio.create_task(self._run())
        return self.status()

    def emit(self, kind: str, item: dict):
        """AI:非阻塞提交原始数据。@param kind 类型；item 记录。@return 无。"""
        if self.state != "recording":
            return
        try:
            self.queue.put_nowait((kind, item))
        except asyncio.QueueFull:
            self.state, self.error = "failed", "记录队列已满，记录不完整"

    def _write_batch(self, batch: list):
        """AI:工作线程按原始数据写盘。@param batch 数据批。@return 无。"""
        for kind, item in batch:
            if kind == "uart":
                data = bytes.fromhex(item["data_hex"])
                self.files["uart"].write(data)
                index = {k: v for k, v in item.items() if k != "data_hex"}
                index.update(file_offset=self.uart_offset, length=len(data))
                self.files["uart_index"].write((json_text(index) + "\n").encode())
                self.uart_offset += len(data)
            else:
                self.files[kind].write((json_text(item) + "\n").encode())
            self.written += 1
        for stream in self.files.values():
            stream.flush()

    async def _run(self):
        """AI:持续排空队列并保存终态，写盘错误保留。@return 无。"""
        try:
            while self.state == "recording" or not self.queue.empty():
                batch = []
                try:
                    batch.append(await asyncio.wait_for(self.queue.get(), timeout=0.2))
                except asyncio.TimeoutError:
                    continue
                while not self.queue.empty() and len(batch) < 100:
                    batch.append(self.queue.get_nowait())
                await asyncio.to_thread(self._write_batch, batch)
        except (OSError, ValueError) as exc:
            self.state, self.error = "failed", f"记录写入失败：{exc}"
        finally:
            for stream in self.files.values():
                try:
                    stream.close()
                except OSError as exc:
                    self.state, self.error = "failed", str(exc)
            if self.state != "failed":
                self.state = "completed"
            self.metadata.update(state=self.state, error=self.error, written_records=self.written,
                                 finished_at=datetime.now(timezone.utc).isoformat())
            try:
                if self.path:
                    (self.path / "会话.json").write_text(json_text(self.metadata), encoding="utf-8")
            except OSError as exc:
                self.state, self.error = "failed", f"无法保存记录终态：{exc}"

    async def stop(self):
        """AI:显式停止并等待队列写完。@return 完成或失败状态。"""
        if self.state == "recording":
            self.state = "stopping"
        if self.worker:
            await self.worker
        return self.status()

    def status(self) -> dict:
        """AI:查询当前记录状态。@return 路径、数量及完整性状态。"""
        return {"state": self.state, "path": str(self.path) if self.path else None,
                "error": self.error, "written_records": self.written, "queued": self.queue.qsize()}
