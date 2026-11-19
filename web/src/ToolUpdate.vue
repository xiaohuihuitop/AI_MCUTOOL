<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { desktopCommand } from './desktop'
import { version as current } from '../package.json'

type Status = {phase:'idle'|'checking'|'current'} | {phase:'downloading';version:string;received:number;total:number} |
  {phase:'ready'|'installing';version:string} | {phase:'failed';message:string;cached_version:string|null}
const status = ref<Status>({phase:'idle'})
const deferred = ref('')
const error = ref('')
let timer: ReturnType<typeof setTimeout> | undefined
let live = true

/** AI:读取原生下载进度，页面退出后结束刷新。@returns 本次读取完成。 */
async function refresh() {
  try {
    const next = await desktopCommand<Status>('desktop_update_status')
    if (next.phase === 'checking') deferred.value = ''
    status.value = next
  } catch (e) { error.value = e instanceof Error ? e.message : '无法读取更新状态' }
  if (live) timer = setTimeout(refresh, status.value.phase === 'downloading' ? 350 : 1500)
}
/** AI:对当前可见版本明确发起安装。@param version 用户选择的版本。@returns 安装交接结果。 */
async function install(version: string) {
  error.value = ''
  try { await desktopCommand('desktop_install_update', {version}) }
  catch (e) { error.value = e instanceof Error ? e.message : '工具更新失败' }
}
onMounted(refresh)
onBeforeUnmount(()=>{ live = false; clearTimeout(timer) })
</script>
<template>
  <section v-if="status.phase==='downloading' || status.phase==='ready' || status.phase==='installing' || status.phase==='failed' || error" class="tool-update" aria-label="工具更新">
    <template v-if="status.phase==='downloading'">正在下载工具 {{status.version}} <progress :value="status.received" :max="status.total"/>{{ Math.floor(status.received*100/status.total) }}%</template>
    <template v-else-if="status.phase==='ready'">
      <span>工具 {{current}} → {{status.version}}</span>
      <button v-if="deferred===status.version" class="text-button" @click="deferred=''">查看已下载更新</button>
      <template v-else><button class="button primary" @click="install(status.version)">立即安装</button><button class="text-button" @click="deferred=status.version">稍后</button></template>
    </template>
    <template v-else-if="status.phase==='installing'">正在安装工具 {{status.version}}</template>
    <template v-else-if="status.phase==='failed'">
      <span>{{status.message}}</span><button class="text-button" @click="error='';desktopCommand('desktop_prepare_update')">重新检查</button>
      <button v-if="status.cached_version" class="button" @click="install(status.cached_version)">安装已下载的 {{status.cached_version}}</button>
    </template>
    <span v-if="error && (status.phase!=='failed' || error!==status.message)" role="alert">{{error}}</span>
  </section>
</template>
<style scoped>
.tool-update { display:flex; align-items:center; flex-wrap:wrap; gap:12px; padding:8px 22px; border-bottom:1px solid var(--line); background:white; font-size:13px }
.tool-update progress { max-width:8rem }
</style>
