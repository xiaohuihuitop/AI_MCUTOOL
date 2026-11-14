import type { Sample } from './api'
import type { Point, PointSource } from './measurement'

/** AI:以10Hz保留最近四小时，额外一份样本用于首尾区间插值。 */
export const WAVEFORM_SECONDS = 4 * 60 * 60
export const WAVEFORM_CAPACITY = WAVEFORM_SECONDS * 10 + 1
const usableQualities = new Set(['uncalibrated', 'calibrated', 'outside_calibrated_range'])

/** AI:单通道紧凑环形历史，避免长时间采集产生大量响应式对象。 */
export class ChannelHistory implements PointSource {
  private times: Float64Array
  private values: Float64Array
  private quality: Uint16Array
  private breaks: Uint8Array
  private names: string[] = []
  private start = 0
  length = 0
  evicted = false

  /** AI:创建通道存储。@param channel 原始通道名。@param capacity 最大样本数。@returns 通道实例。 */
  constructor(readonly channel: string, readonly capacity = WAVEFORM_CAPACITY) {
    this.times = new Float64Array(capacity)
    this.values = new Float64Array(capacity)
    this.quality = new Uint16Array(capacity)
    this.breaks = new Uint8Array(capacity)
  }

  /** AI:定位逻辑索引对应的环形位置。@param index 升序逻辑索引。@returns 数组位置。 */
  private position(index: number) { return (this.start + index) % this.capacity }

  /** AI:读取原始采样秒数。@param index 逻辑索引。@returns 设备启动后的秒数。 */
  time(index: number) { return this.times[this.position(index)] }

  /** AI:追加单个新样本，同一时间保留新值并保留断点。@param sample 原始采样。@returns 无。 */
  append(sample: Sample) {
    const time = sample.t_us / 1e6
    if (!Number.isFinite(time) || (this.length && time < this.time(this.length - 1))) return
    let index: number
    const replace = this.length > 0 && time === this.time(this.length - 1)
    if (replace) index = this.position(this.length - 1)
    else {
      if (this.length === this.capacity) { this.start = (this.start + 1) % this.capacity; this.length--; this.evicted = true }
      index = this.position(this.length++)
    }
    let quality = this.names.indexOf(sample.quality)
    if (quality < 0) { quality = this.names.length; this.names.push(sample.quality) }
    this.times[index] = time
    this.values[index] = sample.value === null ? NaN : sample.value
    this.quality[index] = quality
    this.breaks[index] = Number(Boolean(sample.break_before || (replace && this.breaks[index])))
    while (this.length > 1 && time - this.time(0) > WAVEFORM_SECONDS) {
      this.start = (this.start + 1) % this.capacity; this.length--; this.evicted = true
    }
  }

  /** AI:读取供图形和统计使用的点，无效质量不参与计算。@param index 升序逻辑索引。@returns 显示单位的点，越界为undefined。 */
  at(index: number): Point | undefined {
    if (index < 0 || index >= this.length) return undefined
    const slot = this.position(index), value = this.values[slot]
    return { t: this.times[slot], value: Number.isFinite(value) && usableQualities.has(this.names[this.quality[slot]]) ? value * (this.channel === 'battery_i' ? 1000 : 1) : null, breakBefore: Boolean(this.breaks[slot]) }
  }

  /** AI:复制当前历史用于暂停或导出，后续滚动不会改变该快照。@returns 独立通道历史。 */
  snapshot() {
    const copy = new ChannelHistory(this.channel, Math.max(1, this.length))
    copy.names = [...this.names]; copy.length = this.length; copy.evicted = this.evicted
    for (let i = 0; i < this.length; i++) {
      const slot = this.position(i)
      copy.times[i] = this.times[slot]; copy.values[i] = this.values[slot]
      copy.quality[i] = this.quality[slot]; copy.breaks[i] = this.breaks[slot]
    }
    return copy
  }

  /** AI:清空当前显示历史，复用已分配内存。@returns 无。 */
  clear() { this.start = 0; this.length = 0; this.evicted = false }

  /** AI:生成CSV原始数值字段，电流保持安培，缺失值留空。@param index 逻辑索引。@param origin 本图时间起点。@returns 该点的可转义字段。 */
  csvRow(index: number, origin: number): (string | number)[] {
    const slot = this.position(index), value = this.values[slot]
    return [this.times[slot].toFixed(6), (this.times[slot] - origin).toFixed(6), this.channel, Number.isFinite(value) ? value : '', this.channel === 'battery_i' ? 'A' : 'V', this.names[this.quality[slot]], this.breaks[slot]]
  }
}

/** AI:按图表管理历史与去重位置，清空显示不倒退数据游标。 */
export class WaveformHistory {
  readonly channels: ChannelHistory[]
  private cursor = 0
  deviceId = ''
  bootId = ''
  context = ''

  /** AI:创建一组独立波形。@param keys 该组通道名。@param capacity 测试或生产缓存上限。@returns 波形实例。 */
  constructor(keys: string[], capacity = WAVEFORM_CAPACITY) { this.channels = keys.map(key => new ChannelHistory(key, capacity)) }

  /** AI:改变设备、启动或后台时重置历史及游标。@param context 后台/设备/启动身份。@param deviceId 设备。@param bootId 启动。@returns 是否重置。 */
  select(context: string, deviceId: string, bootId: string) {
    if (this.context === context) return false
    this.context = context; this.deviceId = deviceId; this.bootId = bootId; this.cursor = 0; this.clear()
    return true
  }

  /** AI:只追加属于当前身份且未读过的样本。@param samples 按公共游标升序的一批数据。@returns 是否增加历史。 */
  append(samples: Sample[]) {
    let changed = false
    for (const sample of samples) {
      if (sample.cursor <= this.cursor || sample.device_id !== this.deviceId || sample.boot_id !== this.bootId) continue
      this.cursor = sample.cursor
      const channel = this.channels.find(channel => channel.channel === sample.channel)
      if (channel) { channel.append(sample); changed = true }
    }
    return changed
  }

  /** AI:清空本组显示，不重置读取位置以免回放旧样本。@returns 无。 */
  clear() { this.channels.forEach(channel => channel.clear()) }
}

/** AI:转义CSV字段并阻止设备文本被表格软件解释为公式。@param value 字段。@returns 带双引号的CSV字段。 */
function csvField(value: string | number) {
  let text = String(value)
  if (typeof value === 'string' && /^[=+\-@\t\r]/.test(text)) text = "'" + text
  return '"' + text.replace(/"/g, '""') + '"'
}

/** AI:导出组内全部原始样本，按采样时间合并，生成期间仅用冻结快照。
 * @param channels 独立快照，包含隐藏通道。
 * @param deviceId 设备身份。
 * @param bootId 启动身份。
 * @param origin 本图时间起点。
 * @returns UTF-8无BOM的CSV文本块。
 */
export function waveformCsv(channels: ChannelHistory[], deviceId: string, bootId: string, origin: number): string[] {
  const chunks = ['设备,启动,采样时间_s,相对时间_s,通道,数值,单位,质量,前方断点\r\n']
  const indices = channels.map(() => 0)
  let lines: string[] = []
  while (true) {
    let next = -1
    for (let i = 0; i < channels.length; i++) if (indices[i] < channels[i].length && (next < 0 || channels[i].time(indices[i]) < channels[next].time(indices[next]))) next = i
    if (next < 0) break
    lines.push([deviceId, bootId, ...channels[next].csvRow(indices[next]++, origin)].map(csvField).join(',') + '\r\n')
    if (lines.length === 4096) { chunks.push(lines.join('')); lines = [] }
  }
  if (lines.length) chunks.push(lines.join(''))
  return chunks
}
