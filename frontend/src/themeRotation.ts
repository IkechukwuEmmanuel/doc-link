export type ThemeName =
  | "oxidized-copper"
  | "walnut-ink"
  | "storm-slate"
  | "white"
  | "black";

/**
 * Map the current hour (0-23) to a brand theme name.
 * The mapping is intentionally simple: Each hour block maps to a theme.
 * Adjust the mapping as needed for your preferred visual cadence.
 */
export function currentThemeBasedOnTime(): ThemeName {
  const hour = new Date().getHours();
  if (hour >= 6 && hour < 12) {
    return "oxidized-copper";
  }
  if (hour >= 12 && hour < 18) {
    return "walnut-ink";
  }
  if (hour >= 18 && hour < 20) {
    return "storm-slate";
  }
  if (hour >= 20 && hour < 22) {
    return "white";
  }
  return "black";
}

/**
 * Map locale timezone to a theme – trivial fallback.
 * Currently just returns the same value as time-based.
 */
export function currentThemeBasedOnLocation(): ThemeName {
  const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
  // Use timezone to slightly shift the mapping.
  // For brevity we ignore complex timezone logic.
  return tz?.startsWith("US") ? "walnut-ink" : currentThemeBasedOnTime();
}
