param([switch]$SkipBrowser)
# AI:正式验证结果集中保存在项目临时目录，实物测试不在本脚本内。
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
$runRoot = Join-Path $projectRoot ('docs/temp/verify-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
New-Item -ItemType Directory -Path $runRoot | Out-Null
$utf8 = [System.Text.UTF8Encoding]::new($false)

function Invoke-VerifiedCommand {
    <# AI:执行检查并保留输出。@param Name 检查名；Program 程序；Arguments 参数。@return 无，失败抛错。 #>
    param([string]$Name,[string]$Program,[string[]]$Arguments)
    $output = & $Program @Arguments 2>&1
    $exitCode = $LASTEXITCODE
    [System.IO.File]::WriteAllLines((Join-Path $runRoot ($Name + '.log')), [string[]]@($output | ForEach-Object { "$_" }), $utf8)
    $output | Write-Output
    if ($exitCode -ne 0) { throw "$Name 检查失败，退出码 $exitCode" }
}

Push-Location $projectRoot
try {
    Invoke-VerifiedCommand 'python-tests' (Join-Path $projectRoot '.venv/Scripts/python.exe') @('-m','pytest','tests','-q',('--basetemp=' + (Join-Path $runRoot 'pytest')))
    Invoke-VerifiedCommand 'native-core-build' 'gcc' @('-std=c11','-Wall','-Wextra','-Werror','-Ifirmware/main','tests/firmware/core_test.c','firmware/main/tool_core.c','-o',(Join-Path $runRoot 'core-test.exe'))
    Invoke-VerifiedCommand 'native-core-run' (Join-Path $runRoot 'core-test.exe') @()
    Invoke-VerifiedCommand 'native-measurement-build' 'gcc' @('-std=c11','-Wall','-Wextra','-Werror','-Ifirmware/main','tests/firmware/measurement_test.c','-o',(Join-Path $runRoot 'measurement-test.exe'))
    Invoke-VerifiedCommand 'native-measurement-run' (Join-Path $runRoot 'measurement-test.exe') @()
    & (Join-Path $PSScriptRoot 'build-firmware.ps1')
    Push-Location web
    try {
        Invoke-VerifiedCommand 'web-build' 'npm.cmd' @('run','build')
        if (-not $SkipBrowser) { Invoke-VerifiedCommand 'browser-mcp' 'npm.cmd' @('run','test:e2e') }
    } finally { Pop-Location }
    $summary = @{completed_at=(Get-Date).ToString('o'); python_tests='passed'; native_core='passed'; native_measurement='passed'; firmware_build='passed'; web_build='passed'; browser_mcp=$(if($SkipBrowser){'not_run'}else{'passed'}); hardware='not_run'} | ConvertTo-Json
    [System.IO.File]::WriteAllText((Join-Path $runRoot 'result.json'), $summary, $utf8)
    Write-Host "验证结果：$runRoot"
} finally { Pop-Location }
