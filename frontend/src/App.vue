<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import CoastScene from './components/CoastScene.vue'
import { timeOfDay } from './scene/motion.js'
const hour = ref(12)
const covered = ref(true)
const playing = ref(false)
const coast = ref(null)
let sceneTime = 12
let frame = 0
let previous = null
let lastUi = 0
let lastPalette = 0
function tick(now) {
  if (previous !== null && !document.hidden) {
    // Preserve the existing 240-second day, using elapsed time at screen cadence.
    sceneTime += (now - previous) / 10000
    const updatePalette = now - lastPalette >= 80
    coast.value?.setTime(sceneTime, updatePalette)
    if (updatePalette) lastPalette = now
    if (now - lastUi >= 100) { hour.value = timeOfDay(sceneTime); lastUi = now }
  }
  previous = now
  frame = requestAnimationFrame(tick)
}
function seek(event) {
  playing.value = false
  sceneTime = Math.floor(sceneTime / 24) * 24 + Number(event.target.value)
  hour.value = timeOfDay(sceneTime)
  coast.value?.setTime(sceneTime)
}
function resetFrameTime() { previous = null }
watch(playing, value => {
  cancelAnimationFrame(frame)
  previous = null
  if (value) frame = requestAnimationFrame(tick)
  else { hour.value = timeOfDay(sceneTime); coast.value?.setTime(sceneTime) }
})
onMounted(() => {
  document.addEventListener('visibilitychange', resetFrameTime)
})
onUnmounted(() => {
  cancelAnimationFrame(frame)
  document.removeEventListener('visibilitychange', resetFrameTime)
})
const timeLabel = computed(() => `${String(Math.floor(hour.value)).padStart(2, '0')}:${String(Math.floor((hour.value % 1) * 60)).padStart(2, '0')}`)
</script>

<template>
  <main class="coast-study">
    <CoastScene ref="coast" />
    <Transition name="glass">
      <section v-if="covered" class="content-placeholder" aria-label="中央内容区域占位"></section>
    </Transition>
    <form class="study-controls" aria-label="场景预览" @submit.prevent>
      <span class="study-name">海 岸</span><span class="divider"></span>
      <label for="time">时间 <output>{{ timeLabel }}</output></label>
      <input id="time" :value="hour" type="range" min="0" max="23.99" step="0.01" aria-label="预览一天中的光线" @input="seek" />
      <button type="button" :aria-pressed="playing" @click="playing = !playing">{{ playing ? '暂停昼夜' : '播放昼夜' }}</button>
      <button type="button" :aria-pressed="covered" @click="covered = !covered">{{ covered ? '查看全景' : '显示遮挡' }}</button>
    </form>
  </main>
</template>

<style>
* { box-sizing: border-box; }
html, body, #app { margin: 0; width: 100%; min-height: 100%; }
body { font-family: 'Microsoft YaHei', system-ui, sans-serif; }
button, input { font: inherit; }
.coast-study { height: 100svh; min-height: 480px; position: relative; overflow: hidden; background: #aacbd1; }
.content-placeholder { position: absolute; top: 4%; bottom: 11%; left: 29%; width: 42%; border: 1px solid rgb(255 255 255 / 45%); border-radius: 16px; background: rgb(248 250 247 / 77%); backdrop-filter: blur(22px); box-shadow: 0 16px 65px rgb(25 58 67 / 7%); }
.study-controls { position: absolute; bottom: 24px; left: 50%; transform: translateX(-50%); display: flex; align-items: center; gap: 18px; height: 46px; padding: 0 10px 0 20px; white-space: nowrap; color: #344f57; background: rgb(248 250 247 / 88%); border: 1px solid rgb(255 255 255 / 65%); border-radius: 30px; box-shadow: 0 4px 24px #233f4d12; backdrop-filter: blur(16px); font-size: 11px; }
.study-name { font-size: 12px; letter-spacing: 3px; }
.divider { height: 14px; width: 1px; background: #344f5726; }
.study-controls label { display: flex; gap: 10px; align-items: center; }
.study-controls output { font-variant-numeric: tabular-nums; min-width: 34px; }
.study-controls input { width: 116px; height: 3px; accent-color: #597b7e; cursor: pointer; }
.study-controls button { border: 0; background: #e3eae5; border-radius: 20px; padding: 8px 14px; cursor: pointer; color: #344f57; font-size: 11px; }
.study-controls button:hover { background: #d4e1db; }
.study-controls button:focus-visible, .study-controls input:focus-visible { outline: 2px solid #344f57; outline-offset: 4px; }
.glass-enter-active, .glass-leave-active { transition: opacity .35s; }
.glass-enter-from, .glass-leave-to { opacity: 0; }
@media (max-width: 700px) { .content-placeholder { left: 18%; width: 64%; top: 5%; bottom: 15%; } .study-controls { gap: 8px; bottom: 18px; padding-left: 12px; } .study-name, .divider { display: none; } .study-controls input { width: 50px; } .study-controls button { padding: 8px 10px; } }
</style>
