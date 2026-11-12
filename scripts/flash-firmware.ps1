param(
    [Parameter(Mandatory=$true)][ValidatePattern('^COM[1-9][0-9]*$')][string]$Port,
    [string]$IdfPython = 'C:\Espressif\tools\python\v5.4.4\venv\Scripts\python.exe'
)
# AI:用户明确运行本脚本才会下载；不自动选择串口，不自动擦除NVS。
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
$buildRoot = Join-Path $projectRoot 'firmware/build'
foreach ($name in @('ai_mcutool.bin','bootloader/bootloader.bin','partition_table/partition-table.bin','flash_args')) {
    if (-not (Test-Path -LiteralPath (Join-Path $buildRoot $name))) { throw "本次下载产物缺失：$name" }
}
if (-not (Test-Path -LiteralPath $IdfPython)) { throw '指定的ESP-IDF Python不存在' }
$portJson = & $IdfPython -c 'import json,sys; from serial.tools import list_ports; p=next((p for p in list_ports.comports() if p.device.upper()==sys.argv[1].upper()),None); print(json.dumps(None if p is None else {"port":p.device,"vid":p.vid,"pid":p.pid,"serial":p.serial_number}))' $Port
if ($LASTEXITCODE -ne 0) { throw 'USB身份枚举失败，未开始下载' }
$selectedPort = $portJson | ConvertFrom-Json
if ($null -eq $selectedPort -or $selectedPort.vid -ne 12346) { throw '该端口未识别为乐鑫原生USB，未开始下载；请确认工具板和下载模式' }
Write-Host "向明确选择的 $Port 下载ESP32-S3工具固件。请确认USB供电时未同时连接DC。"
Push-Location $buildRoot
try {
    & $IdfPython -m esptool --chip esp32s3 --port $Port --baud 460800 --before default_reset --after hard_reset write_flash '@flash_args'
    if ($LASTEXITCODE -ne 0) { throw '下载或写后校验失败，请保留错误并检查实际设备状态' }
} finally { Pop-Location }
