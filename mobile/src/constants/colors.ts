/**
 * WatchSmart brand palette — mirrors frontend/tailwind.config.js tokens.
 * The app is dark-only by design (matches the web app).
 */
export const Colors = {
  obsidian: "#05070A",
  velvet: "#0B111A",
  surface: "#111827",
  surfaceLight: "#1F2937",
  border: "rgba(255,255,255,0.10)",
  borderStrong: "rgba(255,255,255,0.20)",

  amber: "#FF7A18",
  amberDark: "#FF4D00",

  text: "#FFFFFF",
  textSecondary: "#9CA3AF",
  textTertiary: "#6B7280",

  success: "#22C55E",
  saving: "#F59E0B",
  danger: "#EF4444",
} as const;

export type ColorToken = keyof typeof Colors;
