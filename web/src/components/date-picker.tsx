"use client";
import { useCallback, useRef, useState } from "react";
import dynamic from "next/dynamic";
import { CalendarDays, ChevronLeft, ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";
import { addDays, dayDiff, formatDate, isoDate } from "@/lib/format";
import { type PriceQuery } from "@/lib/date-prices";
import { useDismiss } from "./ui";

type Phase = "start" | "end";

const loadCalendar = () => import("./calendar-popover");
const CalendarPopover = dynamic(() => loadCalendar().then((m) => m.CalendarPopover), { ssr: false });

// Google Flights style date fields: one or two fields with ◀ ▶ one day
// arrows, and a two month calendar popover with prices under each day.
export function DateRangeField({
  start,
  end,
  range,
  onChange,
  prices,
  labels = ["Departure", "Return"],
  min,
  className,
  size = "md",
}: {
  start: string;
  end?: string;
  range: boolean;
  onChange: (start: string, end?: string) => void;
  prices?: PriceQuery | null;
  labels?: [string, string];
  min?: string;
  className?: string;
  size?: "md" | "lg";
}) {
  const today = isoDate(new Date());
  const minDate = min ?? today;
  const [open, setOpen] = useState(false);
  const [phase, setPhase] = useState<Phase>("start");
  const ref = useRef<HTMLDivElement>(null);
  const close = useCallback(() => setOpen(false), []);
  useDismiss(ref, open, close);
  const len = range && end ? Math.max(0, dayDiff(start, end)) : 0;

  function shiftStart(n: number) {
    const s = addDays(start, n);
    if (s < minDate) return;
    if (range && end) onChange(s, addDays(end, n));
    else onChange(s, end);
  }
  function shiftEnd(n: number) {
    if (!end) return;
    const e = addDays(end, n);
    if (e < start) return;
    onChange(start, e);
  }

  function openAt(p: Phase) {
    setPhase(p);
    setOpen(true);
  }

  const lg = size === "lg";
  return (
    // start loading the calendar as soon as someone reaches for the field
    <div ref={ref} className={cn("relative", className)} onPointerEnter={() => void loadCalendar()} onFocus={() => void loadCalendar()}>
      <div className={cn("grid gap-px overflow-hidden rounded-xl border border-border bg-border", range ? "grid-cols-2" : "grid-cols-1")}>
        <Box
          label={labels[0]}
          value={start}
          active={open && phase === "start"}
          lg={lg}
          onOpen={() => openAt("start")}
          onPrev={() => shiftStart(-1)}
          onNext={() => shiftStart(1)}
          prevDisabled={addDays(start, -1) < minDate}
        />
        {range && end && (
          <Box
            label={labels[1]}
            value={end}
            active={open && phase === "end"}
            lg={lg}
            onOpen={() => openAt("end")}
            onPrev={() => shiftEnd(-1)}
            onNext={() => shiftEnd(1)}
            prevDisabled={addDays(end, -1) < start}
          />
        )}
      </div>
      {open && (
        <CalendarPopover
          start={start}
          end={range ? end : undefined}
          range={range}
          phase={phase}
          setPhase={setPhase}
          minDate={minDate}
          prices={prices ?? null}
          tripLen={len}
          onChange={onChange}
          onDone={close}
          labels={labels}
        />
      )}
    </div>
  );
}

function Box({
  label,
  value,
  active,
  onOpen,
  onPrev,
  onNext,
  prevDisabled,
  lg,
}: {
  label: string;
  value: string;
  active: boolean;
  onOpen: () => void;
  onPrev: () => void;
  onNext: () => void;
  prevDisabled?: boolean;
  lg?: boolean;
}) {
  return (
    <div className={cn("flex min-w-0 items-center bg-surface transition-colors", active && "bg-accent-soft/60")}>
      <button
        type="button"
        onClick={onOpen}
        className={cn("flex min-w-0 flex-1 items-center gap-2 text-left focus-visible:outline-none", lg ? "h-14 pl-3" : "h-11 pl-3")}
        aria-label={`${label}: ${formatDate(value)}. Open calendar`}
      >
        <CalendarDays className="hidden size-4 shrink-0 text-muted min-[420px]:block" />
        <span className="min-w-0">
          <span className="block text-[11px] leading-tight font-medium text-muted">{label}</span>
          <span className={cn("block truncate leading-tight font-semibold", lg ? "text-[15px]" : "text-sm")}>{formatDate(value)}</span>
        </span>
      </button>
      <div className="flex shrink-0 items-center pr-1">
        <button
          type="button"
          onClick={onPrev}
          disabled={prevDisabled}
          aria-label={`${label} one day earlier`}
          className="grid size-7 place-items-center rounded-md text-muted hover:bg-surface-2 hover:text-fg disabled:opacity-30"
        >
          <ChevronLeft className="size-4" />
        </button>
        <button
          type="button"
          onClick={onNext}
          aria-label={`${label} one day later`}
          className="grid size-7 place-items-center rounded-md text-muted hover:bg-surface-2 hover:text-fg"
        >
          <ChevronRight className="size-4" />
        </button>
      </div>
    </div>
  );
}
