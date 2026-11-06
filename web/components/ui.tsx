// Small shared pieces of the visual system (docs/DESIGN.md, "Visual design").

import { bandStyle, sentenceCase } from "@/lib/bands";
import type { Sentence } from "@/lib/summary";

/** A section label in letter-spaced capitals. */
export function Label({ children }: { children: React.ReactNode }) {
  return (
    <p className="text-small font-medium tracking-[0.08em] text-muted uppercase">{children}</p>
  );
}

/** The band as a coloured shape and its words; colour is never the only cue. */
export function BandMarker({ band }: { band: string }) {
  const style = bandStyle(band);
  return (
    <span className="inline-flex items-center gap-1.5 text-small text-ink">
      <span aria-hidden style={{ color: style.strong }}>
        {style.mark}
      </span>
      {sentenceCase(band)}
    </span>
  );
}

/** A sentence from lib/summary.ts with its strong and monospace parts. */
export function Prose({ sentence }: { sentence: Sentence }) {
  return (
    <>
      {sentence.map((part, i) => {
        if (part.mono) {
          return (
            <code key={i} className="font-mono text-[0.92em] font-semibold">
              {part.text}
            </code>
          );
        }
        return part.strong ? (
          <strong key={i} className="font-semibold">
            {part.text}
          </strong>
        ) : (
          <span key={i}>{part.text}</span>
        );
      })}
    </>
  );
}

/** A grey block standing in for a section that is not ready yet. */
export function Skeleton({ lines = 3 }: { lines?: number }) {
  return (
    <div aria-hidden className="space-y-2">
      {Array.from({ length: lines }, (_, i) => (
        <div key={i} className="h-3 rounded-sm bg-wash" style={{ width: `${90 - i * 15}%` }} />
      ))}
    </div>
  );
}
