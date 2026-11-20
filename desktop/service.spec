# -*- mode: python ; coding: utf-8 -*-
"""AI:将后台、MCP、Python运行库与已构建网页打成同一目录。"""
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

project = Path(SPECPATH).parent
hidden = collect_submodules('uvicorn') + collect_submodules('fastmcp') + collect_submodules('mcp') + collect_submodules('burner_redis')
metadata = copy_metadata('fastmcp', recursive=True) + copy_metadata('ai-mcutool')
resources = collect_data_files('docket') + collect_data_files('fastmcp') + collect_data_files('mcp') + collect_data_files('burner_redis')
analysis = Analysis([str(project / 'desktop/service_entry.py')], pathex=[str(project / 'host')],
                    binaries=[], datas=[(str(project / 'web/dist'), 'web/dist'),
                                        (str(project / 'host/mcutool/firmware-signing.pub'), 'mcutool'),
                                        *collect_data_files('esptool'), *metadata, *resources],
                    hiddenimports=hidden, hookspath=[], hooksconfig={}, runtime_hooks=[],
                    excludes=['pytest', 'IPython', 'notebook'], noarchive=False, optimize=0)
python_archive = PYZ(analysis.pure)
program = EXE(python_archive, analysis.scripts, [], exclude_binaries=True,
              name='MCUTOOL-service', debug=False, bootloader_ignore_signals=False,
              strip=False, upx=False, console=True, disable_windowed_traceback=False)
bundle = COLLECT(program, analysis.binaries, analysis.datas, strip=False, upx=False, name='MCUTOOL-service')
