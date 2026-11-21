param(
    [Parameter(Mandatory)][string]$Service,
    [Parameter(Mandatory)][ValidateSet('Check','CloseBridges')][string]$Mode,
    [int]$RuntimePid = 0
)
<# AI:仅识别本安装目录的服务；后台退出前只检查，获准退出后才释放 MCP 桥接。 #>
$ErrorActionPreference = 'Stop'
if ([Environment]::Is64BitOperatingSystem -and ![Environment]::Is64BitProcess) {
    <# AI:NSIS 是 32 位程序，使用系统原生 PowerShell 核对 64 位服务的路径及命令行。 #>
    & "$env:SystemRoot\Sysnative\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $PSCommandPath -Service $Service -Mode $Mode -RuntimePid $RuntimePid
    exit $LASTEXITCODE
}
$Service = [IO.Path]::GetFullPath($Service)
$parked = $Service + '.updating'
$all = @(Get-CimInstance Win32_Process -Filter "Name='MCUTOOL-service.exe' OR Name='MCUTOOL-service.exe.updating'" |
    Where-Object { $_.ExecutablePath -ieq $Service -or $_.ExecutablePath -ieq $parked })
$bridges = @()
foreach ($item in $all) {
    if ($Mode -eq 'Check' -and $item.ProcessId -eq $RuntimePid) { continue }
    $process = Get-Process -Id $item.ProcessId -ErrorAction SilentlyContinue
    if (!$process) { continue }
    <# AI:持有句柄并核对启动时间，防止进程号重用。完整命令行区分 stdio 与持有设备的后台。 #>
    $null = $process.Handle
    if ($process.HasExited -or [math]::Abs(($process.StartTime - $item.CreationDate).TotalMilliseconds) -gt 5) { continue }
    if ($process.Path -ine $Service -and $process.Path -ine $parked) { continue }
    if ($item.CommandLine -notmatch '^(?:"[^"]+"|\S+)\s+mcp(?:\s|$)') {
        if ($process.HasExited) { continue }
        Write-Error 'Another MCU TOOL runtime or service operation is active.'
        exit 1
    }
    $bridges += $process
}
if ($Mode -eq 'CloseBridges') {
    foreach ($bridge in $bridges) {
        if (!$bridge.HasExited) {
            try { $bridge.Kill() } catch { if (!$bridge.HasExited) { throw } }
            if (!$bridge.WaitForExit(5000)) { throw 'MCU TOOL MCP did not exit.' }
        }
    }
}
exit 0
