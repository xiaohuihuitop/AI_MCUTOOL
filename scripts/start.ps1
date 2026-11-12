param([int]$Port = 8766, [switch]$NoBrowser)
# AI:明确启动本项目共享后台，启动器不连接设备。
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
if (-not (Test-Path (Join-Path $projectRoot '.venv/Scripts/python.exe')) -or -not (Test-Path (Join-Path $projectRoot 'web/dist/index.html'))) {
    throw '运行环境或网页产物缺失，请先运行 scripts/install.ps1。'
}
$launchArgs = @('-m','mcutool.cli','start','--data-dir',(Join-Path $projectRoot '.mcutool'),'--port',"$Port")
if ($NoBrowser) { $launchArgs += '--no-browser' }
& (Join-Path $projectRoot '.venv/Scripts/python.exe') @launchArgs
if ($LASTEXITCODE -ne 0) { throw '启动未完成，请查看上面的错误说明。' }
