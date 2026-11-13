import assert from 'node:assert/strict'
import { spawn, execFileSync } from 'node:child_process'
import { createServer } from 'node:net'
import { mkdirSync, openSync, readFileSync, writeFileSync, existsSync } from 'node:fs'
import { resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium } from '../../web/node_modules/playwright/index.mjs'

const root = fileURLToPath(new URL('../..', import.meta.url))
const desktopExe = process.env.MCUTOOL_TEST_DESKTOP
const serviceExe = process.env.MCUTOOL_TEST_SERVICE
const pwsh = process.env.MCUTOOL_TEST_PWSH
assert(desktopExe && serviceExe && pwsh, '显式指定桌面程序、后台程序和PowerShell 7')
const runRoot = resolve(root, 'docs/temp', `desktop-ui-${Date.now()}`)
const dataDir = resolve(runRoot, 'runtime')
mkdirSync(runRoot, {recursive:true})
const python = resolve(root, '.venv/Scripts/python.exe')
const children = []
let browser, page, app, observer
const report = {status:'running', runRoot, desktopExe, checks:[]}

/** AI:分配互不重复的本机测试端口。@returns 三个暂未使用的端口。 */
async function ports() {
  const listeners = []
  for (let i=0;i<3;i++) {
    const server=createServer(); await new Promise(ok=>server.listen(0,'127.0.0.1',ok)); listeners.push(server)
  }
  const values=listeners.map(server=>server.address().port)
  await Promise.all(listeners.map(server=>new Promise(ok=>server.close(ok))))
  return values
}
const [fixturePort, runtimePort, debugPort] = await ports()
const endpoint=`http://127.0.0.1:${runtimePort}`
const appArgs=['--data-dir',dataDir,'--port',String(runtimePort),'--test-mode','--hidden']

/** AI:启动本测试自己的进程并记录其输出。@param name 日志名；exe 程序；args 参数；extra 附加启动选项。@returns 进程句柄。 */
function launch(name,exe,args,extra={}) {
  const log=openSync(resolve(runRoot,`${name}.log`),'a')
  const child=spawn(exe,args,{cwd:root,windowsHide:true,stdio:['ignore',log,log],...extra})
  children.push(child); return child
}

/** AI:有上限等待外部条件，失败保留具体检查名称。@param label 检查名；work 单次检查；timeout 上限。@returns 成功值。 */
async function until(label,work,timeout=45000) {
  const end=Date.now()+timeout
  while (Date.now()<end) {
    const value=await work()
    if (value) return value
    await new Promise(ok=>setTimeout(ok,100))
  }
  throw new Error(`超时：${label}`)
}

/** AI:查询当前测试后台，不创建观察会话。@returns 后台公开状态。 */
async function status() {
  const info=JSON.parse(readFileSync(resolve(dataDir,'runtime.json'),'utf8'))
  const response=await fetch(endpoint+'/api/runtime/status',{headers:{Authorization:'Bearer '+info.token}})
  assert.equal(response.status,200)
  return response.json()
}

/** AI:只针对当前测试桌面进程执行Windows窗口验证。@param action 操作；output 可选输出文件。@returns 验证输出。 */
function windowAction(action,output) {
  return execFileSync(pwsh,['-NoProfile','-ExecutionPolicy','Bypass','-File',resolve(root,'tests/desktop/window.ps1'),
    '-TargetProcessId',String(app.pid),'-ExpectedExe',desktopExe,'-Action',action,...(output?['-OutputPath',output]:[])],{encoding:'utf8',windowsHide:true,timeout:20000}).trim()
}

/** AI:启动独立桌面进程并连接其专用WebView2调试端口。@returns 已显示工作台的页面。 */
async function openDesktop() {
  // AI:产品进程不借用开发环境；Python和Node仅由外部测试驱动使用。
  const desktopEnv={...process.env,PATH:resolve(process.env.SystemRoot,'System32')+';'+process.env.SystemRoot,
    WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS:`--remote-debugging-address=127.0.0.1 --remote-debugging-port=${debugPort}`}
  delete desktopEnv.PYTHONPATH; delete desktopEnv.PYTHONHOME
  app=launch('desktop',desktopExe,appArgs,{env:desktopEnv})
  await until('WebView2调试端口',async()=>{try{return (await fetch(`http://127.0.0.1:${debugPort}/json/version`)).ok}catch{return false}})
  browser=await chromium.connectOverCDP(`http://127.0.0.1:${debugPort}`)
  page=await until('工作台页面',async()=>browser.contexts().flatMap(c=>c.pages())[0])
  await page.waitForURL(endpoint+'/',{timeout:45000})
  await page.getByText('测试环境 · 当前数据来自显式测试设备，不代表实物测量。',{exact:true}).waitFor()
  await until('桌面会话',async()=>(await status()).clients.some(c=>c.kind==='desktop'&&c.active))
}

/** AI:确认退出而不把网页关闭异常当成成功证据。@param command 明确退出命令。@returns 进程实际退出。 */
async function exitApp(command) {
  await page.evaluate(command=>window.__TAURI__.core.invoke(command),command).catch(()=>{})
  await until('桌面进程退出',async()=>app.exitCode!==null,15000)
  await browser.close().catch(()=>{})
}

try {
  launch('fixture',python,['-m','uvicorn','tests.device_server:app','--host','127.0.0.1','--port',String(fixturePort),'--log-level','warning'])
  await until('测试设备',async()=>{try{return (await fetch(`http://127.0.0.1:${fixturePort}/docs`)).ok}catch{return false}})
  launch('runtime',serviceExe,['serve','--data-dir',dataDir,'--port',String(runtimePort),'--test-mode'])
  await until('测试后台',async()=>{try{return (await fetch(endpoint)).ok}catch{return false}})
  await openDesktop()
  await page.getByRole('button',{name:'Wi-Fi',exact:true}).click()
  await page.getByLabel('设备地址',{exact:true}).fill(`http://127.0.0.1:${fixturePort}`)
  await page.getByLabel('访问令牌',{exact:true}).fill('fixture')
  await page.getByRole('button',{name:'连接工具',exact:true}).click()
  await page.getByRole('button',{name:'申请操作权',exact:true}).click()
  await page.getByRole('button',{name:'真实电池',exact:true}).click()
  await page.getByRole('button',{name:'串口与记录',exact:true}).click()
  await page.getByRole('button',{name:'开始记录',exact:true}).click()
  await until('记录开始',async()=>(await status()).recording.state==='recording')
  const before=await status()
  assert.equal(before.control.owner.kind,'desktop')
  const blocked=await page.evaluate(async()=>{try{await window.__TAURI__.core.invoke('desktop_stop');return ''}catch(e){return String(e)}})
  assert.match(blocked,/记录/)
  report.checks.push('记录进行中拒绝停止后台')
  const cdp=await page.context().newCDPSession(page)
  windowAction('close')
  assert.equal(windowAction('visible'),'false')
  await cdp.send('Emulation.setScriptExecutionDisabled',{value:true})
  for (let i=0;i<5;i++) {
    await new Promise(ok=>setTimeout(ok,14000))
    const current=await status()
    assert.equal(current.recording.state,'recording')
    assert.equal(current.control.owner.id,before.control.owner.id)
    assert.equal(current.control.owner_active,true)
    assert(current.recording.written_records>before.recording.written_records)
    console.log(`隐藏与暂停页面脚本检查 ${i+1}/5：原生续约和记录正常`)
  }
  report.checks.push('关闭隐藏70秒且页面脚本暂停，操作权和磁盘记录保持')
  await cdp.send('Emulation.setScriptExecutionDisabled',{value:false})
  const second=launch('second-instance',desktopExe,appArgs)
  await until('重复启动退出第二进程',async()=>second.exitCode!==null,12000)
  assert.equal(windowAction('visible'),'true')
  assert.equal((await status()).instance_id,before.instance_id)
  report.checks.push('重复启动复用同一桌面窗口和后台')
  await page.reload()
  await until('重载后仍为原桌面会话',async()=>(await status()).control.owner_active)
  assert.equal((await status()).clients.filter(c=>c.kind==='desktop'&&c.active).length,1)
  report.checks.push('页面刷新复用原桌面会话')
  const observerLog=openSync(resolve(runRoot,'mcp-observer.log'),'a')
  observer=launch('observer',python,[resolve(root,'tests/desktop/mcp_observer.py'),serviceExe,dataDir],{stdio:['pipe','pipe',observerLog]})
  await new Promise((ok,bad)=>{observer.stdout.once('data',chunk=>{try{assert(JSON.parse(chunk.toString().trim()).ready);ok()}catch(e){bad(e)}});observer.once('exit',()=>bad(new Error('MCP观察者提前退出')))})
  await exitApp('desktop_exit')
  const continued=await status()
  assert(continued.connected && continued.recording.state==='recording')
  report.checks.push('退出桌面端后MCP与记录继续')
  await openDesktop()
  await page.getByRole('button',{name:'接管操作权',exact:true}).click()
  await page.getByRole('button',{name:'确认接管',exact:true}).click()
  await page.getByRole('button',{name:'串口与记录',exact:true}).click()
  await page.getByRole('button',{name:'停止并保存',exact:true}).click()
  await until('记录结束',async()=>(await status()).recording.state==='completed')
  await page.locator('.record-item').first().locator('summary').click()
  await page.getByRole('button',{name:'测量.jsonl',exact:true}).first().click()
  const measurement=resolve(runRoot,'测量.jsonl')
  windowAction('save',measurement)
  await until('原始记录保存',async()=>existsSync(measurement))
  assert(readFileSync(measurement,'utf8').trim().split('\n').length>0)
  JSON.parse(readFileSync(measurement,'utf8').trim().split('\n')[0])
  report.checks.push('原生保存对话框下载完整测量记录')
  const otherClient=await page.evaluate(async()=>{try{await window.__TAURI__.core.invoke('desktop_stop');return ''}catch(e){return String(e)}})
  assert.match(otherClient,/其他客户端/)
  report.checks.push('仍有MCP使用者时拒绝停止后台')
  await page.getByRole('button',{name:'设备设置',exact:true}).click()
  await page.getByText('后台与客户端',{exact:true}).click()
  await page.getByRole('button',{name:'导出诊断日志',exact:true}).click()
  const exported=resolve(runRoot,'desktop-diagnostics.zip')
  windowAction('save',exported)
  await until('原生对话框日志保存',async()=>existsSync(exported))
  execFileSync(python,['-c','import json,sys,zipfile; z=zipfile.ZipFile(sys.argv[1]); assert set(z.namelist()) <= {"诊断信息.json","runtime.log","desktop.log"}; assert json.loads(z.read("诊断信息.json"))["version"] == "0.3.0"',exported],{windowsHide:true})
  report.checks.push('原生保存对话框导出诊断日志')
  await page.getByRole('button',{name:'供电与测量',exact:true}).click()
  const visible=launch('show-final-window',desktopExe,appArgs)
  await until('显示最终工作台',async()=>visible.exitCode!==null && windowAction('visible')==='true',12000)
  await page.screenshot({path:resolve(runRoot,'desktop-page.png'),fullPage:true})
  observer.stdin.write('detach\n')
  await until('MCP明确退出',async()=>observer.exitCode!==null,15000)
  await exitApp('desktop_stop')
  await until('后台实际停止',async()=>{try{await fetch(endpoint);return false}catch{return true}},15000)
  report.checks.push('停止后台并退出完成')
  report.status='passed'
} catch(error) {
  report.status='failed'; report.error=String(error.stack??error)
  if(page) { await page.screenshot({path:resolve(runRoot,'failure.png'),fullPage:true}).catch(()=>{}) }
  throw error
} finally {
  writeFileSync(resolve(runRoot,'result.json'),JSON.stringify(report,null,2),'utf8')
  for(const child of children.reverse()) {
    if(child.exitCode===null) {
      try { execFileSync('taskkill.exe',['/PID',String(child.pid),'/T','/F'],{windowsHide:true,stdio:'ignore'}) } catch {}
    }
  }
  console.log(`桌面验证结果：${runRoot}`)
}
