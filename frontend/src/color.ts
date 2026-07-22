// Diverging blue<->red scale (surplus <-> deficit) with a neutral gray midpoint,
// per the palette in dataviz skill references/palette.md.
const NEUTRAL = { r: 0xf0, g: 0xef, b: 0xec };
const BLUE_POLE = { r: 0x18, g: 0x4f, b: 0x95 }; // step 600, strong surplus
const RED_POLE = { r: 0x8f, g: 0x23, b: 0x23 }; // deep red, strong deficit

function lerp(a: number, b: number, t: number): number {
  return Math.round(a + (b - a) * t);
}

function mixToHex(from: typeof NEUTRAL, to: typeof NEUTRAL, t: number): string {
  const r = lerp(from.r, to.r, t);
  const g = lerp(from.g, to.g, t);
  const b = lerp(from.b, to.b, t);
  return `rgb(${r}, ${g}, ${b})`;
}

/** ratio in [-1, 1]: negative = surplus (blue), positive = deficit (red), 0 = neutral gray */
export function deficitColor(ratio: number): string {
  const clamped = Math.max(-1, Math.min(1, ratio));
  if (clamped >= 0) return mixToHex(NEUTRAL, RED_POLE, clamped);
  return mixToHex(NEUTRAL, BLUE_POLE, -clamped);
}

export const STATUS_COLOR: Record<string, string> = {
  idle: "#0ca30c",
  incoming: "#2a78d6",
  busy: "#4a3aa7",
  charging: "#fab219",
  reserved: "#eda100",
  offline: "#898781",
};

export const SCENARIO_COLOR: Record<string, string> = {
  A_PASSIVE: "#2a78d6",
  B_REPOSITION_NO_RESERVE: "#008300",
  C_REPOSITION_SOFT_RESERVE: "#eb6834",
};
