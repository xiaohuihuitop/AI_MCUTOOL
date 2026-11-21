import assert from 'node:assert/strict'
import { execFileSync, spawn } from 'node:child_process'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { setTimeout as delay } from 'node:timers/promises'
import { chromium } from '../../web/node_modules/playwright/index.mjs'

// AI:只在一次性的 Windows runner 执行正式覆盖安装，避开开发电脑的共享后台。
assert.equal(process.env.RUNNER_ENVIRONMENT, 'github-hosted')
const previous = process.env.PREVIOUS
const expected = JSON.parse(readFileSync(new URL('../../desktop/package.json', import.meta.url))).version
const exe = join(process.env.LOCALAPPDATA, 'MCU TOOL', 'mcutool-desktop.exe')
const runtimeFile = join(process.env.LOCALAPPDATA, 'MCU_TOOL', 'data', 'runtime.json')
const debug = 'http://127.0.0.1:29756'

/** AI:读取实际安装的桌面文件版本。@returns Windows 产品版本。 */
function installed() {
  return execFileSync('powershell.exe', ['-NoProfile', '-Command',
    '(Get-Item -LiteralPath $env:MCUTOOL_QA_EXE).VersionInfo.ProductVersion'],
  {env:{...process.env,MCUTOOL_QA_EXE:exe}, encoding:'utf8', windowsHide:true}).trim()
}

/** AI:等待桌面、后台或安装器异步完成。@param label 检查项。@param read 状态查询。@returns 已满足的状态。 */
async function until(label, read) {
  const deadline = Date.now() + 240_000
  while (Date.now() < deadline) {
    const value = await read()
    if (value) return value
    await delay(500)
  }
  throw Error('超时：' + label)
}

/** AI:加载当前后台的发现记录。@returns 当前身份，后台正在交接时返回空。 */
function runtime() {
  try { return JSON.parse(readFileSync(runtimeFile, 'utf8')) }
  catch (error) { if (error.code === 'ENOENT') return null; throw error }
}

assert.equal(installed(), previous)
const oldDesktop = spawn(exe, [], {windowsHide:true, stdio:'ignore', env:{...process.env,
  WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS:'--remote-debugging-address=127.0.0.1 --remote-debugging-port=29756'}})
let browser
try {
  const old = await until('旧版后台启动', runtime)
  assert.equal(old.version, previous)
  await until('旧工作台调试端口', () => fetch(debug + '/json/version').then(r => r.ok, () => false))
  browser = await chromium.connectOverCDP(debug)
  const page = await until('旧工作台就绪', () => browser.contexts().flatMap(c => c.pages()).find(p => p.url() === old.url + '/'))
  await until('公开更新下载和验签', async () => {
    const state = await page.evaluate(() => window.__TAURI__.core.invoke('desktop_update_status'))
    if (state.phase === 'failed') throw Error(state.message)
    if (state.phase !== 'ready') return false
    assert.equal(state.version, expected)
    return true
  })
  await page.getByRole('region',{name:'工具更新'}).getByRole('button',{name:'立即安装'}).click()
  await until('旧桌面退出', () => oldDesktop.exitCode !== null)
  await browser.close()
  browser = null
  const next = await until('新后台和新桌面会话', async () => {
    const current = runtime()
    if (current?.version !== expected || current.instance_id === old.instance_id) return false
    const response = await fetch(current.url+'/api/runtime/status', {headers:{Authorization:'Bearer '+current.token}})
    const state = await response.json()
    return state.version === expected && state.clients.some(c => c.kind === 'desktop' && c.active) && state
  })
  assert.equal(installed(), expected)
  assert.equal(next.connected, false)
  assert.equal(next.firmware_update.phase, 'idle')
  console.log(`已验证正式桌面 ${previous} → ${expected}，桌面重启、同一数据目录回读成功，固件更新入口已加载。`)
} finally {
  if (browser) await browser.close()
  oldDesktop.unref()
}
