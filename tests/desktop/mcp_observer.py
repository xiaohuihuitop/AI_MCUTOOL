"""AI:保持一个真实冻结MCP观察者，供桌面退出与共享记录测试使用。"""
import asyncio
import json
from pathlib import Path
import sys
from fastmcp import Client


async def main():
    """AI:连接明确的测试后台并等待父测试要求退出。@return 无，不修改工具输出。"""
    service, data = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
    async with Client({'mcpServers':{'mcutool':{'command':str(service),'args':['mcp','--data-dir',str(data)]}}}) as client:
        state = (await client.call_tool('connect',{'client_name':'桌面联合验证MCP'})).data
        assert state['test_mode'] and state['connected']
        print(json.dumps({'ready':True,'instance_id':state['instance_id'],'recording':state['recording']['state']}),flush=True)
        await asyncio.to_thread(sys.stdin.readline)
        await client.call_tool('detach',{})
        state = (await client.call_tool('runtime_status',{})).data
        print(json.dumps({'detached':True,'connected':state['connected']}),flush=True)


if __name__ == '__main__':
    asyncio.run(main())
