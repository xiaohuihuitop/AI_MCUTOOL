param(
    [string]$IdfRoot = 'D:\esp\.espressif\v5.4.4\esp-idf',
    [string]$ToolsRoot = 'C:\Espressif\tools'
)
# AI:仅配置当前构建进程，不修改用户全局环境或其他IDE。
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
$env:IDF_PATH = $IdfRoot
$env:IDF_TOOLS_PATH = $ToolsRoot
$env:IDF_PYTHON_ENV_PATH = Join-Path $ToolsRoot 'python\v5.4.4\venv'
$env:IDF_CCACHE_ENABLE = '0'
$env:ESP_ROM_ELF_DIR = Join-Path $ToolsRoot 'esp-rom-elfs\20241011'
$pythonPath = Join-Path $env:IDF_PYTHON_ENV_PATH 'Scripts\python.exe'
$buildPaths = @(
    (Join-Path $ToolsRoot 'cmake\3.30.2\bin'),
    (Join-Path $ToolsRoot 'ninja\1.12.1'),
    (Join-Path $ToolsRoot 'xtensa-esp-elf\esp-14.2.0_20260121\xtensa-esp-elf\bin'),
    (Join-Path $env:IDF_PYTHON_ENV_PATH 'Scripts')
)
foreach ($toolPath in $buildPaths) { if (-not (Test-Path -LiteralPath $toolPath)) { throw "构建工具目录不存在：$toolPath" } }
$env:PATH = ($buildPaths -join ';') + ';' + $env:PATH
Push-Location (Join-Path $projectRoot 'firmware')
try {
    & $pythonPath (Join-Path $IdfRoot 'tools\idf.py') '-DIDF_TARGET=esp32s3' build
    if ($LASTEXITCODE -ne 0) { throw "固件编译失败，退出码 $LASTEXITCODE" }
} finally { Pop-Location }
