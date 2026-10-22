// A reproducible star map: uniform positions in a disk, independent magnitudes.
export function createStars(count = 1200, seed = 0x25a7c9) {
  let state = seed >>> 0
  const random = () => {
    state = (state + 0x6d2b79f5) >>> 0
    let value = state
    value = Math.imul(value ^ (value >>> 15), value | 1)
    value ^= value + Math.imul(value ^ (value >>> 7), value | 61)
    return ((value ^ (value >>> 14)) >>> 0) / 4294967296
  }
  return Array.from({ length: count }, () => {
    const angle = random() * Math.PI * 2
    const distance = Math.sqrt(random())
    // Faint stars dominate; a small bright population gives the eye anchors.
    const magnitude = random() ** 3
    return {
      x: Math.cos(angle) * distance,
      y: Math.sin(angle) * distance,
      radius: .35 + magnitude * 1.15,
      opacity: .15 + magnitude * .8,
      color: ['#f3f1e9', '#dae9ff', '#ffe5bd'][Math.floor(random() * 3)],
      halo: magnitude > .88,
    }
  })
}
