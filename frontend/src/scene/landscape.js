// Foreground shelf enters from behind the viewer at the left/bottom edge.
// Its low rim leaves a continuous band of sea beneath the distant islands.
export const capeOffsetX = -24
export const capeTransform = `translate(${capeOffsetX} 0)`
// The rear rim sits above the hind hooves so their contact points lie inside the shelf.
export const capeRidge = [[0,774],[72,789],[131,810],[188,815],[231,814],[270,813],[291,807],[309,797],[326,792],[349,800],[370,819],[391,846],[400,868],[388,923],[402,970],[382,1022],[361,1080]]
export const leftCape = `M${capeRidge.map(([x,y]) => `${x} ${y}`).join('L')}H0Z`
// Keep the approved image at its native aspect ratio; hoof contacts determine the rim.
export const stagPlacement = { x: 174, y: 635, width: 1306 * .165, height: 1205 * .165 }
export const capeSurface = 'M0 774L72 789 131 810 188 815 231 814 270 813 291 807 309 797 326 792 349 800 370 819 391 846 400 868 356 883 306 889 251 902 190 913 116 925 48 937 0 949Z'
export const leftFaces = [
  { paint: 'rock-light', d: capeSurface },
  { paint: 'rock-mid', d: 'M0 774L72 789 131 810 188 815 231 814 270 813 291 807 309 797 326 792 349 800 370 819 338 818 304 823 267 849 190 862 120 852 54 841 0 815Z' },
  { paint: 'rock-dark', d: 'M306 889L356 883 400 868 388 923 402 970 382 1022 361 1080H298L312 1046 299 1000 314 957Z' },
  { paint: 'rock-light', d: 'M0 949L48 937 116 925 190 913 251 902 230 947 244 985 223 1037 208 1080H0Z' },
  { paint: 'rock-dark', d: 'M251 902L285 894 263 943 273 977 256 1022 262 1080H226L234 1034 247 996 238 954Z' },
]
export const capeGrass = [
  'M0 774L72 789 131 810 162 817 142 825 110 821 65 805 0 794Z',
  'M210 815L231 814 270 813 291 807 309 797 326 792 349 800 337 804 318 803 298 817 278 825 244 827 220 825Z',
]
export const capeCracks = 'M37 876L94 883 122 877M267 862L292 854 326 858M59 977L70 1004 61 1032'
export const rightCape = 'M1920 846L1884 865 1863 901 1826 912 1790 954 1732 974 1710 1017 1669 1040 1655 1080H1920Z'
export const rightFaces = [
  { paint: 'rock-light', d: 'M1920 846L1884 865 1863 901 1892 922 1920 920Z M1863 901L1826 912 1790 954 1806 973 1859 957 1892 922Z M1790 954L1732 974 1710 1017 1754 1010 1806 973Z' },
  { paint: 'rock-dark', d: 'M1920 920L1892 922 1859 957 1806 973 1754 1010 1710 1017 1669 1040 1655 1080H1920Z' },
  { paint: 'rock-mid', d: 'M1920 920L1892 922 1859 957 1879 997 1920 1009Z M1754 1010L1806 973 1859 957 1827 1007 1772 1033 1694 1060 1669 1040 1710 1017Z' },
]
// A shallow bay viewed close to sea level. The right shore stays in the foreground.
const coastCurve = 'C1770 900 1615 922 1435 943C1200 970 905 990 554 954S195 837 0 835'
export const shoreline = `M1920 892${coastCurve}`
export const wetBeach = `${shoreline}V1080H1920Z`
export const dryBeach = 'M1920 906C1770 914 1615 936 1435 957C1200 985 905 1006 548 978S180 866 0 856V1080H1920Z'
export const waterArea = `M0 567H1920V892${coastCurve}Z`

