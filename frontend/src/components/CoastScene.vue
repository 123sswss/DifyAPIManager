<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import StarMap from './StarMap.vue'
import DeerSilhouette from './DeerSilhouette.vue'
import { STAR_DEGREES_PER_HOUR, timeOfDay, sunPosition, sunReflection } from '../scene/motion.js'
import { headlandPath, leftHeadlandPath, rightHeadlandPath, leftFoot, rightFoot } from '../scene/terrain.js'
import { leftCape, leftFaces, capeGrass, capeCracks, capeTransform, rightCape, rightFaces, wetBeach, dryBeach, waterArea, shoreline } from '../scene/landscape.js'
import { projectionLight, projectionMatrix } from '../scene/projections.js'
import { wavePaths } from '../scene/waves.js'
import { NIGHT_COLORS, nightAmount } from '../scene/lighting.js'
const props = defineProps({ animated: { type: Boolean, default: true } })
const motionPreference = window.matchMedia('(prefers-reduced-motion: reduce)')
const motionAllowed = ref(!motionPreference.matches)
const motionEnabled = computed(() => props.animated && motionAllowed.value)
function updateMotionPreference(event) { motionAllowed.value = !event.matches }
const paletteHour = ref(12)
const starRotation = ref(null)
const sun = ref(null)
const reflection = ref(null)
const scene = ref(null)
const deer = ref(null)
const wetEdge = ref(null)
const dryEdge = ref(null)
const foamEdge = ref(null)
const waterClip = ref(null)
const beachClip = ref(null)
let waveFrame = 0
let waveElapsed = 0
let wavePrevious = null
let waveLastPaint = -Infinity
function paintWaves() {
  const paths = wavePaths(waveElapsed)
  for (const [node, path] of [[wetEdge.value, paths.wet], [dryEdge.value, paths.dry], [foamEdge.value, paths.edge], [waterClip.value, paths.water], [beachClip.value, paths.wet]]) {
    if (node && node.getAttribute('d') !== path) node.setAttribute('d', path)
  }
}
function animateWaves(now) {
  if (wavePrevious !== null && !document.hidden) waveElapsed += now - wavePrevious
  wavePrevious = now
  // Keep the faster shore motion smooth while updating only boundary paths.
  if (!document.hidden && now - waveLastPaint >= 30) { paintWaves(); waveLastPaint = now }
  waveFrame = requestAnimationFrame(animateWaves)
}
function resetWaveClock() { wavePrevious = null }
function updateWaveAnimation() {
  cancelAnimationFrame(waveFrame)
  resetWaveClock()
  if (motionEnabled.value && scene.value) waveFrame = requestAnimationFrame(animateWaves)
}
watch(motionEnabled, updateWaveAnimation)
const aspect = ref(1)
const viewport = ref({ width: 1920, height: 1080 })
let observer
let projectionNodes = []
onMounted(() => {
  projectionNodes = Array.from(scene.value.querySelectorAll('[data-projection]')).map(node => ({
    node, base: Number(node.dataset.base), depth: Number(node.dataset.depth || 1),
    skew: Number(node.dataset.skew || 1), slope: Number(node.dataset.slope || 0),
    strength: Number(node.dataset.strength || 1), kind: node.dataset.projection,
  }))
  observer = new ResizeObserver(([entry]) => {
    aspect.value = (entry.contentRect.width / entry.contentRect.height) / (1920 / 1080)
    viewport.value = { width: entry.contentRect.width, height: entry.contentRect.height }
  })
  observer.observe(scene.value)
  setTime(12)
  paintWaves()
  updateWaveAnimation()
  motionPreference.addEventListener('change', updateMotionPreference)
  document.addEventListener('visibilitychange', resetWaveClock)
})
onUnmounted(() => {
  observer?.disconnect()
  motionPreference.removeEventListener('change', updateMotionPreference)
  cancelAnimationFrame(waveFrame)
  document.removeEventListener('visibilitychange', resetWaveClock)
})
const scaleX = computed(() => Math.min(1, 1 / aspect.value))
const scaleY = computed(() => Math.min(1, aspect.value))
// Separate pigments preserve the geometric planes across every time of day.
const stops = [
  { h: 0, c: ['#101e37','#34445e','#344e66','#263e56','#334d60','#59656e','#434e5c','#303e50','#283b4c','#536878','#122d40','#344b51'], sun: 0, stars: 1 },
  { h: 5, c: ['#49556f','#d2a69a','#c8b4ac','#798d9e','#96a5aa','#b9a89a','#958b88','#666e78','#536c75','#c2b9b2','#536e7c','#c7c7bb'], sun: .1, stars: .25 },
  { h: 7, c: ['#9dbdc8','#f5ddba','#e9d7b9','#76a8b2','#aacac6','#ead6b6','#c7b89f','#9d9f92','#7b9993','#fff3da','#739e9f','#c5cfb5'], sun: .9, stars: 0 },
  { h: 12, c: ['#8db9cd','#dfebe5','#dce9de','#6ea6b5','#9bc6c6','#e6d9bf','#bdb8a4','#919c94','#78938a','#f4f2de','#5f929a','#b6c2a0'], sun: 1, stars: 0 },
  { h: 16, c: ['#95b9c9','#f0dfbf','#ebd9b6','#76a5af','#a6c6c1','#e8d0a7','#c3ad91','#94988b','#7e9487','#fff0d3','#6e9697','#bfbd97'], sun: 1, stars: 0 },
  { h: 18.5, c: ['#7f91ac','#efb797','#efc29c','#8b9fab','#b9b7ad','#d5af91','#b5998b','#817e85','#747d80','#f6d9bd','#7b8b91','#b3a48e'], sun: .9, stars: 0 },
  { h: 20, c: ['#293a58','#9b8392','#aa9199','#5e748c','#7f8c9c','#999395','#7c7c87','#555f74','#4b6572','#aab4bd','#405e73','#869697'], sun: 0, stars: .65 },
  { h: 24, c: ['#101e37','#34445e','#344e66','#263e56','#334d60','#59656e','#434e5c','#303e50','#283b4c','#536878','#122d40','#344b51'], sun: 0, stars: 1 },
]
const names = ['sky-top','sky-bottom','haze','sea','shallows','sand','rock-light','rock-mid','rock-dark','turbine','wet-sand','grass']
const light = computed(() => {
  const h = Math.max(0, Math.min(24, paletteHour.value))
  const index = stops.findIndex((s, i) => i < stops.length - 1 && h >= s.h && h <= stops[i + 1].h)
  const a = stops[Math.max(0, index)], b = stops[Math.max(0, index) + 1]
  const t = (h - a.h) / (b.h - a.h)
  const darkness = nightAmount(h)
  const mix = (x, y, name) => `rgb(${[1, 3, 5].map(i => {
    const base = parseInt(x.slice(i, i + 2), 16) * (1 - t) + parseInt(y.slice(i, i + 2), 16) * t
    return Math.round(base * (1 - darkness) + parseInt(NIGHT_COLORS[name].slice(i, i + 2), 16) * darkness)
  }).join(',')})`
  const stars = a.stars * (1 - t) + b.stars * t
  return {
    style: Object.fromEntries(names.map((n, i) => [`--${n}`, mix(a.c[i], b.c[i], n)])),
    sun: (a.sun * (1 - t) + b.sun * t) * (1 - darkness),
    stars: stars + (1 - stars) * darkness,
  }
})
function setTime(hour, updatePalette = true) {
  // Unwrapped time keeps the slower star motion continuous through midnight.
  starRotation.value?.setAttribute('transform', `rotate(${-hour * STAR_DEGREES_PER_HOUR})`)
  const { x, y } = sunPosition(hour)
  sun.value?.setAttribute('cx', x)
  sun.value?.setAttribute('cy', y)
  if (updatePalette) paletteHour.value = timeOfDay(hour)
  deer.value?.setTime(hour)
  const { width, length, opacity } = sunReflection(x, y, 27 * scaleX.value, 27 * scaleY.value)
  const half = width / 2
  reflection.value?.setAttribute('d', `M${x-half} 567 L${x+half} 567 L${x+half*1.35} ${567+length} L${x-half*1.35} ${567+length}Z`)
  reflection.value?.setAttribute('opacity', light.value.sun * opacity)
  const projected = projectionLight(hour)
  for (const item of projectionNodes) {
    item.node.setAttribute('transform', projectionMatrix(item.base, projected.skew * item.skew, projected.depth * item.depth, item.slope))
    const strength = item.kind === 'water' ? .06 + projected.daylight * .26 : projected.daylight * .19
    item.node.setAttribute('opacity', strength * item.strength)
  }
}
defineExpose({ setTime })
const turbines = [
  { x: 350, y: 665, s: .53, p: -7 }, { x: 422, y: 592, s: .29, p: -2 },
  { x: 465, y: 575, s: .18, p: -11 }, { x: 1481, y: 580, s: .25, p: -5 },
  { x: 1550, y: 598, s: .36, p: -10 }, { x: 1690, y: 646, s: .94, p: -3 },
  { x: 1846, y: 610, s: .48, p: -13 },
]
const starFrame = computed(() => {
  const width = viewport.value.width
  const height = viewport.value.height * 567 / 1080
  // An east-facing composition keeps the celestial pole beyond the left edge.
  const x = -width * 2.5, y = -height * .25
  // Cover all four corners through a full turn, with a small offscreen margin.
  const radius = Math.hypot(Math.max(x, width - x), Math.max(y, height - y)) + 12
  const innerRadius = Math.hypot(x, y) - 12
  return { width, height, x, y, radius, innerRadius }
})
</script>

<template>
  <svg ref="scene" class="coast-scene" :class="{ 'motion-paused': !motionEnabled }" :style="light.style" viewBox="0 0 1920 1080" preserveAspectRatio="none" role="img" aria-label="平潭风貌的矢量海岸：岩石山、弧形沙湾与旋转的海上风力发电机，光色随预览时间变化">
    <defs>
      <linearGradient id="sky" x2="0" y2="1"><stop stop-color="var(--sky-top)" /><stop offset="1" stop-color="var(--sky-bottom)" /></linearGradient>
      <linearGradient id="sea" x2="0" y2="1"><stop stop-color="var(--sea)" /><stop offset="1" stop-color="var(--shallows)" /></linearGradient>
      <linearGradient id="sun-trail" x2="0" y2="1"><stop stop-color="#ffe6ba" stop-opacity=".4" /><stop offset="1" stop-color="#ffe6ba" stop-opacity="0" /></linearGradient>
      <linearGradient id="sun-trail-edges"><stop stop-color="white" stop-opacity="0" /><stop offset=".25" stop-color="white" /><stop offset=".75" stop-color="white" /><stop offset="1" stop-color="white" stop-opacity="0" /></linearGradient>
      <mask id="soft-reflection" maskContentUnits="objectBoundingBox"><rect width="1" height="1" fill="url(#sun-trail-edges)" /></mask>
      <linearGradient id="mist" x2="0" y2="1"><stop stop-color="var(--haze)" stop-opacity=".45" /><stop offset="1" stop-color="var(--haze)" stop-opacity="0" /></linearGradient>
      <path id="blade" d="M-5 1 C-9-23-6-68-2-113 Q0-135 3-124 L8-29 Q9-8 3 2Z" />
      <path id="left-cape-shape" :d="leftCape" />
      <path id="right-cape-outline" :d="rightCape" />
      <path id="distant-cape-outline" :d="headlandPath" />
      <path id="left-distant-outline" :d="leftHeadlandPath" />
      <path id="right-distant-outline" :d="rightHeadlandPath" />
      <clipPath id="water-area"><path ref="waterClip" :d="waterArea" /></clipPath>
      <clipPath id="beach-area"><path ref="beachClip" :d="wetBeach" /></clipPath>
      <linearGradient id="projection-fade" x2="0" y2="1"><stop stop-color="white" stop-opacity="0" /><stop offset="1" stop-color="white" /></linearGradient>
      <mask id="water-projection-fade" maskContentUnits="objectBoundingBox"><rect width="1" height="1" fill="url(#projection-fade)" /></mask>
      <linearGradient id="turbine-projection-fade" x2="0" y2="1"><stop stop-color="white" stop-opacity="0" /><stop offset=".35" stop-color="white" stop-opacity=".04" /><stop offset=".7" stop-color="white" stop-opacity=".3" /><stop offset="1" stop-color="white" stop-opacity=".85" /></linearGradient>
      <mask id="turbine-water-fade" maskContentUnits="objectBoundingBox"><rect width="1" height="1" fill="url(#turbine-projection-fade)" /></mask>
      <filter id="turbine-water-softness" x="-30%" y="-10%" width="160%" height="120%" color-interpolation-filters="sRGB"><feGaussianBlur stdDeviation="1.8" /></filter>
      <!-- Each physical turbine is defined once; its moving blades are reused below. -->
      <g v-for="(t, i) in turbines" :id="`turbine-shape-${i}`" :key="i">
        <path d="M-5 0L-2-198H3L7 0Z" />
        <path d="M3-197L7 0H3L0-197Z" opacity=".2" />
        <path d="M-11-205Q-13-210-6-211H17L19-201H-9Z" />
        <g transform="translate(-6 -205)"><g class="rotor" :style="{ animationDelay: `${t.p}s` }"><use href="#blade" /><use href="#blade" transform="rotate(120)" /><use href="#blade" transform="rotate(240)" /><circle r="6" /></g></g>
      </g>
    </defs>
    <path fill="url(#sky)" d="M0 0H1920V690H0Z" />
    <!-- Pixel-proportioned inner viewport keeps circular star paths on every screen. -->
    <svg x="0" y="0" width="1920" height="567" :viewBox="`0 0 ${starFrame.width} ${starFrame.height}`" preserveAspectRatio="none" overflow="hidden" :opacity="light.stars" class="star-field">
      <g :transform="`translate(${starFrame.x} ${starFrame.y})`">
        <!-- Scene time is the sole clock; the angular speed is configured in motion.js. -->
        <g ref="starRotation" class="star-rotation" :transform="`rotate(${-12 * STAR_DEGREES_PER_HOUR})`">
          <StarMap :inner-radius="starFrame.innerRadius" :outer-radius="starFrame.radius" />
        </g>
      </g>
    </svg>
    <ellipse ref="sun" cx="903.46" cy="120.28" :rx="27 * scaleX" :ry="27 * scaleY" fill="#fff1ce" :opacity="light.sun" />
    <path fill="url(#sea)" d="M0 567H1920V1080H0Z" />
    <path fill="url(#mist)" d="M0 567H1920V678H0Z" />
    <path ref="reflection" d="M891.46 572L915.46 572L1003.46 890L803.46 890Z" fill="url(#sun-trail)" mask="url(#soft-reflection)" opacity="0" />
    <g class="water-projections" clip-path="url(#water-area)" fill="color-mix(in srgb, var(--rock-dark) 65%, #182e40)">
      <g data-projection="water" :data-base="leftFoot.intercept" :data-slope="leftFoot.slope" data-depth=".7" data-skew=".45"><use href="#left-distant-outline" mask="url(#water-projection-fade)" /></g>
      <g data-projection="water" :data-base="rightFoot.intercept" :data-slope="rightFoot.slope" data-depth=".7" data-skew=".45"><use href="#right-distant-outline" mask="url(#water-projection-fade)" /></g>
      <g v-for="(t, i) in turbines" :key="i" :transform="`translate(${t.x} ${t.y}) scale(${t.s * scaleX} ${t.s * scaleY})`">
        <g data-projection="water" data-base="0" data-depth="1.15" data-strength=".6"><use :href="`#turbine-shape-${i}`" mask="url(#turbine-water-fade)" filter="url(#turbine-water-softness)" /></g>
      </g>
    </g>
    <!-- Opaque, complete land silhouettes occlude the sun and the water reflection. -->
    <use class="distant-headlands" href="#distant-cape-outline" fill="color-mix(in srgb, var(--rock-mid) 55%, var(--haze))" />
    <g stroke="var(--haze)" stroke-width="2" stroke-linecap="round" opacity=".25"><path d="M65 658H174M260 625H310M375 675H454M1433 653H1510M1754 701H1820M1823 651H1882M1325 723H1406M288 749H332" /></g>
    <!-- Offshore objects sit behind every foreground rock and the stag. -->
    <g class="offshore-turbines" fill="var(--turbine)">
      <g v-for="(t, i) in turbines" :key="i" :transform="`translate(${t.x} ${t.y}) scale(${t.s * scaleX} ${t.s * scaleY})`">
        <use :href="`#turbine-shape-${i}`" />
        <path d="M-10 2H13" stroke="var(--turbine)" stroke-width="2" opacity=".35" />
      </g>
    </g>
    <!-- Wet sand follows the whole bay, including the area behind the content. -->
    <path ref="wetEdge" class="wet-beach" :d="wetBeach" fill="color-mix(in srgb, var(--sand) 78%, var(--rock-mid))" />
    <path ref="dryEdge" class="dry-beach" :d="dryBeach" fill="var(--sand)" />
    <path ref="foamEdge" class="shoreline" :d="shoreline" transform="translate(0 3)" fill="none" stroke="#fff" stroke-width="1.7" stroke-linecap="round" stroke-dasharray="160 25 61 18 240 35" opacity=".55" />
    <path d="M1810 992Q1720 987 1664 1000M1497 1020Q1437 1024 1397 1028M349 983Q293 967 247 962" fill="none" stroke="var(--rock-light)" stroke-width="1.5" opacity=".25" stroke-linecap="round" />
    <!-- The right cape casts a low shadow across the sand; the near shelf continues offscreen. -->
    <g class="land-projections" clip-path="url(#beach-area)" fill="color-mix(in srgb, var(--rock-dark) 65%, #182e40)">
      <g data-projection="land" data-base="1040" data-depth=".4"><use href="#right-cape-outline" /></g>
    </g>
    <!-- A broad near shelf runs out from the viewer's side, above a broken cliff face. -->
    <g class="foreground-cape" :transform="capeTransform">
      <g class="left-cape">
        <use href="#left-cape-shape" fill="var(--rock-mid)" />
        <path v-for="(face, i) in leftFaces" :key="i" :d="face.d" :fill="`var(--${face.paint})`" />
        <path v-for="(patch, i) in capeGrass" :key="`grass-${i}`" :d="patch" fill="var(--grass)" />
        <path :d="capeCracks" fill="none" stroke="var(--rock-dark)" stroke-width="1.7" opacity=".2" stroke-linecap="round" />
      </g>
      <DeerSilhouette ref="deer" :hour="paletteHour" />
    </g>
    <g class="right-cape">
      <use href="#right-cape-outline" fill="var(--rock-mid)" />
      <path v-for="(face, i) in rightFaces" :key="i" :d="face.d" :fill="`var(--${face.paint})`" />
    </g>
    <g fill="var(--rock-mid)"><path d="M1557 973L1575 960 1599 963 1612 978 1601 989 1566 988Z" /><path d="M1450 1034L1464 1029 1476 1035 1470 1042 1454 1041Z" /><path d="M528 1036L547 1025 569 1028 579 1042 561 1050 534 1049Z" /></g>
    <path d="M1557 973L1575 960 1599 963 1587 976Z M528 1036L547 1025 569 1028 553 1039Z" fill="var(--rock-light)" />
  </svg>
</template>

<style scoped>
.coast-scene { display: block; width: 100%; height: 100%; }
.rotor { animation: turn 22s linear infinite; transform-origin: 0 0; }
.motion-paused .rotor { animation-play-state: paused; }
@keyframes turn { to { transform: rotate(360deg); } }
@media (prefers-reduced-motion: reduce) { .rotor { animation-play-state: paused; } }
</style>

