; AI:安装创建专用快捷方式；卸载保留用户数据，并拒绝删除仍被后台使用的程序。
!macro NSIS_HOOK_POSTINSTALL
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
  Delete "$DESKTOP\MCU TOOL.lnk"
!macroend
