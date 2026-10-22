import { stagPlacement, capeOffsetX } from './landscape.js'
import { sunPosition } from './motion.js'
import { projectionLight } from './projections.js'

// Native-alpha sole endpoints. The whole line between them is the fixed hinge.
export const shadowHooves = [
  { x: stagPlacement.x + 357 / 1306 * stagPlacement.width, y: stagPlacement.y + 1145 / 1205 * stagPlacement.height },
  { x: stagPlacement.x + 931 / 1306 * stagPlacement.width, y: stagPlacement.y + 950 / 1205 * stagPlacement.height },
]
const [leftHoof, rightHoof] = shadowHooves
const slope = (rightHoof.y - leftHoof.y) / (rightHoof.x - leftHoof.x)
const centerX = (leftHoof.x + rightHoof.x) / 2
const groundY = x => leftHoof.y + slope * (x - leftHoof.x)

// Sample across lines parallel to the hinge. Height zero is an explicit row,
// so interpolation also fixes every contact point on that row exactly.
const heights = [-80, 0, 40, 80, 125, 175, 225, 260]
const vertex = (x, height) => ({ x, y: groundY(x) - height })
const triangles = []
for (let i = 1; i < heights.length; i++) {
  const x0 = stagPlacement.x, x1 = x0 + stagPlacement.width
  const a = vertex(x0, heights[i - 1]), b = vertex(x1, heights[i - 1])
  const c = vertex(x1, heights[i]), d = vertex(x0, heights[i])
  triangles.push([a, b, c], [a, c, d])
}
export const shadowTriangles = triangles.map((points, id) => ({
  id, points, path: `M${points.map(p => `${p.x} ${p.y}`).join('L')}Z`,
}))

function affine(source, target) {
  const [p, q, r] = source, [s, t, u] = target
  const ux = q.x - p.x, uy = q.y - p.y, vx = r.x - p.x, vy = r.y - p.y
  const tx = t.x - s.x, ty = t.y - s.y, wx = u.x - s.x, wy = u.y - s.y
  const det = ux * vy - uy * vx
  const a = (tx * vy - wx * uy) / det, b = (ty * vy - wy * uy) / det
  const c = (wx * ux - tx * vx) / det, d = (wy * ux - ty * vx) / det
  return [a, b, c, d, s.x - a * p.x - c * p.y, s.y - b * p.x - d * p.y]
}

export function deerShadowFrame(hour) {
  const { x, phase } = sunPosition(hour)
  const { daylight } = projectionLight(hour)
  const elevation = Math.max(0, Math.sin(phase * Math.PI))
  const skew = Math.max(-1, Math.min(1, (centerX + capeOffsetX - x) / 750)) * (.5 + (1 - elevation) * .4)
  const depth = .2 + (1 - elevation) * .22
  function project(point) {
    const height = groundY(point.x) - point.y
    // A projective denominator expands the far end while the hinge stays fixed.
    // The near and far edges form the parallel bases of a trapezoid.
    const perspective = 1 - .0011 * height
    const px = centerX + (point.x - centerX + skew * height) / perspective
    return { x: px, y: groundY(px) + depth * height / perspective }
  }
  return {
    opacity: .38 * daylight,
    matrices: shadowTriangles.map(({ points }) => affine(points, points.map(project))),
  }
}
