<# AI:安装仓库对应的正式桌面版本及AI使用指引。
@param Auth Git使用已有GitHub凭据；Token使用GH_TOKEN环境变量；Anonymous用于公开仓库。
@param PackageDirectory 已下载的安装器及同名.sha256目录，指定后不访问网络。
@param InstallDirectory 安装路径，默认当前用户MCU TOOL目录。
@param IntegrationDirectory 接入配置、下载和备份位置。
@param SkillDirectory Skill安装目标，空值沿用已有个人副本或官方个人目录。
@param ConfigureCodex 使用Codex CLI登记mcutool，备份配置后只更新同名服务。
@param CodexCommand Codex CLI命令名或绝对路径。
@param DownloadOnly 仅下载并校验安装器，不安装或修改客户端。
@param Launch 完成后显示桌面窗口。
@return 输出实际安装、数据、Skill与MCP配置位置；失败以非零退出。
#>
[CmdletBinding()]
param(
    [ValidateSet('Git','Token','Anonymous')][string]$Auth = 'Git',
    [string]$PackageDirectory,
    [string]$InstallDirectory = (Join-Path $env:LOCALAPPDATA 'MCU TOOL'),
    [string]$IntegrationDirectory = (Join-Path $env:LOCALAPPDATA 'MCU_TOOL/setup'),
    [string]$SkillDirectory,
    [switch]$ConfigureCodex,
    [string]$CodexCommand = 'codex',
    [switch]$DownloadOnly,
    [switch]$Launch
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2
<# AI:显式加载当前引擎自带模块，避免AI启动器继承另一版PowerShell的模块搜索路径。 #>
foreach ($moduleName in @('Microsoft.PowerShell.Utility','Microsoft.PowerShell.Management','CimCmdlets')) {
    Import-Module (Join-Path $PSHOME ('Modules/'+$moduleName+'/'+$moduleName+'.psd1')) -ErrorAction Stop
}
$projectRoot = Split-Path $PSScriptRoot -Parent
$utf8 = [Text.UTF8Encoding]::new($false)

function Write-Utf8 {
    <# AI:写入UTF-8无BOM文件。@param Path 目标。@param Text 完整文本。@return 无。 #>
    param([string]$Path,[string]$Text)
    [IO.File]::WriteAllText($Path,$Text,$script:utf8)
}

function Get-GitHubAuthorization {
    <# AI:仅在需要网络时取得明确模式的GitHub授权，凭据不输出、不落盘。@return 授权字符串或空。 #>
    if ($Auth -eq 'Anonymous') { return '' }
    if ($Auth -eq 'Token') {
        if (-not $env:GH_TOKEN) { throw 'Set GH_TOKEN for -Auth Token; do not put the token in command arguments.' }
        return 'Bearer ' + $env:GH_TOKEN
    }
    $git = Get-Command git -ErrorAction Stop
    $info = [Diagnostics.ProcessStartInfo]::new()
    $info.FileName = $git.Source; $info.Arguments = 'credential fill'
    $info.UseShellExecute = $false; $info.CreateNoWindow = $true
    $info.RedirectStandardInput = $true; $info.RedirectStandardOutput = $true; $info.RedirectStandardError = $true
    $info.EnvironmentVariables['GIT_TERMINAL_PROMPT'] = '0'
    $info.EnvironmentVariables['GCM_INTERACTIVE'] = 'Never'
    $process = [Diagnostics.Process]::new(); $process.StartInfo = $info
    try {
        [void]$process.Start()
        $output = $process.StandardOutput.ReadToEndAsync(); $errorOutput = $process.StandardError.ReadToEndAsync()
        $process.StandardInput.Write("protocol=https`nhost=github.com`n`n"); $process.StandardInput.Close()
        if (-not $process.WaitForExit(15000)) { $process.Kill(); throw 'Git credential lookup timed out.' }
        if ($process.ExitCode -ne 0) { throw 'GitHub credentials unavailable. Sign in to Git for this repository, or explicitly use -Auth Token.' }
        $tokenLine = @($output.Result -split "`n" | Where-Object { $_.StartsWith('password=') })
        if ($tokenLine.Count -ne 1) { throw 'GitHub credential does not include a token.' }
        return 'Bearer ' + $tokenLine[0].Substring(9).TrimEnd("`r")
    } finally { $process.Dispose() }
}

function Receive-ReleaseFile {
    <# AI:下载指定GitHub资产；授权仅发往API主机，签名重定向不带授权。@param Asset GitHub资产对象。@param Target 目标文件。@param Authorization API凭据。@return 无。 #>
    param($Asset,[string]$Target,[string]$Authorization)
    Add-Type -AssemblyName System.Net.Http
    $handler = [Net.Http.HttpClientHandler]::new(); $handler.AllowAutoRedirect = $false
    $http = [Net.Http.HttpClient]::new($handler); $http.Timeout = [TimeSpan]::FromMinutes(15)
    $request = [Net.Http.HttpRequestMessage]::new([Net.Http.HttpMethod]::Get,[string]$Asset.url)
    if ($request.RequestUri.Scheme -ne 'https' -or $request.RequestUri.Host -ne 'api.github.com') { throw 'Invalid GitHub asset endpoint.' }
    $request.Headers.Add('User-Agent','MCUTOOL-Setup')
    $request.Headers.Add('Accept','application/octet-stream')
    if ($Authorization) { $request.Headers.Add('Authorization',$Authorization) }
    $response = $null; $stream = $null
    try {
        $response = $http.SendAsync($request,[Net.Http.HttpCompletionOption]::ResponseHeadersRead).GetAwaiter().GetResult()
        if ([int]$response.StatusCode -in @(301,302,303,307,308)) {
            $location = $response.Headers.Location
            if (-not $location.IsAbsoluteUri -or $location.Scheme -ne 'https' -or -not ($location.Host.EndsWith('.githubusercontent.com') -or $location.Host -eq 'github.com')) { throw 'Unexpected GitHub download redirect.' }
            $response.Dispose()
            $response = $http.GetAsync($location,[Net.Http.HttpCompletionOption]::ResponseHeadersRead).GetAwaiter().GetResult()
        }
        [void]$response.EnsureSuccessStatusCode()
        $stream = [IO.File]::Open($Target,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write)
        $response.Content.CopyToAsync($stream).GetAwaiter().GetResult()
    } finally {
        if ($stream) { $stream.Dispose() }; if ($response) { $response.Dispose() }
        $request.Dispose(); $http.Dispose(); $handler.Dispose()
    }
}

function Confirm-Installer {
    <# AI:同时对照仓库固定摘要与随包校验文件，失败禁止运行。@param Directory 文件目录。@param Release 固定发布描述。@return 安装器绝对路径。 #>
    param([string]$Directory,$Release)
    $installerPath = Join-Path $Directory $Release.installer
    $checksumPath = $installerPath + '.sha256'
    $checksum = [IO.File]::ReadAllText($checksumPath,$script:utf8).Trim()
    if ($checksum -notmatch '^([0-9a-fA-F]{64})\s+\*?(.+)$' -or $Matches[2] -cne $Release.installer) { throw 'Invalid installer checksum file.' }
    if ($Matches[1].ToLowerInvariant() -cne $Release.sha256) { throw 'Release checksum differs from the repository descriptor.' }
    if ((Get-FileHash -LiteralPath $installerPath -Algorithm SHA256).Hash.ToLowerInvariant() -cne $Release.sha256) { throw 'Installer SHA256 mismatch; installation was not started.' }
    return [IO.Path]::GetFullPath($installerPath)
}

function Read-McpReply {
    <# AI:读取本次只读MCP探测响应，限时且不打印完整管道内容。@param Process 本次探测子进程。@param Id 请求编号。@return 对应JSON响应。 #>
    param([Diagnostics.Process]$Process,[int]$Id)
    for ($count=0; $count -lt 10; $count++) {
        $line = $Process.StandardOutput.ReadLineAsync()
        if (-not $line.Wait(15000) -or -not $line.Result) { throw 'MCP readiness probe did not respond.' }
        $reply = $line.Result | ConvertFrom-Json
        if ($reply.PSObject.Properties['id'] -and $reply.id -eq $Id) {
            if ($reply.PSObject.Properties['error']) { throw 'MCP readiness probe returned an error.' }
            return $reply.result
        }
    }
    throw 'MCP readiness response was not found.'
}

function Confirm-McpRuntime {
    <# AI:真实启动安装版stdio MCP，只调用initialize及ping，不启动共享后台或连接硬件。@param Service 程序。@param DataDirectory 共享数据目录。@param Version 期望版本。@return 无。 #>
    param([string]$Service,[string]$DataDirectory,[string]$Version)
    $info = [Diagnostics.ProcessStartInfo]::new()
    $info.FileName = $Service; $info.Arguments = 'mcp --data-dir "' + $DataDirectory + '"'
    $info.UseShellExecute = $false; $info.CreateNoWindow = $true
    $info.RedirectStandardInput = $true; $info.RedirectStandardOutput = $true; $info.RedirectStandardError = $true
    $process = [Diagnostics.Process]::new(); $process.StartInfo = $info
    try {
        [void]$process.Start(); $errorOutput = $process.StandardError.ReadToEndAsync()
        $process.StandardInput.WriteLine('{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"MCUTOOL-Setup","version":"1.0"}}}')
        $null = Read-McpReply $process 1
        $process.StandardInput.WriteLine('{"jsonrpc":"2.0","method":"notifications/initialized"}')
        $process.StandardInput.WriteLine('{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"ping","arguments":{}}}')
        $reply = Read-McpReply $process 2
        $text = @($reply.content | Where-Object type -EQ 'text')[0].text
        $ping = $text | ConvertFrom-Json
        if ($ping.version -cne $Version -or 'press_keys' -notin $ping.tools -or 'read_data' -notin $ping.tools) { throw 'Installed MCP version or capabilities do not match.' }
        Write-Host ('MCP ready: version ' + $ping.version + ', ' + $ping.tools.Count + ' tools; no hardware connected by this probe.')
    } finally {
        if ($process.Id) { $process.StandardInput.Close(); if (-not $process.WaitForExit(5000)) { $process.Kill() } }
        $process.Dispose()
    }
}

if ($env:OS -ne 'Windows_NT' -or -not [Environment]::Is64BitOperatingSystem) { throw 'This installer requires Windows x64.' }
$release = [IO.File]::ReadAllText((Join-Path $projectRoot 'integrations/desktop-release.json'),$utf8) | ConvertFrom-Json
if ($release.repository -cne 'xiaohuihuitop/AI_MCUTOOL' -or $release.tag -cne ('v'+$release.version) -or $release.installer -cne ('MCUTOOL-'+$release.version+'-windows-x64-setup.exe') -or $release.sha256 -notmatch '^[0-9a-f]{64}$') { throw 'Invalid release descriptor.' }
$InstallDirectory = [IO.Path]::GetFullPath($InstallDirectory)
$IntegrationDirectory = [IO.Path]::GetFullPath($IntegrationDirectory)
$desktopExe = Join-Path $InstallDirectory 'mcutool-desktop.exe'
$serviceExe = Join-Path $InstallDirectory 'runtime/MCUTOOL-service/MCUTOOL-service.exe'
$installedVersion = if (Test-Path -LiteralPath $desktopExe) { [Diagnostics.FileVersionInfo]::GetVersionInfo($desktopExe).ProductVersion } else { '' }
$needsInstall = $installedVersion -cne $release.version -or -not (Test-Path -LiteralPath $serviceExe)
if ($ConfigureCodex -and -not $DownloadOnly) { $codexCli = Get-Command $CodexCommand -ErrorAction Stop }
New-Item -ItemType Directory -Path $IntegrationDirectory -Force | Out-Null

if ($needsInstall -or $DownloadOnly) {
    if (-not $PackageDirectory) {
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        $authorization = Get-GitHubAuthorization
        $headers = @{'User-Agent'='MCUTOOL-Setup';'Accept'='application/vnd.github+json'}
        if ($authorization) { $headers.Authorization = $authorization }
        try { $remote = Invoke-RestMethod -Uri ('https://api.github.com/repos/'+$release.repository+'/releases/tags/'+$release.tag) -Headers $headers }
        catch { throw 'Cannot access the specified GitHub Release. Check repository access and -Auth; no alternate version is used.' }
        if ($remote.tag_name -cne $release.tag -or $remote.draft -or $remote.prerelease) { throw 'The requested stable release is not published.' }
        $PackageDirectory = Join-Path $IntegrationDirectory ('downloads/'+$release.tag+'-'+[Guid]::NewGuid().ToString('N'))
        New-Item -ItemType Directory -Path $PackageDirectory -Force | Out-Null
        foreach ($name in @($release.installer,($release.installer+'.sha256'))) {
            $assets = @($remote.assets | Where-Object name -CEQ $name)
            if ($assets.Count -ne 1) { throw ('Missing or duplicate release asset: '+$name) }
            Receive-ReleaseFile $assets[0] (Join-Path $PackageDirectory $name) $authorization
        }
    }
    $installerPath = Confirm-Installer $PackageDirectory $release
    if ($DownloadOnly) { Write-Output ($installerPath); return }
    $running = @(Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -and $_.ExecutablePath.StartsWith($InstallDirectory+'\',[StringComparison]::OrdinalIgnoreCase) })
    if ($running.Count) { throw 'MCU TOOL is in use. Finish recording/jobs and use Stop backend and exit before upgrading.' }
    $installer = Start-Process -FilePath $installerPath -ArgumentList @('/S',('/D='+$InstallDirectory)) -WindowStyle Hidden -PassThru
    $installer.WaitForExit()
    if ($installer.ExitCode -ne 0) { throw ('Installer failed: '+$installer.ExitCode) }
    if (-not (Test-Path -LiteralPath $serviceExe) -or [Diagnostics.FileVersionInfo]::GetVersionInfo($desktopExe).ProductVersion -cne $release.version) { throw 'Installed version was not confirmed.' }
} else { Write-Host ('Reusing installed MCU TOOL '+$installedVersion+'.') }

$desktopSettings = Join-Path $env:LOCALAPPDATA 'MCU_TOOL/desktop.json'
if (Test-Path -LiteralPath $desktopSettings) {
    $settings = [IO.File]::ReadAllText($desktopSettings,$utf8) | ConvertFrom-Json
    $dataDirectory = [string]$settings.data_dir
    if (-not [IO.Path]::IsPathRooted($dataDirectory)) { throw 'Existing desktop data_dir must be absolute.' }
} else { $dataDirectory = Join-Path $env:LOCALAPPDATA 'MCU_TOOL/data' }
$dataDirectory = [IO.Path]::GetFullPath($dataDirectory)
Confirm-McpRuntime $serviceExe $dataDirectory $release.version
$mcp = @{mcpServers=@{mcutool=@{command=$serviceExe;args=@('mcp','--data-dir',$dataDirectory)}}}
$mcpPath = Join-Path $IntegrationDirectory 'mcp-config.json'
Write-Utf8 $mcpPath ($mcp | ConvertTo-Json -Depth 5)

if (-not $SkillDirectory) {
    $oldSkill = Join-Path $env:USERPROFILE '.codex/skills/xhh-mcu-tool'
    $SkillDirectory = if (Test-Path -LiteralPath $oldSkill) { $oldSkill } else { Join-Path $env:USERPROFILE '.agents/skills/xhh-mcu-tool' }
}
$SkillDirectory = [IO.Path]::GetFullPath($SkillDirectory)
$skillSource = Join-Path $projectRoot 'integrations/skill/xhh-mcu-tool'
$backupDirectory = Join-Path $IntegrationDirectory ('backups/'+[Guid]::NewGuid().ToString('N'))
if (Test-Path -LiteralPath $SkillDirectory) {
    New-Item -ItemType Directory -Path $backupDirectory -Force | Out-Null
    Copy-Item -LiteralPath $SkillDirectory -Destination (Join-Path $backupDirectory 'xhh-mcu-tool') -Recurse
}
New-Item -ItemType Directory -Path $SkillDirectory -Force | Out-Null
Get-ChildItem -LiteralPath $skillSource | Copy-Item -Destination $SkillDirectory -Recurse -Force
if ($ConfigureCodex) {
    $codexRoot = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $env:USERPROFILE '.codex' }
    $config = Join-Path $codexRoot 'config.toml'
    if (Test-Path -LiteralPath $config) { New-Item -ItemType Directory -Path $backupDirectory -Force | Out-Null; Copy-Item -LiteralPath $config -Destination (Join-Path $backupDirectory 'config.toml') }
    & $codexCli.Source mcp add mcutool -- $serviceExe mcp --data-dir $dataDirectory
    if ($LASTEXITCODE -ne 0) { throw 'Codex MCP registration failed. The original configuration backup is in the setup backup directory.' }
    $registered = (& $codexCli.Source mcp get mcutool --json) | ConvertFrom-Json
    if ($LASTEXITCODE -ne 0 -or $registered.transport.command -cne $serviceExe -or ($registered.transport.args -join "`n") -cne (@('mcp','--data-dir',$dataDirectory) -join "`n")) { throw 'Codex MCP registration did not match the installed runtime.' }
}
Write-Output (@{version=$release.version;desktop=$desktopExe;data_dir=$dataDirectory;skill=$SkillDirectory;mcp_config=$mcpPath;codex_configured=[bool]$ConfigureCodex} | ConvertTo-Json)
if ($Launch) { Start-Process -FilePath $desktopExe -WindowStyle Normal }
