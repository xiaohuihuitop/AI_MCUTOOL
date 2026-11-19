<script setup lang="ts">
import { computed, onMounted, onBeforeUnmount, ref } from 'vue'
import type { Snapshot } from './api'

const props = defineProps<{ snapshot: Snapshot | null; live: boolean; receivedAt: number }>()
const now = ref(performance.now())
let clock: ReturnType<typeof setInterval>
onMounted(() => { clock = setInterval(() => { now.value = performance.now() }, 250) })
onBeforeUnmount(() => clearInterval(clock))
const age = computed(() => Math.max(0, now.value - props.receivedAt))
// AI:使用设备状态自己的身份，避免重启或更换设备时沿用旧快照。
const confirmed = computed(() => {
  const s = props.snapshot, board = s?.device_state
  if (!props.live || !s?.connected || !board || s.device_state_stale || age.value > 3000 ||
      !s.device.device_id || !s.device.boot_id || board.device_id !== s.device.device_id || board.boot_id !== s.device.boot_id) return null
  return board
})
const power = computed(() => confirmed.value?.power)
const charging = computed(() => confirmed.value?.charge)
const keyMask = computed(() => {
  const mask = confirmed.value?.keys_mask
  return Number.isInteger(mask) && mask >= 0 && mask <= 31 ? mask as number : null
})
const direction = computed(() => {
  const s = props.snapshot, i = s?.latest.battery_i
  if (!confirmed.value || !s || !i || i.device_id !== s.device.device_id || i.boot_id !== s.device.boot_id ||
      i.channel !== 'battery_i' || i.unit !== 'A' || i.stale !== false || !Number.isFinite(i.age_ms) ||
      i.age_ms! + age.value > 3000 || !['calibrated','uncalibrated'].includes(i.quality) ||
      i.value === null || !Number.isFinite(i.value)) return 0
  return Math.sign(i.value)
})
// AI:元件面坐标取自交付 PCB 布局及 Issue #7 的俯视预览。图中不显示器件位号。
const keys = [57,83,109,135,161]
const bottom = [{x:125,name:'可调电源'},{x:203,name:'真实电池'},{x:284,name:'产品供电'},
                {x:353,name:'产品充电'},{x:427,name:'充电器 5V'}]
const routes = computed(() => {
  const known = ['battery','external','off'].includes(power.value)
  const on = power.value === 'battery' || power.value === 'external'
  return [
    {id:'battery', d:'M203 355V342H284V355', active:power.value==='battery', known, dir:direction.value},
    {id:'external',d:'M125 355V324H284V355', active:power.value==='external', known, dir:direction.value},
    {id:'supply',d:'M284 417V474H507', active:on, known, dir:direction.value},
    {id:'charge',d:'M427 355V334H353V355 M353 417V442H507', active:charging.value===true, known:typeof charging.value==='boolean', dir:0}
  ]
})
</script>

<template>
  <section class="panel board-panel" aria-label="工具板实时状态">
    <div class="panel-title"><h2>工具板实时状态</h2><span class="hint">{{ confirmed ? '元件面俯视' : '状态未更新' }}</span></div>
    <div class="board-surface">
      <svg viewBox="15 15 640 490" role="img" aria-label="工具板供电、充电和五路按键触点状态">
        <defs>
          <g id="board-terminal"><rect x="-9" y="-6" width="18" height="12" rx="2" fill="#2b423c" stroke="#d1bb8f"/><circle cx="-4" r="2.3" fill="#e7ce9b"/><circle cx="4" r="2.3" fill="#e7ce9b"/></g>
        </defs>
        <rect x="86" y="32" width="396.5" height="349.3" rx="7" fill="#204f48" stroke="#153b36"/>
        <g fill="#455e54" stroke="#728c79" aria-hidden="true">
          <rect v-for="y in keys" :key="y" x="406" :y="y-5" width="20" height="10" rx="2"/>
          <rect v-for="y in [205,238,271,304]" :key="y" x="373" :y="y-4" width="13" height="8" rx="1"/>
          <rect x="273" y="277" width="23" height="12" rx="2"/><rect x="276" y="318" width="17" height="9" rx="1"/>
        </g>
        <rect x="126" y="48" width="84" height="74" rx="4" fill="#a4b4a9" stroke="#d3ddd1"/>
        <rect x="134" y="54" width="68" height="14" rx="2" fill="#5e796a"/>
        <text x="168" y="98" text-anchor="middle" class="chip-name">ESP32-S3</text>
        <text x="176" y="264" class="board-name">MCU TOOL</text>
        <g v-for="(name,k) in ['USB-C','DC 5V']" :key="name" :transform="`translate(0,${[192,263][k]})`">
          <rect x="84" y="-9" :width="k ? 70 : 46" height="18" rx="2" fill="#b2c4bb" stroke="#dce7df"/>
          <text x="76" y="5" text-anchor="end">{{name}}</text>
        </g>
        <g v-for="(y,k) in keys" :key="y" :transform="`translate(0,${y})`" :data-key="k+1"
           :data-contact="keyMask===null?'unknown':(keyMask & (1<<k))?'closed':'open'">
          <use href="#board-terminal" transform="translate(464 0) rotate(90)"/>
          <path d="M468 -4H491L507 0H526 M468 4H488L501 9H564V0H554" class="lead"/>
          <text v-if="keyMask===null" x="540" y="4" text-anchor="middle">?</text>
          <path v-else :d="(keyMask & (1<<k))?'M526 0H554':'M526 0L554 -10'" class="blade"/>
          <circle cx="526" r="2.6" class="contact"/><circle cx="554" r="2.6" class="contact"/>
          <text x="582" y="5">KEY{{ k+1 }}</text>
        </g>
        <g v-for="(y,k) in [203,236,269,302]" :key="y" :transform="`translate(0,${y})`">
          <use href="#board-terminal" transform="translate(464 0) rotate(90)"/>
          <path d="M471 0H518" class="lead"/><text x="526" y="5">电压 {{ k+1 }}</text>
        </g>
        <g transform="translate(472 358)"><rect x="-5" y="-10" width="10" height="20" fill="#2b423c" stroke="#d1bb8f"/>
          <circle v-for="y in [-5,0,5]" :key="y" :cy="y" r="1.5" fill="#e7ce9b"/>
          <path d="M6 0H46" class="lead"/><text x="54" y="5">目标串口</text></g>
        <g v-for="p in bottom" :key="p.name" :transform="`translate(${p.x} 362)`">
          <use href="#board-terminal"/><path d="M0 7V29" class="lead"/><text y="47" text-anchor="middle">{{p.name}}</text>
        </g>
        <g v-for="route in routes" :key="route.id" :data-route="route.id" :data-state="!route.known?'unknown':route.active?'on':'off'">
          <path :d="route.d" class="route"/>
          <path v-if="route.active && route.dir" :d="route.d" class="flow" :class="{reverse:route.dir<0}"/>
        </g>
        <rect x="507" y="420" width="130" height="76" rx="7" fill="#fff" stroke="#b5c9c5"/>
        <text x="627" y="437" text-anchor="end">被测设备</text>
        <circle cx="507" cy="442" r="3" fill="#a5651a"/><text x="518" y="456">充电口</text>
        <circle cx="507" cy="474" r="3" fill="#207e68"/><text x="518" y="486">电池口</text>
      </svg>
    </div>
  </section>
</template>

<style scoped>
.board-panel{margin-bottom:14px}
.board-surface{overflow-x:auto;background:#f3f7f6;border-radius:6px}
svg{display:block;width:100%;max-width:760px;min-width:440px;margin:auto}
text{font-family:inherit;font-size:14px;fill:#264a4b}
.chip-name{font-size:12px}.board-name{font-size:20px;font-weight:650;fill:#bbd2c2}
path{fill:none;stroke-linejoin:round;stroke-linecap:round}
.lead,.blade,.contact{stroke:#758b88;stroke-width:1.6}.blade{stroke-width:2.7}.contact{fill:#fff}
[data-contact=closed] :is(.lead,.blade,.contact){stroke:#14785c;stroke-width:2.5}
.route{stroke:#869791;stroke-width:1.6}
[data-state=unknown] .route{stroke-dasharray:2 5}
[data-state=on] .route{stroke:#4fae89;stroke-width:4}
[data-route=charge][data-state=on] .route{stroke:#bc803a}
.flow{stroke:#e3fcf0;stroke-width:2;stroke-dasharray:6 12;animation:board-flow .8s linear infinite}
.reverse{animation-direction:reverse}
@keyframes board-flow{to{stroke-dashoffset:-18}}
@media(prefers-reduced-motion:reduce){.flow{animation:none}}
</style>
