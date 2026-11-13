import { test, expect, type Page, type WebSocketRoute } from '@playwright/test'
import type { Sample } from '../src/api'

/** AI:构造明确标识的浏览器测量夹具，不访问真实设备。@param boot 当前启动标识。@param gap 是否注入电流缺口。@param end 最后采样秒数。@returns 状态及推送帧。 */
function fixture(boot='chart-boot',gap=false,end=120) {
  const samples:Sample[]=[]
  for(let t=0;t<=end;t++) for(const [channel,value] of [['battery_v',3.9],['battery_i',.012],['ain1',3.3],['ain2',1.8],['ain3',5],['ain4',.003]] as const) {
    const missing=gap&&channel==='battery_i'&&t===60
    samples.push({channel,value:missing?null:value,nominal:value,unit:channel==='battery_i'?'A':'V',quality:missing?'sensor_error':'uncalibrated',device_id:'CHART-TEST',boot_id:boot,cursor:samples.length+1,t_us:t*1e6})
  }
  const latest=Object.fromEntries(samples.slice(-6).map(row=>[row.channel,row]))
  const status={instance_id:'chart-runtime',connected:true,test_mode:true,device:{device_id:'CHART-TEST',boot_id:boot},device_state:{power:'off',charge:false,keys_mask:0,uart:{}},device_state_stale:false,control:{owner:null,owner_active:false,revision:0,device_claimed:false},latest,jobs:[],clients:[],recording:{state:'idle',written_records:0},last_error:null}
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
  return {send:(boot:string,end=120)=>socket.send(JSON.stringify(fixture(boot,false,end)))}
}

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
  await page.screenshot({path:testInfo.outputPath('四路电压-正式界面.png'),fullPage:true})
  await page.setViewportSize({width:390,height:844})
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true)
  await page.screenshot({path:testInfo.outputPath('四路电压-窄屏.png'),fullPage:true})
  expect(errors).toEqual([])
})

test('缓存滚动后旧选区不被静默改写，用户可以明确重选当前历史',async({page})=>{
  const stream=await openChart(page),panel=page.locator('[data-mode="battery"]')
  await panel.getByRole('switch',{name:'时间游标与统计'}).click()
  stream.send('chart-boot',240)
  await expect(panel.getByLabel('A游标时间')).toHaveValue('30.000')
  await expect(panel.locator('[data-stat="charge"]')).toHaveText('—')
  await panel.getByRole('button',{name:'重选当前历史'}).click()
  await expect(panel.locator('[data-stat="charge"]')).toHaveText('0.331667')
})
