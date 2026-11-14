import { test, expect } from '@playwright/test'
import { ChannelHistory, WaveformHistory, waveformCsv } from '../src/waveform'
import { dataDomain, intervalStats, linePath } from '../src/measurement'
import type { Sample } from '../src/api'

/** AI:构造10Hz确定值样本。@param tick 100ms序号。@param value 安培值。@param changes 特殊测试字段。@returns 原始样本。 */
function sample(tick:number,value=.012,changes:Partial<Sample>={}):Sample {
  return {channel:'battery_i',value,nominal:value,unit:'A',quality:'uncalibrated',t_us:tick*100000,cursor:tick+1,device_id:'TEST',boot_id:'BOOT',...changes}
}

test('四小时10Hz保留完整数据、准确积分、绘图有界且CSV包含所有原始样本',()=>{
  const history=new ChannelHistory('battery_i')
  for(let tick=0;tick<=144000;tick++) history.append(sample(tick))
  expect(history.length).toBe(144001)
  expect(intervalStats(history,0,14400)!.integral/3600).toBeCloseTo(48,8)
  expect(dataDomain(history,.1)).toEqual({low:11.9,high:12.1})
  const path=linePath(history,t=>t/14400*900,v=>v,{low:0,high:14400})
  expect(path.length).toBeLessThan(65000)
  const csv=waveformCsv([history],'TEST','BOOT',0).join('')
  expect(csv.trim().split('\n')).toHaveLength(144002)
  expect(csv).toContain('"14400.000000","14400.000000","battery_i","0.012","A"')
  history.append(sample(144001))
  expect(history.evicted).toBe(true)
  expect(intervalStats(history,0,14400)).toBeNull()
  expect(intervalStats(history,.1,14400.1)!.integral/3600).toBeCloseTo(48,8)
})

test('像素压缩保留单点峰谷和缺口，暂停快照不受覆盖及清空影响',()=>{
  const history=new ChannelHistory('battery_i',20)
  for(let tick=0;tick<20;tick++) history.append(sample(tick,tick===5?.1:tick===6?-.05:.012,{break_before:tick===10}))
  const frozen=history.snapshot(),path=linePath(history,()=>0,v=>v)
  expect(path).toContain('100.00');expect(path).toContain('-50.00')
  expect(path.split('M')).toHaveLength(3)
  expect(intervalStats(history,0,1.9)).toBeNull()
  history.clear();history.append(sample(20))
  expect(frozen.length).toBe(20);expect(frozen.at(5)?.value).toBe(100)
})

test('清空不回放旧数据，不同设备启动不会拼接，异常质量按原样导出',()=>{
  const history=new WaveformHistory(['battery_i'])
  history.select('runtime/TEST/BOOT','TEST','BOOT');history.append([sample(0),sample(1)])
  history.clear();history.append([sample(0),sample(1),sample(2)])
  expect(history.channels[0].length).toBe(1)
  history.select('runtime/TEST/NEW','TEST','NEW');history.append([sample(3),sample(4,0,{boot_id:'NEW',value:null,quality:'sensor_error',break_before:true})])
  expect(history.channels[0].length).toBe(1)
  expect(history.channels[0].at(0)?.value).toBeNull()
  expect(waveformCsv(history.channels,'TEST','NEW',.4).join('')).toContain('"battery_i","","A","sensor_error","1"')
})
