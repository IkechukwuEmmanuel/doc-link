// Presence/cursor palette — separate from the brand palette (design spec 1.1).
// 10 evenly-spaced hues, AA-legible on both light and dark bg, red/amber skipped
// so presence never reads as danger/warning. Assigned round-robin per session.

export interface PresenceColor {
  name: string;
  /** Cursor line + flag background. */
  solid: string;
  /** Low-opacity selection fill. */
  selection: string;
}

export const PRESENCE_PALETTE: PresenceColor[] = [
  { name: "indigo", solid: "#6366f1", selection: "rgba(99, 102, 241, 0.18)" },
  { name: "sky", solid: "#0ea5e9", selection: "rgba(14, 165, 233, 0.18)" },
  { name: "teal", solid: "#14b8a6", selection: "rgba(20, 184, 166, 0.18)" },
  { name: "emerald", solid: "#10b981", selection: "rgba(16, 185, 129, 0.18)" },
  { name: "lime", solid: "#65a30d", selection: "rgba(101, 163, 13, 0.18)" },
  { name: "violet", solid: "#8b5cf6", selection: "rgba(139, 92, 246, 0.18)" },
  { name: "fuchsia", solid: "#c026d3", selection: "rgba(192, 38, 211, 0.18)" },
  { name: "pink", solid: "#db2777", selection: "rgba(219, 39, 119, 0.18)" },
  { name: "cyan", solid: "#06b6d4", selection: "rgba(6, 182, 212, 0.18)" },
  { name: "blue", solid: "#3b82f6", selection: "rgba(59, 130, 246, 0.18)" },
];

export function presenceColorForIndex(i: number): PresenceColor {
  return PRESENCE_PALETTE[i % PRESENCE_PALETTE.length];
}
