export const STAR_DEGREES_PER_HOUR = 1
export const timeOfDay = hours => ((hours % 24) + 24) % 24

export function sunPosition(hours) {
  const phase = (timeOfDay(hours) - 6) / 13
  return { x: 225 + phase * 1470, y: 567 - Math.sin(phase * Math.PI) * 450, phase }
}

export function sunVisibility(y, radius, horizon = 567) {
  const fraction = Math.max(0, Math.min(1, (horizon + radius - y) / (radius * 2)))
  return fraction * fraction * (3 - 2 * fraction)
}
import { skylineAt } from './terrain.js'


export function sunReflection(x, y, rx, ry) {
  const visible = sunVisibility(y, ry, skylineAt(x))
  const altitude = Math.max(0, (567 - y - ry) / ry)
  // Half a disk exposed gives one solar diameter; more exposure broadens the trail.
  const width = rx * 2 * visible * 2 * (1 + Math.min(altitude, 5) * .12)
  const opacity = visible <= .5 ? visible * 1.2 : .6 / (visible * 2 + altitude * .45)
  return { width, opacity, length: (170 + Math.min(altitude, 5) * 25) * Math.min(1, visible * 2) }
}
