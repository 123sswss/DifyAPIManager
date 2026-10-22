import { sunPosition, timeOfDay } from './motion.js'
import { projectionLight } from './projections.js'

export const NIGHT_COLORS = {
  'sky-top': '#071221', 'sky-bottom': '#122337', haze: '#152e3d',
  sea: '#0e2430', shallows: '#172f3a', sand: '#2d3943',
  'rock-light': '#253342', 'rock-mid': '#1b2b3a', 'rock-dark': '#142a32',
  turbine: '#3b535e', 'wet-sand': '#0b202c', grass: '#1e3737',
}

function smoothstep(start, end, value) {
  const t = Math.max(0, Math.min(1, (value - start) / (end - start)))
  return t * t * (3 - 2 * t)
}

export function nightAmount(hour) {
  const h = timeOfDay(hour)
  // Hold the deep-night palette from 20:00 to 05:00, easing into each twilight.
  return Math.max(1 - smoothstep(5, 6.5, h), smoothstep(19.1, 20, h))
}

export function deerIllumination(hour) {
  const h = timeOfDay(hour)
  const { phase } = sunPosition(hour)
  const { daylight } = projectionLight(hour)
  const elevation = Math.max(0, Math.sin(phase * Math.PI))
  // Sea-facing dawn leaves the foreground stag backlit until morning fills in.
  const morning = h < 12 ? smoothstep(6, 8.5, h) : 1
  const exposure = daylight * (1 - nightAmount(hour)) * morning
  return {
    ambient: .22 * exposure,
    warm: .28 * (1 - elevation) ** 2 * exposure,
    night: .78 * (1 - exposure),
  }
}
