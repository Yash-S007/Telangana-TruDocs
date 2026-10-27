// Shared by the Survey Map and Village Map drawings.

// Both maps are drawn 640×480 (4:3) and scaled to the screen.
export const MAP_W = 640
export const MAP_H = 480

// Web Mercator metres, the projection satellite imagery is drawn in.
export function merc([lon, lat]) {
  return [(lon * 20037508.34) / 180, Math.log(Math.tan(Math.PI / 4 + (lat * Math.PI) / 360)) * 6378137]
}
