"""AI:按固定字段导出诊断信息，避免把设备凭据和原始业务数据带入日志包。"""
from datetime import datetime, timezone
import io
import json
import platform
import re
import zipfile


def redact_log(text: str, secrets: list[str]) -> str:
    """AI:清除授权值和常见敏感日志字段。@param text 日志；secrets 本次后台持有的凭据。@return 脱敏文本。"""
    for secret in sorted((s for s in secrets if s), key=len, reverse=True):
        text = text.replace(secret, '<REDACTED>')
    text = re.sub(r'(?i)Bearer\s+[^\s\"\',;}]+', 'Bearer <REDACTED>', text)
    text = re.sub(r'(?i)([\"\']?(?:password|token|session_id|controller)[\"\']?\s*[:=]\s*)([\"\'][^\"\'\r\n]*[\"\']|[^\s,;}]+)', r'\1<REDACTED>', text)
    return re.sub(r'\b[a-fA-F0-9]{64}\b', '<REDACTED>', text)


def diagnostic_archive(runtime, runtime_token: str) -> bytes:
    """AI:生成有界诊断ZIP。@param runtime 共享后台；runtime_token 本机凭据用于脱敏。@return ZIP字节，不含记录文件、任务参数或原始串口。"""
    snapshot = runtime.snapshot()
    device = snapshot['device']
    status = snapshot['device_state']
    summary = {
        'created_at': datetime.now(timezone.utc).isoformat(), 'version': snapshot['version'],
        'platform': platform.platform(), 'instance_id': snapshot['instance_id'],
        'connected': snapshot['connected'], 'connection': snapshot['connection'],
        'test_mode': snapshot['test_mode'],
        'device': {key: device[key] for key in ('device_id', 'boot_id', 'firmware_version', 'hardware_revision', 'protocol_version', 'measurement') if key in device},
        'device_state': {key: status[key] for key in ('uptime_ms', 'power', 'charge', 'keys_mask', 'busy', 'uart', 'measurement', 'nvs_ready') if key in status},
        'recording': {key: snapshot['recording'].get(key) for key in ('state', 'error', 'written_records')},
        'clients': [{'kind': client['kind'], 'active': client['active']} for client in snapshot['clients']],
        'jobs': [{key: job.get(key) for key in ('request_id', 'method', 'state', 'created_at', 'action_id', 'error')} for job in snapshot['jobs']],
        'last_error': snapshot['last_error'],
    }
    secrets = [runtime_token, runtime.controller, *runtime.sessions]
    transport = runtime.transport
    if transport is not None and hasattr(transport, 'client'):
        auth = transport.client.headers.get('Authorization', '')
        if auth.startswith('Bearer '):
            secrets.append(auth[7:])
    def redact_value(value):
        """AI:按结构脱敏以保持JSON合法。@param value 任意诊断字段。@return 不含凭据的同形数据。"""
        if isinstance(value, dict):
            return {key: '<REDACTED>' if key.lower() in ('password', 'token', 'session_id', 'controller', 'authorization') else redact_value(item) for key, item in value.items()}
        if isinstance(value, list):
            return [redact_value(item) for item in value]
        return redact_log(value, secrets) if isinstance(value, str) else value

    content = json.dumps(redact_value(summary), ensure_ascii=False, indent=2)
    # AI:导出字段经过白名单筛选，错误文本仍做脱敏；不复制整个数据目录。
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('诊断信息.json', content)
        for name in ('runtime.log', 'desktop.log'):
            path = runtime.data_dir / name
            if path.is_file():
                with path.open('rb') as stream:
                    stream.seek(max(0, path.stat().st_size - 256 * 1024))
                    log = stream.read(256 * 1024).decode('utf-8', errors='replace')
                archive.writestr(name, redact_log(log, secrets))
    return output.getvalue()
