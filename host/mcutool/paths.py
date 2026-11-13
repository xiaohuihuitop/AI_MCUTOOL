"""AI:集中定义源码运行与Windows打包运行的资源位置和启动命令。"""
import os
from pathlib import Path
import sys


def web_dist() -> Path:
    """AI:定位当前运行形态随附的网页。@return 必须实际存在的网页目录，不寻找其他版本资源。"""
    if getattr(sys, 'frozen', False):
        return Path(sys._MEIPASS) / 'web' / 'dist'
    return Path(__file__).resolve().parents[2] / 'web' / 'dist'


def runtime_command() -> list[str]:
    """AI:返回启动同一版本后台的命令前缀。@return 冻结程序自身或当前Python模块入口。"""
    if getattr(sys, 'frozen', False):
        return [sys.executable]
    return [sys.executable, '-m', 'mcutool.cli']


def default_data_dir() -> Path:
    """AI:选择当前运行形态约定的数据目录。@return 安装版每用户目录，源码版当前项目目录；显式参数优先。"""
    if getattr(sys, 'frozen', False):
        return Path(os.environ['LOCALAPPDATA']) / 'MCU_TOOL' / 'data'
    return Path.cwd() / '.mcutool'
