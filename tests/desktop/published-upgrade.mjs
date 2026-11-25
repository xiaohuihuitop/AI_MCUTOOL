import assert from 'node:assert/strict'
import { execFileSync, spawn } from 'node:child_process'
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { setTimeout as delay } from 'node:timers/promises'
import { chromium } from '../../web/node_modules/playwright/index.mjs'

// AI:只在一次性的 Windows runner 执行正式覆盖安装，避开开发电脑的共享后台。
assert.equal(process.env.RUNNER_ENVIRONMENT, 'github-hosted')
const previous = process.env.PREVIOUS
const expected = JSON.parse(readFileSync(new URL('../../desktop/package.json', import.meta.url))).version
const exe = join(process.env.LOCALAPPDATA, 'MCU TOOL', 'mcutool-desktop.exe')
const dataDir = join(process.env.RUNNER_TEMP, 'MCU TOOL 用户记录')
const configDir = join(process.env.LOCALAPPDATA, 'MCU_TOOL')
const configFile = join(configDir, 'desktop.json')
const historyDir = join(dataDir, 'recordings', 'existing')
const historyFile = join(historyDir, 'history.jsonl')
const settings = JSON.stringify({data_dir:dataDir,port:29755})
const history = '{"sample":1}\n'
const runtimeFile = join(dataDir, 'runtime.json')
const debug = 'http://127.0.0.1:29756'
const recovery = process.env.TEST_RECOVERY === 'true'
const desktopTemp = join(process.env.RUNNER_TEMP, 'desktop-update-temp')

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

/** AI:在独立工作台模拟临时目录不可写，确认失败后的会话持续续约并可重试。
 * @param page 已完成下载的真实旧版工作台页面。@param old 更新前的后台信息。
 * @returns 恢复后的工作台重试按钮。
 */
async function checkRecovery(page, old) {
  const account = execFileSync('powershell.exe', ['-NoProfile', '-Command',
    '[Security.Principal.WindowsIdentity]::GetCurrent().User.Value'], {encoding:'utf8', windowsHide:true}).trim()
  assert.match(account, /^S-1-[\d-]+$/)
  const region = page.getByRole('region', {name:'工具更新'})
  const retry = region.getByRole('button', {name:'安装已下载的 ' + expected, exact:true})
  // AI:只禁止在本轮桌面专用的临时目录下新建子目录，使已经验签的安装器无法暂存。
  execFileSync('icacls.exe', [desktopTemp, '/deny', '*' + account + ':(AD)'], {windowsHide:true})
  try {
    await region.getByRole('button', {name:'立即安装'}).click()
    await retry.waitFor({timeout:90000})
    const failure = await page.evaluate(() => window.__TAURI__.core.invoke('desktop_update_status'))
    assert.equal(failure.phase, 'failed')
    assert.match(failure.message, /启动更新安装器失败.*原版本后台和桌面会话已恢复/s)
  } finally {
    execFileSync('icacls.exe', [desktopTemp, '/remove:d', '*' + account], {windowsHide:true})
  }
  const restored = runtime()
  assert.equal(restored?.state, 'ready')
  assert.notEqual(restored.instance_id, old.instance_id)
  const session = await page.evaluate(() => window.__TAURI__.core.invoke('desktop_context'))
  assert.equal(session.instance_id, restored.instance_id)
  // AI:持续观察超过一分钟的会话有效期，观察器只读状态，由桌面自己续约。
  const start = performance.now()
  do {
    const response = await fetch(restored.url+'/api/runtime/status', {
      headers:{Authorization:'Bearer '+restored.token}, signal:AbortSignal.timeout(5000)})
    assert.ok(response.ok)
    const status = await response.json()
    assert.equal(status.instance_id, restored.instance_id)
    assert.equal(status.version, previous)
    assert.equal(status.connected, false)
    assert.ok(status.clients.some(c => c.id === session.client_id && c.kind === 'desktop' && c.active))
    await delay(1000)
  } while (performance.now() - start < 75000)
  console.log('安装器启动失败后，旧工作台恢复并持续观察 75 秒，准备重试缓存的正式包。')
  return retry
}

assert.equal(installed(), previous)
mkdirSync(configDir, {recursive:true})
mkdirSync(historyDir, {recursive:true})
writeFileSync(configFile, settings)
writeFileSync(historyFile, history)
if (recovery) mkdirSync(desktopTemp)
const oldDesktop = spawn(exe, [], {windowsHide:true, stdio:'ignore', env:{...process.env,
  ...(recovery ? {TEMP:desktopTemp, TMP:desktopTemp} : {}),
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
  const install = recovery ? await checkRecovery(page, old)
    : page.getByRole('region',{name:'工具更新'}).getByRole('button',{name:'立即安装'})
  await install.click()
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
  assert.equal(readFileSync(configFile,'utf8'), settings)
  assert.equal(readFileSync(historyFile,'utf8'), history)
  // AI:单实例提示与主窗口均以 MCU TOOL 开头，窗口检查要求只有一个可见工作台。
  const pid = execFileSync('powershell.exe',['-NoProfile','-Command',
    '(Get-Process -Name mcutool-desktop | Where-Object Path -eq $env:MCUTOOL_QA_EXE).Id'],
    {env:{...process.env,MCUTOOL_QA_EXE:exe},encoding:'utf8',windowsHide:true}).trim()
  assert.match(pid, /^\d+$/)
  const visible = execFileSync('pwsh',['-NoProfile','-File','tests/desktop/window.ps1',
    '-TargetProcessId',pid,'-ExpectedExe',exe,'-Action','visible'],{encoding:'utf8',windowsHide:true}).trim()
  assert.equal(visible,'true')
  assert.equal(next.connected, false)
  assert.equal(next.firmware_update.phase, 'idle')
  const current = runtime()
  const headers = {Authorization:'Bearer '+current.token, 'Content-Type':'application/json'}
  const attached = await fetch(current.url+'/api/sessions', {method:'POST', headers,
    body:JSON.stringify({name:'发布验收', kind:'web'})})
  assert.ok(attached.ok)
  headers['X-Session-Id'] = (await attached.json()).session_id
  try {
    const prepare = await fetch(current.url+'/api/firmware/prepare', {method:'POST', headers})
    assert.equal((await prepare.json()).error.code, 'NOT_CONNECTED')
    const html = await (await fetch(current.url)).text()
    const asset = html.match(/<script[^>]+type="module"[^>]+src="(\/assets\/[^"]+\.js)"/)
    assert.ok(asset, '安装器中的工作台资源缺失')
    const script = await (await fetch(current.url+asset[1])).text()
    assert.ok(script.includes('/api/firmware/install') && script.includes('确认升级'))
  } finally {
    await fetch(current.url+'/api/sessions/current', {method:'DELETE', headers})
  }
  console.log(`已验证正式桌面 ${previous} → ${expected}，桌面重启、同一数据目录回读成功，固件更新入口已加载。`)
} finally {
  if (browser) await browser.close()
  oldDesktop.unref()
}
