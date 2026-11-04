// Band names come from the API in lower case ("above repo average"); the UI only changes
// their case and gives each band one colour, used everywhere a band appears.

export const ABOVE = "above repo average";
export const NO_CLEAR = "no clear difference";
export const BELOW = "below repo average";

type Style = { pill: string; dot: string; bar: string };

const STYLES: Record<string, Style> = {
  [ABOVE]: {
    pill: "bg-emerald-50 text-emerald-800 ring-emerald-600/20",
    dot: "#047857",
    bar: "#a7f3d0",
  },
  [NO_CLEAR]: {
    pill: "bg-slate-100 text-slate-700 ring-slate-500/20",
    dot: "#475569",
    bar: "#cbd5e1",
  },
  [BELOW]: {
    pill: "bg-rose-50 text-rose-800 ring-rose-600/20",
    dot: "#be123c",
    bar: "#fecdd3",
  },
};

const FALLBACK: Style = { pill: "bg-neutral-100 text-neutral-700 ring-neutral-500/20", dot: "#525252", bar: "#d4d4d4" };

export const bandStyle = (band: string): Style => STYLES[band] ?? FALLBACK;

export const sentenceCase = (text: string) => text.charAt(0).toUpperCase() + text.slice(1);

export const BAND_ORDER = [ABOVE, NO_CLEAR, BELOW];
