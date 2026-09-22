// Full amounts, never abbreviated: "$1,000", "NOK 12,450". The opts argument
// is accepted for old call sites and ignored.
export function formatPrice(amount: number | null | undefined, currency: string, _opts?: { compact?: boolean }) {
  void _opts;
  if (amount == null || Number.isNaN(amount)) return "–";
  try {
    return new Intl.NumberFormat("en-US", {
      style: "currency",
      currency,
      maximumFractionDigits: 0,
      minimumFractionDigits: 0,
    }).format(Math.round(amount));
  } catch {
    return `${currency} ${Math.round(amount).toLocaleString("en-US")}`;
  }
}

export function formatDuration(min: number | null | undefined) {
  if (min == null) return "–";
  const h = Math.floor(min / 60);
  const m = Math.round(min % 60);
  if (h >= 48) return `${Math.floor(h / 24)}d ${h % 24}h`;
  return m ? `${h}h ${m}m` : `${h}h`;
}

// Engine datetimes are naive local times ("2026-11-20T12:35:00"). Parse the
// parts directly so the browser time zone never shifts them.
export function parseLocal(iso: string) {
  const [d, t = "00:00"] = iso.split("T");
  const [y, mo, da] = d.split("-").map(Number);
  const [h, mi] = t.split(":").map(Number);
  return { y, mo, da, h, mi };
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

export function formatTime(iso: string) {
  const { h, mi } = parseLocal(iso);
  return `${String(h).padStart(2, "0")}:${String(mi).padStart(2, "0")}`;
}

export function formatDate(iso: string | null | undefined, withWeekday = true) {
  if (!iso) return "–";
  const { y, mo, da } = parseLocal(iso);
  const wd = DAYS[new Date(Date.UTC(y, mo - 1, da)).getUTCDay()];
  return withWeekday ? `${wd}, ${MONTHS[mo - 1]} ${da}` : `${MONTHS[mo - 1]} ${da}`;
}

export function dayDiff(a: string, b: string) {
  const pa = parseLocal(a);
  const pb = parseLocal(b);
  return Math.round(
    (Date.UTC(pb.y, pb.mo - 1, pb.da) - Date.UTC(pa.y, pa.mo - 1, pa.da)) / 86400000,
  );
}

export function relativeTime(date: string | Date | null | undefined) {
  if (!date) return "never";
  const d = typeof date === "string" ? new Date(date) : date;
  const s = Math.round((Date.now() - d.getTime()) / 1000);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

export function isoDate(d: Date) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

export function addDays(iso: string, n: number) {
  const { y, mo, da } = parseLocal(iso);
  const d = new Date(Date.UTC(y, mo - 1, da + n));
  return d.toISOString().slice(0, 10);
}
