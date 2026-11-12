# AI:安装依赖仅使用项目目录，不升级系统Python或其他工具。
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
Push-Location $projectRoot
try {
    if (-not (Test-Path '.venv/Scripts/python.exe')) {
        python -m venv .venv
        if ($LASTEXITCODE -ne 0) { throw '创建Python项目环境失败' }
    }
    & .venv/Scripts/python.exe -m pip install -r requirements.lock.txt
    if ($LASTEXITCODE -ne 0) { throw 'Python依赖安装失败' }
    & .venv/Scripts/python.exe -m pip install --no-deps -e .
    if ($LASTEXITCODE -ne 0) { throw '共享后台安装失败' }
    Push-Location web
    try {
        npm ci
        if ($LASTEXITCODE -ne 0) { throw '网页依赖安装失败' }
        npm run build
        if ($LASTEXITCODE -ne 0) { throw '网页构建失败' }
    } finally { Pop-Location }
    Write-Host '安装完成，运行项目根目录的 启动工具.cmd。'
} finally { Pop-Location }
