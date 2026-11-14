import { test, expect } from '@playwright/test'
import { intervalStats, linePath, seriesFor, valueAt, type Point } from '../src/measurement'
import type { Sample } from '../src/api'

/** AI:构造仅供测量算法验证的样本。@param time 秒数。@param value 安培读数。@param changes 覆盖的身份、质量或连续性字段。@returns 测试样本。 */
function sample(time: number, value: number | null, changes: Partial<Sample> = {}): Sample {
  return { channel:'battery_i',value,nominal:value,unit:'A',quality:'uncalibrated',t_us:time*1e6,device_id:'tool',boot_id:'boot',cursor:time+1,...changes }
}
/** AI:构造已经换算单位的通道数据。@param rows 时间与读数列表。@returns 升序测试点。 */
function points(rows: [number, number | null][]): Point[] { return rows.map(([t,value])=>({t,value,breakBefore:false})) }

test('测量按设备和启动隔离，电流只进行一次 A 到 mA 换算', () => {
  const rows = seriesFor([sample(0,.012),sample(1,.015,{boot_id:'old'}),sample(2,.02,{device_id:'other'}),sample(3,-.003)],'battery_i','tool','boot')
  expect(rows.map(row=>row.value)).toEqual([12,-3])
})

test('非均匀采样的区间平均值按时间加权，插值边界参与积分', () => {
  const rows = points([[0,10],[.1,20],[.3,40]])
  expect(intervalStats(rows,0,.3)?.average).toBeCloseTo(25,10)
  expect(intervalStats(rows,.05,.2)?.integral).toBeCloseTo(3.375,10)
  expect(valueAt(rows,4)).toBeNull()
})

test('净电量保留正负方向和毫安秒到毫安时的单位', () => {
  const rows = points([[0,20],[.1,-10],[.2,-10]])
  expect(intervalStats(rows,0,.2)?.integral).toBe(-.5)
  const constant = points([[0,12],[.2,12]])
  expect(intervalStats(constant,0,.2)!.integral/3600).toBeCloseTo(12*.2/3600,12)
})

test('缺点、无效点和显式丢样不能被曲线或统计跨过', () => {
  const cases = [points([[0,1],[3,2]]),points([[0,1],[1,null],[2,2]]),[{t:0,value:1,breakBefore:false},{t:1,value:2,breakBefore:true}]]
  for (const rows of cases) {
    expect(intervalStats(rows,rows[0].t,rows.at(-1)!.t)).toBeNull()
    expect(linePath(rows,x=>x,y=>y)).not.toContain('L')
  }
  expect(valueAt(cases[0],1)).toBeNull()
  expect(valueAt(cases[2],.5)).toBeNull()
  expect(intervalStats(points([[0,1],[1,2]]),1,1)).toBeNull()
})

test('过量程、传感器错误和无效校准保留断点，同时间重复读数去重', () => {
  const rows=seriesFor([sample(0,.01),sample(1,.02,{quality:'out_of_range'}),sample(2,.03,{quality:'sensor_error'}),sample(3,.04,{quality:'invalid_calibration'}),sample(4,.05),sample(4,.06,{cursor:20})],'battery_i','tool','boot')
  expect(rows.map(row=>row.value)).toEqual([10,null,null,null,60])
  expect(intervalStats(rows,0,4)).toBeNull()
})
