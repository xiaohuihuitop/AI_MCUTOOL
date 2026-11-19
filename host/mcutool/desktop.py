"""AI:桌面进程使用的小型引导接口，硬件操作仍通过原共享后台。"""
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import sys
import httpx
from . import __version__
from .cli import ensure_runtime
from .errors import ToolError
from .client import runtime_info


def desktop_start(data_dir: Path, port: int, test_mode: bool = False) -> dict:
    """AI:启动或复用同版本后台并登记桌面会话。@param data_dir 明确目录；port 本机端口；test_mode 仅附着明确启动的测试后台。@return 仅通过私有管道交给桌面进程的凭据和身份。"""
    info = runtime_info(data_dir) if test_mode else ensure_runtime(data_dir, port=port)
    with httpx.Client(base_url=info['url'], headers={'Authorization': 'Bearer ' + info['token']},
                      timeout=5, trust_env=False) as client:
        ping = client.get('/api/ping')
        ping.raise_for_status()
        identity = ping.json()
        if identity.get('version') != __version__ or identity.get('desktop_protocol') != 1 or identity.get('instance_id') != info['instance_id']:
            raise ToolError('RUNTIME_MISMATCH', '现有后台不支持当前桌面版，请先正常退出旧后台')
        if bool(identity.get('test_mode')) != test_mode:
            raise ToolError('TEST_MODE_MISMATCH', '桌面启动方式与后台测试标识不一致，请明确选择同一运行环境')
        response = client.post('/api/sessions', json={'name': '桌面工作台', 'kind': 'desktop'})
        if response.is_error:
            raise ToolError('DESKTOP_ATTACH_FAILED', response.json().get('error', {}).get('message', '桌面会话创建失败'))
        session = response.json()
        return {**info, 'session_id': session['session_id'], 'client_id': session['client_id']}


def check_uninstall(runtime_pid: int | None = None) -> None:
    """AI:检查安装目录的运行程序占用。@param runtime_pid 更新预检时允许的已核验后台，卸载时为空。@return 无，有其他占用则报告进程号。"""
    if os.name != 'nt' or not getattr(sys, 'frozen', False):
        raise ToolError('INVALID_MODE', '卸载检查只用于已安装的Windows运行程序')
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    process_ids = (wintypes.DWORD * 8192)()
    used = wintypes.DWORD()
    psapi = ctypes.WinDLL('psapi', use_last_error=True)
    if not psapi.EnumProcesses(process_ids, ctypes.sizeof(process_ids), ctypes.byref(used)):
        raise ToolError('UNINSTALL_CHECK_FAILED', '无法检查运行程序，请关闭工具后重试')
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    executable = Path(sys.executable).resolve()
    for pid in process_ids[:used.value // ctypes.sizeof(wintypes.DWORD)]:
        if pid in (0, os.getpid(), runtime_pid):
            continue
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            continue
        try:
            name = ctypes.create_unicode_buffer(32768)
            size = wintypes.DWORD(len(name))
            if kernel.QueryFullProcessImageNameW(handle, 0, name, ctypes.byref(size)) and Path(name.value).resolve() == executable:
                raise ToolError('RUNTIME_IN_USE', f'安装目录中的服务进程 PID {pid} 仍在使用。请先从对应 AI 客户端退出 MCP，或正常关闭其他共享后台，再重试。')
        finally:
            kernel.CloseHandle(handle)
