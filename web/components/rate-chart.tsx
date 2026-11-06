"use client";

import { useEffect, useRef, useState } from "react";

import type { BandedArea } from "@/lib/api";
import { bandStyle, sentenceCase } from "@/lib/bands";
import { percent, plural } from "@/lib/format";

// One row per banded area: the 95% interval as a bar, the merge rate as a mark shaped by band,
// and the repo average as a labelled vertical line. Rows keep the API's order (by band, then
// alphabetical), so the chart implies no ranking. Drawn at the container's real width so text
// keeps one size; below NARROW px the area names sit above their bars.

const NARROW = 520;
// Every monospace character has the same width (about 0.6 em, so 7.4 px at 12 px), which is why
// one constant is enough to decide how many characters of a name fit.
const CHAR = 7.4;
const TICKS = [0, 0.25, 0.5, 0.75, 1];

type Props = { groups: { band: string; areas: BandedArea[] }[]; repoRate: number | null };

/** Long area names keep their end, where the distinctive part is. */
function fit(name: string, width: number): string {
  const max = Math.floor(width / CHAR);
  return name.length <= max ? name : `…${name.slice(name.length - max + 1)}`;
}

function describe(a: BandedArea): string {
  const [low, high] = a.wilson_interval;
  return (
    `${a.area}: ${percent(a.merge_rate)} merged, 95% interval ${percent(low)} to ${percent(high)}; ` +
    `${a.mature_newcomer_prs} finished newcomer PRs from ${plural(a.distinct_newcomer_authors, "author")}. ` +
    `${sentenceCase(a.band)}.`
  );
}

function Mark({ band, x, y }: { band: string; x: number; y: number }) {
  const { mark, strong } = bandStyle(band);
  if (mark === "▲") return <path d={`M${x} ${y - 6}L${x + 6} ${y + 4}L${x - 6} ${y + 4}Z`} fill={strong} />;
  if (mark === "▼") return <path d={`M${x} ${y + 6}L${x + 6} ${y - 4}L${x - 6} ${y - 4}Z`} fill={strong} />;
  return <circle cx={x} cy={y} r={5} fill={strong} />;
}

export default function RateChart({ groups, repoRate }: Props) {
  const rows = groups.flatMap((g) => g.areas);
  const box = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(720);
  const [hovered, setHovered] = useState<string | null>(null);
  const [focused, setFocused] = useState<string | null>(null);
  useEffect(() => {
    const element = box.current;
    if (!element) return;
    const observer = new ResizeObserver(([entry]) => setWidth(Math.round(entry.contentRect.width)));
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  const narrow = width < NARROW;
  const labelWidth = narrow ? 0 : Math.min(280, Math.round(width * 0.32));
  const left = narrow ? 8 : labelWidth + 16;
  const right = 24;
  const top = 34; // room for the repo-average label
  const row = narrow ? 46 : 34;
  const height = top + rows.length * row + 28;
  const x = (value: number) => left + value * (width - left - right);
  // keyboard focus wins over the mouse, so a focused row keeps its outline
  const active = focused ?? hovered;
  const shown = rows.find((r) => r.area === active) ?? null;

  return (
    <figure className="space-y-3">
      <div ref={box}>
        <svg
          viewBox={`0 0 ${width} ${height}`}
          width={width}
          height={height}
          className="block w-full"
          role="group"
          aria-label="Merge rate and 95% interval per area, compared with the repo average"
        >
          {TICKS.map((tick) => (
            <g key={tick} aria-hidden>
              <line x1={x(tick)} x2={x(tick)} y1={top - 6} y2={height - 24} stroke="var(--color-line)" />
              <text x={x(tick)} y={height - 8} textAnchor="middle" className="fill-muted font-sans text-[12px]">
                {tick * 100}%
              </text>
            </g>
          ))}
          {rows.map((area, i) => {
            const style = bandStyle(area.band);
            const rowTop = top + i * row;
            const barY = narrow ? rowTop + 30 : rowTop + row / 2;
            const [low, high] = area.wilson_interval;
            const isActive = area.area === active;
            return (
              <g
                key={area.area}
                tabIndex={0}
                role="img"
                aria-label={describe(area)}
                onMouseEnter={() => setHovered(area.area)}
                onMouseLeave={() => setHovered(null)}
                onFocus={() => setFocused(area.area)}
                onBlur={() => setFocused(null)}
                className="outline-none"
              >
                {/* the accent outline on the row is the visible focus and hover cue */}
                <rect
                  x={1}
                  y={rowTop + 1}
                  width={width - 2}
                  height={row - 2}
                  fill={isActive ? "var(--color-wash)" : "transparent"}
                  stroke={isActive ? "var(--color-accent)" : "none"}
                  strokeWidth={2}
                />
                <text
                  x={narrow ? left : 0}
                  y={narrow ? rowTop + 14 : barY}
                  dominantBaseline="middle"
                  className="fill-ink font-mono text-[12px]"
                >
                  {fit(area.area, narrow ? width - left - 8 : labelWidth)}
                </text>
                {low !== null && high !== null && (
                  <rect x={x(low)} y={barY - 4} width={Math.max(3, x(high) - x(low))} height={8} rx={4} fill={style.soft} stroke={style.strong} strokeWidth={1} />
                )}
                {area.merge_rate !== null && <Mark band={area.band} x={x(area.merge_rate)} y={barY} />}
              </g>
            );
          })}
          {repoRate !== null && (
            <g aria-hidden>
              <line x1={x(repoRate)} x2={x(repoRate)} y1={top - 10} y2={height - 24} stroke="var(--color-ink)" strokeWidth={1.25} />
              <text
                x={x(repoRate)}
                y={top - 16}
                textAnchor={repoRate > 0.75 ? "end" : "start"}
                className="fill-ink font-sans text-[12px] font-semibold"
              >
                repo average {percent(repoRate)}
              </text>
            </g>
          )}
        </svg>
      </div>
      <figcaption className="min-h-[3em] text-small text-muted" aria-live="polite">
        {shown
          ? describe(shown)
          : "Mark: merge rate (▲ above, ● no clear difference, ▼ below the repo average). Bar: 95% interval. Point at or tab to a row for its sample size."}
      </figcaption>
      <table className="sr-only">
        <caption>Merge rate and 95% interval per area, compared with the repo average</caption>
        <thead>
          <tr>
            <th scope="col">Area</th>
            <th scope="col">Band</th>
            <th scope="col">Merge rate</th>
            <th scope="col">95% interval</th>
            <th scope="col">Finished newcomer PRs</th>
            <th scope="col">Authors</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((a) => (
            <tr key={a.area}>
              <th scope="row">{a.area}</th>
              <td>{sentenceCase(a.band)}</td>
              <td>{percent(a.merge_rate)}</td>
              <td>
                {percent(a.wilson_interval[0])} to {percent(a.wilson_interval[1])}
              </td>
              <td>{a.mature_newcomer_prs}</td>
              <td>{a.distinct_newcomer_authors}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </figure>
  );
}
