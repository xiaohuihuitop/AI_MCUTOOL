param([Parameter(Mandatory)][string]$Installer, [Parameter(Mandatory)][string]$Version)
# AI:在一次性 Windows 主机复现 MCP 持有运行库以及安装期间重新启动。
$ErrorActionPreference = 'Stop'
if ($env:RUNNER_ENVIRONMENT -ne 'github-hosted') { throw '此测试需要独立 Windows runner' }
$root = Join-Path $env:LOCALAPPDATA 'MCU TOOL'
$service = Join-Path $root 'runtime/MCUTOOL-service/MCUTOOL-service.exe'
$dll = Join-Path $root 'runtime/MCUTOOL-service/_internal/ucrtbase.dll'
$data = Join-Path $env:RUNNER_TEMP 'handoff-test'
$bridges = [Collections.Generic.List[Diagnostics.Process]]::new()

function Start-Bridge {
    <# AI:启动旧安装的真实 stdio 入口并保持标准输入。@return 已保留的桥接进程。 #>
    $info = [Diagnostics.ProcessStartInfo]::new($service)
    $info.UseShellExecute = $false
    $info.CreateNoWindow = $true
    $info.RedirectStandardInput = $true
    $info.RedirectStandardOutput = $true
    $info.RedirectStandardError = $true
    foreach ($arg in 'mcp','--data-dir',$data) { $info.ArgumentList.Add($arg) }
    $child = [Diagnostics.Process]::Start($info)
    $bridges.Add($child)
    return $child
}

try {
    $first = Start-Bridge
    $second = Start-Bridge
    $end = [datetime]::UtcNow.AddSeconds(40)
    do {
        $first.Refresh()
        if ($first.Modules.FileName -contains $dll) { break }
        Start-Sleep -Milliseconds 100
    } while ([datetime]::UtcNow -lt $end)
    if ($first.Modules.FileName -notcontains $dll) { throw '未重现运行库被 MCP 加载的前提' }
    $setup = Start-Process $Installer -ArgumentList '/S' -WindowStyle Hidden -PassThru
    $end = [datetime]::UtcNow.AddMinutes(4)
    $sawClosedEntry = $false
    while (!$setup.HasExited -and [datetime]::UtcNow -lt $end) {
        if (!(Test-Path -LiteralPath $service)) {
            $sawClosedEntry = $true
            $launched = $false
            try { $null = Start-Bridge; $launched = $true }
            catch [System.ComponentModel.Win32Exception] { if ($_.Exception.NativeErrorCode -ne 2) { throw } }
            catch [System.Management.Automation.MethodInvocationException] {
                if ($_.Exception.InnerException.NativeErrorCode -ne 2) { throw }
            }
            if ($launched -and !(Test-Path $service)) { throw '替换期间仍可启动 MCP' }
            break
        }
        Start-Sleep -Milliseconds 50
    }
    if (!$setup.WaitForExit(240000) -or $setup.ExitCode -ne 0) { throw '安装器未成功完成' }
    if (!$first.HasExited -or !$second.HasExited -or !$sawClosedEntry) { throw '桥接进程交接未通过' }
    if ((Get-Item (Join-Path $root 'mcutool-desktop.exe')).VersionInfo.ProductVersion -ne $Version) { throw '桌面版本不符' }
    $null = & $service start --data-dir $data --port 29759 --no-browser
    if ($LASTEXITCODE) { throw '新版服务启动失败' }
    $r = Get-Content -Raw (Join-Path $data 'runtime.json') | ConvertFrom-Json
    try {
        $s = Invoke-RestMethod ($r.url+'/api/runtime/status') -Headers @{Authorization=('Bearer '+$r.token)} -NoProxy
        if ($s.version -ne $Version -or $s.connected) { throw '新版后台回读失败' }
        $html = (Invoke-WebRequest $r.url -NoProxy).Content
        foreach ($match in [regex]::Matches($html,'(?:src|href)="(/assets/[^"]+)"')) {
            if ((Invoke-WebRequest ($r.url+$match.Groups[1].Value) -NoProxy).StatusCode -ne 200) { throw '工作台资源缺失' }
        }
    } finally { $null = & $service stop --data-dir $data }
    Write-Output "MCP 占用、复制期间重新启动、安装退出和 $Version 后台回读均通过。"
} finally {
    foreach ($child in $bridges) {
        if (!$child.HasExited) { $child.StandardInput.Close(); $null = $child.WaitForExit(5000) }
    }
}
