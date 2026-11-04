// Display rounding only; the values themselves are exactly what the API returned.

export const rate = (value: number | null) => (value === null ? "–" : value.toFixed(3));

export const percent = (value: number | null) =>
  value === null ? "–" : `${Math.round(value * 100)}%`;

export const hours = (value: number | null) => (value === null ? "–" : `${value.toFixed(1)} h`);

export const date = (iso: string | null) => (iso === null ? "–" : iso.slice(0, 10));

/** Short form for cards: "~19 h" under two days, "~3 d" after. */
export function shortDuration(h: number | null): string {
  if (h === null) return "–";
  if (h < 48) return `~${Math.max(1, Math.round(h))} h`;
  return `~${Math.round(h / 24)} d`;
}

/** Plain words for the summary, by fixed rules (the value is a median in hours). */
export function durationWords(h: number): string {
  if (h < 1) return "under an hour";
  if (h < 36) return `about ${Math.round(h)} hour${Math.round(h) === 1 ? "" : "s"}`;
  if (h < 24 * 14) return `about ${Math.round(h / 24)} days`;
  return `about ${Math.round(h / (24 * 7))} weeks`;
}

/** "a", "a and b", "a, b and c" */
export function listWords(items: string[]): string {
  if (items.length <= 1) return items.join("");
  return `${items.slice(0, -1).join(", ")} and ${items[items.length - 1]}`;
}
