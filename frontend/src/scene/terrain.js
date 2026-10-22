export const leftRidge = [[0,549],[40,528],[81,534],[120,505],[155,514],[189,540],[231,558],[291,574],[338,579]]
export const rightRidge = [[1664,580],[1709,577],[1759,566],[1814,545],[1850,529],[1885,518],[1920,522]]
const line = points => points.map(([x,y],i) => `${i ? 'L' : 'M'}${x} ${y}`).join(' ')
export const leftHeadlandPath = `${line(leftRidge)} L0 603Z`
export const rightHeadlandPath = `${line(rightRidge)} L1920 600Z`
export const headlandPath = `${leftHeadlandPath} ${rightHeadlandPath}`
export const leftFoot = { slope: (579 - 603) / 338, intercept: 603 }
export const rightFoot = { slope: (600 - 580) / (1920 - 1664), intercept: 450 }

export function skylineAt(x) {
  let horizon = 567
  for (const ridge of [leftRidge, rightRidge, foregroundRidge]) {
    for (let i=1; i<ridge.length; i++) {
      const [ax,ay]=ridge[i-1], [bx,by]=ridge[i]
      if (x>=ax && x<=bx) horizon = Math.min(horizon, ay+(by-ay)*(x-ax)/(bx-ax))
    }
  }
  return horizon
}
import { capeRidge, capeOffsetX } from './landscape.js'
const foregroundRidge = capeRidge.map(([x, y]) => [x + capeOffsetX, y])

