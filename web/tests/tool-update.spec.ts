import { test, expect } from '@playwright/test'

test('工具更新展示进度，稍后保留包，用户点击安装才交接', async ({page}) => {
  await page.addInitScript(() => {
    const qa = window as any
    qa.updateState = {phase:'downloading',version:'9.0.0',received:250,total:1000}
    qa.installs = []
    qa.__TAURI__ = {core:{invoke: async (name:string, args?:{version:string})=>{
      if (name==='desktop_update_status') return qa.updateState
      if (name==='desktop_install_update') { qa.installs.push(args?.version); return }
      if (name==='desktop_context') {
        const token = document.querySelector<HTMLMetaElement>('meta[name="mcutool-token"]')!.content
        const session = await fetch('/api/sessions',{method:'POST',headers:{Authorization:'Bearer '+token,'Content-Type':'application/json'},body:JSON.stringify({kind:'web',name:'更新界面验收'})})
        return session.json()
      }
      throw new Error('未预期的桌面调用 '+name)
    }}}
  })
  await page.goto('/')
  const panel = page.getByRole('region',{name:'工具更新'})
  await expect(panel).toContainText('25%')
  await expect(panel.getByRole('button',{name:'立即安装'})).toHaveCount(0)
  await page.evaluate(()=>{ (window as any).updateState={phase:'ready',version:'9.0.0'} })
  await panel.getByRole('button',{name:'稍后'}).click()
  await expect(panel.getByRole('button',{name:'立即安装'})).toHaveCount(0)
  await panel.getByRole('button',{name:'查看已下载更新'}).click()
  expect(await page.evaluate(()=>(window as any).installs)).toEqual([])
  await panel.getByRole('button',{name:'立即安装'}).click()
  expect(await page.evaluate(()=>(window as any).installs)).toEqual(['9.0.0'])
  await page.evaluate(()=>{ (window as any).updateState={phase:'failed',message:'无法联网',cached_version:'9.0.0'} })
  await expect(panel.getByRole('button',{name:'安装已下载的 9.0.0'})).toBeVisible()
})
