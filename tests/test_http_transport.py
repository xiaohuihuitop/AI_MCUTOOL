"""AI:使用真实本地HTTP服务验证设备地址和实际请求路径。"""
import asyncio
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from threading import Thread
import pytest

from mcutool.transports import HttpTransport
from mcutool.errors import ToolError


@pytest.fixture
def device_http():
    """AI:提供仅监听回环的设备协议服务。@return 服务地址与实际收到的请求，不操作实物。"""
    received = []

    class Handler(BaseHTTPRequestHandler):
        """AI:记录真实网络请求，并返回同一请求编号。"""

        def do_POST(self):
            """AI:响应设备信息查询。@return 无，JSON写入HTTP响应。"""
            message = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            received.append((self.path, self.headers.get('Authorization'), message))
            body = json.dumps({'v': 1, 'id': message['id'], 'boot_id': 'test', 'ok': True,
                               'result': {'device_id': 'HTTP-TEST'}}).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):
            """AI:测试服务不输出访问日志。@param format 日志模板；args 参数。@return 无。"""

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = Thread(target=server.serve_forever, kwargs={'poll_interval': .01}, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}', received
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.mark.parametrize('prefix,suffix', [('', ''), (' ', ''), ('\t ', ' \r\n'), (' ', '/ ')])
def test_pasted_device_address_reaches_same_http_endpoint(device_http, prefix, suffix):
    """AI:复制地址产生的首尾空白不能使HTTP地址失去协议。@param device_http 服务；prefix/suffix 输入两端字符。@return 无。"""
    address, received = device_http
    message = {'v': 1, 'id': 'address-check', 'method': 'device.info', 'params': {}}

    async def exchange():
        """AI:通过生产传输对象执行一次只读请求。@return 实际HTTP响应。"""
        transport = HttpTransport(prefix + address + suffix, 'test-device-token')
        try:
            return await transport.request(message)
        finally:
            await transport.close()

    result = asyncio.run(exchange())
    assert result['result']['device_id'] == 'HTTP-TEST'
    assert received == [('/rpc', 'Bearer test-device-token', message)]


@pytest.mark.parametrize('address', ['192.168.1.62', 'https://192.168.1.62', 'http://127.0.0.\t1'])
def test_invalid_address_is_rejected_without_guessing_protocol(address):
    """AI:只清理两端空白，其他无效输入不能触发协议替换或内部字符修补。@param address 无效输入。@return 无。"""
    with pytest.raises(ToolError) as failure:
        HttpTransport(address, 'test-device-token')
    assert failure.value.code == 'INVALID_ADDRESS'


def test_shared_runtime_stores_the_canonical_http_address(tmp_path):
    """AI:共享状态保留实际请求地址，供网页与MCP比较同一目标。@param tmp_path 隔离数据目录。@return 无。"""
    from fastapi.testclient import TestClient
    from mcutool.app import create_app
    from tests.support.device import TestDevice
    device = TestDevice()
    app = create_app(tmp_path, token='test-runtime-token', transport_factory=lambda _: device, test_mode=True)
    with TestClient(app) as client:
        headers = {'Authorization': 'Bearer test-runtime-token'}
        session = client.post('/api/sessions', headers=headers, json={'name': '地址检查', 'kind': 'web'}).json()
        headers['X-Session-ID'] = session['session_id']
        result = client.post('/api/connect', headers=headers, json={'kind': 'http', 'address': ' http://test/ ', 'token': 'fixture'})
        assert result.status_code == 200
        assert result.json()['connection']['address'] == 'http://test'
