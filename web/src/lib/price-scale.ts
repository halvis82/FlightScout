// Continuous price color ramp: green (cheapest) through yellow and orange to
// red (most expensive), relative to the visible set. OKLCH keeps perceived
// lightness steady; the lightness and chroma come from CSS vars per theme.

export function priceScale(values: number[]) {
  const finite = values.filter((v) => Number.isFinite(v));
  const min = finite.length ? Math.min(...finite) : 0;
  const max = finite.length ? Math.max(...finite) : 0;
  // Rank based (percentile) so one outlier doesn't squash everything else
  // into one color; blended with the linear position to keep big gaps visible.
  const sorted = [...finite].sort((a, b) => a - b);
  const rank = (v: number) => {
    if (sorted.length < 2) return 0;
    let lo = 0, hi = sorted.length;
    while (lo < hi) {
      const mid = (lo + hi) >> 1;
      if (sorted[mid] < v) lo = mid + 1;
      else hi = mid;
    }
    return lo / (sorted.length - 1);
  };
  const lin = (v: number) => (max > min ? Math.min(1, Math.max(0, (v - min) / (max - min))) : 0);
  const t = (v: number) => Math.min(1, 0.75 * rank(v) + 0.25 * lin(v));
  // hue 150 (green) -> 95 (yellow) -> 60 (orange) -> 27 (red)
  const hue = (v: number) => 150 - t(v) * 123;
  return {
    min,
    max,
    t,
    color: (v: number) => `oklch(var(--price-l) var(--price-c) ${hue(v).toFixed(1)})`,
    bg: (v: number) => `oklch(var(--price-bg-l) var(--price-bg-c) ${hue(v).toFixed(1)})`,
    // theme independent fill that stays readable with dark text (map labels)
    solid: (v: number) => `oklch(0.85 0.14 ${hue(v).toFixed(1)})`,
  };
}

export const PRICE_GRADIENT =
  "linear-gradient(90deg, oklch(var(--price-l) var(--price-c) 150), oklch(var(--price-l) var(--price-c) 95), oklch(var(--price-l) var(--price-c) 60), oklch(var(--price-l) var(--price-c) 27))";
