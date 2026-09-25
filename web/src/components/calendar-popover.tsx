"use client";
// The two month calendar popover (react-day-picker + date-fns, ~100 KB):
// loaded on first open, not with the page.
import { createContext, useContext } from "react";
import { DayPicker, type DayButtonProps } from "react-day-picker";
import { X } from "lucide-react";
import { cn } from "@/lib/utils";
import { addDays, dayDiff, formatDate, isoDate } from "@/lib/format";
import { addMonths, monthOf, useDatePrices, type PriceQuery } from "@/lib/date-prices";
import { priceScale, PRICE_GRADIENT } from "@/lib/price-scale";
import { useApp } from "./app-context";
import { useMemo, useState } from "react";

const toDate = (iso: string) => {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(y, m - 1, d);
};

type Phase = "start" | "end";

export function CalendarPopover({
  start,
  end,
  range,
  phase,
  setPhase,
  minDate,
  prices,
  tripLen,
  onChange,
  onDone,
  labels,
}: {
  start: string;
  end?: string;
  range: boolean;
  phase: Phase;
  setPhase: (p: Phase) => void;
  minDate: string;
  prices: PriceQuery | null;
  tripLen: number;
  onChange: (s: string, e?: string) => void;
  onDone: () => void;
  labels: [string, string];
}) {
  const { money } = useApp();
  const [month, setMonth] = useState(() => monthOf(phase === "end" && end ? end : start));
  // Prices are fixed to the trip length when the calendar opened, so the
  // numbers don't jump around while picking.
  const [len] = useState(tripLen);
  const q = useMemo(() => (prices ? { ...prices, tripDays: range ? len || null : null } : null), [prices, range, len]);
  const months = useMemo(() => [month, addMonths(month, 1)], [month]);
  const data = useDatePrices(q, months);

  // In the return phase prices sit on the return day (departure + length).
  const byDay = useMemo(() => {
    const m = new Map<string, number>();
    data.prices.forEach((p, d) => m.set(phase === "end" && range ? addDays(d, len) : d, p.price));
    return m;
  }, [data.prices, phase, range, len]);
  const scale = useMemo(() => priceScale([...byDay.values()]), [byDay]);
  const cur = data.prices.values().next().value?.currency ?? prices?.currency ?? "USD";
  const loading = data.loading.size > 0;

  function pick(d: string) {
    if (!range) {
      onChange(d);
      onDone();
      return;
    }
    if (phase === "start") {
      onChange(d, addDays(d, Math.max(len, 0)));
      setPhase("end");
      return;
    }
    if (d < start) {
      onChange(d, addDays(d, Math.max(len, 0)));
      return;
    }
    onChange(start, d);
    onDone();
  }

  const sel = toDate(start);
  const endD = end ? toDate(end) : undefined;
  const modifiers = {
    range_start: sel,
    range_end: range && endD ? endD : sel,
    range_middle: range && endD ? (day: Date) => day > sel && day < endD : () => false,
  };

  const phaseLabel = range ? (phase === "start" ? `Pick ${labels[0].toLowerCase()}` : `Pick ${labels[1].toLowerCase()}`) : "Pick a date";
  return (
    <PriceCtx.Provider value={{ byDay, scale, loading: data.loading, fmt: (v: number) => money(v, cur) }}>
    <div
      className={cn(
        "pop-in z-50 border border-border bg-surface shadow-[var(--shadow-lg)]",
        "fixed inset-x-0 bottom-0 max-h-[85vh] overflow-y-auto rounded-t-2xl",
        "sm:absolute sm:inset-x-auto sm:bottom-auto sm:left-0 lg:left-auto lg:right-0 sm:mt-2 sm:max-h-none sm:w-max sm:overflow-visible sm:rounded-2xl",
      )}
      role="dialog"
      aria-label="Choose dates"
    >
      <div className="flex items-center justify-between gap-3 border-b border-border px-4 py-3">
        <div className="min-w-0">
          <div className="text-sm font-semibold">{phaseLabel}</div>
          <div className="truncate text-xs text-muted">
            {formatDate(start)}
            {range && end && ` to ${formatDate(end)} · ${dayDiff(start, end)} night${dayDiff(start, end) === 1 ? "" : "s"}`}
          </div>
        </div>
        <button type="button" onClick={onDone} className="rounded-md p-1.5 text-muted hover:bg-surface-2 hover:text-fg sm:hidden" aria-label="Close">
          <X className="size-4" />
        </button>
      </div>
      <div className="px-2 pt-2 sm:px-3">
        <DayPicker
          numberOfMonths={2}
          month={toDate(`${month}-01`)}
          onMonthChange={(m) => setMonth(monthOf(isoDate(m)))}
          startMonth={toDate(`${monthOf(minDate)}-01`)}
          disabled={{ before: toDate(minDate) }}
          weekStartsOn={1}
          showOutsideDays={false}
          fixedWeeks
          modifiers={modifiers}
          onDayClick={(d, m) => !m.disabled && pick(isoDate(d))}
          components={{ DayButton: PriceDayButton }}
          modifiersClassNames={{
            range_start: "rdp-rs",
            range_end: "rdp-re",
            range_middle: "rdp-rm",
          }}
          classNames={{
            root: "relative",
            months: "flex flex-col gap-4 sm:flex-row sm:gap-6",
            month: "min-w-0",
            month_caption: "flex h-9 items-center justify-center text-sm font-semibold",
            caption_label: "",
            nav: "absolute inset-x-1 top-0 z-10 flex h-9 items-center justify-between pointer-events-none",
            button_previous: "pointer-events-auto grid size-8 place-items-center rounded-full text-muted hover:bg-surface-2 hover:text-fg disabled:opacity-25",
            button_next: "pointer-events-auto grid size-8 place-items-center rounded-full text-muted hover:bg-surface-2 hover:text-fg disabled:opacity-25",
            chevron: "size-4 fill-current",
            month_grid: "border-collapse",
            weekdays: "",
            weekday: "h-8 w-11 text-[11px] font-medium text-faint sm:w-12",
            week: "",
            day: "rdp-day p-0 text-center",
            day_button:
              "h-12 w-11 rounded-lg text-sm transition-colors hover:bg-surface-2 focus-visible:ring-2 focus-visible:ring-[var(--ring)] focus-visible:outline-none sm:w-12",
            today: "rdp-today",
            disabled: "opacity-30 pointer-events-none",
            outside: "invisible",
          }}
        />
      </div>
      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border px-4 py-3 text-xs text-muted">
        <div className="flex min-w-0 items-center gap-2">
          {!data.enabled ? (
            <span>Pick a destination to see prices</span>
          ) : loading ? (
            <span className="flex items-center gap-2">
              <span className="skeleton h-2 w-10" /> Loading prices
            </span>
          ) : byDay.size ? (
            <>
              <span className="tabular-nums">{money(scale.min, cur)}</span>
              <span className="h-1.5 w-16 rounded-full" style={{ background: PRICE_GRADIENT }} />
              <span className="tabular-nums">{money(scale.max, cur)}</span>
              <span className="hidden text-faint sm:inline">
                {range ? `${len} night round trips${phase === "end" ? ", on the return day" : ""}` : "one way"}
              </span>
            </>
          ) : data.failed ? (
            <span title={data.error ?? undefined}>Prices aren&apos;t available right now</span>
          ) : (
            <span>No prices found for these months</span>
          )}
        </div>
        <button type="button" onClick={onDone} className="h-8 rounded-lg bg-accent px-4 text-sm font-medium text-accent-fg hover:brightness-110">
          Done
        </button>
      </div>
    </div>
    </PriceCtx.Provider>
  );
}

type PriceCtxValue = { byDay: Map<string, number>; scale: ReturnType<typeof priceScale>; loading: Set<string>; fmt: (v: number) => string };
const PriceCtx = createContext<PriceCtxValue | null>(null);

function PriceDayButton(props: DayButtonProps) {
  const { day, modifiers: mods, className, ...rest } = props;
  const ctx = useContext(PriceCtx)!;
  const iso = isoDate(day.date);
  const p = ctx.byDay.get(iso);
  const monthLoading = ctx.loading.has(iso.slice(0, 7)) && !mods.disabled && !mods.outside;
  const selected = mods.range_start || mods.range_end;
  return (
    <button {...rest} className={cn(className, "flex flex-col items-center justify-center gap-1")}>
      <span className="leading-none">{day.date.getDate()}</span>
      {!mods.outside &&
        (p != null && !mods.disabled ? (
          <span className="text-[10px] leading-none font-semibold tabular-nums" style={selected ? undefined : { color: ctx.scale.color(p) }}>
            {ctx.fmt(p)}
          </span>
        ) : monthLoading ? (
          <span className="skeleton h-2 w-7" />
        ) : (
          <span className="h-2.5" />
        ))}
    </button>
  );
}
