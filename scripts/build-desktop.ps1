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
        $buildArgs += @('--','--locked')
        & npm.cmd @buildArgs
        if ($LASTEXITCODE -ne 0) { throw '桌面程序或安装器构建失败' }
        # AI:免安装构建没有安装器的最后一次改名，保留开发桌面的同一服务入口。
        $targetRoot = if ($env:CARGO_TARGET_DIR) { $env:CARGO_TARGET_DIR } else { Join-Path $projectRoot 'desktop/src-tauri/target' }
        $devEntry = Join-Path $targetRoot 'x86_64-pc-windows-msvc/release/runtime/MCUTOOL-service/MCUTOOL-service.exe'
        Copy-Item -LiteralPath (Join-Path $projectRoot 'desktop/runtime/MCUTOOL-service/MCUTOOL-service.exe') -Destination $devEntry -Force
    } finally { Pop-Location }
} finally { Pop-Location }
