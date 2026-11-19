import { test, expect } from '@playwright/test'

test('USB 刷新仅预选，保留手选并在 COM 号变化后识别上次验证的设备', async ({page}) => {
  const bluetooth = {port:'COM3',description:'蓝牙',vid:null,pid:null,serial_number:null,esp_candidate:false}
  const tool = {port:'COM40',description:'USB Serial',vid:0x303a,pid:0x1001,serial_number:'BOARD-A',esp_candidate:true}
  const other = {...tool,port:'COM9',serial_number:'BOARD-B'}
  let list = [bluetooth, tool]
  let connectCalls = 0
  let accept = false
  await page.route('**/api/ports', route => route.fulfill({json:{ports:list}}))
  await page.route('**/api/connect', async route => {
    connectCalls++
    expect(route.request().postDataJSON()).toEqual({kind:'usb',port:'COM40'})
    if (!accept) return route.fulfill({status:409,json:{error:{message:'设备协议不匹配'}}})
    const status = await (await page.request.get('/api/runtime/status')).json()
    return route.fulfill({json:{...status,connected:true,device:{device_id:'TEST-A'}}})
  })
  await page.goto('/')
  const select = page.getByLabel('设备端口')
  const refresh = page.getByRole('button',{name:'刷新端口'})
  const connect = page.getByRole('button',{name:'连接工具',exact:true})
  await expect(select).toHaveValue('COM40')
  await expect(select.locator('option:checked')).toContainText('候选')
  await connect.click()
  await expect(page.getByRole('alert')).toContainText('设备协议不匹配')
  list = [bluetooth,tool,other]
  await refresh.click()
  await expect(select).toHaveValue('')
  await expect(connect).toBeDisabled()
  await select.selectOption('COM3')
  await refresh.click()
  await expect(select).toHaveValue('COM3')
  list = [tool]
  await refresh.click()
  await expect(select).toHaveValue('COM40')
  expect(connectCalls).toBe(1)
  accept = true
  await connect.click()
  await expect(select).toHaveCount(0)
  list = [{...tool,port:'COM72'},other,bluetooth]
  await page.reload()
  await expect(select).toHaveValue('COM72')
  list = [{...tool,port:'COM71'},{...tool,port:'COM72'}]
  await refresh.click()
  await expect(select).toHaveValue('')
  list = [bluetooth]
  await refresh.click()
  await expect(select).toHaveValue('')
  await select.selectOption('COM3')
  await expect(connect).toBeEnabled()
  expect(connectCalls).toBe(2)
})
