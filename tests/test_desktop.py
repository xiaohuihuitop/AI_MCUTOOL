"""AI:验证桌面共享会话、冻结程序引导以及诊断信息边界。"""
import asyncio
import io
import json
from pathlib import Path
import socket
import subprocess
import sys
import zipfile
import pytest
from fastapi.testclient import TestClient
from mcutool import __version__
from mcutool.app import create_app
from mcutool.desktop import desktop_start
from mcutool.client import RuntimeClient
from tests.support.device import TestDevice


def test_desktop_session_does_not_stop_shared_recording_when_detached(tmp_path):
    """AI:桌面退出应只分离自身，观察者和记录继续。@param tmp_path 隔离目录。@return 无。"""
    device = TestDevice()
    app = create_app(tmp_path, token='test-runtime-token', test_mode=True, transport_factory=lambda _: device)
    with TestClient(app) as http:
        headers = {'Authorization': 'Bearer test-runtime-token'}
        session = http.post('/api/sessions', headers=headers, json={'name':'桌面','kind':'desktop'}).json()
        desktop = {**headers, 'X-Session-ID':session['session_id']}
        assert http.post('/api/connect', headers=desktop, json={'kind':'http','address':'http://test','token':'fixture'}).status_code == 200
        assert http.post('/api/control/claim', headers=desktop, json={}).status_code == 200
        assert http.post('/api/recording/start', headers=desktop).status_code == 200
        assert http.post('/api/sessions/heartbeat', headers=desktop).status_code == 200
        assert http.delete('/api/sessions/current', headers=desktop).status_code == 200
        state = http.get('/api/runtime/status', headers=headers).json()
        assert state['recording']['state'] == 'recording' and state['connected']
        assert not state['control']['owner_active']


def test_diagnostics_omit_credentials_and_raw_recordings(tmp_path):
    """AI:导出有效JSON和脱敏日志，不能复制授权或原始数据。@param tmp_path 隔离目录。@return 无。"""
    app = create_app(tmp_path, token='private-runtime-secret', test_mode=True)
    with TestClient(app) as http:
        headers = {'Authorization':'Bearer private-runtime-secret'}
        session = http.post('/api/sessions', headers=headers, json={'name':'桌面','kind':'desktop'}).json()
        headers['X-Session-ID'] = session['session_id']
        runtime = app.state.runtime
        runtime.last_error = {'code':'TEST','message':'Bearer private-runtime-secret','details':{'password':'wifi-secret','token':'device-secret'}}
        (tmp_path/'runtime.log').write_text('Authorization: Bearer private-runtime-secret\npassword="wifi-secret"\n'+session['session_id'],encoding='utf-8')
        (tmp_path/'runtime.json').write_text('must-not-export-runtime-file',encoding='utf-8')
        record = tmp_path/'recordings'/'private'; record.mkdir(parents=True)
        (record/'串口.bin').write_bytes(b'must-not-export-raw-uart')
        result = http.get('/api/diagnostics', headers=headers)
        assert result.status_code == 200
        with zipfile.ZipFile(io.BytesIO(result.content)) as archive:
            assert set(archive.namelist()) == {'诊断信息.json','runtime.log'}
            summary = json.loads(archive.read('诊断信息.json'))
            assert summary['last_error']['details']['password'] == '<REDACTED>'
            assert summary['last_error']['details']['token'] == '<REDACTED>'
            combined = b'\n'.join(archive.read(name) for name in archive.namelist())
            for secret in ('private-runtime-secret','wifi-secret','device-secret',session['session_id'],'must-not-export-raw-uart','must-not-export-runtime-file'):
                assert secret.encode() not in combined


def test_desktop_bootstrap_starts_one_runtime_and_reports_desktop_session(tmp_path):
    """AI:真实进程引导返回桌面会话，同目录再次启动复用后台。@param tmp_path 隔离数据目录。@return 无。"""
    with socket.socket() as listener:
        listener.bind(('127.0.0.1',0)); port=listener.getsockname()[1]
    base = [sys.executable,'-m','mcutool.cli']
    sessions = []
    try:
        first = desktop_start(tmp_path, port)
        sessions.append(first)
        second = desktop_start(tmp_path, port)
        sessions.append(second)
        assert first['instance_id'] == second['instance_id'] and first['version'] == __version__
        assert first['session_id'] != second['session_id']
        async def finish():
            """AI:通过原协议退出测试会话。@return 无。"""
            import httpx
            async with httpx.AsyncClient(base_url=first['url'],headers={'Authorization':'Bearer '+first['token']},trust_env=False) as http:
                state = (await http.get('/api/runtime/status')).json()
                assert all(s['kind']=='desktop' for s in state['clients'])
                for session in sessions:
                    await http.delete('/api/sessions/current',headers={'X-Session-ID':session['session_id']})
        asyncio.run(finish())
    finally:
        result = subprocess.run(base+['stop','--data-dir',str(tmp_path)],capture_output=True,timeout=15)
        assert result.returncode == 0
