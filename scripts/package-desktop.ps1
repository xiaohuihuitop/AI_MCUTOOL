# AI:只复制明确构建的桌面安装器和说明，创建独立交付目录并生成SHA256清单。
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
$version = (Get-Content -Raw -LiteralPath (Join-Path $projectRoot 'desktop/package.json') | ConvertFrom-Json).version
$installerDir = Join-Path $projectRoot 'desktop/src-tauri/target/x86_64-pc-windows-msvc/release/bundle/nsis'
$installers = @(Get-ChildItem -LiteralPath $installerDir -File -Filter "*_${version}_x64-setup.exe")
if ($installers.Count -ne 1) { throw '未找到当前版本的唯一Windows x64安装器，请先完成桌面构建' }
$signaturePath = $installers[0].FullName + '.sig'
if (-not (Test-Path -LiteralPath $signaturePath -PathType Leaf)) { throw '当前安装器缺少更新签名，请使用正式签名配置重新构建' }
$releaseRoot = Join-Path $projectRoot 'release'
$destination = Join-Path $releaseRoot ('MCUTOOL-Desktop-' + $version + '-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
if (Test-Path -LiteralPath $destination) { throw '交付目录已存在，不覆盖已有产物' }
New-Item -ItemType Directory -Path $destination | Out-Null
$installer = Join-Path $destination ('MCUTOOL-' + $version + '-windows-x64-setup.exe')
Copy-Item -LiteralPath $installers[0].FullName -Destination $installer
Copy-Item -LiteralPath $signaturePath -Destination ($installer + '.sig')
foreach ($file in @('README.md','AGENTS.md','docs/桌面版使用说明.md','docs/软件使用说明.md','docs/上位机界面与图表使用说明.md','docs/固定10Hz与长时间波形验证报告.md','docs/0.4.1发布与验证说明.md','docs/INA226实板启动与测量限制.md','docs/Wi-Fi连接修复记录.md','integrations/mcp.desktop.example.json','integrations/desktop-release.json','scripts/setup-desktop.ps1','scripts/flash-firmware.ps1','firmware/build/ai_mcutool.bin','firmware/build/bootloader/bootloader.bin','firmware/build/partition_table/partition-table.bin','firmware/build/flash_args')) {
    $target = Join-Path $destination $file
    New-Item -ItemType Directory -Path (Split-Path $target -Parent) -Force | Out-Null
    Copy-Item -LiteralPath (Join-Path $projectRoot $file) -Destination $target
}
$evidence = Join-Path $destination 'docs/软件验证证据'
New-Item -ItemType Directory -Path $evidence -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $projectRoot 'docs/软件验证证据/固定10Hz-0.4.0') -Destination $evidence -Recurse
Copy-Item -LiteralPath (Join-Path $projectRoot 'docs/软件验证证据/发布-0.4.1') -Destination $evidence -Recurse
$skillTarget = Join-Path $destination 'integrations/skill'
New-Item -ItemType Directory -Path $skillTarget -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $projectRoot 'integrations/skill/xhh-mcu-tool') -Destination $skillTarget -Recurse
Compress-Archive -LiteralPath (Join-Path $skillTarget 'xhh-mcu-tool') -DestinationPath (Join-Path $destination ('MCUTOOL-Skill-' + $version + '.zip'))
$utf8 = [Text.UTF8Encoding]::new($false)
$hash = (Get-FileHash -LiteralPath $installer -Algorithm SHA256).Hash.ToLowerInvariant()
<# AI:仓库安装入口必须绑定本次真实安装器，拒绝打包过期摘要。 #>
$releaseDescriptor = Get-Content -Raw -LiteralPath (Join-Path $projectRoot 'integrations/desktop-release.json') | ConvertFrom-Json
if ($releaseDescriptor.version -cne $version -or $releaseDescriptor.sha256 -cne $hash) { throw '固定发布描述与本次安装器不一致，请核对版本与SHA256后再打包' }
[IO.File]::WriteAllText(($installer + '.sha256'),($hash + '  ' + (Split-Path $installer -Leaf) + "`n"),$utf8)
$files = @(Get-ChildItem -LiteralPath $destination -Recurse -File | ForEach-Object {
    @{path=$_.FullName.Substring($destination.Length+1).Replace('\','/'); bytes=$_.Length; sha256=(Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()}
})
$firmwareProject = Get-Content -Raw -LiteralPath (Join-Path $projectRoot 'firmware/CMakeLists.txt')
if ($firmwareProject -notmatch 'project\(ai_mcutool VERSION ([0-9]+\.[0-9]+\.[0-9]+)\)') { throw '无法确定固件版本，不生成交付清单' }
$manifest = @{version=$version; platform='windows-x64'; firmware_version=$Matches[1]; source_state='uncommitted-working-tree'; created_at=(Get-Date).ToString('o'); files=$files}
[IO.File]::WriteAllText((Join-Path $destination 'manifest.json'),($manifest | ConvertTo-Json -Depth 6),$utf8)
$latest = @{version=$version; directory=$destination; installer=$installer; sha256=$hash; created_at=(Get-Date).ToString('o')}
[IO.File]::WriteAllText((Join-Path $releaseRoot 'latest-desktop.json'),($latest | ConvertTo-Json),$utf8)
$latest | ConvertTo-Json
