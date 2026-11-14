import { test, expect, type Page, type WebSocketRoute } from '@playwright/test'
import type { Sample } from '../src/api'

/** AI:构造明确标识的浏览器测量夹具，不访问真实设备。@param boot 当前启动标识。@param gap 是否注入电流缺口。@param end 最后采样秒数。@returns 状态及推送帧。 */
function fixture(boot='chart-boot',gap=false,end=120) {
  const samples:Sample[]=[]
  for(let tick=0;tick<=end*10;tick++) for(const [channel,value] of [['battery_v',3.9],['battery_i',.012],['ain1',3.3],['ain2',1.8],['ain3',5],['ain4',.003]] as const) {
    const t=tick/10
    const missing=gap&&channel==='battery_i'&&t===60
    samples.push({channel,value:missing?null:value,nominal:value,unit:channel==='battery_i'?'A':'V',quality:missing?'sensor_error':'uncalibrated',device_id:'CHART-TEST',boot_id:boot,cursor:samples.length+1,t_us:t*1e6})
  }
  const latest=Object.fromEntries(samples.slice(-6).map(row=>[row.channel,row]))
  const status={instance_id:'chart-runtime',connected:true,test_mode:true,device:{device_id:'CHART-TEST',boot_id:boot,measurement:{sample_rate_hz:10}},device_state:{power:'off',charge:false,keys_mask:0,uart:{}},device_state_stale:false,control:{owner:null,owner_active:false,revision:0,device_claimed:false},latest,jobs:[],clients:[],recording:{state:'idle',written_records:0},last_error:null}
  return {status,data:{measurements:{items:samples,lost:0},uart:{items:[],lost:0},events:{items:[],lost:0}}}
}

/** AI:隔离浏览器后台读取和推送，只提供显式测试样本。@param page 测试页面。@param gap 是否注入缺口。@returns 可发送后续启动数据的连接。 */
async function openChart(page:Page,gap=false) {
  const frame=fixture('chart-boot',gap)
  let socket:WebSocketRoute
  await page.route('**/api/sessions',route=>route.fulfill({json:{session_id:'chart-session',client_id:'chart-client'}}))
  await page.route('**/api/status',route=>route.fulfill({json:frame.status}))
  await page.route('**/api/ports',route=>route.fulfill({json:{ports:[]}}))
  await page.routeWebSocket('**/ws',ws=>{socket=ws;ws.onMessage(()=>ws.send(JSON.stringify(frame)))})
  await page.goto('/')
  await expect(page.locator('[data-mode="battery"] .reading-number').first()).toContainText('3.900')
  return {send:(boot:string,end=120)=>socket.send(JSON.stringify(fixture(boot,false,end))), sendFrame:(next:ReturnType<typeof fixture>)=>socket.send(JSON.stringify(next))}
}

for (const mode of ['battery','aux']) test(`${mode}滚轮缩放后新数据继续进入可见窗口`,async({page})=>{
  const stream=await openChart(page)
  if(mode==='aux') await page.getByRole('button',{name:'四路电压',exact:true}).click()
  const panel=page.locator(`[data-mode="${mode}"]`),chart=panel.locator('svg.measurement-chart')
  await chart.evaluate(el=>{const r=el.getBoundingClientRect(),hit=el.querySelector('[data-drag="time"]')!;el.dispatchEvent(new WheelEvent('wheel',{bubbles:true,cancelable:true,clientX:r.left+r.width/2,clientY:r.top+Number(hit.getAttribute('y'))+40,deltaY:-400}))})
  const low=Number(await chart.getAttribute('data-window-start')),high=Number(await chart.getAttribute('data-window-end'))
  stream.send('chart-boot',121)
  await expect(panel.locator('.waveform-state')).toContainText('0:02:01')
  await expect(chart).toHaveAttribute('data-window-end','121')
  expect(Number(await chart.getAttribute('data-window-end'))-Number(await chart.getAttribute('data-window-start'))).toBeCloseTo(high-low,5)
})

test('回看历史后可保留缩放回到实时，暂停后开始也恢复跟随',async({page})=>{
  const stream=await openChart(page),panel=page.locator('[data-mode="battery"]'),chart=panel.locator('svg.measurement-chart')
  await chart.evaluate(el=>{const r=el.getBoundingClientRect(),hit=el.querySelector('[data-drag="time"]')!;el.dispatchEvent(new WheelEvent('wheel',{bubbles:true,cancelable:true,clientX:r.left+r.width/2,clientY:r.top+Number(hit.getAttribute('y'))+40,deltaY:-600}))})
  const initialSpan=Number(await chart.getAttribute('data-window-end'))-Number(await chart.getAttribute('data-window-start'))
  const hit=await chart.locator('[data-drag="time"]').boundingBox();expect(hit).not.toBeNull()
  await page.mouse.move(hit!.x+hit!.width*.5,hit!.y+40);await page.mouse.down();await page.mouse.move(hit!.x+hit!.width*.7,hit!.y+40);await page.mouse.up()
  await expect(panel.getByRole('button',{name:'回到实时',exact:true})).toBeVisible()
  const historyEnd=await chart.getAttribute('data-window-end')
  stream.send('chart-boot',121)
  await expect(panel.locator('.waveform-state')).toContainText('0:02:01')
  await expect(chart).toHaveAttribute('data-window-end',historyEnd!)
  await panel.getByRole('button',{name:'回到实时',exact:true}).click()
  await expect(chart).toHaveAttribute('data-window-end','121')
  expect(121-Number(await chart.getAttribute('data-window-start'))).toBeCloseTo(initialSpan,5)
  await panel.getByRole('button',{name:'暂停显示'}).click();stream.send('chart-boot',122)
  await expect(chart).toHaveAttribute('data-window-end','121')
  await panel.getByRole('button',{name:'开始显示'}).click()
  await expect(chart).toHaveAttribute('data-window-end','122')
})

test('电池双轴、游标开关、完整区间统计及缩放保留区间',async({page},testInfo)=>{
  await openChart(page)
  const panel=page.locator('[data-mode="battery"]'),chart=panel.locator('svg.measurement-chart')
  await expect(panel.locator('.analysis-content')).toHaveCount(0)
  await panel.getByRole('switch',{name:'时间游标与统计'}).click()
  await expect(panel.locator('[data-stat="charge"]')).toHaveText('0.200000')
  await expect(panel.locator('[data-drag="a"]')).toHaveCount(1)
  await panel.getByLabel('A游标时间').fill('40')
  await panel.getByLabel('A游标时间').press('Tab')
  await expect(panel.locator('[data-stat="charge"]')).toHaveText('0.166667')
  await chart.evaluate(el=>{const r=el.getBoundingClientRect(),hit=el.querySelector('[data-drag="time"]')!;el.dispatchEvent(new WheelEvent('wheel',{bubbles:true,cancelable:true,clientX:r.left+r.width/2,clientY:r.top+Number(hit.getAttribute('y'))+50,deltaY:-400}))})
  await expect(chart).not.toHaveAttribute('data-window-start','0')
  await expect(panel.locator('[data-stat="charge"]')).toHaveText('0.166667')
  await panel.getByRole('switch',{name:'时间游标与统计'}).click()
  await expect(panel.locator('.analysis-content')).toHaveCount(0)
  await expect(panel.locator('[data-drag="a"]')).toHaveCount(0)
  await panel.getByRole('switch',{name:'时间游标与统计'}).click()
  await expect(panel.getByLabel('A游标时间')).toHaveValue('40.000')
  const labelsClear=await chart.evaluate(el=>{const labels=[...el.querySelectorAll<SVGTextElement>('.axis-title')].map(node=>node.getBBox());const handles=[...el.querySelectorAll<SVGGElement>('.cursor-hit')].map(node=>node.querySelectorAll('rect')[1].getBBox());return labels.every(label=>handles.every(handle=>label.y+label.height+4<=handle.y))})
  expect(labelsClear).toBe(true)
  await page.screenshot({path:testInfo.outputPath('电池游标统计-正式界面.png'),fullPage:true})
  await expect(panel.locator('details,.chart-help,.waveform-hint')).toHaveCount(0)
  const summary=await panel.locator('.analysis-grid').evaluate(el=>[...el.children].map(node=>node.getBoundingClientRect().width))
  expect(Math.max(...summary)).toBeLessThanOrEqual(321)
  await page.getByRole('button',{name:'操作记录',exact:true}).click()
  await expect(page.getByRole('heading',{name:'操作记录',exact:true})).toBeVisible()
})

test('缺口不产生伪电量，换启动不沿用旧游标或暂停历史',async({page})=>{
  const stream=await openChart(page,true),panel=page.locator('[data-mode="battery"]')
  await panel.getByRole('switch',{name:'时间游标与统计'}).click()
  await expect(panel.locator('[data-stat="charge"]')).toHaveText('—')
  await expect(panel.locator('.analysis-warning')).toBeVisible()
  await panel.getByRole('button',{name:'暂停显示'}).click()
  stream.send('next-boot')
  await expect(panel.getByRole('button',{name:'暂停显示'})).toBeVisible()
  await expect(panel.locator('[data-stat="charge"]')).toHaveText('0.200000')
})

test('四路单选刻度、实虚线、独立比例颜色及显隐不影响读数',async({page},testInfo)=>{
  const errors:string[]=[];page.on('pageerror',error=>errors.push(error.message))
  await openChart(page)
  await page.getByRole('button',{name:'四路电压',exact:true}).click()
  const panel=page.locator('[data-mode="aux"]'),chart=panel.locator('.measurement-chart')
  await expect(panel.locator('input[type="checkbox"]')).toHaveCount(0)
  const middle=await chart.evaluate(el=>{const rect=el.querySelector('clipPath rect')!,zero=el.querySelector('.zero-line')!;return Number(zero.getAttribute('y1'))===Number(rect.getAttribute('y'))+Number(rect.getAttribute('height'))/2})
  expect(middle).toBe(true)
  await panel.getByRole('button',{name:'AIN2，选择Y轴刻度',exact:true}).click()
  await expect(panel.locator('.channel-select[aria-pressed="true"]')).toHaveCount(1)
  await expect(panel.locator('.axis-status')).toContainText('AIN2')
  await expect(panel.locator('path[data-channel="ain2"]')).not.toHaveAttribute('stroke-dasharray')
  await expect(panel.locator('path[data-channel="ain1"]')).toHaveAttribute('stroke-dasharray','6 4')
  const before=await panel.locator('path[data-channel="ain1"]').getAttribute('d')
  await panel.getByLabel('AIN2每格电压',{exact:true}).fill('0.25');await panel.getByLabel('AIN2每格电压',{exact:true}).press('Tab')
  expect(await panel.locator('path[data-channel="ain1"]').getAttribute('d')).toBe(before)
  await panel.getByLabel('AIN2曲线颜色',{exact:true}).fill('#dd3355')
  await expect(panel.locator('path[data-channel="ain2"]')).toHaveAttribute('stroke','#dd3355')
  await panel.getByRole('button',{name:'AIN2曲线显示开关',exact:true}).click()
  await expect(panel.locator('path[data-channel="ain2"]')).toBeHidden()
  await expect(panel.locator('.reading-number').nth(1)).toContainText('1.800')
  await panel.getByRole('button',{name:'AIN2，选择Y轴刻度',exact:true}).click()
  await expect(panel.locator('path[data-channel="ain2"]')).toBeHidden()
  await panel.getByRole('button',{name:'AIN2曲线显示开关',exact:true}).click()
  await panel.getByRole('button',{name:'恢复视图',exact:true}).click()
  const spacing=await panel.getByLabel('AIN1每格电压',{exact:true}).evaluate(el=>el.getBoundingClientRect().left-el.parentElement!.getBoundingClientRect().left)
  expect(spacing).toBeLessThanOrEqual(42)
  await expect(panel.locator('.channel-instructions,.chart-help,.waveform-hint')).toHaveCount(0)
  await page.screenshot({path:testInfo.outputPath('四路电压-正式界面.png'),fullPage:true})
  await page.setViewportSize({width:390,height:844})
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true)
  await page.screenshot({path:testInfo.outputPath('四路电压-窄屏.png'),fullPage:true})
  expect(errors).toEqual([])
})

test('历史超过原有短缓存后仍保留游标统计',async({page})=>{
  const stream=await openChart(page),panel=page.locator('[data-mode="battery"]')
  await panel.getByRole('switch',{name:'时间游标与统计'}).click()
  stream.send('chart-boot',240)
  await expect(panel.getByLabel('A游标时间')).toHaveValue('30.000')
  await expect(panel.locator('[data-stat="charge"]')).toHaveText('0.200000')
  await expect(panel.locator('.waveform-state')).toContainText('0:04:00')
})

test('两组暂停、清空和导出独立，隐藏通道仍导出',async({page},testInfo)=>{
  const stream=await openChart(page),battery=page.locator('[data-mode="battery"]'),aux=page.locator('[data-mode="aux"]')
  await battery.getByRole('button',{name:'暂停显示'}).click()
  const count=await battery.locator('.waveform-state').getAttribute('data-count')
  stream.send('chart-boot',130)
  await expect(battery.locator('.waveform-state')).toHaveAttribute('data-count',count!)
  await expect(aux.locator('.waveform-state')).toHaveAttribute('data-count','5204')
  const downloadPromise=page.waitForEvent('download')
  await battery.getByRole('button',{name:'导出',exact:true}).click()
  const download=await downloadPromise
  const file=testInfo.outputPath('电池波形.csv');await download.saveAs(file)
  const {readFile}=await import('node:fs/promises'),csv=await readFile(file,'utf8')
  expect(csv.startsWith('设备,启动')).toBe(true)
  expect(csv.trim().split('\n')).toHaveLength(2403)
  expect(csv).toContain('"battery_i","0.012","A"')
  expect(csv).not.toContain('"ain1"')
  await battery.getByRole('button',{name:'清空',exact:true}).click()
  await expect(battery.locator('.waveform-state')).toHaveAttribute('data-count','0')
  await expect(battery.getByRole('button',{name:'导出',exact:true})).toBeDisabled()
  await battery.getByRole('button',{name:'开始显示'}).click()
  stream.send('chart-boot',131)
  await expect(battery.locator('.waveform-state')).toHaveAttribute('data-count','20')
  await expect(battery.locator('svg.measurement-chart')).toHaveAttribute('data-window-start','130.1')
  await page.getByRole('button',{name:'四路电压',exact:true}).click()
  await aux.getByRole('button',{name:'AIN2曲线显示开关',exact:true}).click()
  const auxDownload=page.waitForEvent('download')
  await aux.getByRole('button',{name:'导出',exact:true}).click()
  const auxFile=testInfo.outputPath('四路电压波形.csv');await (await auxDownload).saveAs(auxFile)
  const auxCsv=await readFile(auxFile,'utf8')
  expect(auxCsv).toContain('"ain2","1.8","V"');expect(auxCsv).not.toContain('battery_')
  await aux.getByRole('button',{name:'清空',exact:true}).click()
  await expect(aux.locator('.waveform-state')).toHaveAttribute('data-count','0')
  await expect(battery.locator('.waveform-state')).toHaveAttribute('data-count','20')
})

test('三小时以上的10Hz波形可交互并从原始采样计算电量',async({page},testInfo)=>{
  test.setTimeout(120000)
  const errors:string[]=[];page.on('pageerror',error=>errors.push(error.message))
  const stream=await openChart(page),frame=fixture('long-boot',false,0)
  const panel=page.locator('[data-mode="battery"]')
  // AI:批量注入3小时15分钟的真实格式数据，验证容量与交互，不冒充实板长时间运行。
  for(let part=0;part<13;part++) {
    const items:Sample[]=[]
    for(let tick=part*9000;tick<=(part+1)*9000;tick++) for(const [channel,value] of [['battery_v',3.9],['battery_i',.012]] as const) {
      items.push({channel,value,nominal:value,unit:channel==='battery_i'?'A':'V',quality:'uncalibrated',device_id:'CHART-TEST',boot_id:'long-boot',cursor:tick*2+(channel==='battery_v'?1:2),t_us:tick*100000})
    }
    frame.data.measurements.items=items
    frame.status.latest=Object.fromEntries(items.slice(-2).map(row=>[row.channel,row]))
    stream.sendFrame(frame)
    await expect(panel.locator('.waveform-state')).toHaveAttribute('data-count',String(((part+1)*9000+1)*2))
  }
  await expect(panel.locator('.waveform-state')).toContainText('3:15:00')
  await panel.getByRole('button',{name:'暂停显示'}).click()
  await panel.getByRole('switch',{name:'时间游标与统计'}).click()
  await panel.getByLabel('A游标时间').fill('0');await panel.getByLabel('A游标时间').press('Tab')
  await panel.getByLabel('B游标时间').fill('11700');await panel.getByLabel('B游标时间').press('Tab')
  await expect(panel.locator('[data-stat="charge"]')).toHaveText('39.000000')
  const size=await panel.locator('path[data-channel="battery_i"]').getAttribute('d')
  expect(size!.length).toBeLessThan(100000)
  await page.screenshot({path:testInfo.outputPath('三小时十五分钟波形.png'),fullPage:true})
  expect(errors).toEqual([])
})
