import { sunPosition } from './motion.js'

export function projectionLight(hours) {
  const { phase, y } = sunPosition(hours)
  const elevation = Math.max(0, Math.sin(phase * Math.PI))
  return {
    // A positive direction sends the projected silhouette away from the rising sun.
    skew: Math.cos(phase * Math.PI) * (.35 + (1 - elevation) * .55),
    depth: .25 + (1 - elevation) * .5,
    daylight: Math.max(0, Math.min(1, (637 - y) / 70)),
  }
}

export function projectionMatrix(base, skew, depth, slope = 0) {
  // Fix every point along the shoreline y=slope*x+base, including tilted shores.
  return `matrix(${1 + skew * slope} ${(1 + depth) * slope} ${-skew} ${-depth} ${skew * base} ${(1 + depth) * base})`
}
