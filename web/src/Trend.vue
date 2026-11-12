<script setup lang="ts">
import { computed, onMounted, onBeforeUnmount, ref } from 'vue'
import type { Sample } from './api'
const props = defineProps<{ samples: Sample[]; channel: string }>()
const container = ref<HTMLDivElement | null>(null)
const width = ref(900)
let observer: ResizeObserver | undefined
onMounted(() => {
  // AI:使用实际容器宽度绘图，避免窄屏把坐标文字整体缩小到不可读。
  observer = new ResizeObserver(entries => { width.value = Math.max(280, entries[0].contentRect.width) })
  if (container.value) observer.observe(container.value)
})
onBeforeUnmount(() => observer?.disconnect())
const chart = computed(() => {
  const rows = props.samples.filter(s => s.channel === props.channel).slice(-120)
  const factor = props.channel === 'battery_i' ? 1000 : 1
  const valid = rows.filter(s => s.value !== null)
  if (valid.length < 2) return null
  const lastBoot = valid.at(-1)!.boot_id
  const current = rows.filter(s => s.boot_id === lastBoot)
  const points = current.filter(s => s.value !== null)
  if (points.length < 2) return null
  const values = points.map(s => s.value! * factor)
  let low = Math.min(...values), high = Math.max(...values)
  const margin = Math.max((high - low) * .15, props.channel === 'battery_i' ? .1 : .01)
  low -= margin; high += margin
  const first = current[0].t_us, last = current.at(-1)!.t_us
  if (last <= first) return null
  let path = '', previous = 0, connected = false
  for (const row of current) {
    if (row.value === null) { connected = false; continue }
    const x = 58 + (row.t_us - first) / (last - first) * (width.value - 80)
    const y = 20 + (high - row.value * factor) / (high - low) * 180
    const join = connected && row.t_us - previous <= 2500000
    path += `${join ? 'L' : 'M'}${x.toFixed(2)},${y.toFixed(2)} `
    previous = row.t_us; connected = true
  }
  return {path, low, high, duration: Math.round((last - first) / 1000000), unit: factor === 1000 ? 'mA' : 'V'}
})
</script>

<template>
  <div ref="container" class="trend-wrap">
    <svg v-if="chart" :viewBox="`0 0 ${width} 236`" role="img" :aria-label="`${channel}测量趋势，时间跨度${chart.duration}秒`">
      <g v-for="i in 5" :key="i"><line x1="58" :x2="width-22" :y1="20+(i-1)*45" :y2="20+(i-1)*45" stroke="#dce5e9" stroke-dasharray="3 4"/><text x="48" :y="24+(i-1)*45" text-anchor="end" fill="#647783" font-size="12">{{ (chart.high-(chart.high-chart.low)*(i-1)/4).toFixed(2) }}</text></g>
      <path :d="chart.path" fill="none" stroke="#177e89" stroke-width="2.3" stroke-linecap="round"/>
      <text x="58" y="226" fill="#647783" font-size="12">{{ chart.duration }} 秒前</text><text :x="width-22" y="226" text-anchor="end" fill="#647783" font-size="12">最近采样 · {{ chart.unit }}</text>
    </svg>
    <div v-else class="empty-trend"><span class="empty-cross">＋</span><strong>等待连续采样</strong><span>至少两份有效读数后显示趋势</span></div>
  </div>
</template>
