# AI:只打包本次已构建的软件，始终创建新目录，不覆盖旧交付。
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
$version = '0.1.2'
$name = 'MCUTOOL-' + $version + '-' + (Get-Date -Format 'yyyyMMdd-HHmmss')
$releaseRoot = Join-Path $projectRoot 'release'
$destination = Join-Path $releaseRoot $name
if (Test-Path -LiteralPath $destination) { throw '交付目录已存在，停止以避免覆盖' }
New-Item -ItemType Directory -Path $destination -Force | Out-Null
$files = @()
foreach ($directory in @('firmware/main','host/mcutool','web/src','web/tests','web/dist','protocol','integrations','scripts','tests','docs/软件验证证据','docs/软件界面')) {
    $files += Get-ChildItem -LiteralPath (Join-Path $projectRoot $directory) -Recurse -File | Where-Object { $_.FullName -notmatch '[\\/]__pycache__[\\/]' -and $_.Extension -ne '.pyc' }
}
$singleFiles = @('GLOSSARY.md','pyproject.toml','requirements.lock.txt','启动工具.cmd',
    'firmware/CMakeLists.txt','firmware/sdkconfig.defaults','firmware/sdkconfig','firmware/partitions.csv',
    'web/package.json','web/package-lock.json','web/tsconfig.json','web/vite.config.ts','web/index.html','web/playwright.config.ts',
    'docs/软件使用说明.md','docs/软件验证报告.md','docs/INA226实板启动与测量限制.md','docs/Wi-Fi连接修复记录.md',
    'firmware/build/ai_mcutool.bin','firmware/build/ai_mcutool.elf','firmware/build/ai_mcutool.map',
    'firmware/build/bootloader/bootloader.bin','firmware/build/partition_table/partition-table.bin',
    'firmware/build/flash_args','firmware/build/flasher_args.json','firmware/build/project_description.json')
foreach ($relative in $singleFiles) {
    $source = Join-Path $projectRoot $relative
    if (-not (Test-Path -LiteralPath $source -PathType Leaf)) { throw "交付文件缺失：$relative" }
    $files += Get-Item -LiteralPath $source
}
$manifest = @()
foreach ($file in ($files | Sort-Object FullName -Unique)) {
    $relative = $file.FullName.Substring($projectRoot.Length + 1)
    $target = Join-Path $destination $relative
    New-Item -ItemType Directory -Path (Split-Path $target -Parent) -Force | Out-Null
    Copy-Item -LiteralPath $file.FullName -Destination $target
    $manifest += @{path=$relative.Replace([char]92,[char]47); bytes=$file.Length; sha256=(Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToLowerInvariant()}
}
$utf8 = [System.Text.UTF8Encoding]::new($false)
$packageReadme = @'
# MCU TOOL 0.1.2 软件交付

这是电脑端及网页0.1.2软件包，修复Wi-Fi地址首尾空白导致连接失败的问题。工具固件保持0.1.1，包含共享后台、已构建网页、MCP、使用Skill、源码和验证资料。

新目录首次使用：准备Python 3.11、Node.js 22和PowerShell 7，运行 `scripts/install.ps1`，然后双击 `启动工具.cmd`。软件包没有附带独立运行时或桌面安装器。

- [使用说明](docs/软件使用说明.md)
- [验证报告](docs/软件验证报告.md)
- [Wi-Fi连接修复记录](docs/Wi-Fi连接修复记录.md)
- [INA226实板检查与测量限制](docs/INA226实板启动与测量限制.md)
- [AI使用Skill](integrations/skill/mcu-assistant-tool/SKILL.md)
- [MCP配置示例](integrations/mcp.example.json)：移动后需调整两个绝对路径。

本次固件位于 `firmware/build/`。`manifest.json` 包含每个交付文件的SHA256。启动不会自动连接硬件或开启输出；已完成首板USB启动、真实Wi-Fi连接及只读采集检查，量化电气与精度验收尚未完成。
'@
$readmePath = Join-Path $destination 'README.md'
[System.IO.File]::WriteAllText($readmePath, $packageReadme, $utf8)
$manifest += @{path='README.md'; bytes=(Get-Item -LiteralPath $readmePath).Length; sha256=(Get-FileHash -LiteralPath $readmePath -Algorithm SHA256).Hash.ToLowerInvariant()}
$metadata = @{version=$version; firmware_version='0.1.1'; created_at=(Get-Date).ToString('o'); source_state='uncommitted-working-tree'; hardware_tested=$true; hardware_acceptance_complete=$false; hardware_checks='usb-startup-wifi-and-readonly-sensors'; files=$manifest} | ConvertTo-Json -Depth 6
[System.IO.File]::WriteAllText((Join-Path $destination 'manifest.json'), $metadata, $utf8)
$archive = Join-Path $releaseRoot ($name + '.zip')
Compress-Archive -LiteralPath $destination -DestinationPath $archive -CompressionLevel Optimal
$sha = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant()
[System.IO.File]::WriteAllText(($archive + '.sha256'), ($sha + '  ' + (Split-Path $archive -Leaf) + "`n"), $utf8)
$latest = @{version=$version; directory=$destination; archive=$archive; sha256=$sha; created_at=(Get-Date).ToString('o')} | ConvertTo-Json
[System.IO.File]::WriteAllText((Join-Path $releaseRoot 'latest.json'), $latest, $utf8)
Write-Output $latest
