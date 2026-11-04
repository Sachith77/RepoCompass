"use client";

import { useEffect, useRef, useState } from "react";

import type { BandedArea } from "@/lib/api";
import { ABOVE, BAND_ORDER, BELOW, NO_CLEAR, bandStyle, sentenceCase } from "@/lib/bands";
import { percent } from "@/lib/format";

// Plain SVG: one row per banded area, the 95% interval as a bar, the merge rate as a dot,
// and a vertical line at the repo rate. Rows keep the API's order (by band, then
// alphabetical), so the chart implies no ranking.

const LEFT = 8;
const MARKS: Record<string, string> = { [ABOVE]: "▲", [NO_CLEAR]: "●", [BELOW]: "▼" };
const RIGHT = 16;
const ROW = 40;
const TOP = 28;

type Props = { groups: { band: string; areas: BandedArea[] }[]; repoRate: number | null };

export default function RateChart({ groups, repoRate }: Props) {
  const rows = groups.flatMap((g) => g.areas);
  const [selected, setSelected] = useState<string | null>(null);
  // draw at the container's real width, so text stays the same size on a phone and a laptop
  const box = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(640);
  useEffect(() => {
    const element = box.current;
    if (!element) return;
    const observer = new ResizeObserver(([entry]) => setWidth(Math.round(entry.contentRect.width)));
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  const x = (value: number) => LEFT + value * (width - LEFT - RIGHT);
  const height = TOP + rows.length * ROW + 24;
  const chosen = rows.find((r) => r.area === selected) ?? null;

  return (
    <figure className="space-y-3">
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-neutral-600">
        {BAND_ORDER.filter((b) => groups.some((g) => g.band === b)).map((band) => (
          <span key={band} className="flex items-center gap-1.5">
            <span style={{ color: bandStyle(band).dot }} aria-hidden>
              {MARKS[band]}
            </span>
            {sentenceCase(band)}
          </span>
        ))}
        <span className="flex items-center gap-1.5">
          <span className="h-3 w-px bg-neutral-900" /> Repo rate {percent(repoRate)}
        </span>
      </div>
      <div ref={box}>
      <svg
        viewBox={`0 0 ${width} ${height}`}
        width={width}
        height={height}
        className="block w-full"
        role="group"
        aria-label="Merge rate and 95% interval per area, compared with the repo rate"
      >
        {[0, 0.25, 0.5, 0.75, 1].map((tick) => (
          <g key={tick}>
            <line x1={x(tick)} x2={x(tick)} y1={TOP - 8} y2={height - 20} stroke="#e5e5e5" />
            <text x={x(tick)} y={height - 6} textAnchor="middle" className="fill-neutral-500 text-[11px]">
              {tick * 100}%
            </text>
          </g>
        ))}
        {rows.map((area, i) => {
          const style = bandStyle(area.band);
          const y = TOP + i * ROW;
          const [low, high] = area.wilson_interval;
          const isSelected = area.area === selected;
          return (
            <g
              key={area.area}
              role="button"
              tabIndex={0}
              aria-pressed={isSelected}
              onClick={() => setSelected(isSelected ? null : area.area)}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  setSelected(isSelected ? null : area.area);
                }
              }}
              className="cursor-pointer focus-visible:outline-2 focus-visible:outline-blue-600"
            >
              <title>
                {`${area.area}: ${percent(area.merge_rate)} merged, 95% interval ` +
                  `${percent(low)}–${percent(high)}, n=${area.mature_newcomer_prs}, ` +
                  `${area.distinct_newcomer_authors} authors`}
              </title>
              <rect x={0} y={y - 4} width={width} height={ROW} fill={isSelected ? "#f5f5f5" : "transparent"} />
              {/* a mark as well as a colour, so bands are told apart without colour */}
              <text x={LEFT} y={y + 8} className="text-[12px]" fill={style.dot}>
                {MARKS[area.band] ?? "●"}
              </text>
              <text x={LEFT + 16} y={y + 8} className="fill-neutral-800 font-mono text-[12px]">
                {area.area}
              </text>
              {low !== null && high !== null && (
                <rect x={x(low)} y={y + 16} width={Math.max(2, x(high) - x(low))} height={8} rx={4} fill={style.bar} />
              )}
              {area.merge_rate !== null && (
                <circle cx={x(area.merge_rate)} cy={y + 20} r={5} fill={style.dot} />
              )}
            </g>
          );
        })}
        {repoRate !== null && (
          <line x1={x(repoRate)} x2={x(repoRate)} y1={TOP - 12} y2={height - 20} stroke="#171717" strokeWidth={1.5} />
        )}
      </svg>
      </div>
      <figcaption className="min-h-5 text-sm text-neutral-600">
        {chosen
          ? `${chosen.area}: ${percent(chosen.merge_rate)} merged (${chosen.merged_prs} of ` +
            `${chosen.mature_newcomer_prs} mature newcomer PRs from ${chosen.distinct_newcomer_authors} ` +
            `authors), 95% interval ${percent(chosen.wilson_interval[0])}–${percent(chosen.wilson_interval[1])}.`
          : "Dot: merge rate. Bar: 95% interval. Hover or click a row for its sample size."}
      </figcaption>
    </figure>
  );
}
