<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, shallowRef, watch } from 'vue'
import { Download, Eraser, Pause, Play, RotateCcw } from 'lucide-vue-next'
import { saveWaveform, type Sample } from './api'
import { clamp, dataDomain, intervalStats, linePath, valueAt, type Domain } from './measurement'
import { WaveformHistory, waveformCsv, type ChannelHistory } from './waveform'

const props = defineProps<{ samples: Sample[]; latest: Record<string, Sample>; deviceId: string; bootId: string; runtimeId: string; sampleRate?: number; live: boolean; mode: 'battery' | 'aux' }>()
type Channel = { key: string; label: string; unit: string; color: string; visible: boolean; scale: number; offset: number }
const isBattery = props.mode === 'battery'
const channels = reactive<Channel[]>(isBattery ? [
  { key: 'battery_v', label: '电池接口电压', unit: 'V', color: '#2563eb', visible: true, scale: 1, offset: 0 },
  { key: 'battery_i', label: '电池端电流', unit: 'mA', color: '#bd650c', visible: true, scale: 1, offset: 0 }
] : ['ain1','ain2','ain3','ain4'].map((key, index) => ({ key, label: key.toUpperCase(), unit: 'V', color: ['#2563eb','#16806a','#bd650c','#8354b6'][index], visible: true, scale: [1,.5,2,.002][index], offset: 0 })))
const active = ref(0), analysis = ref(false), paused = ref(false), frozen = shallowRef<ChannelHistory[]>([])
const history = new WaveformHistory(channels.map(channel => channel.key)), revision = ref(0)
const exporting = ref(false), exportMessage = ref(''), exportError = ref('')
const view = ref<Domain | null>(null), following = ref(true), manualAxes = ref<(Domain | null)[]>([null, null])
const origin = ref<number | null>(null), cursorA = ref<number | null>(null), cursorB = ref<number | null>(null)
const host = ref<HTMLDivElement | null>(null), readings = ref<HTMLDivElement | null>(null), svg = ref<SVGSVGElement | null>(null)
const width = ref(900), readingHeight = ref(isBattery ? 92 : 216)
const hover = ref<{ time: number; x: number; y: number } | null>(null)
let observer: ResizeObserver | undefined
type Drag = { kind: string; x: number; y: number; window: Domain; index: number; offset: number; axis: Domain | null }
let drag: Drag | null = null
const qualityNames: Record<string,string> = { uncalibrated:'未校准', calibrated:'已应用校准', invalid_calibration:'校准无效', outside_calibrated_range:'超出校准范围', out_of_range:'超量程', sensor_error:'读取失败' }
const clipId = `measurement-${props.mode}-clip`
const series = computed(() => { if (paused.value) return frozen.value; revision.value; return history.channels.slice() })
const available = computed<Domain | null>(() => {
  let low = Infinity, high = -Infinity
  for (const rows of series.value) if (rows.length) { low = Math.min(low, rows.time(0)); high = Math.max(high, rows.time(rows.length - 1)) }
  return high > low ? { low, high } : null
})
const windowRange = computed(() => {
  const bounds = available.value, selected = view.value
  if (!bounds || !selected) return bounds
  if (!following.value) return selected
  // AI:缩放只改变时间跨度，实时模式的右边界始终使用最新采样时刻。
  return { low: Math.max(bounds.low, bounds.high - (selected.high - selected.low)), high: bounds.high }
})
const top = computed(() => readingHeight.value + 54)
const height = computed(() => Math.max(isBattery ? 330 : 430, top.value + 252))
const left = 62, right = computed(() => width.value - (isBattery ? 62 : 54)), bottom = computed(() => height.value - 32)
const axisDomains = computed(() => isBattery ? channels.map((_, index) => manualAxes.value[index] ?? dataDomain(series.value[index], index === 0 ? .01 : .1)) : [])
const paths = computed(() => channels.map((channel, index) => !channel.visible || !windowRange.value || (isBattery && !axisDomains.value[index]) ? '' : linePath(series.value[index], x, value => y(value, index), windowRange.value)))
const xTicks = computed(() => {
  const range = windowRange.value
  if (!range) return []
  const count = width.value < 430 ? 2 : 4
  return Array.from({ length: count + 1 }, (_, index) => ({ time: range.low + (range.high - range.low) * index / count, index, count }))
})
const yTicks = computed(() => Array.from({ length: isBattery ? 5 : 9 }, (_, index) => {
  const fraction = index / (isBattery ? 4 : 8), axis = axisDomains.value[0], channel = channels[active.value]
  return { y: top.value + fraction * (bottom.value - top.value), value: isBattery ? axis ? axis.high - fraction * (axis.high - axis.low) : null : (4 - fraction * 8 - channel.offset) * channel.scale, label: isBattery || index % 2 === 0 }
}))
const zeroY = computed(() => isBattery ? null : y(0, active.value))
const cursorReady = computed(() => analysis.value && cursorA.value !== null && cursorB.value !== null && windowRange.value)
const cursorPositions = computed(() => {
  const range = windowRange.value
  if (!cursorReady.value || !range) return []
  const a = x(cursorA.value!), b = x(cursorB.value!), nearby = b - a < 26, middle = clamp((a + b) / 2, left + 24, right.value - 24)
  return [{ name: 'a', time: cursorA.value!, x: a, handle: nearby ? middle - 12 : a }, { name: 'b', time: cursorB.value!, x: b, handle: nearby ? middle + 12 : b }].filter(cursor => cursor.time >= range.low && cursor.time <= range.high)
})
const statistics = computed(() => cursorReady.value ? series.value.map(rows => intervalStats(rows, cursorA.value!, cursorB.value!)) : [])
const selectionBand = computed(() => {
  if (!cursorReady.value) return null
  const start = clamp(x(cursorA.value!), left, right.value), end = clamp(x(cursorB.value!), left, right.value)
  return { x: start, width: Math.max(0, end - start) }
})
const hasValues = computed(() => series.value.some(rows => { let valid = 0; for (let i = 0; i < rows.length; i++) if (rows.at(i)!.value !== null && ++valid === 2) return true; return false }))
const sampleCount = computed(() => series.value.reduce((sum, rows) => sum + rows.length, 0))
const historyExpired = computed(() => series.value.some(rows => rows.evicted))
const durationText = computed(() => { const seconds = Math.max(0, Math.floor(available.value ? available.value.high - available.value.low : 0)); return `${Math.floor(seconds/3600)}:${String(Math.floor(seconds/60)%60).padStart(2,'0')}:${String(seconds%60).padStart(2,'0')}` })
const selectionExpired = computed(() => cursorReady.value && available.value && (cursorA.value! < available.value.low || cursorB.value! > available.value.high))

/** AI:将采样时间变成所有通道共用的横坐标。@param time 设备采样秒数。@returns 图内横坐标。 */
function x(time: number) { const range = windowRange.value!; return left + (time - range.low) / (range.high - range.low) * (right.value - left) }
/** AI:按双轴范围或独立通道比例绘图，零偏移时零点位于中线。@param value V 或 mA 读数。@param index 通道序号。@returns 图内纵坐标。 */
function y(value: number, index: number) {
  if (!isBattery) { const channel = channels[index]; return (top.value + bottom.value) / 2 - (value / channel.scale + channel.offset) * (bottom.value - top.value) / 8 }
  const axis = axisDomains.value[index]!
  return bottom.value - (value - axis.low) / (axis.high - axis.low) * (bottom.value - top.value)
}
/** AI:缺失读数明确显示横线，保留有效的负值。@param value 已换算的测量值。@param digits 小数位数。@returns 数字文本。 */
function format(value: number | null | undefined, digits = 3) { return value == null || !Number.isFinite(value) ? '—' : value.toFixed(digits) }
/** AI:显示当前设备的最新读数，暂停或隐藏曲线不改变该值。@param channel 通道信息。@returns 读数文本。 */
function latestValue(channel: Channel) { const sample = props.latest[channel.key]; return sample?.device_id === props.deviceId && sample.boot_id === props.bootId ? format(sample.value === null ? null : sample.value * (channel.unit === 'mA' ? 1000 : 1)) : '—' }
/** AI:保留校准质量和断线、过期提示。@param channel 通道信息。@returns 状态文字。 */
function quality(channel: Channel) { const sample = props.latest[channel.key]; if (!sample) return '未读取'; if (!props.live || sample.stale) return '数据已过期'; return qualityNames[sample.quality] ?? sample.quality }
/** AI:显示相对于本次设备历史起点的采样时间。@param time 设备绝对采样秒数。@returns 时间文本。 */
function timeText(time: number) { const seconds = time - origin.value!; if (windowRange.value && windowRange.value.high - windowRange.value.low < 10) return `${seconds.toFixed(1)}s`; return seconds >= 3600 ? `${Math.floor(seconds/3600)}:${String(Math.floor(seconds/60)%60).padStart(2,'0')}:${String(Math.floor(seconds%60)).padStart(2,'0')}` : `${Math.floor(seconds / 60)}:${String(Math.floor(seconds % 60)).padStart(2,'0')}` }
/** AI:按当前轴精度格式化刻度，极大或极小尺度使用科学计数。@param value 刻度值。@param index 轴或通道序号。@returns 刻度文本。 */
function tickText(value: number | null, index: number) { if (value === null) return ''; const span = isBattery ? axisDomains.value[index]!.high - axisDomains.value[index]!.low : channels[index].scale * 8; return Math.abs(value) >= 1000 || span < .001 ? value.toExponential(1) : value.toFixed(span < .1 ? 4 : span < 1 ? 3 : 2) }
/** AI:当前完整区间内初始化 A/B，关闭分析不清除已有选区。@returns 无。 */
function initializeCursors() { const range = windowRange.value; if (range && cursorA.value === null) { cursorA.value = range.low + (range.high - range.low) / 4; cursorB.value = range.low + (range.high - range.low) * .75 } }
/** AI:由用户明确重选当前保留历史，不静默移动过期的统计区间。@returns 无。 */
function reselectCursors() { const range = available.value; if (range) { view.value = null; cursorA.value = range.low + (range.high - range.low) / 4; cursorB.value = range.low + (range.high - range.low) * .75 } }
/** AI:显示暂停只冻结曲线和分析样本，最新数值仍实时更新。@returns 无。 */
function togglePause() { if (!paused.value) frozen.value = history.channels.map(channel => channel.snapshot()); paused.value = !paused.value; if (!paused.value) { frozen.value = []; following.value = true }; hover.value = null }
/** AI:恢复跟随最新采样，保留时间跨度、纵轴和A/B区间。@returns 无。 */
function followLatest() { paused.value = false; frozen.value = []; following.value = true; hover.value = null }
/** AI:仅清空本图历史、时间起点和游标，不改变设备与其他图表。@returns 无。 */
function clearWaveform() {
  history.clear(); frozen.value = history.channels.map(channel => channel.snapshot()); revision.value++
  origin.value = null; cursorA.value = cursorB.value = null; view.value = null; following.value = true; hover.value = null
  exportMessage.value = ''; exportError.value = ''
}
/** AI:导出点击时本组的全部保留样本，包含隐藏通道，暂停时采用冻结历史。@returns 保存完成或可见错误。 */
async function exportWaveform() {
  if (exporting.value || !sampleCount.value) return
  exporting.value = true; exportMessage.value = ''; exportError.value = ''
  const snapshot = series.value.map(channel => channel.snapshot()), deviceId = props.deviceId, bootId = props.bootId, start = origin.value ?? 0
  try {
    await new Promise<void>(resolve => requestAnimationFrame(() => resolve()))
    const parts = waveformCsv(snapshot, deviceId, bootId, start)
    const filename = `MCUTOOL-${isBattery ? '电池' : '四路电压'}-${new Date().toISOString().replace(/[:.]/g,'-')}.csv`
    const saved = await saveWaveform(filename, parts)
    exportMessage.value = saved ? '波形数据已导出' : '已取消导出'
  } catch (error) { exportError.value = error instanceof Error ? error.message : '波形导出失败' }
  finally { exporting.value = false }
}
/** AI:恢复时间跟随与默认纵轴，不修改游标、颜色、显隐及设备。@returns 无。 */
function resetView() { view.value = null; following.value = true; manualAxes.value = [null,null]; hover.value = null; if (!isBattery) channels.forEach((channel,index) => { channel.scale = [1,.5,2,.002][index]; channel.offset = 0 }) }
/** AI:校验独立比例或偏移的输入，非法值明确停留在输入框。@param event 表单变化。@param index 通道序号。@param field 仅显示比例或偏移。@returns 无。 */
function setChannelNumber(event: Event, index: number, field: 'scale' | 'offset') { const input = event.target as HTMLInputElement; if (input.reportValidity()) channels[index][field] = Number(input.value) }
/** AI:设置分析游标，不允许零长度或交叉区间。@param event 输入事件。@param name A 或 B。@returns 无。 */
function setCursor(event: Event, name: 'a' | 'b') { const input = event.target as HTMLInputElement; if (!input.reportValidity() || origin.value === null) return; const value = Number(input.value) + origin.value; if (name === 'a') cursorA.value = value; else cursorB.value = value }
/** AI:将鼠标坐标转为图内位置。@param event 指针或滚轮事件。@returns 像素位置。 */
function position(event: PointerEvent | WheelEvent) { const rect = svg.value!.getBoundingClientRect(); return { x: event.clientX - rect.left, y: event.clientY - rect.top } }
/** AI:开始游标或坐标轴平移，只捕获当前图表指针。@param event 指针按下事件。@returns 无。 */
function pointerDown(event: PointerEvent) {
  if (event.button !== 0 || !windowRange.value) return
  const target = (event.target as Element).closest<SVGElement>('[data-drag]'); if (!target) return
  const point = position(event), kind = target.dataset.drag!, index = kind === 'right' ? 1 : isBattery ? 0 : active.value
  drag = { kind, ...point, window: { ...windowRange.value }, index, offset: channels[index].offset, axis: isBattery ? axisDomains.value[index] && { ...axisDomains.value[index]! } : null }
  hover.value = null; svg.value!.setPointerCapture(event.pointerId); event.preventDefault()
}
/** AI:拖动时间、纵轴或游标；悬停读数始终来自原始数据。@param event 指针移动事件。@returns 无。 */
function pointerMove(event: PointerEvent) {
  const range = windowRange.value, bounds = available.value; if (!range || !bounds) return
  const point = position(event), plotWidth = right.value - left, plotHeight = bottom.value - top.value
  if (drag) {
    if (drag.kind === 'a' || drag.kind === 'b') {
      const time = range.low + (point.x - left) / plotWidth * (range.high - range.low), step = Math.min(.001, (bounds.high - bounds.low) / 100)
      if (drag.kind === 'a') cursorA.value = clamp(time, bounds.low, Math.min(bounds.high, cursorB.value! - step))
      else cursorB.value = clamp(time, Math.max(bounds.low, cursorA.value! + step), bounds.high)
    } else if (drag.kind === 'time') {
      const span = Math.min(drag.window.high - drag.window.low, bounds.high - bounds.low), shift = (point.x - drag.x) / plotWidth * span
      const low = clamp(drag.window.low - shift, bounds.low, bounds.high - span); following.value = false; view.value = { low, high: low + span }
    } else if (isBattery && drag.axis) {
      const shift = (point.y - drag.y) / plotHeight * (drag.axis.high - drag.axis.low)
      manualAxes.value[drag.index] = { low: drag.axis.low + shift, high: drag.axis.high + shift }
    } else if (!isBattery) channels[drag.index].offset = drag.offset - (point.y - drag.y) / plotHeight * 8
    return
  }
  hover.value = point.x >= left && point.x <= right.value && point.y >= top.value && point.y <= bottom.value ? { ...point, time: range.low + (point.x - left) / plotWidth * (range.high - range.low) } : null
}
/** AI:释放拖动指针。@param event 抬起或取消事件。@returns 无。 */
function pointerUp(event: PointerEvent) { drag = null; if (svg.value?.hasPointerCapture(event.pointerId)) svg.value.releasePointerCapture(event.pointerId) }
/** AI:滚轮在图内缩放时间，在刻度区只缩放对应纵轴；游标统计区间保持不变。@param event 滚轮事件。@returns 无。 */
function wheel(event: WheelEvent) {
  const range = windowRange.value, bounds = available.value; if (!range || !bounds) return
  const point = position(event); if (point.y < top.value || point.y > bottom.value) return
  const delta = event.deltaY * (event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? bottom.value - top.value : 1), factor = Math.exp(clamp(delta,-600,600)*.0015)
  event.preventDefault(); hover.value = null
  if (point.x >= left && point.x <= right.value) {
    const fraction = (point.x-left)/(right.value-left), anchor = range.low + fraction*(range.high-range.low), span = clamp((range.high-range.low)*factor, Math.min(.1,bounds.high-bounds.low),bounds.high-bounds.low)
    const low = clamp(anchor-fraction*span,bounds.low,bounds.high-span); view.value = { low, high: low+span }
  } else if (isBattery) {
    const index = point.x < left ? 0 : 1, axis = axisDomains.value[index]; if (!axis) return
    const fraction = (bottom.value-point.y)/(bottom.value-top.value), anchor = axis.low+fraction*(axis.high-axis.low), span = clamp((axis.high-axis.low)*factor,.000001,1e6)
    manualAxes.value[index] = { low: anchor-fraction*span, high: anchor+(1-fraction)*span }
  } else if (point.x < left) {
    const channel = channels[active.value], division = (bottom.value-point.y)/(bottom.value-top.value)*8-4, anchor = (division-channel.offset)*channel.scale
    channel.scale = clamp(channel.scale*factor,.000001,1000); channel.offset = division-anchor/channel.scale
  }
}
watch(() => props.samples, samples => {
  const changed = history.select(`${props.runtimeId}/${props.deviceId}/${props.bootId}`, props.deviceId, props.bootId)
  if (changed) { paused.value=false;frozen.value=[];origin.value=null;cursorA.value=null;cursorB.value=null;resetView() }
  if (history.append(samples) || changed) revision.value++
}, { immediate: true })
watch(available, range => { if (range && origin.value === null) origin.value=range.low; if (analysis.value) initializeCursors() }, { immediate: true })
watch(analysis, enabled => { if (enabled) initializeCursors() })
onMounted(() => {
  observer = new ResizeObserver(() => { if (host.value?.clientWidth) width.value=host.value.clientWidth; if (readings.value?.offsetHeight) readingHeight.value=readings.value.offsetHeight })
  if (host.value) observer.observe(host.value)
  if (readings.value) observer.observe(readings.value)
})
onBeforeUnmount(() => observer?.disconnect())
</script>

<template>
  <section class="panel measurement-panel" :class="{narrow:width<620,tight:width<360}" :data-mode="mode">
    <div class="panel-title"><h2>{{ isBattery?'电池电压与电流':'四路电压测量' }}</h2><div class="chart-tools">
      <label v-if="isBattery" class="analysis-switch"><input v-model="analysis" type="checkbox" role="switch" aria-label="时间游标与统计"/>时间游标与统计</label>
      <span v-else class="axis-status">Y 轴：{{ channels[active].label }} · {{channels[active].visible?'实线':'曲线隐藏'}}</span>
    </div></div>
    <div class="waveform-toolbar">
      <div class="chart-tools" role="group" :aria-label="isBattery?'电池波形操作':'四路电压波形操作'">
        <button class="button compact-button" :class="{primary:paused}" :aria-label="paused?'开始显示':'暂停显示'" @click="togglePause"><Play v-if="paused" :size="14"/><Pause v-else :size="14"/>{{paused?'开始':'暂停'}}</button>
        <button class="button compact-button" @click="clearWaveform"><Eraser :size="14"/>清空</button>
        <button class="button compact-button" :disabled="exporting || !sampleCount" @click="exportWaveform"><Download :size="14"/>{{exporting?'导出中…':'导出'}}</button>
        <button class="button compact-button" @click="resetView"><RotateCcw :size="14"/>恢复视图</button>
        <button v-if="!following" class="button primary compact-button" @click="followLatest">回到实时</button>
      </div>
      <span class="waveform-state" :data-count="sampleCount">{{paused?'已暂停':following?'实时':'历史'}} · {{sampleRate ? `${sampleRate} Hz · ` : ''}}{{durationText}}</span>
    </div>
    <p v-if="historyExpired" class="analysis-warning">当前保留最近 4 小时</p>
    <p v-if="exportError" class="inline-error" role="alert">{{exportError}}</p><p v-else-if="exportMessage" class="analysis-note" role="status">{{exportMessage}}</p>
    <slot name="status"/>
    <div ref="host" class="chart-stage">
      <div ref="readings" class="chart-readings" :class="{'four-readings':!isBattery}">
        <div v-for="(channel,index) in channels" :key="channel.key" class="channel-reading" :style="{'--channel-color':channel.color}">
          <div class="channel-heading"><span v-if="isBattery" class="reading-label"><i class="line-swatch" :class="{dashed:index===1}"/>{{channel.label}}</span>
            <template v-else><button class="channel-select" :aria-pressed="active===index" :aria-label="`${channel.label}，选择Y轴刻度`" @click="active=index"><i class="line-swatch" :class="{dashed:active!==index}"/>{{channel.label}}</button><input class="channel-color" v-model="channel.color" type="color" :aria-label="`${channel.label}曲线颜色`"/></template>
          </div>
          <div class="reading-line"><div class="reading-number" :class="{stale:!live || latest[channel.key]?.stale}">{{latestValue(channel)}}<small>{{channel.unit}}</small></div><span class="quality" :class="{warning:quality(channel)!=='已应用校准'}">{{quality(channel)}}</span></div>
          <template v-if="!isBattery">
            <button class="curve-toggle" :aria-label="`${channel.label}曲线显示开关`" :aria-pressed="channel.visible" @click="channel.visible=!channel.visible;hover=null">{{channel.visible?'曲线显示':'曲线隐藏'}}</button>
            <div class="channel-adjust"><label>V/格<input :value="Number(channel.scale.toPrecision(7))" type="number" min="0.000001" max="1000" step="any" required :aria-label="`${channel.label}每格电压`" @change="setChannelNumber($event,index,'scale')"/></label><label>偏移<input :value="Number(channel.offset.toPrecision(7))" type="number" step="any" required :aria-label="`${channel.label}上下偏移`" @change="setChannelNumber($event,index,'offset')"/></label></div>
          </template>
        </div>
      </div>
      <svg ref="svg" class="measurement-chart" :style="{height:`${height}px`}" :viewBox="`0 0 ${width} ${height}`" role="img" :aria-label="isBattery?'电池电压与电流双轴图':'四路电压独立比例图'" :data-window-start="windowRange?.low" :data-window-end="windowRange?.high" @pointerdown="pointerDown" @pointermove="pointerMove" @pointerup="pointerUp" @pointercancel="pointerUp" @pointerleave="!drag && (hover=null)" @wheel="wheel" @dblclick="resetView">
        <defs><clipPath :id="clipId"><rect :x="left" :y="top" :width="Math.max(0,right-left)" :height="bottom-top"/></clipPath></defs>
        <text class="axis-title" :x="left" :y="top-30" :fill="isBattery?channels[0].color:channels[active].color">{{isBattery?'电压 / V':`${channels[active].label} / V`}}</text><text v-if="isBattery" class="axis-title" :x="right" :y="top-30" text-anchor="end" :fill="channels[1].color">电流 / mA</text>
        <rect v-if="selectionBand" class="selection-band" :x="selectionBand.x" :y="top" :width="selectionBand.width" :height="bottom-top"/>
        <g v-for="(tick,index) in yTicks" :key="index"><line :x1="left" :x2="right" :y1="tick.y" :y2="tick.y" class="chart-grid"/><text v-if="tick.label" :x="left-8" :y="tick.y+4" text-anchor="end" :fill="isBattery?channels[0].color:channels[active].color">{{tickText(tick.value,isBattery?0:active)}}</text><text v-if="isBattery && axisDomains[1]" :x="right+8" :y="tick.y+4" :fill="channels[1].color">{{tickText(axisDomains[1].high-(axisDomains[1].high-axisDomains[1].low)*index/4,1)}}</text></g>
        <line v-if="zeroY!==null && zeroY>=top && zeroY<=bottom" class="zero-line" :x1="left" :x2="right" :y1="zeroY" :y2="zeroY"/>
        <g :clip-path="`url(#${clipId})`"><path v-for="(channel,index) in channels" v-show="channel.visible" :key="channel.key" :data-channel="channel.key" :d="paths[index]" fill="none" :stroke="channel.color" :stroke-dasharray="(isBattery?index===0:active===index)?undefined:'6 4'" stroke-width="2" stroke-linejoin="round"/>
          <g v-if="hover"><line :x1="x(hover.time)" :x2="x(hover.time)" :y1="top" :y2="bottom" class="hover-line"/><template v-for="(channel,index) in channels" :key="channel.key"><circle v-if="channel.visible && valueAt(series[index],hover.time)!==null && (!isBattery || axisDomains[index])" :cx="x(hover.time)" :cy="y(valueAt(series[index],hover.time)!,index)" r="3.5" :fill="channel.color"/></template></g>
        </g>
        <text v-if="!hasValues" :x="(left+right)/2" :y="(top+bottom)/2-10" text-anchor="middle" class="empty-chart">等待连续有效采样</text>
        <text v-else-if="!channels.some(channel=>channel.visible)" :x="(left+right)/2" :y="(top+bottom)/2-10" text-anchor="middle" class="empty-chart">曲线均已隐藏，读数继续显示</text>
        <g v-for="tick in xTicks" :key="tick.index"><text :x="x(tick.time)" :y="height-10" :text-anchor="tick.index===0?'start':tick.index===tick.count?'end':'middle'">{{timeText(tick.time)}}</text></g>
        <rect data-drag="time" class="plot-hit" :x="left" :y="top" :width="Math.max(0,right-left)" :height="bottom-top"/>
        <rect data-drag="left" class="axis-hit" x="0" :y="top" :width="left" :height="bottom-top"/><rect v-if="isBattery" data-drag="right" class="axis-hit" :x="right" :y="top" :width="width-right" :height="bottom-top"/>
        <g v-for="cursor in cursorPositions" :key="cursor.name" :data-drag="cursor.name" class="cursor-hit"><rect :x="cursor.x-9" :y="top" width="18" :height="bottom-top" fill="transparent"/><line :x1="cursor.x" :x2="cursor.x" :y1="top" :y2="bottom" stroke="#65758a"/><line :x1="cursor.x" :x2="cursor.handle" :y1="top" :y2="top-1" stroke="#65758a"/><rect :x="cursor.handle-11" :y="top-19" width="22" height="19" rx="3" fill="#52647b"/><text :x="cursor.handle" :y="top-6" text-anchor="middle" fill="#fff">{{cursor.name.toUpperCase()}}</text></g>
      </svg>
      <div v-if="hover" class="chart-tooltip" role="tooltip" :style="{left:`${clamp(hover.x+14,0,Math.max(0,width-192))}px`,top:`${Math.max(top-25,Math.min(hover.y+12,height-132))}px`}"><strong>{{format(hover.time-origin!,2)}} s</strong><div v-for="(channel,index) in channels" :key="channel.key"><span :style="{color:channel.color}">{{channel.label}}</span> {{format(valueAt(series[index],hover.time))}} {{channel.unit}}</div></div>
    </div>
    <div v-if="isBattery && analysis" class="analysis-content">
      <div class="analysis-grid"><section><h3>时间游标</h3><table><thead><tr><th>时间 / s</th><th>电压 / V</th><th>电流 / mA</th></tr></thead><tbody><tr v-for="name in ['a','b'] as const" :key="name"><td><label class="cursor-input">{{name.toUpperCase()}}<input type="number" step="any" required :disabled="!cursorReady" :aria-label="`${name.toUpperCase()}游标时间`" :value="origin===null || (name==='a'?cursorA:cursorB)===null?'':format((name==='a'?cursorA!:cursorB!)-origin,3)" :min="available && origin!==null ? (name==='a'?available.low:cursorA!+.000001)-origin:undefined" :max="available && origin!==null ? (name==='a'?cursorB!-.000001:available.high)-origin:undefined" @change="setCursor($event,name)"/></label></td><td>{{format((name==='a'?cursorA:cursorB)===null?null:valueAt(series[0],name==='a'?cursorA!:cursorB!))}}</td><td>{{format((name==='a'?cursorA:cursorB)===null?null:valueAt(series[1],name==='a'?cursorA!:cursorB!))}}</td></tr></tbody></table></section>
        <section><h3>A—B 区间统计</h3><table><thead><tr><th>项目</th><th>电压 / V</th><th>电流 / mA</th></tr></thead><tbody><tr v-for="item in [{key:'max',label:'最大值'},{key:'min',label:'最小值'},{key:'average',label:'平均值'}] as const" :key="item.key"><td>{{item.label}}</td><td :data-stat="`voltage-${item.key}`">{{format(statistics[0]?.[item.key])}}</td><td :data-stat="`current-${item.key}`">{{format(statistics[1]?.[item.key])}}</td></tr></tbody></table></section></div>
      <div class="analysis-total"><span>A—B 时长 <strong>{{cursorReady?format(cursorB!-cursorA!,3):'—'}}</strong> s</span><span>区间净电量 <strong data-stat="charge">{{statistics[1]?format(statistics[1].integral/3600,6):'—'}}</strong> mAh</span></div>
      <p v-if="!statistics[0] || !statistics[1]" class="analysis-warning" role="status">选区数据不完整<button v-if="selectionExpired" class="text-button" @click="reselectCursors">重选当前历史</button></p>
    </div>
    <slot/>
  </section>
</template>

<style scoped>
.measurement-panel{min-width:0;padding:14px}.panel-title{gap:10px;flex-wrap:wrap;margin-bottom:10px}
.waveform-toolbar{display:flex;align-items:center;justify-content:space-between;gap:10px;flex-wrap:wrap;margin-bottom:6px}.waveform-state{font:11px "Consolas","Microsoft YaHei",monospace;color:#617084}
.chart-tools{display:flex;gap:6px;align-items:center;flex-wrap:wrap}.chart-tools .compact-button{font-size:11px;min-height:28px;padding:4px 8px}.axis-status{font-size:12px;color:#617084}
.analysis-switch{display:inline-flex;align-items:center;gap:7px;font-size:12px;color:#617084}.analysis-switch input{appearance:none;position:relative;width:30px;height:18px;min-height:18px;padding:0;margin:0;border:1px solid #bdc8d6;border-radius:12px;background:#dce3eb;flex-shrink:0;cursor:pointer}.analysis-switch input:before{content:"";position:absolute;top:2px;left:2px;width:12px;height:12px;border-radius:50%;background:#fff}.analysis-switch input:checked{border-color:#2563eb;background:#2563eb}.analysis-switch input:checked:before{left:14px}
.chart-stage{position:relative;min-width:0}.chart-readings{position:absolute;left:62px;right:62px;top:8px;display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px;z-index:1}.chart-readings.four-readings{right:16px;grid-template-columns:repeat(4,minmax(0,1fr));gap:16px}.channel-reading{min-width:0}
.channel-heading,.reading-line{display:flex;align-items:center;gap:10px;flex-wrap:wrap}.reading-line{gap:6px 12px}.reading-label{display:flex;align-items:center;gap:6px;font-size:12px;color:#617084}.line-swatch{display:inline-block;width:17px;border-top:2px solid var(--channel-color);flex-shrink:0}.line-swatch.dashed{border-top-style:dashed}
.reading-number{font-family:"Bahnschrift","Consolas",monospace;font-size:38px;line-height:1.2;letter-spacing:-.7px;color:#202c3b;margin-top:4px;font-variant-numeric:tabular-nums}.reading-number small{font:13px "Segoe UI",sans-serif;color:#617084;margin-left:5px}.reading-number.stale{color:#7a8797}.quality{font-size:10px;line-height:1.4;color:#617084}.quality.warning{color:#89600a}.four-readings .reading-number{font-size:27px;line-height:1.3}.four-readings .reading-number small{font-size:12px}
.channel-select{display:inline-flex;gap:6px;align-items:center;font:600 12px "Segoe UI","Microsoft YaHei",sans-serif;min-height:27px;padding:3px 6px;border:1px solid transparent;border-radius:4px;background:#fff;color:#617084}.channel-select[aria-pressed=true]{color:var(--channel-color);border-color:var(--channel-color);background:color-mix(in srgb,var(--channel-color) 8%,white)}.channel-heading .channel-color{width:29px;height:24px;min-height:24px;padding:2px;margin:0}
.curve-toggle{display:flex;align-items:center;gap:5px;font-size:10px;min-height:24px;padding:2px 6px;margin-top:4px;border:1px solid #e1e7ef;border-radius:4px;background:#fff;color:#617084}.curve-toggle:before{content:"";width:6px;height:6px;border:1px solid #9aa7b7;border-radius:50%}.curve-toggle[aria-pressed=true]:before{background:var(--channel-color);border-color:var(--channel-color)}
.channel-adjust{display:grid;gap:4px;margin-top:6px;color:#617084}.channel-adjust label{display:grid;grid-template-columns:34px 78px;align-items:center;gap:6px;margin:0;font-size:11px}.channel-adjust input[type=number]{width:78px;min-height:25px;height:25px;margin:0;padding:2px 4px;font:12px "Consolas",monospace}
.measurement-chart{display:block;width:100%;touch-action:none;user-select:none;fill:#617084}.measurement-chart text{font:11px "Segoe UI","Microsoft YaHei",sans-serif}.measurement-chart path{pointer-events:none}.chart-grid{stroke:#e1e7ef;stroke-width:1}.zero-line{stroke:#aab7c8;stroke-width:1.4}.hover-line{stroke:#9aa9bb;stroke-dasharray:2 3;pointer-events:none}.selection-band{fill:#edf3ff;opacity:.7}.plot-hit,.axis-hit{fill:transparent}.plot-hit{cursor:grab}.axis-hit{cursor:ns-resize}.cursor-hit{cursor:ew-resize}.empty-chart{fill:#617084}
.chart-tooltip{position:absolute;z-index:3;pointer-events:none;background:#fff;color:#202c3b;border:1px solid #e1e7ef;border-radius:5px;padding:8px 10px;box-shadow:0 3px 12px #202c3b18;font:12px/1.7 "Consolas","Microsoft YaHei",monospace;max-width:100%;overflow-wrap:anywhere}.chart-tooltip strong{font-weight:500}
.analysis-content{margin-top:10px;border-top:1px solid #e1e7ef;padding-top:10px}.analysis-grid{display:grid;grid-template-columns:minmax(260px,320px) minmax(240px,300px);justify-content:start;gap:24px}.analysis-grid h3{font-size:12px;margin-bottom:5px}.analysis-grid table{width:100%;border-collapse:collapse;table-layout:fixed;font-size:12px;font-variant-numeric:tabular-nums}.analysis-grid th{font-size:11px;font-weight:400;color:#617084;text-align:right;white-space:nowrap}.analysis-grid td{text-align:right;padding:4px 0;white-space:nowrap}.analysis-grid th:first-child,.analysis-grid td:first-child{text-align:left;width:39%}.analysis-grid td:not(:first-child){font-family:"Consolas",monospace}.cursor-input{display:inline-flex;align-items:center;gap:5px;font-size:12px}.cursor-input input{width:96px;min-height:26px;padding:2px 4px;margin:0;font:12px "Consolas",monospace}
.analysis-total{display:flex;justify-content:flex-start;gap:10px 28px;flex-wrap:wrap;margin-top:8px;color:#617084;font-size:12px}.analysis-total strong{font:500 17px "Bahnschrift","Consolas",monospace;color:#202c3b;margin-left:6px}.analysis-warning{font-size:11px;color:#89600a;margin-top:7px}.analysis-note{font-size:11px;color:#617084;margin-top:6px}
.narrow .chart-readings{left:16px;right:12px;gap:12px}.narrow .four-readings{grid-template-columns:repeat(2,minmax(0,1fr))}.narrow .analysis-grid{grid-template-columns:minmax(0,320px);gap:14px}.narrow .reading-number{font-size:30px}.narrow .four-readings .reading-number{font-size:26px}.tight .reading-number{font-size:22px;letter-spacing:-.6px}.tight .reading-number small{font-size:11px;margin-left:4px}.tight .reading-label{font-size:11px}.tight .line-swatch{width:12px}.tight .channel-adjust label{grid-template-columns:32px 68px;gap:4px}.tight .channel-adjust input[type=number]{width:68px}.tight .channel-select{font-size:11px;padding:3px 4px}.tight .channel-heading{gap:4px}.tight .chart-readings{left:0;right:0;gap:10px}.tight .four-readings .reading-number{font-size:24px}
@media(pointer:coarse){.channel-select,.curve-toggle{min-height:40px}.channel-adjust input[type=number],.cursor-input input{font-size:16px;min-height:36px}.analysis-switch{min-height:40px}}
</style>
