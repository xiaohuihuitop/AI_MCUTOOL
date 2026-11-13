export type Sample = {channel: string; value: number | null; nominal: number | null; unit: string; quality: string; t_us: number; boot_id: string; cursor: number; stale?: boolean; age_ms?: number}
export type Job = {request_id: string; method: string; state: string; action_id: number | null; actor: string; error: {message: string} | null; created_at: number; result: Record<string, unknown> | null}
export type Snapshot = {
  instance_id: string; connected: boolean; test_mode: boolean;
  device: Record<string, any>; device_state: Record<string, any>; device_state_stale: boolean;
  control: {owner: {id: string; name: string; kind: string} | null; owner_active: boolean; revision: number; device_claimed: boolean};
  latest: Record<string, Sample>; jobs: Job[]; clients: {id: string; name: string; kind: string; active: boolean}[];
  recording: {state: string; path: string | null; error: string | null; written_records: number};
  last_error: {message: string} | null;
}

import { desktopCommand, isDesktop } from './desktop'

export const token = document.querySelector<HTMLMetaElement>('meta[name="mcutool-token"]')?.content ?? ''
let sessionId = ''

/** AI:设置当前页面会话。@param id 后台会话令牌。@returns 无。 */
export function setSession(id: string) { sessionId = id }
/** AI:取得当前页面会话。@returns 会话令牌，仅用于本机调用。 */
export function getSession() { return sessionId }
/** AI:访问同源后台，失败保留明确说明。@param path 接口路径。@param method HTTP方法。@param body 参数。@returns JSON结果。 */
export async function api<T = any>(path: string, method = 'GET', body?: unknown): Promise<T> {
  const response = await fetch(path, {method, headers: {'Authorization': `Bearer ${token}`, 'X-Session-ID': sessionId, 'Content-Type': 'application/json'}, body: body === undefined ? undefined : JSON.stringify(body)})
  const data = await response.json()
  if (!response.ok) {
    const message = data.error?.message ?? (Array.isArray(data.detail) ? data.detail.map((x: any) => x.msg).join('；') : '请求未完成，请检查输入和连接状态')
    throw new Error(message)
  }
  return data as T
}
/** AI:下载原始记录文件。@param record 记录目录。@param filename 文件名。@returns 完成或抛错。 */
export async function download(record: string, filename: string) {
  if (isDesktop) {
    await desktopCommand('desktop_save_recording', {record, filename})
    return
  }
  const response = await fetch(`/api/recordings/${encodeURIComponent(record)}/${encodeURIComponent(filename)}`, {headers: {'Authorization': `Bearer ${token}`, 'X-Session-ID': sessionId}})
  if (!response.ok) throw new Error('记录文件下载失败')
  const url = URL.createObjectURL(await response.blob())
  const link = document.createElement('a'); link.href = url; link.download = filename; link.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

/** AI:导出脱敏诊断ZIP。@returns 是否已发起保存或下载，取消保存为false。 */
export async function exportDiagnostics(): Promise<boolean> {
  if (isDesktop) return desktopCommand<boolean>('desktop_export')
  const response = await fetch('/api/diagnostics', {headers: {'Authorization': `Bearer ${token}`, 'X-Session-ID': sessionId}})
  if (!response.ok) throw new Error('诊断日志导出失败，请检查后台连接')
  const url = URL.createObjectURL(await response.blob())
  const link = document.createElement('a'); link.href = url; link.download = 'MCUTOOL-诊断日志.zip'; link.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
  return true
}
