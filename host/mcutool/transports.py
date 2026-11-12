"""AI:设备传输只由共享后台持有，不自动重连或重放请求。"""
import asyncio
import time
from typing import Protocol
from urllib.parse import urlsplit
import httpx
import serial
from .errors import ToolError
from .protocol import FrameDecoder, MAX_PAYLOAD, encode_frame


class Transport(Protocol):
    """AI:USB 和 HTTP 的公共通信接口。"""

    async def request(self, message: dict) -> dict:
        """AI:发送一次请求。@param message 信封。@return 对应响应，不自动重发。"""
        ...

    async def close(self) -> None:
        """AI:关闭通信资源。@return 无，不改变板上输出。"""
        ...


class HttpTransport:
    """AI:向明确选定地址发送设备命令。"""

    def __init__(self, address: str, token: str):
        """AI:建立 HTTP 通信。@param address 设备地址；token 设备令牌。@return 无。"""
        parts = urlsplit(address)
        if parts.scheme != "http" or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment or parts.path not in ("", "/"):
            raise ToolError("INVALID_ADDRESS", "填写设备 HTTP 地址，例如 http://192.168.1.80")
        if not token or "\r" in token or "\n" in token:
            raise ToolError("INVALID_TOKEN", "需要有效的设备访问令牌")
        self.client = httpx.AsyncClient(base_url=address.rstrip("/"), timeout=8, trust_env=False,
                                       follow_redirects=False, headers={"Authorization": f"Bearer {token}"})

    async def request(self, message: dict) -> dict:
        """AI:执行单次 HTTP 请求。@param message 信封。@return 设备响应。"""
        try:
            async with self.client.stream("POST", "/rpc", json=message) as response:
                if response.status_code == 401:
                    raise ToolError("DEVICE_AUTH", "设备访问令牌不匹配")
                response.raise_for_status()
                data = bytearray()
                async for chunk in response.aiter_bytes():
                    data.extend(chunk)
                    if len(data) > MAX_PAYLOAD:
                        raise ToolError("FRAME_LIMIT", "设备 HTTP 响应超过协议长度限制")
                import json
                return json.loads(data)
        except (httpx.HTTPError, ValueError) as exc:
            raise ToolError("CONNECTION_ERROR", f"设备 HTTP 通信失败：{type(exc).__name__}") from exc

    async def close(self):
        """AI:释放 HTTP 连接。@return 无。"""
        await self.client.aclose()


class UsbTransport:
    """AI:原生 USB Serial/JTAG 帧通信，单请求串行。"""

    def __init__(self, port: str):
        """AI:打开明确指定端口。@param port 系统串口名。@return 无。"""
        self.decoder = FrameDecoder()
        self.serial = serial.Serial(port=None, baudrate=115200, timeout=0.1, write_timeout=2)
        # AI:打开前取消握手输出，避免打开 ESP USB 口时主动触发复位。
        self.serial.dtr = False
        self.serial.rts = False
        self.serial.port = port
        try:
            self.serial.open()
        except serial.SerialException as exc:
            raise ToolError("PORT_BUSY", f"无法打开串口 {port}，请检查连接和占用") from exc
        self.lock = asyncio.Lock()

    def _exchange(self, message: dict) -> dict:
        """AI:在工作线程收发一帧。@param message 请求。@return 对应响应。"""
        try:
            frame = encode_frame(message)
            if self.serial.write(frame) != len(frame):
                raise ToolError("CONNECTION_ERROR", "USB 请求未完整发送，结果未知")
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline:
                for response in self.decoder.feed(self.serial.read(max(1, min(self.serial.in_waiting, 8192)))):
                    if response.get("id") == message["id"]:
                        return response
            raise ToolError("CONNECTION_ERROR", "USB 响应超时，请查询任务结果，不能重放操作")
        except serial.SerialException as exc:
            raise ToolError("CONNECTION_ERROR", "USB 连接中断，操作结果可能未知") from exc

    async def request(self, message: dict) -> dict:
        """AI:串行发送一次 USB 命令。@param message 信封。@return 对应响应。"""
        async with self.lock:
            work = asyncio.create_task(asyncio.to_thread(self._exchange, message))
            try:
                return await asyncio.shield(work)
            except asyncio.CancelledError:
                # AI:取消等待不会停止串口线程；等待线程收尾后才释放串行锁。
                await work
                raise

    async def close(self):
        """AI:等待在途调用结束后释放端口。@return 无。"""
        async with self.lock:
            await asyncio.to_thread(self.serial.close)
