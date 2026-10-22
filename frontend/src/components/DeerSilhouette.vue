<script setup>
import { computed, onMounted, ref } from 'vue'
import stagAsset from '../assets/stag-climbing-v5.png'
import { stagPlacement, capeSurface } from '../scene/landscape.js'
import { shadowTriangles, deerShadowFrame } from '../scene/deerShadow.js'
import { NIGHT_COLORS, deerIllumination } from '../scene/lighting.js'

const props = defineProps({ hour: { type: Number, default: 12 } })
const shadow = ref(null)
const shadowTiles = []
const illumination = computed(() => deerIllumination(props.hour))

function setTime(hour) {
  const frame = deerShadowFrame(hour)
  shadow.value?.setAttribute('opacity', frame.opacity)
  for (let i = 0; i < frame.matrices.length; i++) {
    shadowTiles[i]?.setAttribute('transform', `matrix(${frame.matrices[i].join(' ')})`)
  }
}
onMounted(() => setTime(props.hour))
defineExpose({ setTime })
</script>

<template>
  <g class="deer-silhouette" role="img" aria-label="雄鹿立于岩岸，前蹄踏高、后蹄立低，朝斜前方眺望">
    <defs>
      <!-- The original alpha limits the lighting overlays to the approved deer. -->
      <mask id="coast-stag-alpha" maskUnits="userSpaceOnUse" v-bind="stagPlacement" style="mask-type: alpha">
        <image :href="stagAsset" v-bind="stagPlacement" />
      </mask>
      <clipPath id="coast-stag-ground"><path :d="capeSurface" /></clipPath>
      <radialGradient id="coast-stag-shadow-fade" cx=".5" cy=".425" r=".65">
        <stop stop-color="#0b1927" stop-opacity=".85" />
        <stop offset=".45" stop-color="#0b1927" stop-opacity=".65" />
        <stop offset=".8" stop-color="#0b1927" stop-opacity=".215" />
        <stop offset="1" stop-color="#0b1927" stop-opacity="0" />
      </radialGradient>
      <filter id="coast-stag-shadow-softness" filterUnits="userSpaceOnUse" x="75" y="750" width="350" height="220" color-interpolation-filters="sRGB">
        <feGaussianBlur stdDeviation="5.75" />
      </filter>
      <g id="coast-stag-shadow-source" mask="url(#coast-stag-alpha)">
        <rect v-bind="stagPlacement" fill="url(#coast-stag-shadow-fade)" />
      </g>
      <clipPath v-for="tile in shadowTriangles" :id="`coast-stag-shadow-tile-${tile.id}`" :key="tile.id" clipPathUnits="userSpaceOnUse">
        <path :d="tile.path" />
      </clipPath>
    </defs>
    <g class="deer-ground-shadow" clip-path="url(#coast-stag-ground)" aria-hidden="true">
      <g ref="shadow" opacity="0" filter="url(#coast-stag-shadow-softness)">
        <g v-for="tile in shadowTriangles" :key="tile.id" :ref="el => shadowTiles[tile.id] = el" class="deer-shadow-tile">
          <g :clip-path="`url(#coast-stag-shadow-tile-${tile.id})`"><use href="#coast-stag-shadow-source" /></g>
        </g>
      </g>
    </g>
    <image class="deer-image" :href="stagAsset" v-bind="stagPlacement" />
    <g class="deer-light" mask="url(#coast-stag-alpha)" aria-hidden="true">
      <rect v-bind="stagPlacement" fill="var(--haze)" :opacity="illumination.ambient" />
      <rect v-bind="stagPlacement" fill="#efb17d" :opacity="illumination.warm" />
      <rect v-bind="stagPlacement" :fill="NIGHT_COLORS['sky-top']" :opacity="illumination.night" />
    </g>
  </g>
</template>

<style scoped>
.deer-silhouette { pointer-events: none; }
</style>
