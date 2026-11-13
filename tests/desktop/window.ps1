param(
    [Parameter(Mandatory=$true)][int]$TargetProcessId,
    [Parameter(Mandatory=$true)][string]$ExpectedExe,
    [Parameter(Mandatory=$true)][ValidateSet('visible','close','save','inspect')][string]$Action,
    [string]$OutputPath
)
# AI:只操作验证脚本创建的明确程序，输出文件限制在本项目docs/temp内。
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$projectRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$targetProcess = Get-Process -Id $TargetProcessId
if ([System.IO.Path]::GetFullPath($targetProcess.Path) -ne [System.IO.Path]::GetFullPath($ExpectedExe)) { throw '目标进程与测试程序不一致' }
if ($OutputPath) {
    $OutputPath = [System.IO.Path]::GetFullPath($OutputPath)
    $allowedRoot = [System.IO.Path]::GetFullPath((Join-Path $projectRoot 'docs/temp')) + '\'
    if (-not $OutputPath.StartsWith($allowedRoot,[System.StringComparison]::OrdinalIgnoreCase)) { throw '验证输出必须位于docs/temp' }
}
Add-Type -AssemblyName UIAutomationClient,UIAutomationTypes
Add-Type @'
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Text;
public static class DesktopTestWindow {
  private delegate bool Visitor(IntPtr h, IntPtr arg);
  [DllImport("user32.dll")] private static extern bool EnumWindows(Visitor visit, IntPtr arg);
  [DllImport("user32.dll")] private static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] private static extern int GetWindowText(IntPtr h, StringBuilder text, int count);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
  [DllImport("user32.dll")] public static extern bool PostMessage(IntPtr h, uint message, IntPtr w, IntPtr l);
  /// AI:枚举指定PID的工作台顶层窗口。@param pid 明确测试进程。@return 匹配的窗口句柄。
  public static IntPtr[] Find(int pid) {
    var windows = new List<IntPtr>();
    EnumWindows((h,a)=>{uint owner; GetWindowThreadProcessId(h,out owner); var title=new StringBuilder(256); GetWindowText(h,title,256); if(owner==pid && title.ToString().StartsWith("MCU TOOL"))windows.Add(h); return true;},IntPtr.Zero);
    return windows.ToArray();
  }
}
'@
$windows = [DesktopTestWindow]::Find($TargetProcessId)
if ($Action -eq 'save' -or $Action -eq 'inspect') {
    $condition = [System.Windows.Automation.AndCondition]::new(
        [System.Windows.Automation.PropertyCondition]::new([System.Windows.Automation.AutomationElement]::ProcessIdProperty,$TargetProcessId),
        [System.Windows.Automation.PropertyCondition]::new([System.Windows.Automation.AutomationElement]::ClassNameProperty,'#32770'))
    $deadline = [DateTime]::UtcNow.AddSeconds(12)
    do {
        $dialog = [System.Windows.Automation.AutomationElement]::RootElement.FindFirst([System.Windows.Automation.TreeScope]::Children,$condition)
        if (-not $dialog) { Start-Sleep -Milliseconds 100 }
    } while (-not $dialog -and [DateTime]::UtcNow -lt $deadline)
    if (-not $dialog) { throw '未找到本测试程序的保存对话框' }
    if ($Action -eq 'inspect') {
        $dialog.FindAll([System.Windows.Automation.TreeScope]::Descendants,[System.Windows.Automation.Condition]::TrueCondition) | ForEach-Object {
            [PSCustomObject]@{name=$_.Current.Name;id=$_.Current.AutomationId;type=$_.Current.ControlType.ProgrammaticName}
        } | ConvertTo-Json
        exit 0
    }
    # AI:列表项目也可能使用相同AutomationId，必须同时核对控件类型。
    $filename = $dialog.FindFirst([System.Windows.Automation.TreeScope]::Descendants,[System.Windows.Automation.AndCondition]::new(
        [System.Windows.Automation.PropertyCondition]::new([System.Windows.Automation.AutomationElement]::AutomationIdProperty,'1001'),
        [System.Windows.Automation.PropertyCondition]::new([System.Windows.Automation.AutomationElement]::ControlTypeProperty,[System.Windows.Automation.ControlType]::Edit)))
    $save = $dialog.FindFirst([System.Windows.Automation.TreeScope]::Descendants,[System.Windows.Automation.AndCondition]::new(
        [System.Windows.Automation.PropertyCondition]::new([System.Windows.Automation.AutomationElement]::AutomationIdProperty,'1'),
        [System.Windows.Automation.PropertyCondition]::new([System.Windows.Automation.AutomationElement]::ControlTypeProperty,[System.Windows.Automation.ControlType]::Button)))
    if (-not $filename -or -not $save) { throw '保存对话框控件不匹配，请检查实际UI自动化树' }
    ([System.Windows.Automation.ValuePattern]$filename.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern)).SetValue($OutputPath)
    ([System.Windows.Automation.InvokePattern]$save.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern)).Invoke()
    'save-submitted'
    exit 0
}
if ($windows.Count -ne 1) { throw '未唯一识别测试工作台窗口' }
$window = $windows[0]
switch ($Action) {
    'visible' { [DesktopTestWindow]::IsWindowVisible($window).ToString().ToLowerInvariant() }
    'close' { [DesktopTestWindow]::PostMessage($window,0x0010,[IntPtr]::Zero,[IntPtr]::Zero) | Out-Null; 'close-requested' }
}
