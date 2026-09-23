"use client";
import { useEffect, useId, useMemo, useRef, useState, type ReactNode } from "react";
import { Building2, MapPin, Plane, Star, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { METROS, airportWithCity, cityOf, countryName, fold, searchAirports, useAirports } from "@/lib/airports-client";
import { useApp } from "./app-context";
import { StarButton } from "./favorites";

type Option = { key: string; title: string; sub: string; codes: string[]; kind: "place" | "metro" | "airport"; star?: string };

// Multi airport picker. Accepts IATA codes, metro codes (NYC), city names
// (accents optional) and saved places. Values are airport or metro codes.
export function AirportInput({
  value,
  onChange,
  placeholder = "City or airport",
  single,
  className,
  label,
  icon,
  size = "md",
  autoFocus,
}: {
  value: string[];
  onChange: (v: string[]) => void;
  placeholder?: string;
  single?: boolean;
  className?: string;
  label?: string;
  icon?: ReactNode;
  size?: "md" | "lg";
  autoFocus?: boolean;
}) {
  const { rows } = useAirports();
  const { places } = useApp();
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const [hi, setHi] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const boxRef = useRef<HTMLDivElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const id = useId();

  useEffect(() => {
    const close = (e: MouseEvent) => {
      if (!boxRef.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);

  const options = useMemo<Option[]>(() => {
    const s = fold(q);
    const out: Option[] = [];
    if (!s) {
      for (const p of places)
        out.push({ key: `p${p.id}`, title: p.label, sub: p.codes.map((c) => `${c}${cityOf(c) && cityOf(c) !== p.label ? ` (${cityOf(c)})` : ""}`).join(", "), codes: p.codes, kind: "place" });
      return out.slice(0, 10);
    }
    for (const p of places) if (fold(p.label).includes(s)) out.push({ key: `p${p.id}`, title: p.label, sub: `Saved · ${p.codes.join(", ")}`, codes: p.codes, kind: "place" });
    for (const [code, m] of Object.entries(METROS))
      if (code.toLowerCase().startsWith(s) || fold(m.label).includes(s)) out.push({ key: code, title: m.label, sub: `${code} · ${m.codes.join(", ")}`, codes: [code], kind: "metro" });
    if (rows)
      for (const r of searchAirports(rows, s, 8))
        out.push({ key: r.iata, title: airportWithCity(r.iata), sub: `${r.iata} · ${countryName(r.country)}`, codes: [r.iata], kind: "airport", star: r.iata });
    return out.slice(0, 10);
  }, [q, rows, places]);

  useEffect(() => {
    listRef.current?.querySelector(`[data-i="${hi}"]`)?.scrollIntoView({ block: "nearest" });
  }, [hi]);

  function add(codes: string[]) {
    const next = single ? codes.slice(0, 1) : [...new Set([...value, ...codes])];
    onChange(next);
    setQ("");
    setHi(0);
    setOpen(false);
  }

  function commitTyped() {
    const t = q.trim().toUpperCase();
    if (options[hi]) add(options[hi].codes);
    else if (/^[A-Z]{3,4}$/.test(t)) add([t]);
  }

  const lg = size === "lg";
  return (
    <div ref={boxRef} className={cn("relative min-w-0", className)}>
      <div
        className={cn(
          "group/ai flex w-full cursor-text items-center gap-2 border border-border bg-surface transition-colors hover:border-border-strong",
          "focus-within:border-accent focus-within:ring-2 focus-within:ring-[var(--ring)]",
          lg ? "min-h-14 rounded-xl px-3 py-1.5" : "min-h-10 rounded-lg px-2 py-1",
        )}
        onClick={() => inputRef.current?.focus()}
      >
        {icon && <span className="shrink-0 text-muted">{icon}</span>}
        <div className="min-w-0 flex-1">
          {label && <div className="text-[11px] leading-tight font-medium text-muted">{label}</div>}
          <div className="flex flex-wrap items-center gap-1">
            {value.map((c) => (
              <span
                key={c}
                title={airportWithCity(c)}
                className={cn(
                  "inline-flex max-w-full items-center gap-0.5 rounded-md bg-accent-soft py-0.5 pr-0.5 pl-1.5 text-accent",
                  lg ? "text-sm" : "text-xs",
                )}
              >
                <span className="truncate">
                  {METROS[c] ? (
                    <span className="font-semibold">{METROS[c].label}</span>
                  ) : (
                    <>
                      <span className="font-semibold">{c}</span>
                      {cityOf(c) && <span className="opacity-80"> ({cityOf(c)})</span>}
                    </>
                  )}
                </span>
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
            ))}
            <input
              ref={inputRef}
              value={q}
              autoFocus={autoFocus}
              role="combobox"
              aria-expanded={open && options.length > 0}
              aria-controls={`${id}-list`}
              aria-activedescendant={open && options[hi] ? `${id}-${hi}` : undefined}
              aria-autocomplete="list"
              aria-label={label ?? placeholder}
              onChange={(e) => {
                setQ(e.target.value);
                setOpen(true);
                setHi(0);
              }}
              onFocus={() => setOpen(true)}
              onKeyDown={(e) => {
                if (e.key === "ArrowDown") {
                  e.preventDefault();
                  setOpen(true);
                  setHi((h) => Math.min(h + 1, options.length - 1));
                } else if (e.key === "ArrowUp") {
                  e.preventDefault();
                  setHi((h) => Math.max(h - 1, 0));
                } else if (e.key === "Enter" || e.key === "," || e.key === "Tab") {
                  if (q.trim()) {
                    e.preventDefault();
                    commitTyped();
                  } else if (e.key === "Enter" && open && options[hi]) {
                    e.preventDefault();
                    add(options[hi].codes);
                  }
                } else if (e.key === "Backspace" && !q && value.length) {
                  onChange(value.slice(0, -1));
                } else if (e.key === "Escape") setOpen(false);
              }}
              placeholder={value.length ? (single ? "" : "Add airport") : placeholder}
              className={cn(
                "h-6 min-w-[4.5rem] flex-1 bg-transparent px-0.5 outline-none placeholder:text-faint",
                lg ? "text-[15px] font-medium" : "text-sm",
                single && value.length > 0 && !q && "w-0 min-w-0",
              )}
            />
          </div>
        </div>
        {value.length > 0 && (
          <button
            type="button"
            aria-label="Clear all"
            title="Clear"
            onMouseDown={(e) => e.preventDefault()}
            onClick={(e) => {
              e.stopPropagation();
              onChange([]);
              setQ("");
              inputRef.current?.focus();
            }}
            className="shrink-0 rounded-full p-1 text-faint opacity-0 transition-opacity hover:bg-surface-2 hover:text-fg group-hover/ai:opacity-100 focus-visible:opacity-100"
          >
            <X className="size-3.5" />
          </button>
        )}
      </div>
      {open && options.length > 0 && (
        <div
          ref={listRef}
          id={`${id}-list`}
          role="listbox"
          className="pop-in absolute z-40 mt-1.5 max-h-80 w-full min-w-[300px] overflow-y-auto rounded-xl border border-border bg-surface p-1 shadow-[var(--shadow-lg)]"
        >
          {!q && (
            <div className="flex items-center gap-1.5 px-2.5 pt-1.5 pb-1 text-[11px] font-medium text-faint">
              <Star className="size-3" /> Your places
            </div>
          )}
          {options.map((o, i) => {
            const Icon = o.kind === "place" ? MapPin : o.kind === "metro" ? Building2 : Plane;
            return (
              <div
                key={o.key + i}
                id={`${id}-${i}`}
                data-i={i}
                role="option"
                aria-selected={i === hi}
                onMouseEnter={() => setHi(i)}
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => add(o.codes)}
                className={cn("flex cursor-pointer items-center gap-2.5 rounded-lg px-2.5 py-2", i === hi && "bg-surface-2")}
              >
                <span className="grid size-8 shrink-0 place-items-center rounded-lg bg-surface-2 text-muted">
                  <Icon className="size-4" />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-medium">{o.title}</span>
                  <span className="block truncate text-xs text-muted">{o.sub}</span>
                </span>
                {o.star && <StarButton code={o.star} />}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

// Quick pick chips for saved places, shown under route inputs.
export function PlaceChips({ onPick, kinds, className, prefix }: { onPick: (codes: string[]) => void; kinds?: string[]; className?: string; prefix?: string }) {
  const { places } = useApp();
  const list = places.filter((p) => !kinds || kinds.includes(p.kind));
  if (!list.length) return null;
  return (
    <div className={cn("flex flex-wrap gap-1.5", className)}>
      {list.map((p) => (
        <button
          key={p.id}
          type="button"
          onClick={() => onPick(p.codes)}
          title={p.codes.map((c) => airportWithCity(c)).join(", ")}
          className="inline-flex items-center gap-1 rounded-full border border-border bg-surface px-2.5 py-1 text-xs text-muted transition-colors hover:border-accent hover:text-accent"
        >
          {prefix && <span className="text-faint">{prefix}</span>}
          {p.label}
        </button>
      ))}
    </div>
  );
}
