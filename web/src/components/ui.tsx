"use client";
import {
  forwardRef,
  useEffect,
  useRef,
  useState,
  type ButtonHTMLAttributes,
  type InputHTMLAttributes,
  type ReactNode,
  type RefObject,
  type SelectHTMLAttributes,
} from "react";
import { ChevronDown } from "lucide-react";
import { cn } from "@/lib/utils";

type Variant = "primary" | "secondary" | "ghost" | "danger" | "soft";

export const Button = forwardRef<
  HTMLButtonElement,
  ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: "sm" | "md" | "lg"; loading?: boolean }
>(function Button({ className, variant = "secondary", size = "md", loading, children, disabled, onClick, ...rest }, ref) {
  // Foolproof by default: if the click handler is async, the button stays
  // disabled (with a spinner) until it finishes and extra clicks are ignored.
  const [running, setRunning] = useState(false);
  const busy = useRef(false);
  return (
    <button
      ref={ref}
      disabled={disabled || loading || running}
      aria-busy={loading || running || undefined}
      onClick={(e) => {
        if (busy.current) return;
        const r = onClick?.(e) as unknown;
        if (r && typeof (r as Promise<unknown>).then === "function") {
          busy.current = true;
          setRunning(true);
          (r as Promise<unknown>).finally(() => {
            busy.current = false;
            setRunning(false);
          });
        }
      }}
      className={cn(
        "inline-flex items-center justify-center gap-1.5 rounded-lg font-medium whitespace-nowrap transition-[background-color,border-color,color,box-shadow,filter]",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)] disabled:pointer-events-none disabled:opacity-50",
        size === "sm" ? "h-8 px-3 text-xs" : size === "lg" ? "h-12 px-5 text-[15px]" : "h-10 px-4 text-sm",
        variant === "primary" && "bg-accent text-accent-fg shadow-[var(--shadow)] hover:brightness-110 active:brightness-95",
        variant === "secondary" && "border border-border bg-surface text-fg shadow-[var(--shadow)] hover:border-border-strong hover:bg-surface-2",
        variant === "soft" && "bg-accent-soft text-accent hover:brightness-95 dark:hover:brightness-125",
        variant === "ghost" && "text-muted hover:bg-surface-2 hover:text-fg",
        variant === "danger" && "border border-border bg-surface text-bad hover:bg-bad-soft",
        className,
      )}
      {...rest}
    >
      {(loading || running) && <Spinner className="size-3.5" />}
      {children}
    </button>
  );
});

// Unstyled button with the same double click guard as Button, for icon and
// text buttons that run something async (delete, revoke, sign out...).
export function PlainButton({ onClick, disabled, ...rest }: ButtonHTMLAttributes<HTMLButtonElement>) {
  const [running, setRunning] = useState(false);
  const busy = useRef(false);
  return (
    <button
      type="button"
      {...rest}
      disabled={disabled || running}
      aria-busy={running || undefined}
      onClick={(e) => {
        if (busy.current) return;
        const r = onClick?.(e) as unknown;
        if (r && typeof (r as Promise<unknown>).then === "function") {
          busy.current = true;
          setRunning(true);
          (r as Promise<unknown>).finally(() => {
            busy.current = false;
            setRunning(false);
          });
        }
      }}
    />
  );
}

// For small icon or text buttons: same async guard as Button.
export function useOnce<A extends unknown[]>(fn: (...args: A) => Promise<unknown>) {
  const busy = useRef(false);
  const [running, setRunning] = useState(false);
  const run = async (...args: A) => {
    if (busy.current) return;
    busy.current = true;
    setRunning(true);
    try {
      await fn(...args);
    } finally {
      busy.current = false;
      setRunning(false);
    }
  };
  return [run, running] as const;
}

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(function Input({ className, ...rest }, ref) {
  return (
    <input
      ref={ref}
      className={cn(
        "h-10 w-full rounded-lg border border-border bg-surface px-3 text-sm text-fg placeholder:text-faint transition-colors",
        "hover:border-border-strong focus:border-accent focus:ring-2 focus:ring-[var(--ring)] focus:outline-none",
        className,
      )}
      {...rest}
    />
  );
});

export function Select({ className, children, ...rest }: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <span className={cn("relative inline-flex min-w-0", className?.includes("w-full") && "w-full")}>
      <select
        className={cn(
          "h-10 w-full min-w-0 cursor-pointer appearance-none rounded-lg border border-border bg-surface pr-8 pl-3 text-sm text-fg transition-colors",
          "hover:border-border-strong focus:border-accent focus:ring-2 focus:ring-[var(--ring)] focus:outline-none",
          className,
        )}
        {...rest}
      >
        {children}
      </select>
      <ChevronDown className="pointer-events-none absolute top-1/2 right-2.5 size-3.5 -translate-y-1/2 text-muted" />
    </span>
  );
}

export function Field({ label, hint, children, className }: { label: string; hint?: ReactNode; children: ReactNode; className?: string }) {
  return (
    // A div, not a <label>: a label forwards clicks to its first button, which
    // broke picking from dropdowns that contain buttons (chip remove, stars).
    <div role="group" aria-label={label} className={cn("flex min-w-0 flex-col gap-1.5", className)}>
      <span className="text-xs font-medium text-muted">{label}</span>
      {children}
      {hint && <span className="text-xs text-faint">{hint}</span>}
    </div>
  );
}

export function Card({ className, children, ...rest }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div className={cn("rounded-2xl border border-border bg-surface shadow-[var(--shadow)]", className)} {...rest}>
      {children}
    </div>
  );
}

const tones = {
  neutral: "bg-surface-2 text-muted border-transparent",
  accent: "bg-accent-soft text-accent border-transparent",
  good: "bg-good-soft text-good border-transparent",
  warn: "bg-warn-soft text-warn border-transparent",
  danger: "bg-bad-soft text-bad border-transparent",
  bad: "bg-bad-soft text-bad border-transparent",
  info: "bg-info-soft text-info border-transparent",
} as const;

export function Badge({ tone = "neutral", className, children, title }: { tone?: keyof typeof tones; className?: string; children: ReactNode; title?: string }) {
  return (
    <span
      title={title}
      className={cn("inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-[11px] leading-4 font-medium whitespace-nowrap", tones[tone], className)}
    >
      {children}
    </span>
  );
}

export function Switch({ checked, onChange, label, disabled }: { checked: boolean; onChange: (v: boolean) => void; label?: ReactNode; disabled?: boolean }) {
  return (
    <label className={cn("inline-flex items-center gap-2 text-sm select-none", disabled ? "opacity-50" : "cursor-pointer")}>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        disabled={disabled}
        onClick={() => onChange(!checked)}
        className={cn(
          "relative h-5 w-9 shrink-0 rounded-full transition-colors focus-visible:ring-2 focus-visible:ring-[var(--ring)] focus-visible:outline-none",
          checked ? "bg-accent" : "bg-border-strong",
        )}
      >
        <span className={cn("absolute top-0.5 left-0.5 size-4 rounded-full bg-white shadow transition-transform", checked && "translate-x-4")} />
      </button>
      {label}
    </label>
  );
}

export function Segmented<T extends string>({
  value,
  onChange,
  options,
  size = "md",
  className,
}: {
  value: T;
  onChange: (v: T) => void;
  options: { value: T; label: ReactNode }[];
  size?: "sm" | "md";
  className?: string;
}) {
  return (
    <div role="radiogroup" className={cn("inline-flex rounded-lg bg-surface-2 p-0.5", className)}>
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          role="radio"
          aria-checked={value === o.value}
          onClick={() => onChange(o.value)}
          className={cn(
            "rounded-md px-3 font-medium whitespace-nowrap transition-colors focus-visible:ring-2 focus-visible:ring-[var(--ring)] focus-visible:outline-none",
            size === "sm" ? "h-7 text-xs" : "h-8 text-sm",
            value === o.value ? "bg-surface text-fg shadow-[var(--shadow)]" : "text-muted hover:text-fg",
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function Spinner({ className }: { className?: string }) {
  return (
    <svg className={cn("size-4 animate-spin", className)} viewBox="0 0 24 24" fill="none" aria-hidden>
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeOpacity="0.25" strokeWidth="3" />
      <path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
    </svg>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cn("skeleton", className)} aria-hidden />;
}

export function Empty({ title, children, action, icon }: { title: string; children?: ReactNode; action?: ReactNode; icon?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 rounded-2xl border border-dashed border-border-strong/70 bg-surface/50 px-6 py-12 text-center">
      {icon && <div className="mb-1 grid size-11 place-items-center rounded-full bg-accent-soft text-accent">{icon}</div>}
      <div className="text-[15px] font-semibold">{title}</div>
      {children && <div className="max-w-md text-sm text-muted">{children}</div>}
      {action && <div className="mt-2">{action}</div>}
    </div>
  );
}

export function ErrorNote({ children }: { children: ReactNode }) {
  return <div className="rounded-xl border border-bad/25 bg-bad-soft px-3.5 py-2.5 text-sm text-bad">{children}</div>;
}

export function PageHeader({ title, sub, actions }: { title: string; sub?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
      <div className="min-w-0">
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        {sub && <p className="mt-1 max-w-2xl text-sm text-muted">{sub}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

// Close a popover when clicking outside of it or pressing Escape.
export function useDismiss(ref: RefObject<HTMLElement | null>, open: boolean, close: () => void) {
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent | TouchEvent) => {
      if (!ref.current?.contains(e.target as Node)) close();
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && close();
    document.addEventListener("mousedown", onDown);
    document.addEventListener("touchstart", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("touchstart", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [ref, open, close]);
}

// Hover/focus tooltip without a library. Wraps its trigger.
export function Tip({ label, children, className, side = "top" }: { label: ReactNode; children: ReactNode; className?: string; side?: "top" | "bottom" }) {
  return (
    <span className={cn("group/tip relative inline-flex", className)}>
      {children}
      <span
        role="tooltip"
        className={cn(
          "pointer-events-none absolute left-1/2 z-50 w-max max-w-64 -translate-x-1/2 rounded-lg bg-fg px-2.5 py-1.5 text-xs leading-snug font-normal whitespace-normal text-bg opacity-0 shadow-lg transition-opacity delay-150 group-focus-within/tip:opacity-100 group-hover/tip:opacity-100",
          side === "top" ? "bottom-full mb-1.5" : "top-full mt-1.5",
        )}
      >
        {label}
      </span>
    </span>
  );
}
