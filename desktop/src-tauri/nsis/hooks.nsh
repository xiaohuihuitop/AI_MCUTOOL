; AI:安装创建专用快捷方式；卸载保留用户数据，并拒绝删除仍被后台使用的程序。
!define UPDATE_HELPER "${__FILEDIR__}\update-processes.ps1"
!define SERVICE_ENTRY "$INSTDIR\runtime\MCUTOOL-service\MCUTOOL-service.exe"

!macro NSIS_HOOK_PREINSTALL
  ; AI:安装期间固定入口保持关闭，AI客户端重连也无法在复制中途加载运行库。
  InitPluginsDir
  File "/oname=$PLUGINSDIR\update-processes.ps1" "${UPDATE_HELPER}"
  nsExec::ExecToStack '"$SYSDIR\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "$PLUGINSDIR\update-processes.ps1" -Service "${SERVICE_ENTRY}" -Mode CloseBridges'
  Pop $0
  Pop $1
  ${If} $0 != 0
    Abort "后台仍有工作，安装尚未开始。请从当前工作台安装更新。"
  ${EndIf}
  ${If} ${FileExists} "${SERVICE_ENTRY}"
    System::Call 'kernel32::MoveFileExW(w "${SERVICE_ENTRY}", w "${SERVICE_ENTRY}.updating", i 9) i.r0'
    ${If} $0 == 0
      Abort "运行程序正在启动，安装尚未开始。"
    ${EndIf}
    nsExec::ExecToStack '"$SYSDIR\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "$PLUGINSDIR\update-processes.ps1" -Service "${SERVICE_ENTRY}" -Mode CloseBridges'
    Pop $0
    Pop $1
    ${If} $0 != 0
      Rename "${SERVICE_ENTRY}.updating" "${SERVICE_ENTRY}"
      Abort "后台已重新启动，安装尚未开始。"
    ${EndIf}
  ${EndIf}
!macroend

!macro NSIS_HOOK_POSTINSTALL
  ClearErrors
  Rename "$INSTDIR\runtime\MCUTOOL-service\MCUTOOL-service.pending" "${SERVICE_ENTRY}"
  ${If} ${Errors}
    Abort "新运行程序未能就位，请重新运行本版安装器。"
  ${EndIf}
  Delete "${SERVICE_ENTRY}.updating"
  CreateShortCut "$DESKTOP\MCU TOOL.lnk" "$INSTDIR\mcutool-desktop.exe"
!macroend

!macro NSIS_HOOK_PREUNINSTALL
  nsExec::ExecToStack '"$INSTDIR\runtime\MCUTOOL-service\MCUTOOL-service.exe" can-uninstall'
  Pop $0
  Pop $1
  ${If} $0 != 0
    MessageBox MB_OK|MB_ICONEXCLAMATION "后台或MCP仍在使用程序。请先停止后台并退出AI会话，再卸载。" /SD IDOK
    Abort
  ${EndIf}
!macroend

!macro NSIS_HOOK_POSTUNINSTALL
  Delete "${SERVICE_ENTRY}"
  RMDir "$INSTDIR\runtime\MCUTOOL-service"
  RMDir "$INSTDIR\runtime"
  Delete "$DESKTOP\MCU TOOL.lnk"
!macroend
