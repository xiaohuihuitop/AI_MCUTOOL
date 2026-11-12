"""AI:系统级持有锁，文件存在本身不代表资源仍被占用。"""
import os
from pathlib import Path
from .errors import ToolError


class ProcessLock:
    """AI:在Windows通过字节锁隔离后台或设备持有者。"""

    def __init__(self, path: Path):
        """AI:取得独占锁。@param path 持久锁文件，不删除。@return 无，占用时抛错。"""
        if os.name != "nt":
            raise ToolError("PLATFORM_UNSUPPORTED", "首版进程锁仅在Windows完成支持")
        import msvcrt
        path.parent.mkdir(parents=True, exist_ok=True)
        self.file = path.open("a+b")
        if self.file.seek(0, 2) == 0:
            self.file.write(b"0")
            self.file.flush()
        self.file.seek(0)
        try:
            msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            self.file.close()
            raise ToolError("RESOURCE_BUSY", "已有后台持有此资源，请使用原后台或先明确断开") from exc

    def close(self):
        """AI:释放本进程的锁。@return 无，保留锁文件。"""
        if not self.file.closed:
            import msvcrt
            self.file.seek(0)
            msvcrt.locking(self.file.fileno(), msvcrt.LK_UNLCK, 1)
            self.file.close()
