<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { api, type Snapshot } from './api'

const props = defineProps<{state:Snapshot|null; live:boolean; canWrite:boolean}>()
const update = computed(() => props.state?.firmware_update)
const board = computed(() => props.state?.device)
const error = ref(''), deferred = ref(false), submitting = ref(false)
const confirmation = ref<{device_id:string; boot_id:string; version:string} | null>(null)
const deviceKey = computed(() => props.live && props.state?.connected && !props.state.test_mode
  ? JSON.stringify([board.value?.device_id, board.value?.boot_id]) : '')
const relevant = computed(() => !!update.value?.target && board.value?.device_id === update.value.target.device_id &&
  (board.value?.boot_id === update.value.target.boot_id || board.value?.boot_id === update.value.new_boot_id ||
   update.value.phase === 'reconnecting' || (!props.state?.connected && update.value.phase === 'failed')))
const usb = computed(() => props.state?.connection?.kind === 'usb')
const version = computed(() => update.value?.phase === 'ready' ? update.value.version :
  update.value?.phase === 'failed' ? update.value.cached_version : undefined)
const choice = computed(() => {
  const target = update.value?.target
  if (!deviceKey.value || !relevant.value || !version.value || target?.boot_id !== board.value?.boot_id || !target) return null
  return {device_id:target.device_id, boot_id:target.boot_id, version:version.value}
})
watch(() => JSON.stringify(choice.value), () => { confirmation.value = null; deferred.value = false })

/** AI:让共享后台核对当前连接的板。@param retry 用户手动重试。@returns 本次请求完成。 */
async function prepare(retry = false) {
  const key = deviceKey.value
  error.value = ''
  try { await api('/api/firmware/prepare' + (retry ? '?retry=true' : ''), 'POST') }
  catch (e) { if (deviceKey.value === key) error.value = e instanceof Error ? e.message : '固件检查失败' }
}
watch(deviceKey, key => {
  deferred.value = false
  error.value = ''
  if (key && update.value && !['installing','reconnecting'].includes(update.value.phase) &&
      !(relevant.value && update.value.new_boot_id === board.value?.boot_id)) void prepare()
}, {immediate:true})

/** AI:用当前提示里的身份和目标版本提交一次升级。@returns 安装请求受理或错误。 */
async function install() {
  const target = confirmation.value
  if (!target || JSON.stringify(target) !== JSON.stringify(choice.value) || submitting.value) return
  submitting.value = true
  error.value = ''
  try {
    await api('/api/firmware/install','POST',target)
    confirmation.value = null
  } catch (e) { error.value = e instanceof Error ? e.message : '固件升级失败' }
  finally { submitting.value = false }
}
</script>
<template>
  <section v-if="live && (error || (relevant && update && (state?.connected || ['installing','reconnecting','failed'].includes(update.phase)) && !['idle','current'].includes(update.phase)))" class="firmware-update" aria-label="固件更新" aria-live="polite">
    <template v-if="update?.phase==='checking'">正在检查固件更新…</template>
    <template v-else-if="update?.phase==='downloading'">正在下载固件 {{update.version}} <progress :value="update.received" :max="update.total"/></template>
    <template v-else-if="choice && update">
      <span v-if="update.phase==='failed'">{{update.message}}</span>
      <strong>固件 {{update.target?.firmware_version}} → {{version}}</strong>
      <button v-if="deferred" class="text-button" @click="deferred=false">查看已下载固件</button>
      <template v-else>
        <span v-if="!usb">通过 USB 连接这块工具板后可升级。</span>
        <span v-else-if="!canWrite">先在工作台申请操作权。</span>
        <template v-if="confirmation">
          <span>{{confirmation.device_id}} 将重启，供电、充电和按键将断开。升级期间请保持 USB 连接。</span>
          <button class="button primary" :disabled="!canWrite || !usb || submitting" @click="install">确认升级</button>
          <button class="text-button" :disabled="submitting" @click="confirmation=null">取消</button>
        </template>
        <template v-else>
          <button class="button primary" :disabled="!canWrite || !usb" @click="confirmation=choice">{{update.cached_version ? '安装已下载固件' : '升级固件'}}</button>
          <button class="text-button" @click="deferred=true">稍后</button>
        </template>
      </template>
      <button v-if="update.phase==='failed' && !confirmation" class="text-button" @click="prepare(true)">重新检查固件</button>
    </template>
    <template v-else-if="update?.phase==='installing'">正在写入并校验固件 {{update.version}}，请保持 USB 连接。</template>
    <template v-else-if="update?.phase==='reconnecting'">正在重连 {{update.target?.device_id}} 并读取固件版本…</template>
    <template v-else-if="update?.phase==='succeeded'">已重连 {{update.target?.device_id}}，板上固件 {{update.version}}。</template>
    <template v-else-if="update?.phase==='failed'">
      <span>{{update.message}}</span><button v-if="deviceKey" class="text-button" @click="prepare(true)">重新检查固件</button>
    </template>
    <span v-if="error" role="alert">{{error}}</span>
  </section>
</template>
<style scoped>
.firmware-update { display:flex; align-items:center; flex-wrap:wrap; gap:12px; padding:8px 22px; border-bottom:1px solid var(--line); background:white; font-size:13px }
.firmware-update progress { max-width:8rem }
</style>
