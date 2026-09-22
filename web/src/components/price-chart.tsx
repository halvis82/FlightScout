"use client";
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { formatDate } from "@/lib/format";

export type SeriesPoint = { day: string } & Record<string, number | string | null>;

const COLORS = ["var(--series-1)", "var(--series-2)", "var(--series-3)"];

// Price over time. At most three series (fixed color order), a legend is
// always shown for 2+ series, one y axis.
export function PriceChart({
  data,
  series,
  format,
}: {
  data: SeriesPoint[];
  series: string[];
  format: (v: number) => string;
}) {
  return (
    <div className="h-72 w-full">
      {data.length === 1 && <p className="mb-1 text-xs text-muted">One day of data so far. The line fills in as daily checks come in.</p>}
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: 4 }}>
          <CartesianGrid stroke="var(--border)" vertical={false} />
          <XAxis
            dataKey="day"
            tickFormatter={(d: string) => formatDate(d, false)}
            stroke="var(--faint)"
            tick={{ fill: "var(--muted)", fontSize: 11 }}
            tickLine={false}
            axisLine={{ stroke: "var(--border)" }}
            minTickGap={24}
          />
          <YAxis
            tickFormatter={(v: number) => format(v)}
            tick={{ fill: "var(--muted)", fontSize: 11 }}
            tickLine={false}
            axisLine={false}
            width={72}
            domain={[(min: number) => Math.floor(min * 0.95), (max: number) => Math.ceil(max * 1.05)]}
          />
          <Tooltip
            cursor={{ stroke: "var(--border-strong)", strokeWidth: 1 }}
            contentStyle={{
              background: "var(--surface)",
              border: "1px solid var(--border)",
              borderRadius: 8,
              fontSize: 12,
              color: "var(--fg)",
            }}
            labelStyle={{ color: "var(--muted)", marginBottom: 4 }}
            itemStyle={{ color: "var(--fg)", padding: 0 }}
            labelFormatter={(d) => formatDate(String(d))}
            formatter={(v, name) => [format(Number(v)), String(name)]}
          />
          {series.length > 1 && (
            <Legend iconType="plainline" wrapperStyle={{ fontSize: 12, color: "var(--muted)" }} formatter={(v) => <span style={{ color: "var(--muted)" }}>{v}</span>} />
          )}
          {series.slice(0, 3).map((s, i) => (
            <Line
              key={s}
              type="monotone"
              dataKey={s}
              name={s}
              stroke={COLORS[i]}
              strokeWidth={2}
              dot={data.length < 20 ? { r: 3, strokeWidth: 2, stroke: "var(--surface)", fill: COLORS[i] } : false}
              activeDot={{ r: 4, strokeWidth: 2, stroke: "var(--surface)" }}
              connectNulls
              isAnimationActive={false}
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
