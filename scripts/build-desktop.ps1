param([switch]$SkipService, [switch]$NoInstaller)
# AI:生成Windows桌面程序，运行程序与安装器均由明确版本的依赖构建。
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
$pythonPath = Join-Path $projectRoot '.venv/Scripts/python.exe'
$cargoBin = Join-Path $env:USERPROFILE '.cargo/bin'
if (-not (Test-Path -LiteralPath $pythonPath) -or -not (Test-Path -LiteralPath (Join-Path $cargoBin 'cargo.exe'))) {
    throw '缺少项目Python环境或Rust构建工具，请先按桌面版说明准备环境'
}
$env:PATH = $cargoBin + ';' + $env:PATH
# AI:可分发安装器需内嵌公钥，并由 Tauri 将同一版本写入签名；仅构建程序仍可用于本地开发。
if (-not $NoInstaller) {
    if (-not $env:MCUTOOL_UPDATE_PUBLIC_KEY -or -not $env:TAURI_SIGNING_PRIVATE_KEY) {
        throw '构建可更新安装器需要 MCUTOOL_UPDATE_PUBLIC_KEY 和 TAURI_SIGNING_PRIVATE_KEY（私钥或私钥文件路径）'
    }
    $runDirectory = Join-Path $projectRoot ('docs/temp/signed-bundle-' + [Guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $runDirectory -Force | Out-Null
    $signConfig = Join-Path $runDirectory 'updater.json'
    $config = @{plugins=@{updater=@{pubkey=$env:MCUTOOL_UPDATE_PUBLIC_KEY.Trim()}};bundle=@{createUpdaterArtifacts=$true}}
    [IO.File]::WriteAllText($signConfig, ($config | ConvertTo-Json -Depth 5), [Text.UTF8Encoding]::new($false))
}
Push-Location $projectRoot
try {
    Push-Location web
    try {
        npm.cmd run build
        if ($LASTEXITCODE -ne 0) { throw '网页构建失败' }
    } finally { Pop-Location }
    if (-not $SkipService) {
        & $pythonPath -m PyInstaller desktop/service.spec --distpath desktop/runtime --workpath desktop/build/pyinstaller --noconfirm
        if ($LASTEXITCODE -ne 0) { throw '后台运行程序打包失败' }
    }
    if (-not (Test-Path 'desktop/runtime/MCUTOOL-service/MCUTOOL-service.exe')) { throw '缺少已打包的后台运行程序' }
    Push-Location desktop
    try {
        $buildArgs = @('exec','--','tauri','build','--ci','--target','x86_64-pc-windows-msvc')
        if ($NoInstaller) { $buildArgs += '--no-bundle' }
        else { $buildArgs += @('--config', $signConfig) }
        $buildArgs += @('--','--locked')
        & npm.cmd @buildArgs
        if ($LASTEXITCODE -ne 0) { throw '桌面程序或安装器构建失败' }
    } finally { Pop-Location }
} finally { Pop-Location }
