"""AI:显式指定打包程序后验证，无开发Python/Node路径也能启动和提供MCP。"""
import asyncio
import json
import os
from pathlib import Path
import socket
import subprocess
import time
import pytest
from fastmcp import Client

pytestmark = pytest.mark.skipif(not os.environ.get('MCUTOOL_TEST_SERVICE'), reason='需要显式指定已打包运行程序')


def test_frozen_runtime_and_mcp_share_one_process_without_development_path(tmp_path):
    """AI:验证安装版独立运行、MCP复用和卸载占用保护。@param tmp_path 隔离目录。@return 无。"""
    executable = Path(os.environ['MCUTOOL_TEST_SERVICE']).resolve()
    data = tmp_path/'中文记录目录'
    with socket.socket() as listener:
        listener.bind(('127.0.0.1',0)); port=listener.getsockname()[1]
    env = dict(os.environ)
    env['PATH'] = str(Path(os.environ['SystemRoot'])/'System32')+';'+os.environ['SystemRoot']
    env.pop('PYTHONPATH',None); env.pop('PYTHONHOME',None)
    env['PYTHONUTF8'] = '0'
    args = ['--data-dir',str(data),'--port',str(port),'--no-browser']

    def call(*arguments):
        """AI:运行明确的冻结程序。@param arguments 命令参数。@return 完整进程结果，不输出私有配置。"""
        return subprocess.run([str(executable),*arguments],cwd=tmp_path,env=env,capture_output=True,encoding='utf-8',timeout=50)

    try:
        started = call('start',*args)
        assert started.returncode == 0, started.stderr
        identity = json.loads(started.stdout)['instance_id']
        repeated = call('start',*args)
        assert repeated.returncode == 0, repeated.stderr
        assert json.loads(repeated.stdout)['instance_id'] == identity
        assert call('can-uninstall').returncode != 0

        async def mcp():
            """AI:用真实stdio验证冻结MCP与同一后台。@return 无。"""
            async with Client({'mcpServers':{'mcutool':{'command':str(executable),'args':['mcp','--data-dir',str(data)],'env':env}}}) as client:
                ping = (await client.call_tool('ping',{})).data
                state = (await client.call_tool('connect',{'client_name':'冻结MCP验证'})).data
                try:
                    assert ping['version']=='0.5.3' and {'run_charge_cycle','cancel_charge_cycle','action_status'} <= set(ping['tools'])
                    assert state['instance_id']==identity and not state['connected']
                finally:
                    # AI:即使断言失败也明确分离本测试会话，避免阻塞测试后台退出。
                    assert (await client.call_tool('detach',{})).data['detached']
        asyncio.run(mcp())
    finally:
        result = call('stop','--data-dir',str(data))
        assert result.returncode == 0, result.stderr
    deadline = time.monotonic()+10
    while time.monotonic()<deadline:
        if call('can-uninstall').returncode==0: break
        time.sleep(.1)
    else: pytest.fail('冻结运行程序未退出')
