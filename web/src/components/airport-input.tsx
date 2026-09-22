"use client";
import { useEffect, useMemo, useRef, useState } from "react";
import { X } from "lucide-react";
import { cn } from "@/lib/utils";
import { METROS, searchAirports, useAirports } from "@/lib/airports-client";
import { useApp } from "./app-context";

type Option = { code: string; title: string; sub: string; codes: string[] };

// Multi airport picker. Accepts IATA codes, metro codes (NYC), city names and
// saved places. Values are airport or metro codes.
export function AirportInput({
  value,
  onChange,
  placeholder = "City or airport",
  single,
  className,
}: {
  value: string[];
  onChange: (v: string[]) => void;
  placeholder?: string;
  single?: boolean;
  className?: string;
}) {
  const { rows, get } = useAirports();
  const { places } = useApp();
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const [hi, setHi] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const boxRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const close = (e: MouseEvent) => {
      if (!boxRef.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);

  const options = useMemo<Option[]>(() => {
    const s = q.trim().toLowerCase();
    const out: Option[] = [];
    if (!s) {
      for (const p of places) out.push({ code: p.codes.join(","), title: p.label, sub: `${p.kind} · ${p.codes.join(", ")}`, codes: p.codes });
      return out.slice(0, 10);
    }
    for (const p of places)
      if (p.label.toLowerCase().includes(s)) out.push({ code: p.codes.join(","), title: p.label, sub: `Saved place · ${p.codes.join(", ")}`, codes: p.codes });
    for (const [code, m] of Object.entries(METROS))
      if (code.toLowerCase().startsWith(s) || m.label.toLowerCase().includes(s))
        out.push({ code, title: m.label, sub: `${code} · ${m.codes.join(", ")}`, codes: [code] });
    if (rows)
      for (const r of searchAirports(rows, s))
        out.push({ code: r.iata, title: `${r.city || r.name} (${r.iata})`, sub: `${r.name} · ${r.country}`, codes: [r.iata] });
    return out.slice(0, 10);
  }, [q, rows, places]);

  function add(codes: string[]) {
    const next = single ? codes.slice(0, 1) : [...new Set([...value, ...codes])];
    onChange(next);
    setQ("");
    setHi(0);
    if (single) setOpen(false);
    inputRef.current?.focus();
  }

  function commitTyped() {
    const t = q.trim().toUpperCase();
    if (/^[A-Z]{3,4}$/.test(t)) add([t]);
    else if (options[hi]) add(options[hi].codes);
  }

  return (
    <div ref={boxRef} className={cn("relative", className)}>
      <div
        className="flex min-h-9 w-full cursor-text flex-wrap items-center gap-1 rounded-md border border-border bg-surface px-1.5 py-1 focus-within:border-accent focus-within:ring-2 focus-within:ring-[var(--ring)]"
        onClick={() => inputRef.current?.focus()}
      >
        {value.map((c) => {
          const a = get(c);
          return (
            <span
              key={c}
              title={METROS[c]?.label ?? (a ? `${a.name}, ${a.city}` : c)}
              className="inline-flex items-center gap-0.5 rounded bg-accent-soft py-0.5 pr-0.5 pl-1.5 font-mono text-xs font-semibold text-accent"
            >
              {c}
              <button
                type="button"
                aria-label={`Remove ${c}`}
                className="rounded p-0.5 hover:bg-accent/15"
                onClick={(e) => {
                  e.stopPropagation();
                  onChange(value.filter((x) => x !== c));
                }}
              >
                <X className="size-3" />
              </button>
            </span>
          );
        })}
        <input
          ref={inputRef}
          value={q}
          onChange={(e) => {
            setQ(e.target.value);
            setOpen(true);
            setHi(0);
          }}
          onFocus={() => setOpen(true)}
          onKeyDown={(e) => {
            if (e.key === "ArrowDown") {
              e.preventDefault();
              setHi((h) => Math.min(h + 1, options.length - 1));
            } else if (e.key === "ArrowUp") {
              e.preventDefault();
              setHi((h) => Math.max(h - 1, 0));
            } else if (e.key === "Enter" || e.key === "," || e.key === "Tab") {
              if (q.trim()) {
                e.preventDefault();
                commitTyped();
              }
            } else if (e.key === "Backspace" && !q && value.length) {
              onChange(value.slice(0, -1));
            } else if (e.key === "Escape") setOpen(false);
          }}
          placeholder={value.length ? "" : placeholder}
          className="h-6 min-w-[5rem] flex-1 bg-transparent px-1 text-sm outline-none placeholder:text-faint"
        />
      </div>
      {open && options.length > 0 && (
        <div className="absolute z-30 mt-1 w-full min-w-[260px] overflow-hidden rounded-md border border-border bg-surface shadow-lg">
          {!q && <div className="px-2.5 pt-2 pb-1 text-[11px] font-medium uppercase tracking-wide text-faint">Your places</div>}
          {options.map((o, i) => (
            <button
              key={o.code + i}
              type="button"
              onMouseEnter={() => setHi(i)}
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => add(o.codes)}
              className={cn("flex w-full flex-col items-start px-2.5 py-1.5 text-left", i === hi && "bg-surface-2")}
            >
              <span className="text-sm">{o.title}</span>
              <span className="text-xs text-muted">{o.sub}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

// Quick pick chips for saved places, shown under route inputs.
export function PlaceChips({ onPick, kinds }: { onPick: (codes: string[]) => void; kinds?: string[] }) {
  const { places } = useApp();
  const list = places.filter((p) => !kinds || kinds.includes(p.kind));
  if (!list.length) return null;
  return (
    <div className="flex flex-wrap gap-1">
      {list.map((p) => (
        <button
          key={p.id}
          type="button"
          onClick={() => onPick(p.codes)}
          title={p.codes.join(", ")}
          className="rounded-full border border-border px-2 py-0.5 text-xs text-muted hover:border-accent hover:text-accent"
        >
          {p.label}
        </button>
      ))}
    </div>
  );
}
