<script setup>
import { computed } from 'vue'
import { createStarPaths } from '../scene/starPaths.js'
const props = defineProps({ innerRadius: Number, outerRadius: Number })
const map = computed(() => createStarPaths(props.innerRadius, props.outerRadius))
</script>

<template>
  <g class="star-map">
    <path :d="map.halo" fill="#e4edff" opacity=".055" />
    <path v-for="(path, i) in map.paths" :key="i" :d="path.d" :fill="path.color" :opacity="path.opacity" />
  </g>
</template>
