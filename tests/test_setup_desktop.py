"""AI:验证Windows安装入口的离线完整性与真实MCP探测，不修改全局AI配置或硬件。"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import pytest

ROOT = Path(__file__).resolve().parents[1]
VERSION = json.loads((ROOT/'integrations/desktop-release.json').read_text(encoding='utf-8'))['version']
pytestmark = pytest.mark.skipif(os.name != 'nt', reason='Windows PowerShell安装入口')


def fixture(tmp_path):
    """AI:在独立目录提供不会执行的下载样本。@param tmp_path 测试根目录。@return 脚本与包目录。"""
    (tmp_path/'scripts').mkdir()
    (tmp_path/'integrations').mkdir()
    script=tmp_path/'scripts/setup-desktop.ps1'
    shutil.copyfile(ROOT/'scripts/setup-desktop.ps1',script)
    release=json.loads((ROOT/'integrations/desktop-release.json').read_text(encoding='utf-8'))
    package=tmp_path/'download'
    package.mkdir()
    body=b'TEST ONLY: this is never executed'
    (package/release['installer']).write_bytes(body)
    release['sha256']=hashlib.sha256(body).hexdigest()
    (package/(release['installer']+'.sha256')).write_text(release['sha256']+'  '+release['installer']+'\n',encoding='utf-8')
    (tmp_path/'integrations/desktop-release.json').write_text(json.dumps(release),encoding='utf-8')
    return script,package,release


def run(script,*arguments):
    """AI:通过Windows自带5.1执行，不依赖额外PowerShell安装。@param script 正式脚本副本。@param arguments 明确参数。@return 进程结果。"""
    return subprocess.run(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(script),*map(str,arguments)],capture_output=True,timeout=60)


def test_offline_download_requires_both_repository_and_file_integrity(tmp_path):
    """AI:下载校验成功时不执行安装器或创建AI配置。@param tmp_path 隔离目录。@return 无。"""
    script,package,release=fixture(tmp_path)
    output=tmp_path/'output'
    result=run(script,'-PackageDirectory',package,'-IntegrationDirectory',output,'-DownloadOnly')
    assert result.returncode==0,result.stderr
    assert not (output/'mcp-config.json').exists()
    (package/release['installer']).write_bytes(b'corrupted')
    result=run(script,'-PackageDirectory',package,'-IntegrationDirectory',output,'-DownloadOnly')
    assert result.returncode!=0
    assert b'SHA256 mismatch' in result.stderr


def test_replaced_checksum_cannot_override_repository_digest(tmp_path):
    """AI:安装器和伴随摘要同时被替换也无法通过仓库固定摘要。@param tmp_path 隔离目录。@return 无。"""
    script,package,release=fixture(tmp_path)
    body=b'replaced'
    (package/release['installer']).write_bytes(body)
    (package/(release['installer']+'.sha256')).write_text(hashlib.sha256(body).hexdigest()+'  '+release['installer'],encoding='utf-8')
    result=run(script,'-PackageDirectory',package,'-IntegrationDirectory',tmp_path/'output','-DownloadOnly')
    assert result.returncode!=0
    assert b'differs from the repository descriptor' in result.stderr


@pytest.mark.skipif(not os.environ.get('MCUTOOL_SETUP_INSTALLED'),reason='需显式指定本次已安装目录')
def test_existing_runtime_probe_and_skill_install_are_isolated(tmp_path):
    """AI:复用已安装版本并只调用ping，配置输出与Skill均限制在测试目录。@param tmp_path 隔离目录。@return 无。"""
    output=tmp_path/'output'
    skill=tmp_path/'skill'
    # AI:显式覆盖 Windows PowerShell 5.1 在 UTF-8 控制台中创建带 BOM 管道的情况。
    wrapper = tmp_path / 'utf8-console.ps1'
    wrapper.write_text(
        'param($ScriptPath,$Install,$Integration,$Skill)\n'
        "$ErrorActionPreference = 'Stop'\n"
        '$previous = [Console]::InputEncoding\n'
        'try {\n'
        '    [Console]::InputEncoding = [Text.UTF8Encoding]::new($true)\n'
        '    & $ScriptPath -InstallDirectory $Install -IntegrationDirectory $Integration -SkillDirectory $Skill\n'
        '} finally { [Console]::InputEncoding = $previous }\n', encoding='utf-8')
    result=run(wrapper,ROOT/'scripts/setup-desktop.ps1',os.environ['MCUTOOL_SETUP_INSTALLED'],output,skill)
    assert result.returncode==0,result.stderr
    assert f'MCP ready: version {VERSION}, 32 tools'.encode() in result.stdout
    config=json.loads((output/'mcp-config.json').read_text(encoding='utf-8'))
    service=config['mcpServers']['mcutool']
    assert Path(service['command']).is_file()
    assert service['args'][0:2]==['mcp','--data-dir']
    assert Path(service['args'][2]).is_absolute()
    for source in (ROOT/'integrations/skill/xhh-mcu-tool').rglob('*'):
        if source.is_file():
            assert (skill/source.relative_to(ROOT/'integrations/skill/xhh-mcu-tool')).read_bytes()==source.read_bytes()
