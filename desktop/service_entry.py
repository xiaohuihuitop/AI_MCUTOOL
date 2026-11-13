"""AI:安装版共用后台与MCP的单一可执行入口。"""
import multiprocessing
import sys


if __name__ == '__main__':
    multiprocessing.freeze_support()
    # AI:与原生启动器和MCP统一使用UTF-8管道，避免Windows中文代码页破坏JSON。
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if stream is not None:
            stream.reconfigure(encoding='utf-8')
    if len(sys.argv) > 1 and sys.argv[1] == 'mcp':
        sys.argv.pop(1)
        from mcutool.mcp import main
    else:
        from mcutool.cli import main
    main()
