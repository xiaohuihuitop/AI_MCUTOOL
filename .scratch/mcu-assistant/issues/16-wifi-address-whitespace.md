# 修复Wi-Fi地址首部空格导致连接失败

Status: ready-for-human
Progress: completed

用户于2026-11-12报告Wi-Fi页面显示`设备 HTTP 通信失败：UnsupportedProtocol`。工具板已取得192.168.1.62地址，页面实际输入以一个空格开头。诊断资料不记录设备访问令牌。

## 根因与复现

Python的`urlsplit`解析时忽略前导空格，旧地址校验因此通过；HTTPX收到未规范化的原始地址后把它作为缺少协议的相对地址。真实本地HTTP服务测试中，普通地址通过、仅加一个前导空格失败，准确复现用户错误。

复现命令：`.venv/Scripts/python.exe -m pytest tests/test_http_transport.py -q`。修复前结果为1 passed、1 failed，失败原因为UnsupportedProtocol。

## 修复范围

- 地址在校验、HTTP请求、共享连接状态及MCP复用比较中采用同一规范化规则。
- 只去除首尾空白与可选根斜杠，网页同步显示去空白后的值；不补协议，不改通信通道，不重放操作。
- 新增真实HTTP请求回归、无效协议/内部空白拒绝、共享地址状态检查；浏览器和MCP联合用例覆盖带空格地址。
- 电脑端和网页版本0.1.2；设备固件保持0.1.1，本轮不修改或烧录固件。

## 验证

- [x] 修复前稳定复现
- [x] Python回归34项通过
- [x] 网页构建与浏览器/MCP回归
- [x] 真实Wi-Fi连接、设备身份和采样检查
- [x] 更新运行实例与说明

## 结果

电脑端0.1.2已运行，真实工具板通过HTTP连接到192.168.1.62，六路采样有效。MCP使用带空白地址成功复用同一连接，退出后连接保持。未请求硬件写权或控制输出。详情及证据见[Wi-Fi连接修复记录](../../../docs/Wi-Fi连接修复记录.md)。`ready-for-human`表示修复已交付供用户继续使用确认，无待实施的软件步骤。

交付包：`release/MCUTOOL-0.1.2-20261112-175334.zip`，SHA256为`58db43fd8da8a6dfc44a37d3f5acaefb459bbb477402b9796e1d0d85fdcf5a15`。119个文件的哈希、40个本地资料链接、ZIP CRC与UTF-8无BOM检查通过；详细核验保存在同名`.zip.verification.json`。
