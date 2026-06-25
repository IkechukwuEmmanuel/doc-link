/** Shared display formatting for the dashboard list (design spec §2 scan view). */

const UNITS: [number, Intl.RelativeTimeFormatUnit][] = [
  [60, "second"],
  [60, "minute"],
  [24, "hour"],
  [7, "day"],
  [4.34524, "week"],
  [12, "month"],
  [Number.POSITIVE_INFINITY, "year"],
];

const rtf = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });

/** "3 hours ago", "yesterday", etc. Returns "just now" for <5s. */
export function relativeTime(iso: string): string {
  const then = new Date(iso).getTime();
  const diffSeconds = (then - Date.now()) / 1000;
  const abs = Math.abs(diffSeconds);
  if (abs < 5) return "just now";
  let value = diffSeconds;
  for (const [divisor, unit] of UNITS) {
    if (Math.abs(value) < divisor) {
      return rtf.format(Math.round(value), unit);
    }
    value /= divisor;
  }
  return rtf.format(Math.round(value), "year");
}

/** Full, locale-aware timestamp for the hover/title tooltip. */
export function fullTimestamp(iso: string): string {
  return new Date(iso).toLocaleString();
}

export function formatBytes(bytes: number): string {
  if (!bytes) return "—";
  const units = ["B", "KB", "MB", "GB"];
  let value = bytes;
  let i = 0;
  while (value >= 1024 && i < units.length - 1) {
    value /= 1024;
    i += 1;
  }
  return `${value < 10 && i > 0 ? value.toFixed(1) : Math.round(value)} ${units[i]}`;
}
