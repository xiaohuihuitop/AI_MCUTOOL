"""AI:浏览器/MCP端到端验证用显式HTTP测试设备，生产入口不启动它。"""
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from tests.support.device import TestDevice

device = TestDevice()
app = FastAPI()


@app.post("/rpc")
async def rpc(request: Request):
    """AI:测试设备协议入口。@param request 测试请求。@return 信封。"""
    if request.headers.get("authorization") != "Bearer fixture":
        return JSONResponse({"error": "invalid test token"}, status_code=401)
    return await device.request(await request.json())
