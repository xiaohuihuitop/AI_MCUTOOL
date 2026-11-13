import type { Sample } from './api'

/** AI:沿用既有曲线连续性判据，超过此间隔的样本不连接、不积分，单位秒。 */
export const MAX_SAMPLE_GAP = 2.5
export type Point = { t: number; value: number | null; breakBefore: boolean }
export type IntervalStats = { min: number; max: number; average: number; integral: number; duration: number }
export type Domain = { low: number; high: number }

/** AI:筛选指定设备、启动和通道并换算显示单位，重复时间保留较新记录。
 * @param samples 带设备身份的原始历史。
 * @param channel 通道名，电池电流从 A 转为 mA，其余保持 V。
 * @param deviceId 当前工具身份。
 * @param bootId 当前启动身份。
 * @returns 按设备采样秒数排序的读数，无效质量保留为断点。
 */
export function seriesFor(samples: Sample[], channel: string, deviceId: string, bootId: string): Point[] {
  const rows = samples.filter(row => row.channel === channel && row.device_id === deviceId && row.boot_id === bootId).sort((a, b) => a.cursor - b.cursor)
  const points = new Map<number, Point>()
  for (const row of rows) {
    const usable = row.value !== null && Number.isFinite(row.value) && ['uncalibrated', 'calibrated', 'outside_calibrated_range'].includes(row.quality)
    const t = row.t_us / 1e6
    points.set(t, { t, value: usable ? row.value! * (channel === 'battery_i' ? 1000 : 1) : null, breakBefore: Boolean(row.break_before || points.get(t)?.breakBefore) })
  }
  return [...points.values()].sort((a, b) => a.t - b.t)
}

/** AI:只在相邻有效、连续采样之间插值，边界之外及缺口内不估算。
 * @param points 按时间升序的通道数据。
 * @param time 查询的设备采样秒数。
 * @returns 对应显示单位的读数，缺乏有效依据时为 null。
 */
export function valueAt(points: Point[], time: number): number | null {
  let low = 0, high = points.length
  while (low < high) { const mid = (low + high) >>> 1; if (points[mid].t < time) low = mid + 1; else high = mid }
  const right = points[low]
  if (right?.t === time) return right.value
  const left = points[low - 1]
  if (!left || !right || left.value === null || right.value === null || right.breakBefore || right.t - left.t > MAX_SAMPLE_GAP) return null
  return left.value + (right.value - left.value) * (time - left.t) / (right.t - left.t)
}

/** AI:计算完整区间的极值、时间加权平均和梯形积分，遇到缺口明确不给结果。
 * @param points 单一通道、单一设备启动的数据。
 * @param start A 游标绝对采样秒数。
 * @param end B 游标绝对采样秒数，必须大于 A。
 * @returns 完整区间结果或 null；电流积分单位为 mA·s，除以 3600 得到带符号 mAh。
 */
export function intervalStats(points: Point[], start: number, end: number): IntervalStats | null {
  if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start) return null
  const first = valueAt(points, start), last = valueAt(points, end)
  if (first === null || last === null) return null
  const rows = [{ t: start, value: first, breakBefore: false }, ...points.filter(point => point.t > start && point.t < end), { t: end, value: last, breakBefore: points.some(point => point.t === end && point.breakBefore) }]
  let integral = 0, min = first, max = first
  for (let index = 1; index < rows.length; index++) {
    const left = rows[index - 1], right = rows[index], dt = right.t - left.t
    if (left.value === null || right.value === null || right.breakBefore || dt > MAX_SAMPLE_GAP) return null
    integral += (left.value + right.value) * dt / 2
    min = Math.min(min, right.value); max = Math.max(max, right.value)
  }
  return { min, max, average: integral / (end - start), integral, duration: end - start }
}

/** AI:为有效数据生成带留白的纵轴，仅用于显示布局。
 * @param points 单位已经换算的通道数据。
 * @param padding 最小留白，对应通道显示单位。
 * @returns 数据范围；无有效样本时为 null。
 */
export function dataDomain(points: Point[], padding: number): Domain | null {
  const values = points.filter(point => point.value !== null).map(point => point.value!)
  if (!values.length) return null
  const low = Math.min(...values), high = Math.max(...values), margin = Math.max((high - low) * .15, padding)
  return { low: low - margin, high: high + margin }
}

/** AI:按实际时间生成折线，缺口、无效值和已知丢样处断开。
 * @param points 升序通道数据。
 * @param x 秒数到横坐标的变换。
 * @param y 读数到纵坐标的变换。
 * @returns SVG 路径，独立片段使用 M 开始。
 */
export function linePath(points: Point[], x: (time: number) => number, y: (value: number) => number): string {
  let path = '', previous: Point | null = null
  for (const point of points) {
    if (point.value === null) { previous = null; continue }
    const join = previous && !point.breakBefore && point.t - previous.t <= MAX_SAMPLE_GAP
    path += `${join ? 'L' : 'M'}${x(point.t).toFixed(2)},${y(point.value).toFixed(2)} `
    previous = point
  }
  return path
}

/** AI:限制显示坐标或游标在合法范围内。
 * @param value 输入值。
 * @param low 下界。
 * @param high 上界。
 * @returns 限制后的数值。
 */
export function clamp(value: number, low: number, high: number): number { return Math.max(low, Math.min(high, value)) }
