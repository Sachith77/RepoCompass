// Band names come from the API in lower case ("above repo average"); the UI only changes their
// case and gives each band a colour (tokens in globals.css) and a shape, so colour is never the
// only cue: ▲ above, ● no clear difference, ▼ below.

export const ABOVE = "above repo average";
export const NO_CLEAR = "no clear difference";
export const BELOW = "below repo average";

export const BAND_ORDER = [ABOVE, NO_CLEAR, BELOW];

type Style = { mark: string; strong: string; soft: string };

const STYLES: Record<string, Style> = {
  [ABOVE]: { mark: "▲", strong: "var(--color-above)", soft: "var(--color-above-soft)" },
  [NO_CLEAR]: { mark: "●", strong: "var(--color-flat)", soft: "var(--color-flat-soft)" },
  [BELOW]: { mark: "▼", strong: "var(--color-below)", soft: "var(--color-below-soft)" },
};

const FALLBACK: Style = {
  mark: "○",
  strong: "var(--color-muted)",
  soft: "var(--color-line)",
};

export const bandStyle = (band: string): Style => STYLES[band] ?? FALLBACK;

export const sentenceCase = (text: string) => text.charAt(0).toUpperCase() + text.slice(1);
