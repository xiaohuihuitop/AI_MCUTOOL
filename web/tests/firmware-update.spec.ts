import { test, expect } from '@playwright/test'

test('固件预下载、稍后、目标确认和重连后的版本提示', async ({page}) => {
  const device = {device_id:'MCUTOOL-TEST', boot_id:'old', firmware_version:'0.1.3', hardware_revision:'test'}
  const target = {...device}
  const update = {phase:'ready', target, version:'0.1.4', new_boot_id:''}
  let checks = 0
  let clientId = ''
  const writes: unknown[] = []
  await page.route('**/api/sessions', async route => {
    const response = await route.fetch()
    clientId = (await response.json()).client_id
    await route.fulfill({response})
  })
  await page.route('**/api/firmware/prepare', route => { checks++; return route.fulfill({json:update}) })
  await page.route('**/api/firmware/install', route => {
    writes.push(route.request().postDataJSON())
    return route.fulfill({json:{...update, phase:'installing'}})
  })
  let send = () => {}
  await page.routeWebSocket('**/ws', ws => ws.onMessage(async () => {
    const snapshot = await page.evaluate(async () => (await fetch('/api/runtime/status', {
      headers:{Authorization:'Bearer '+document.querySelector<HTMLMetaElement>('meta[name=mcutool-token]')!.content},
    })).json())
    // AI:使用页面自身的操作会话标识驱动界面条件，测试过程均停留在模拟的推送和安装路由。
    const status = {...snapshot, test_mode:false, connected:true, device, device_state_stale:false, firmware_update:update,
      connection:{kind:'usb',port:'COM-TEST'}, control:{owner:{id:clientId},owner_active:true,device_claimed:true}}
    send = () => ws.send(JSON.stringify({status, data:{measurements:{items:[],lost:0},events:{items:[]},uart:{items:[]}}}))
    send()
  }))
  await page.goto('/')
  const panel = page.getByRole('region',{name:'固件更新'})
  await panel.getByRole('button',{name:'稍后'}).click()
  await panel.getByRole('button',{name:'查看已下载固件'}).click()
  await panel.getByRole('button',{name:'升级固件',exact:true}).click()
  await expect(panel).toContainText('MCUTOOL-TEST 将重启')
  expect(writes).toHaveLength(0)
  await panel.getByRole('button',{name:'确认升级'}).click()
  await expect.poll(()=>writes).toEqual([{device_id:'MCUTOOL-TEST',boot_id:'old',version:'0.1.4'}])
  device.boot_id = 'new'
  device.firmware_version = '0.1.4'
  Object.assign(update,{phase:'succeeded',new_boot_id:'new'})
  send()
  await expect(panel).toContainText('已重连 MCUTOOL-TEST，板上固件 0.1.4')
  expect(checks).toBe(1)
})
