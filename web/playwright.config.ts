import { defineConfig } from '@playwright/test'
import { resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = fileURLToPath(new URL('..', import.meta.url))
process.env.MCUTOOL_E2E_DIR ??= resolve(root, 'docs/temp', `browser-${Date.now()}`)
const dataDir = resolve(process.env.MCUTOOL_E2E_DIR, 'runtime')
const python = resolve(root, '.venv/Scripts/python.exe')

export default defineConfig({
  testDir: './tests', fullyParallel: false, workers: 1, timeout: 45000,
  outputDir: resolve(process.env.MCUTOOL_E2E_DIR, 'results'),
  reporter: [['list']],
  use: {baseURL:'http://127.0.0.1:28766', viewport:{width:1440,height:1080}, trace:'retain-on-failure', screenshot:'only-on-failure', channel:'msedge'},
  webServer: [
    {command:`"${python}" -m uvicorn tests.device_server:app --host 127.0.0.1 --port 28767 --log-level warning`, cwd:root, url:'http://127.0.0.1:28767/docs', reuseExistingServer:false, timeout:20000},
    {command:`"${python}" -m mcutool.cli serve --data-dir "${dataDir}" --port 28766 --test-mode`, cwd:root, url:'http://127.0.0.1:28766', reuseExistingServer:false, timeout:20000}
  ]
})
