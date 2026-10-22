import { shoreline, dryBeach } from './landscape.js'

export const WAVE_PERIODS_MS = [5_000, 15_000]
export const WAVE_AMPLITUDES = [8, 4]
export const SHAPE_WAVELENGTH = 1200

function cubicPoint(points, t) {
  const u = 1 - t
  return [0, 1].map(axis => u ** 3 * points[0][axis] + 3*u*u*t*points[1][axis] + 3*u*t*t*points[2][axis] + t ** 3 * points[3][axis])
}

function cubicTangent(points, t) {
  const u = 1 - t
  return [0, 1].map(axis => 3*u*u*(points[1][axis]-points[0][axis]) + 6*u*t*(points[2][axis]-points[1][axis]) + 3*t*t*(points[3][axis]-points[2][axis]))
}

// Subdivide the original bay once. Sampling the curve itself lets waves bend its
// outline; shifting its few original control points mostly translated the bay.
function compile(path) {
  let point, previousControl
  const samples = []
  for (const [, command, values] of path.matchAll(/([MCS])([^MCS]*)/g)) {
    const n = values.trim().split(/[ ,]+/).map(Number)
    if (command === 'M') { point = n; continue }
    const a = command === 'S' ? [2*point[0]-previousControl[0], 2*point[1]-previousControl[1]] : n.slice(0, 2)
    const b = command === 'S' ? n.slice(0, 2) : n.slice(2, 4)
    const end = n.slice(-2)
    const points = [point, a, b, end]
    const steps = Math.ceil(Math.abs(end[0]-point[0]) / 70)
    for (let i=0; i<steps; i++) {
      const dt = 1 / steps
      samples.push({ a: cubicPoint(points, i*dt), b: cubicPoint(points, (i+1)*dt), da: cubicTangent(points, i*dt), db: cubicTangent(points, (i+1)*dt), dt })
    }
    previousControl = b
    point = end
  }
  return samples
}
const wetSamples = compile(shoreline)
const drySamples = compile(dryBeach.slice(0, dryBeach.indexOf('V1080')))

export function waveComponents(x, elapsedMs) {
  const phase = 2 * Math.PI * (x / SHAPE_WAVELENGTH - elapsedMs / WAVE_PERIODS_MS[0])
  return {
    shape: WAVE_AMPLITUDES[0] * Math.cos(phase),
    whole: WAVE_AMPLITUDES[1] * Math.cos(2 * Math.PI * elapsedMs / WAVE_PERIODS_MS[1] + 1.7),
    slope: -WAVE_AMPLITUDES[0] * 2 * Math.PI / SHAPE_WAVELENGTH * Math.sin(phase),
  }
}

export function waveOffset(x, elapsedMs) {
  const wave = waveComponents(x, elapsedMs)
  return wave.shape + wave.whole
}

function deform(samples, elapsedMs, strength) {
  const at = ([x,y], [dx,dy]) => {
    const wave = waveComponents(x, elapsedMs)
    return { x, y: y+(wave.shape+wave.whole)*strength, dx, dy: dy+wave.slope*dx*strength }
  }
  const pair = (x,y) => `${x.toFixed(2)} ${y.toFixed(2)}`
  const first = at(samples[0].a, samples[0].da)
  let d = `M${pair(first.x, first.y)}`
  for (const sample of samples) {
    const a = at(sample.a, sample.da), b = at(sample.b, sample.db), h = sample.dt/3
    d += `C${pair(a.x+a.dx*h,a.y+a.dy*h)} ${pair(b.x-b.dx*h,b.y-b.dy*h)} ${pair(b.x,b.y)}`
  }
  return d
}

export function wavePaths(elapsedMs) {
  const edge = deform(wetSamples, elapsedMs, 1)
  // Dry sand follows only slightly, allowing the wet-sand ribbon to breathe.
  const dryEdge = deform(drySamples, elapsedMs, .35)
  const curve = edge.slice(edge.indexOf('C'))
  const rightY = edge.match(/^M1920\.00 ([\d.-]+)/)[1]
  return {
    edge,
    wet: `${edge}V1080H1920Z`,
    dry: `${dryEdge}V1080H1920Z`,
    water: `M0 567H1920V${rightY}${curve}Z`,
  }
}
