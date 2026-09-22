export function Sparkline({ data, className = "h-10 w-full" }: { data: number[]; className?: string }) {
  if (data.length < 2) return <div className={`${className} grid place-items-center text-[11px] text-faint`}>{data.length ? "1 check so far" : "No checks yet"}</div>;
  const min = Math.min(...data);
  const max = Math.max(...data);
  const span = max - min || 1;
  const w = 100;
  const h = 30;
  const pts = data.map((v, i) => [(i / (data.length - 1)) * w, h - 2 - ((v - min) / span) * (h - 4)]);
  const d = pts.map((p, i) => `${i ? "L" : "M"}${p[0].toFixed(2)},${p[1].toFixed(2)}`).join(" ");
  const last = pts.at(-1)!;
  const down = data.at(-1)! <= data[0];
  return (
    <svg viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" className={className} aria-hidden>
      <path d={`${d} L${w},${h} L0,${h} Z`} fill={down ? "var(--good)" : "var(--bad)"} opacity={0.08} />
      <path d={d} fill="none" stroke={down ? "var(--good)" : "var(--bad)"} strokeWidth={1.5} vectorEffect="non-scaling-stroke" />
      <circle cx={last[0]} cy={last[1]} r={1.8} fill={down ? "var(--good)" : "var(--bad)"} />
    </svg>
  );
}
