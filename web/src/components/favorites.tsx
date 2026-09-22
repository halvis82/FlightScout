"use client";
import { Star } from "lucide-react";
import { useApp, type Place } from "./app-context";
import { api } from "@/lib/client";
import { cityOf } from "@/lib/airports-client";
import { cn } from "@/lib/utils";
import { toast } from "./stores";

// Favorite airports and cities are saved places. Starring a code creates a
// one airport place labeled with its city; unstarring removes it.
export function useFavorites() {
  const { places, refreshPlaces } = useApp();
  const find = (code: string) => places.find((p) => p.codes.length === 1 && p.codes[0] === code);
  const isStarred = (code: string) => Boolean(find(code)) || places.some((p) => p.codes.includes(code));
  async function toggle(code: string) {
    const p = find(code);
    if (p) {
      await api(`/places/${p.id}`, { method: "DELETE" });
      toast({ text: `Removed ${p.label} from favorites` }, 2500);
    } else if (!places.some((x) => x.codes.includes(code))) {
      const label = cityOf(code) ?? code;
      await api("/places", { body: { label, codes: [code], kind: "frequent" } });
      toast({ text: `${label} added to favorites`, action: { label: "Manage", href: "/settings#places" } }, 3000);
    }
    refreshPlaces();
  }
  return { isStarred, toggle, places };
}

export function StarButton({ code, className, size = "sm" }: { code: string; className?: string; size?: "sm" | "md" }) {
  const { isStarred, toggle } = useFavorites();
  const on = isStarred(code);
  return (
    <button
      type="button"
      onMouseDown={(e) => e.preventDefault()}
      onClick={(e) => {
        e.stopPropagation();
        e.preventDefault();
        toggle(code);
      }}
      className={cn("grid shrink-0 place-items-center rounded-md transition-colors hover:bg-surface-2", size === "sm" ? "size-7" : "size-8", className)}
      aria-label={on ? `Remove ${code} from favorites` : `Add ${code} to favorites`}
      aria-pressed={on}
      title={on ? "Favorite. Click to remove" : "Add to favorites"}
    >
      <Star className={cn(size === "sm" ? "size-3.5" : "size-4", on ? "fill-[oklch(0.8_0.16_85)] text-[oklch(0.72_0.16_85)]" : "text-faint")} />
    </button>
  );
}

export function placeKindLabel(p: Place) {
  return p.kind === "home" ? "Home" : p.kind === "interested" ? "Want to go" : "Favorite";
}
