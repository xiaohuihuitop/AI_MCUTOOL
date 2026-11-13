# AI:只复制明确构建的桌面安装器和说明，创建独立交付目录并生成SHA256清单。
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
$version = (Get-Content -Raw -LiteralPath (Join-Path $projectRoot 'desktop/package.json') | ConvertFrom-Json).version
$installerDir = Join-Path $projectRoot 'desktop/src-tauri/target/x86_64-pc-windows-msvc/release/bundle/nsis'
$installers = @(Get-ChildItem -LiteralPath $installerDir -File -Filter "*_${version}_x64-setup.exe")
if ($installers.Count -ne 1) { throw '未找到当前版本的唯一Windows x64安装器，请先完成桌面构建' }
$releaseRoot = Join-Path $projectRoot 'release'
$destination = Join-Path $releaseRoot ('MCUTOOL-Desktop-' + $version + '-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
if (Test-Path -LiteralPath $destination) { throw '交付目录已存在，不覆盖已有产物' }
New-Item -ItemType Directory -Path $destination | Out-Null
$installer = Join-Path $destination ('MCUTOOL-' + $version + '-windows-x64-setup.exe')
Copy-Item -LiteralPath $installers[0].FullName -Destination $installer
foreach ($file in @('docs/桌面版使用说明.md','docs/桌面版验证报告.md','docs/软件使用说明.md','docs/INA226实板启动与测量限制.md','docs/Wi-Fi连接修复记录.md','integrations/mcp.desktop.example.json')) {
    $target = Join-Path $destination $file
    New-Item -ItemType Directory -Path (Split-Path $target -Parent) -Force | Out-Null
    Copy-Item -LiteralPath (Join-Path $projectRoot $file) -Destination $target
}
$evidence = Join-Path $destination 'docs/软件验证证据'
New-Item -ItemType Directory -Path $evidence -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $projectRoot 'docs/软件验证证据/桌面版-0.2.0') -Destination $evidence -Recurse
$utf8 = [Text.UTF8Encoding]::new($false)
$hash = (Get-FileHash -LiteralPath $installer -Algorithm SHA256).Hash.ToLowerInvariant()
[IO.File]::WriteAllText(($installer + '.sha256'),($hash + '  ' + (Split-Path $installer -Leaf) + "`n"),$utf8)
$files = @(Get-ChildItem -LiteralPath $destination -Recurse -File | ForEach-Object {
    @{path=$_.FullName.Substring($destination.Length+1).Replace('\','/'); bytes=$_.Length; sha256=(Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()}
})
$manifest = @{version=$version; platform='windows-x64'; firmware_version='0.1.1'; source_state='uncommitted-working-tree'; created_at=(Get-Date).ToString('o'); files=$files}
[IO.File]::WriteAllText((Join-Path $destination 'manifest.json'),($manifest | ConvertTo-Json -Depth 6),$utf8)
$latest = @{version=$version; directory=$destination; installer=$installer; sha256=$hash; created_at=(Get-Date).ToString('o')}
[IO.File]::WriteAllText((Join-Path $releaseRoot 'latest-desktop.json'),($latest | ConvertTo-Json),$utf8)
$latest | ConvertTo-Json
