<script setup lang="ts">
import { computed, onMounted, onBeforeUnmount, ref, shallowRef, watch } from 'vue'
import { Activity, Cable, Check, ChevronDown, CircleHelp, Download, Gauge, KeyRound, Link, LockKeyhole, Pause, Play, Power, Radio, RefreshCw, Settings2, Square, Terminal, Unplug, Wifi, X } from 'lucide-vue-next'
import Trend from './Trend.vue'
import { version as appVersion } from '../package.json'
import { api, download, exportDiagnostics, getSession, setSession, token, type Job, type Sample, type Snapshot } from './api'
import { desktopCommand, desktopSession, isDesktop } from './desktop'

const state = ref<Snapshot | null>(null), clientId = ref(''), socketLive = ref(false), starting = ref(false)
const tab = ref('供电与测量'), connectionOpen = ref(true), connectionKind = ref<'usb'|'http'>('usb')
type UsbPort = { port: string; description: string; vid: number | null; pid: number | null; serial_number: string | null; esp_candidate: boolean }
const ports = ref<UsbPort[]>([]), port = ref(''), address = ref(''), deviceToken = ref('')
let manualPort: UsbPort | undefined
const lastUsbKey = 'mcutool.lastVerifiedUsb'
const error = ref(''), notice = ref(''), pending = ref(''), lastRequest = ref('')
const selectedKeys = ref([1]), pressMs = ref(100), gapMs = ref(100), repeat = ref(1)
const samples = shallowRef<Sample[]>([])
const uartRows = ref<any[]>([]), events = ref<any[]>([]), serialMode = ref('text'), sendMode = ref('text'), sendText = ref(''), baud = ref(115200)
const records = ref<{id:string;files:string[]}[]>([]), takeoverOpen = ref(false), shutdownRequested = ref(false)
const settingsSsid = ref(''), settingsPassword = ref(''), networkInfo = ref<any>(null)
const calChannel = ref('battery_v'), calGain = ref(1), calOffset = ref(0), calMin = ref(0), calMax = ref(15), calReference = ref(''), calRecords = ref<any[]>([]), deadtime = ref(100)
let socket: WebSocket | null = null, heartbeat: ReturnType<typeof setInterval> | undefined
let measurementContext = ''
let measurementCursor = 0
const interruptedChannels = new Set<string>()

const connected = computed(() => Boolean(state.value?.connected && socketLive.value))
const ownsControl = computed(() => Boolean(state.value?.control.owner?.id === clientId.value && state.value?.control.owner_active))
const canWrite = computed(() => connected.value && ownsControl.value && state.value?.control.device_claimed && !state.value.device_state_stale)
const activeJobs = computed(() => (state.value?.jobs ?? []).filter(j => ['accepted','running'].includes(j.state)))
const board = computed(() => state.value?.device_state ?? {})
const keyJob = computed(() => activeJobs.value.find(j => j.method === 'keys.run'))
const powerBusy = computed(() => Boolean(board.value.charge_cycle_id) || activeJobs.value.some(j => ['power.select','charge.set','charge.run','timing.set'].includes(j.method)))
const uartBusy = computed(() => activeJobs.value.some(j => j.method.startsWith('uart.')))
const recording = computed(() => state.value?.recording.state === 'recording')
const canStopOrphanRecord = computed(() => recording.value && !ownsControl.value && !state.value?.control.owner_active && !activeJobs.value.length)
const channels = ['battery_v','battery_i','ain1','ain2','ain3','ain4']
const labels: Record<string,string> = {battery_v:'电池接口电压',battery_i:'电池端电流',ain1:'电压通道 1',ain2:'电压通道 2',ain3:'电压通道 3',ain4:'电压通道 4'}
const powerNames: Record<string,string> = {off:'关闭',battery:'真实电池',external:'外部电源'}
const qualityNames: Record<string,string> = {uncalibrated:'未校准',calibrated:'已应用校准',invalid_calibration:'校准无效',outside_calibrated_range:'超出校准范围',out_of_range:'超量程',sensor_error:'读取失败'}
const jobNames: Record<string,string> = {accepted:'已受理',running:'执行中',succeeded:'已完成',cancelled:'已取消',failed:'失败',unknown:'结果未知'}
const methodNames: Record<string,string> = {'power.select':'供电选择','charge.set':'充电通路','keys.run':'按键操作','action.cancel':'取消按键','uart.tx':'串口发送开关','uart.configure':'串口设置','uart.write':'串口发送','calibration.set':'保存校准','network.configure':'保存配网','network.connect':'连接Wi-Fi','timing.set':'切换间隔'}
const serialDisplay = computed(() => {
  if (serialMode.value === 'hex') return uartRows.value.map(row => row.data_hex.match(/.{1,2}/g)?.join(' ').toUpperCase() ?? '').join('\n')
  // AI:连续块一起解码，避免UTF-8字符跨块时显示成两个替换字符。
  const hex = uartRows.value.map(row=>row.data_hex).join('')
  const bytes = Uint8Array.from(hex.match(/.{1,2}/g) ?? [], (v:string)=>parseInt(v,16))
  return new TextDecoder().decode(bytes)
})

/** AI:统一展示操作失败且不重发。@param name 等待标识。@param work 单次操作。@returns 完成。 */
async function run(name: string, work: () => Promise<void>) {
  // AI:新操作拥有当前提示；旧任务继续在记录中更新，不能覆盖导出等新结果。
  error.value = ''; pending.value = name; lastRequest.value = ''
  try { await work() } catch (e) { error.value = e instanceof Error ? e.message : '操作未完成' }
  finally { pending.value = '' }
}
/** AI:登记本页面并打开只读推送。@returns 完成，不自动操作设备。 */
async function start() {
  starting.value = true; error.value = ''; socketLive.value = false
  if (heartbeat) clearInterval(heartbeat)
  socket?.close()
  try {
    const session = isDesktop ? await desktopSession() : await api('/api/sessions','POST',{name:`网页 ${new Date().toLocaleTimeString('zh-CN',{hour:'2-digit',minute:'2-digit'})}`,kind:'web'})
    setSession(session.session_id); clientId.value = session.client_id
    state.value = await api('/api/status')
    connectionOpen.value = !state.value?.connected
    await refreshPorts()
    socket = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws`)
    socket.onopen = () => socket?.send(JSON.stringify({token,session_id:getSession()}))
    socket.onmessage = message => {
      const frame = JSON.parse(message.data); state.value = frame.status; socketLive.value = true
      // AI:不同后台、设备或启动不能拼成同一曲线；页面重连的历史回放按游标去重。
      const context = `${frame.status.instance_id}/${frame.status.device.device_id}/${frame.status.device.boot_id}`
      if (measurementContext !== context) { samples.value = []; measurementCursor = 0; interruptedChannels.clear(); measurementContext = context }
      const lostMeasurements = frame.data.measurements.lost || frame.data.events.items.some((event: any) => event.name === 'device_data_gap' && event.stream === 'measurements')
      if (lostMeasurements) channels.forEach(channel => interruptedChannels.add(channel))
      const batch: Sample[] = []
      for (const sample of frame.data.measurements.items as Sample[]) {
        if (sample.device_id !== frame.status.device.device_id || sample.boot_id !== frame.status.device.boot_id || sample.cursor <= measurementCursor) continue
        batch.push({...sample, break_before: interruptedChannels.delete(sample.channel)})
        measurementCursor = sample.cursor
      }
      samples.value = batch
      uartRows.value = [...uartRows.value, ...frame.data.uart.items].slice(-300)
      events.value = [...events.value, ...frame.data.events.items].slice(-300)
      if (frame.data.uart.lost || frame.data.measurements.lost) notice.value = '页面显示缓存存在缺失，请检查原始记录。'
    }
    socket.onclose = () => { socketLive.value = false }
    socket.onerror = () => { error.value = '页面连接中断，请点击“重新连接页面”核对状态。' }
    // AI:桌面活性由原生进程维护，隐藏窗口或网页重载不能令操作持有者过期。
    if (!isDesktop) heartbeat = setInterval(() => { if (socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify({type:'heartbeat'})) },10000)
  } catch(e) { error.value = e instanceof Error ? e.message : '后台连接失败' }
  finally { starting.value = false }
}
/** AI:生成跨 COM 号稳定的 USB 标识。@param p 枚举出的端口。@returns 稳定标识，信息不足时为空。 */
function usbIdentity(p: UsbPort): string {
  return p.vid !== null && p.pid !== null && p.serial_number ? JSON.stringify([p.vid,p.pid,p.serial_number]) : ''
}
/** AI:只枚举端口，优先保留手选设备，其次匹配已验证身份或唯一候选。@returns 完成选择。 */
async function refreshPorts() {
  const list: UsbPort[] = (await api('/api/ports')).ports
  ports.value = list
  const chosen = manualPort
  if (chosen && list.some(p => p.port === chosen.port && p.vid === chosen.vid && p.pid === chosen.pid && p.serial_number === chosen.serial_number)) return
  manualPort = undefined
  const remembered = localStorage.getItem(lastUsbKey)
  const matches = remembered ? list.filter(p => usbIdentity(p) === remembered) : []
  const candidates = list.filter(p => p.esp_candidate)
  port.value = matches.length === 1 ? matches[0].port : candidates.length === 1 ? candidates[0].port : ''
}
/** AI:连接用户指定工具。@returns 完成。 */
async function connect() { await run('connect', async () => {
  const spec = connectionKind.value === 'usb' ? {kind:'usb',port:port.value} : {kind:'http',address:address.value,token:deviceToken.value}
  state.value = await api('/api/connect','POST',spec); connectionOpen.value = false; notice.value = '工具已连接，可先查看状态，再申请操作权。'
}) }
/** AI:显式申请或接管操作权。@param takeover 是否已确认接管。@returns 完成。 */
async function claim(takeover = false) { await run('claim', async () => {
  state.value = await api('/api/control/claim','POST',takeover ? {takeover:true,expected_revision:state.value!.control.revision,expected_device_revision:board.value.revision} : {})
  takeoverOpen.value = false; notice.value = '已取得操作权。'
}) }
/** AI:提交一次有编号的操作。@param method 公共方法。@param params 参数。@returns 完成提交，不代表动作完成。 */
async function command(method: string, params: Record<string,unknown>) { await run(method, async () => {
  const selected = spec.kind === 'usb' ? ports.value.find(p => p.port === spec.port) : undefined
  const requestId = crypto.randomUUID(); lastRequest.value = requestId
  if (selected && state.value?.connected && state.value.device.device_id) {
    const identity = usbIdentity(selected)
    if (identity) localStorage.setItem(lastUsbKey, identity)
    else localStorage.removeItem(lastUsbKey)
  }
  const job: Job = await api('/api/commands','POST',{request_id:requestId,method,params})
  notice.value = `${methodNames[method] ?? method}：${jobNames[job.state] ?? job.state}`
}) }
/** AI:切换选择的组合按键。@param key 1到5。@returns 无。 */
function selectKey(key: number) { selectedKeys.value = selectedKeys.value.includes(key) ? selectedKeys.value.filter(k=>k!==key) : [...selectedKeys.value,key] }
/** AI:将有限点击参数提交给板上计时。@param key 可选单击通道。@returns 完成提交。 */
async function press(key?: number) {
  const mask = key ? 1 << (key-1) : selectedKeys.value.reduce((m,k)=>m|(1<<(k-1)),0)
  if (!mask) { error.value = '至少选择一个按键'; return }
  await command('keys.run',{steps:[{mask,duration_ms:key ? 100 : pressMs.value},{mask:0,duration_ms:key ? 100 : gapMs.value}],repeat:key ? 1 : repeat.value})
}
/** AI:格式化测量，缺失不补零。@param channel 通道。@returns 显示字符串。 */
function valueText(channel: string) {
  const sample = state.value?.latest[channel]
  return sample?.value == null ? '—' : (sample.value * (channel==='battery_i' ? 1000 : 1)).toFixed(channel==='battery_i' ? 3 : 3)
}
/** AI:生成读数质量说明。@param channel 通道。@returns 中文质量。 */
function qualityText(channel: string) {
  const sample = state.value?.latest[channel]
  if (!sample) return '未读取'
  if (!socketLive.value || sample.stale) return '数据已过期'
  return qualityNames[sample.quality] ?? sample.quality
}
/** AI:发送显式文本或二进制字节。@returns 完成提交。 */
async function send() {
  const hex = sendMode.value === 'hex' ? sendText.value.replace(/\s/g,'') : Array.from(new TextEncoder().encode(sendText.value)).map(v=>v.toString(16).padStart(2,'0')).join('')
  await command('uart.write',{data_hex:hex})
}
/** AI:读取记录清单。@returns 完成。 */
async function refreshRecords() { records.value = (await api('/api/recordings')).recordings }
/** AI:按当前运行形态明确停止后台。@returns 请求完成，后台仍执行共享退出检查。 */
async function stopRuntime() {
  if (isDesktop) await desktopCommand('desktop_stop')
  else { await api('/api/runtime/shutdown','POST'); shutdownRequested.value = true }
}
/** AI:读取校准和网络配置的可公开状态。@returns 完成。 */
async function refreshSettings() { await run('settings', async()=> {
  calRecords.value = (await api('/api/read','POST',{method:'calibration.get',params:{}})).channels
  networkInfo.value = await api('/api/read','POST',{method:'network.status',params:{}})
  settingsSsid.value = networkInfo.value.ssid ?? ''; deadtime.value = board.value.power_deadtime_ms ?? 100
}) }

watch(() => state.value?.jobs, jobs => {
  const job = jobs?.find(j=>j.request_id===lastRequest.value)
  if (!job) return
  notice.value = `${methodNames[job.method] ?? job.method}：${jobNames[job.state] ?? job.state}`
  if (job.error) error.value = job.error.message
})
watch(tab, async value => { if (value==='串口与记录') await run('records',refreshRecords); if (value==='设备设置' && connected.value) await refreshSettings() })
watch(calChannel, value => { calMin.value = value==='battery_i' ? -3 : 0; calMax.value = value==='battery_i' ? 3 : 15 })
onMounted(start)
onBeforeUnmount(()=>{if(heartbeat)clearInterval(heartbeat);socket?.close()})
</script>

<template>
  <div class="workbench">
    <header class="masthead">
      <div class="brand-mark"><Activity :size="26"/><div><strong>MCU <span>TOOL</span></strong><small>设备工作台</small></div></div>
      <div class="header-meta"><span class="status-dot" :class="{online:connected}"></span><span>{{ connected ? '工具已连接' : '工具未连接' }}</span><span class="header-divider"></span><span class="mono">{{ state?.device.device_id || '尚未选择设备' }}</span></div>
      <button class="button light" @click="connectionOpen=!connectionOpen"><Cable :size="16"/>连接设置<ChevronDown :size="14"/></button>
    </header>
    <div v-if="state?.test_mode" class="test-banner">测试环境 · 当前数据来自显式测试设备，不代表实物测量。</div>
    <main>
      <section v-if="connectionOpen" class="panel connect-panel">
        <div class="panel-title"><div><h2>连接工具</h2><p>选择这次使用的连接方式和设备。</p></div><button class="icon-button" aria-label="收起连接设置" @click="connectionOpen=false"><X :size="18"/></button></div>
        <div class="connection-form"><div class="segmented"><button :class="{selected:connectionKind==='usb'}" @click="connectionKind='usb'"><Cable :size="16"/>USB</button><button :class="{selected:connectionKind==='http'}" @click="connectionKind='http'"><Wifi :size="16"/>Wi-Fi</button></div>
          <template v-if="connectionKind==='usb'"><label class="grow">设备端口<select v-model="port" aria-label="设备端口" :disabled="!!pending" @change="manualPort=ports.find(p=>p.port===port)">
            <option value="">请选择工具端口</option>
            <option v-for="p in ports" :key="p.port" :value="p.port">{{ p.port }} · {{ p.description }}{{ p.esp_candidate?' · ESP32 USB 候选':'' }}</option>
          </select></label><button class="button" :disabled="!!pending || starting" @click="run('ports',refreshPorts)"><RefreshCw :size="16"/>刷新端口</button></template>
          <template v-else><label class="grow">设备地址<input v-model.trim="address" placeholder="http://192.168.1.80" inputmode="url"/></label><label class="grow">访问令牌<input v-model="deviceToken" type="password" autocomplete="off" placeholder="从USB或配网页面取得"/></label></template>
          <button class="button primary" :disabled="!!pending || !!state?.connected || !socketLive || (connectionKind==='usb' && !port)" @click="connect">{{ pending==='connect'?'连接中…':'连接工具' }}</button>
        </div><p class="hint"><CircleHelp :size="14"/>USB 接电脑时不同时接 DC。Wi-Fi 访问令牌可通过 USB 的设备设置查看。</p>
      </section>

      <div v-if="!socketLive" class="alert warning" role="status"><Radio :size="18"/><span>{{ shutdownRequested?'已请求退出后台。需要使用时请重新运行“启动工具.cmd”；若仍在清理，请等待完成。':starting?'正在连接本机后台…':'页面连接已断开，显示的数据可能过期。' }}</span><button v-if="!shutdownRequested" class="text-button" :disabled="starting" @click="start">重新连接页面</button></div>
      <div v-if="error" class="alert error" role="alert"><span>{{ error }}</span><button class="icon-button" aria-label="关闭错误提示" @click="error=''"><X :size="16"/></button></div>
      <div v-if="notice" class="notice" role="status"><Check :size="15"/>{{ notice }}</div>

      <nav class="tabs" aria-label="功能页面"><div class="tab-links"><button v-for="item in [{name:'供电与测量',icon:Gauge},{name:'四路电压',icon:Activity},{name:'串口与记录',icon:Terminal},{name:'操作记录',icon:Check},{name:'设备设置',icon:Settings2}]" :key="item.name" :class="{active:tab===item.name}" @click="tab=item.name"><component :is="item.icon" :size="16"/>{{ item.name }}</button></div>
        <div class="operator-bar"><span class="owner-label"><LockKeyhole :size="14"/>{{ ownsControl ? '你持有操作权' : state?.control.owner ? `操作权：${state.control.owner.name}${state.control.owner_active?'':'（已失联）'}` : '当前仅观察' }}</span>
          <button v-if="!ownsControl" class="button compact-button" :disabled="!connected || !!pending" @click="state?.control.owner ? takeoverOpen=true : claim()">{{ state?.control.owner?'接管操作权':'申请操作权' }}</button>
          <button v-else class="button compact-button" :disabled="!!activeJobs.length || !!pending" @click="run('release',async()=>{state=await api('/api/control/release','POST')})">释放操作权</button>
        </div>
      </nav>

      <div v-show="tab==='供电与测量'" class="dashboard">
        <aside class="control-column">
          <section class="panel power-panel"><div class="panel-title"><h2><Power :size="18"/>供电与充电</h2><span class="badge" :class="{teal:board.power && board.power!=='off'}">{{ state?.connected ? powerNames[board.power] : '未读取' }}</span></div>
            <label class="field-label">主供电通路</label><div class="power-options"><button v-for="source in ['off','battery','external']" :key="source" :class="{selected:board.power===source && connected}" :disabled="!canWrite || powerBusy || (!!board.charge && source!=='battery')" @click="command('power.select',{source})"><span class="radio-indicator"></span>{{ powerNames[source] }}</button></div>
            <p v-if="board.power_switching" class="hint">正在先断后通，请等待切换结束。</p>
            <p class="hint amber" :style="{visibility:board.charge ? 'visible' : 'hidden'}">切换或关闭主供电前，请先关闭充电。</p>
            <div class="charge-row"><div><strong>充电器通路</strong><small>独立 5V 输入</small></div><button class="switch" role="switch" :aria-checked="!!board.charge" aria-label="充电器通路" :class="{on:board.charge}" :disabled="!canWrite || powerBusy || (!board.charge && board.power!=='battery')" @click="command('charge.set',{enabled:!board.charge})"><span></span></button></div>
            <p class="hint">仅真实电池通路允许充电。通路关闭后，设备电容仍可能有余电。</p>
            <div class="rating-line"><span>主通路目标 <b>2.8–12V / 3A</b></span><span>充电目标 <b>5V / 2A</b></span></div>
          </section>

          <section class="panel"><div class="panel-title"><h2><KeyRound :size="18"/>按键模拟</h2><span class="badge" :class="{teal:keyJob}">{{ keyJob?'执行中':'空闲' }}</span></div>
            <div class="key-bank"><div v-for="key in 5" :key="key" class="key-channel"><button class="key-cap" :class="{selected:selectedKeys.includes(key),pressed:(board.keys_mask & (1<<(key-1)))!==0}" :aria-pressed="selectedKeys.includes(key)" @click="selectKey(key)"><span class="pin-light"></span>K{{key}}</button><button class="text-button" :disabled="!canWrite || !!keyJob" @click="press(key)">单击</button></div></div>
            <p class="hint">选中多个按键可同时按下。</p><div class="three-fields"><label>按下 / ms<input v-model.number="pressMs" type="number" min="10" max="60000"/></label><label>释放 / ms<input v-model.number="gapMs" type="number" min="10" max="60000"/></label><label>次数<input v-model.number="repeat" type="number" min="1" max="1000"/></label></div>
            <div class="button-row"><button class="button primary grow" :disabled="!canWrite || !!keyJob || !!pending" @click="press()"><Play :size="15"/>执行按键</button><button class="button" :disabled="!canWrite || !keyJob?.action_id" @click="command('action.cancel',{action_id:keyJob!.action_id})"><Square :size="14"/>取消</button></div>
            <p class="hint">动作在工具上计时，结束或取消后释放按键。</p>
          </section>
        </aside>

        <div class="measurement-column">
          <Trend mode="battery" :samples="samples" :latest="state?.latest ?? {}" :device-id="state?.device.device_id ?? ''" :boot-id="state?.device.boot_id ?? ''" :runtime-id="state?.instance_id ?? ''" :sample-rate="state?.device.measurement?.sample_rate_hz" :live="connected">
            <template #status><div class="measurement-state"><Power :size="14"/><strong>{{connected ? powerNames[board.power] : '供电状态未读取'}}</strong><span>·</span><span>充电器通路{{connected ? board.charge?'接通':'关闭' : '未读取'}}</span></div></template>
          </Trend>
        </div>
      </div>

      <div v-show="tab==='四路电压'">
        <Trend mode="aux" :samples="samples" :latest="state?.latest ?? {}" :device-id="state?.device.device_id ?? ''" :boot-id="state?.device.boot_id ?? ''" :runtime-id="state?.instance_id ?? ''" :sample-rate="state?.device.measurement?.sample_rate_hz" :live="connected"/>
      </div>

      <div v-show="tab==='串口与记录'" class="serial-grid">
        <section class="panel serial-panel"><div class="panel-title"><h2><Terminal :size="18"/>目标串口</h2><span class="badge" :class="{amber:board.uart?.tx_enabled}">{{ board.uart?.tx_enabled?'发送已启用':'发送高阻' }}</span></div>
          <div class="serial-toolbar"><label>波特率<select v-model.number="baud"><option v-for="rate in [9600,19200,38400,57600,115200,230400,460800,921600]" :key="rate" :value="rate">{{rate}}</option></select></label><button class="button" :disabled="!canWrite || board.uart?.tx_enabled || uartBusy" @click="command('uart.configure',{baudrate:baud})">应用</button><span class="hint">当前 {{board.uart?.baudrate??'—'}} · 8N1</span><button class="button push-right" :disabled="!canWrite || uartBusy" @click="command('uart.tx',{enabled:!board.uart?.tx_enabled})">{{ board.uart?.tx_enabled?'禁用发送':'启用发送' }}</button></div>
          <div class="terminal-heading"><span>接收</span><div class="segmented compact"><button :class="{selected:serialMode==='text'}" @click="serialMode='text'">文本</button><button :class="{selected:serialMode==='hex'}" @click="serialMode='hex'">HEX</button></div><button class="text-button push-right" @click="uartRows=[]">清空显示</button></div>
          <pre class="terminal-output" aria-label="串口接收内容">{{ serialDisplay || '等待目标串口数据…' }}</pre>
          <div class="send-heading"><label>发送格式<select v-model="sendMode"><option value="text">UTF-8 文本</option><option value="hex">十六进制字节</option></select></label><span class="hint">最多 4096 字节，不自动添加换行</span></div><textarea v-model="sendText" aria-label="串口发送内容" rows="3" placeholder="输入发送内容"></textarea><div class="button-row"><span class="hint grow">被测设备掉电前，请先禁用发送。</span><button class="button primary" :disabled="!canWrite || !board.uart?.tx_enabled || uartBusy || !sendText" @click="send">发送</button></div>
        </section>
        <section class="panel record-panel"><div class="panel-title"><h2>持续记录</h2><span class="badge" :class="{teal:recording,amber:state?.recording.state==='failed'}">{{ recording?'记录中':state?.recording.state==='failed'?'记录失败':'未在记录' }}</span></div><p class="hint">保存原始测量、串口字节和操作事件。关闭网页后，已开启的记录继续运行。</p><div class="record-count"><strong>{{ state?.recording.written_records??0 }}</strong><span>条已写记录</span></div><button class="button primary full" :disabled="!ownsControl || !!pending || (!recording && !connected)" @click="run('record',async()=>{await api(`/api/recording/${recording?'stop':'start'}`,'POST');await refreshRecords()})"><Square v-if="recording" :size="15"/><span v-else class="record-dot"></span>{{recording?'停止并保存':'开始记录'}}</button><p v-if="state?.recording.error" class="inline-error">{{state.recording.error}}</p><p v-if="state?.recording.path" class="path-text">{{state.recording.path}}</p>
          <button v-if="canStopOrphanRecord" class="button full" @click="run('record-stop',async()=>{await api('/api/recording/stop','POST',{takeover:true,expected_revision:state!.control.revision});await refreshRecords()})">确认停止无人记录</button><p v-if="canStopOrphanRecord" class="hint">原操作者已离线。此操作只结束本机记录，不接管设备操作权。</p>
          <div class="record-list-heading"><h3>已有记录</h3><button class="icon-button" aria-label="刷新记录" @click="run('records',refreshRecords)"><RefreshCw :size="15"/></button></div><p v-if="!records.length" class="hint">开始记录后，文件会出现在这里。</p><details v-for="record in records" :key="record.id" class="record-item"><summary>{{record.id}}</summary><button v-for="file in record.files" :key="file" class="download-row" @click="run('download',()=>download(record.id,file))"><Download :size="14"/>{{file}}</button></details>
        </section>
      </div>

      <div v-show="tab==='设备设置'" class="settings-grid">
        <section class="panel"><div class="panel-title"><h2>Wi-Fi 配置</h2><button class="icon-button" aria-label="刷新设备设置" :disabled="!connected" @click="refreshSettings"><RefreshCw :size="16"/></button></div><label>Wi-Fi 名称<input v-model="settingsSsid" maxlength="32"/></label><label>Wi-Fi 密码<input v-model="settingsPassword" type="password" autocomplete="new-password"/></label><div class="button-row"><button class="button primary" :disabled="!canWrite || !!pending" @click="command('network.configure',{ssid:settingsSsid,password:settingsPassword})">保存并连接</button><button class="button" :disabled="!canWrite || !!pending" @click="command('network.connect',{})">连接已保存网络</button></div><p class="hint">长按板上 CONFIG 3 秒可进入配网。网络中断不会改变供电状态。</p><div v-if="networkInfo" class="definition-list"><span>当前 IP</span><b class="mono">{{networkInfo.ip||'未取得'}}</b><span>热点</span><b>{{networkInfo.provisioning?'已开启':'关闭'}}</b></div><details v-if="networkInfo?.api_token" class="token-details"><summary>查看 Wi-Fi 访问令牌</summary><code>{{networkInfo.api_token}}</code></details></section>
        <section class="panel"><div class="panel-title"><h2>测量校准</h2><span class="badge">需要参考仪表</span></div><label>通道<select v-model="calChannel"><option v-for="c in channels" :key="c" :value="c">{{labels[c]}}</option></select></label><div class="two-fields"><label>增益<input v-model.number="calGain" type="number" step="0.000001"/></label><label>偏移 / {{calChannel==='battery_i'?'A':'V'}}<input v-model.number="calOffset" type="number" step="0.000001"/></label></div><div class="two-fields"><label>校准范围下限<input v-model.number="calMin" type="number" step="0.001"/></label><label>校准范围上限<input v-model.number="calMax" type="number" step="0.001"/></label></div><label>参考条件<input v-model="calReference" placeholder="仪表、校准点、温度和日期"/></label><button class="button primary" :disabled="!canWrite || !!pending || !calReference" @click="command('calibration.set',{channel:calChannel,gain:calGain,offset:calOffset,min_value:calMin,max_value:calMax,reference:calReference})">保存此通道校准</button><p class="hint">换算值 = 名义读数 × 增益 + 偏移。应用校准不代表额定精度已经验收；近零非线性不能用固定偏移掩盖。</p><div class="cal-summary"><span v-for="c in calRecords" :key="c.channel">{{labels[c.channel]}}：{{c.state==='calibrated'?'有校准记录':c.state==='invalid'?'记录无效':'未校准'}}</span></div></section>
        <section class="panel"><div class="panel-title"><h2>供电切换参数</h2><span class="badge amber">实物待验证</span></div><label>先断后通间隔 / ms<input v-model.number="deadtime" type="number" min="10" max="1000"/></label><button class="button" :disabled="!canWrite || !!activeJobs.length" @click="command('timing.set',{power_deadtime_ms:deadtime})">应用本次间隔</button><p class="hint">仅作用于本次启动，重启恢复 100ms 工程初值。应结合 MOS 关断波形核定，不能当作已验证指标。</p><div class="definition-list"><span>固件版本</span><b>{{state?.device.firmware_version||'未读取'}}</b><span>设备身份</span><b class="mono wrap">{{state?.device.device_id||'未读取'}}</b></div><button class="button full" :disabled="!connected || !!activeJobs.length || (!!state?.control.owner && !ownsControl)" @click="run('disconnect',async()=>{state=await api('/api/disconnect','POST');connectionOpen=true})"><Unplug :size="16"/>断开设备通信</button></section>
      </div>

      <section v-show="tab==='操作记录'" class="panel activity-panel"><div class="panel-title"><h2>操作记录</h2><span class="hint">{{activeJobs.length}} 项正在执行</span></div><div class="activity-table" role="table"><div class="activity-head" role="row"><span>时间</span><span>操作 / 来源</span><span>状态</span><span>说明</span></div><div v-for="job in (state?.jobs??[])" :key="job.request_id" class="activity-row" role="row"><span class="mono">{{new Date(job.created_at*1000).toLocaleTimeString('zh-CN')}}</span><span>{{methodNames[job.method]??job.method}}<small>{{job.actor}}</small></span><span class="badge" :class="{teal:job.state==='succeeded',amber:['running','unknown','failed'].includes(job.state)}">{{jobNames[job.state]??job.state}}</span><span>{{job.error?.message || (job.state==='succeeded'?'控制执行完成，设备响应需另行观测':'可通过任务编号追踪')}}<small class="mono">{{job.request_id.slice(0,12)}}</small></span></div><p v-if="!state?.jobs.length" class="empty-log">尚无操作记录。连接工具后，人工与 AI 的操作会显示在这里。</p></div><details class="event-details"><summary>连接与采集事件（{{events.length}}）</summary><div v-for="event in [...events].reverse().slice(0,30)" :key="event.cursor" class="event-row"><span class="mono">{{new Date(event.received_at*1000).toLocaleTimeString('zh-CN')}}</span><span>{{event.detail}}</span></div></details></section>

      <details v-show="tab==='设备设置'" class="panel runtime-management"><summary>后台与客户端</summary><div class="client-list"><div v-for="client in state?.clients??[]" :key="client.id"><strong>{{client.name}}</strong><span>{{client.kind==='desktop'?'桌面':client.kind==='web'?'网页':client.kind==='mcp'?'AI':'命令行'}}</span><span class="badge" :class="{teal:client.active}">{{client.active?'在线':'已离线'}}</span></div></div><div class="button-row runtime-actions"><p class="hint grow">{{isDesktop?'关闭窗口后保留在托盘。仅退出桌面端会保留后台采集和记录；停止后台前请结束记录、等待动作完成，并让其他客户端退出。':'关闭网页后，后台仍可采集和记录。退出程序前请停止记录，并让其他客户端退出会话；关闭页面的客户端最多60秒后标为离线。'}}</p><button class="button" :disabled="!socketLive || !!pending" @click="run('diagnostics',async()=>{notice=await exportDiagnostics()?'诊断日志已导出':'已取消保存'})"><Download :size="16"/>导出诊断日志</button><button v-if="isDesktop" class="button" :disabled="!!pending" @click="run('desktop-exit',()=>desktopCommand('desktop_exit'))">仅退出桌面端</button><button class="button" :disabled="!socketLive || recording || !!activeJobs.length || !!pending" @click="run('shutdown',stopRuntime)">{{isDesktop?'停止后台并退出':'退出后台'}}</button></div></details>
      <footer><span>MCU TOOL <b>{{appVersion}}</b></span><span>控制状态与实测数据分别呈现 · 实物精度及电气时序待验收</span></footer>
    </main>
    <div v-if="takeoverOpen" class="modal-backdrop" @click.self="takeoverOpen=false"><section class="modal" role="dialog" aria-modal="true" aria-labelledby="takeover-title"><h2 id="takeover-title">交接操作权</h2><p>当前操作者：{{state?.control.owner?.name}}。接管后，你可以改变被测设备状态，请先确认原测试已允许交接。</p><p>有在途动作或状态变化时，后台会拒绝本次接管。</p><div class="button-row"><button class="button" @click="takeoverOpen=false">继续观察</button><button class="button primary" :disabled="!!activeJobs.length || !!pending" @click="claim(true)">确认接管</button></div></section></div>
  </div>
</template>
