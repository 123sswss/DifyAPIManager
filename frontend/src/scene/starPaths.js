import { createStars } from './stars.js'

const stars = createStars(3600)
function circle(x, y, r) {
  return `M${(x-r).toFixed(2)},${y.toFixed(2)}a${r},${r} 0 1,0 ${r*2},0a${r},${r} 0 1,0 ${-r*2},0`
}

// Build only on resize. Merge equal pigments/magnitudes into a few SVG paths.
// The annulus excludes the empty inner disk that can never cross the viewport.
export function createStarPaths(innerRadius, outerRadius) {
  const buckets = new Map()
  let halo = ''
  for (const star of stars) {
    const distance = Math.hypot(star.x, star.y)
    const radius = Math.sqrt(innerRadius ** 2 + distance ** 2 * (outerRadius ** 2 - innerRadius ** 2))
    const x = distance ? star.x / distance * radius : radius
    const y = distance ? star.y / distance * radius : 0
    const opacity = Math.round(star.opacity * 8) / 8
    const size = Math.round(star.radius * 4) / 4
    const key = `${star.color}/${opacity}/${size}`
    if (!buckets.has(key)) buckets.set(key, { color: star.color, opacity, d: '' })
    buckets.get(key).d += circle(x, y, size)
    if (star.halo) halo += circle(x, y, 3)
  }
  return { paths: [...buckets.values()], halo }
}
