type DesktopSession = {client_id: string; session_id: string; instance_id: string; data_dir: string; version: string}

declare global {
  interface Window { __TAURI__?: {core: {invoke<T>(command: string, args?: Record<string, unknown>): Promise<T>}} }
}

export const isDesktop = Boolean(window.__TAURI__?.core)

/** AI:调用当前桌面窗口提供的限定命令。@param command 命令名；args 参数。@returns 命令结果，普通网页不能调用。 */
export async function desktopCommand<T = void>(command: string, args?: Record<string, unknown>): Promise<T> {
  if (!window.__TAURI__?.core) throw new Error('此操作需要桌面版')
  try { return await window.__TAURI__.core.invoke<T>(command, args) }
  catch (error) { throw new Error(typeof error === 'string' ? error : '桌面操作未完成，请检查程序状态') }
}

/** AI:取得原生进程续约的同一个会话。@returns 桌面会话，刷新页面不另建操作者。 */
export function desktopSession() { return desktopCommand<DesktopSession>('desktop_context') }
