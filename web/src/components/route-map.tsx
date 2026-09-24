"use client";
import { useEffect, useRef, useState } from "react";
import * as maplibregl from "maplibre-gl";
import type { GeoJSONSource, Map as MLMap, Marker } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { loadAirports, airport } from "@/lib/airports-client";
import { cn } from "@/lib/utils";

export type MapArc = { from: string; to: string; tone?: "primary" | "muted" | "alt"; dashed?: boolean };
export type MapPoint = {
  code: string;
  lat?: number | null;
  lon?: number | null;
  label?: string;
  tone?: "origin" | "dest" | "hub" | "price" | "best";
  onClick?: () => void;
  title?: string;
  color?: string; // background color (price scale), overrides tone colors
  dot?: boolean; // render a small colored dot instead of a label (declutter)
};

// Served from public/maplibre (copied on postinstall), see scripts/copy-maplibre-worker.mjs.
maplibregl.setWorkerUrl("/maplibre/maplibre-gl-worker.mjs");

const LIGHT = "https://tiles.openfreemap.org/styles/positron";
const DARK = "https://tiles.openfreemap.org/styles/dark";

function isDark() {
  const t = document.documentElement.dataset.theme;
  if (t === "dark") return true;
  if (t === "light") return false;
  return window.matchMedia("(prefers-color-scheme: dark)").matches;
}

// Points along the great circle between two coordinates, with longitudes
// unwrapped so lines crossing the antimeridian draw the short way.
function greatCircle(a: [number, number], b: [number, number], n = 64): [number, number][] {
  const toRad = Math.PI / 180;
  const [lon1, lat1] = [a[0] * toRad, a[1] * toRad];
  const [lon2, lat2] = [b[0] * toRad, b[1] * toRad];
  const d =
    2 *
    Math.asin(
      Math.sqrt(Math.sin((lat2 - lat1) / 2) ** 2 + Math.cos(lat1) * Math.cos(lat2) * Math.sin((lon2 - lon1) / 2) ** 2),
    );
  if (!d) return [a, b];
  const pts: [number, number][] = [];
  for (let i = 0; i <= n; i++) {
    const f = i / n;
    const A = Math.sin((1 - f) * d) / Math.sin(d);
    const B = Math.sin(f * d) / Math.sin(d);
    const x = A * Math.cos(lat1) * Math.cos(lon1) + B * Math.cos(lat2) * Math.cos(lon2);
    const y = A * Math.cos(lat1) * Math.sin(lon1) + B * Math.cos(lat2) * Math.sin(lon2);
    const z = A * Math.sin(lat1) + B * Math.sin(lat2);
    pts.push([Math.atan2(y, x) / toRad, Math.atan2(z, Math.sqrt(x * x + y * y)) / toRad]);
  }
  for (let i = 1; i < pts.length; i++) {
    while (pts[i][0] - pts[i - 1][0] > 180) pts[i][0] -= 360;
    while (pts[i][0] - pts[i - 1][0] < -180) pts[i][0] += 360;
  }
  return pts;
}

export function RouteMap({
  arcs = [],
  points = [],
  className,
  fitKey,
}: {
  arcs?: MapArc[];
  points?: MapPoint[];
  className?: string;
  fitKey?: string;
}) {
  const el = useRef<HTMLDivElement>(null);
  const map = useRef<MLMap | null>(null);
  const keyed = useRef(new Map<string, { marker: maplibregl.Marker; node: HTMLButtonElement }>());
  const handlers = useRef(new Map<string, (() => void) | undefined>());
  const markers = useRef<Marker[]>([]);
  const [ready, setReady] = useState(false);
  const [airportsLoaded, setAirportsLoaded] = useState(false);
  const data = useRef({ arcs, points });
  data.current = { arcs, points };

  useEffect(() => {
    loadAirports().then(() => setAirportsLoaded(true));
    if (!el.current) return;
    const m = new maplibregl.Map({
      container: el.current,
      style: isDark() ? DARK : LIGHT,
      center: [0, 30],
      zoom: 1,
      attributionControl: { compact: true },
      renderWorldCopies: true,
    });
    m.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    m.on("load", () => setReady(true));
    // Re-add our layers whenever the base style changes (theme switch).
    m.on("style.load", () => setReady((r) => (r ? (sync(), r) : r)));
    map.current = m;

    const obs = new MutationObserver(() => m.setStyle(isDark() ? DARK : LIGHT));
    obs.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const onMq = () => m.setStyle(isDark() ? DARK : LIGHT);
    mq.addEventListener("change", onMq);
    return () => {
      obs.disconnect();
      mq.removeEventListener("change", onMq);
      m.remove();
      map.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function coord(p: { code: string; lat?: number | null; lon?: number | null }): [number, number] | null {
    if (p.lat != null && p.lon != null) return [p.lon, p.lat];
    const a = airport(p.code);
    return a ? [a.lon, a.lat] : null;
  }

  function sync() {
    const m = map.current;
    if (!m || !m.isStyleLoaded()) return;
    const { arcs, points } = data.current;
    const accent = getComputedStyle(document.documentElement).getPropertyValue("--accent").trim() || "#1d5fd6";
    const muted = getComputedStyle(document.documentElement).getPropertyValue("--faint").trim() || "#8b94a1";
    const alt = getComputedStyle(document.documentElement).getPropertyValue("--info").trim() || "#5b4bc4";
    const features = arcs.flatMap((a) => {
      const f = coord({ code: a.from });
      const t = coord({ code: a.to });
      if (!f || !t) return [];
      return [
        {
          type: "Feature" as const,
          properties: { color: a.tone === "muted" ? muted : a.tone === "alt" ? alt : accent, dashed: a.dashed ? 1 : 0, w: a.tone === "muted" ? 1.2 : 2.4 },
          geometry: { type: "LineString" as const, coordinates: greatCircle(f, t) },
        },
      ];
    });
    const fc = { type: "FeatureCollection" as const, features };
    const src = m.getSource("arcs") as GeoJSONSource | undefined;
    if (src) src.setData(fc);
    else {
      m.addSource("arcs", { type: "geojson", data: fc });
      m.addLayer({
        id: "arcs-solid",
        type: "line",
        source: "arcs",
        filter: ["==", ["get", "dashed"], 0],
        paint: { "line-color": ["get", "color"], "line-width": ["get", "w"], "line-opacity": 0.9 },
        layout: { "line-cap": "round" },
      });
      m.addLayer({
        id: "arcs-dashed",
        type: "line",
        source: "arcs",
        filter: ["==", ["get", "dashed"], 1],
        paint: { "line-color": ["get", "color"], "line-width": ["get", "w"], "line-dasharray": [2, 2], "line-opacity": 0.9 },
      });
    }

    // Markers are keyed by code and updated in place: rebuilding them on every
    // update (explore streams results in) swallowed clicks mid-render.
    const live = new Set<string>();
    points.forEach((p, i) => {
      const c = coord(p);
      if (!c) return;
      const key = `${p.tone ?? "price"}:${p.code}`;
      live.add(key);
      handlers.current.set(key, p.onClick);
      let entry = keyed.current.get(key);
      if (!entry) {
        const node = document.createElement("button");
        node.type = "button";
        node.addEventListener("click", (e) => {
          e.stopPropagation();
          handlers.current.get(key)?.();
        });
        entry = { marker: new maplibregl.Marker({ element: node }).setLngLat(c).addTo(m), node };
        keyed.current.set(key, entry);
      } else entry.marker.setLngLat(c);
      const node = entry.node;
      node.title = p.title ?? p.code;
      const tone = p.tone ?? "price";
      // keep MapLibre's own classes, maplibregl-marker is what positions the node
      const own = [...node.classList].filter((c) => c.startsWith("maplibregl-"));
      node.className = [
        ...own,
        "rounded-full border font-sans text-[11px] font-semibold leading-none shadow-sm transition-transform hover:scale-110 hover:z-10",
        tone === "origin" && "bg-fg text-bg border-transparent px-1.5 py-1",
        tone === "dest" && "bg-accent text-accent-fg border-transparent px-1.5 py-1",
        tone === "hub" && "bg-surface text-muted border-border px-1.5 py-1",
        tone === "price" && "bg-surface text-fg border-border-strong px-1.5 py-1",
        tone === "best" && "bg-good text-white border-transparent px-1.5 py-1",
      ]
        .filter(Boolean)
        .join(" ");
      node.style.background = p.color ?? "";
      node.style.color = p.color ? "#0b0d10" : "";
      node.style.borderColor = p.color ? "transparent" : "";
      node.style.cursor = p.onClick ? "pointer" : "default";
      node.textContent = p.label ?? p.code;
      node.dataset.rank = String(i);
      // price markers take part in collision handling (cheaper first)
      if (p.color) node.dataset.label = "1";
      else delete node.dataset.label;
    });
    for (const [key, entry] of keyed.current)
      if (!live.has(key)) {
        entry.marker.remove();
        keyed.current.delete(key);
        handlers.current.delete(key);
      }
    markers.current = [...keyed.current.values()]
      .map((e) => e.marker)
      .sort((x, y) => Number(x.getElement().dataset.rank ?? 0) - Number(y.getElement().dataset.rank ?? 0));
    declutter();
  }

  // Hide price labels that overlap a more important one (earlier in the
  // list = cheaper). Hidden ones become small dots. Runs after zoom and pan.
  function declutter() {
    const placed: DOMRect[] = [];
    for (const mk of markers.current) {
      const el = mk.getElement();
      if (el.dataset.label !== "1") continue;
      el.style.visibility = "";
      el.classList.remove("fs-dot");
      const r = el.getBoundingClientRect();
      const hit = placed.some((q) => r.left < q.right + 2 && r.right > q.left - 2 && r.top < q.bottom + 2 && r.bottom > q.top - 2);
      if (hit) el.classList.add("fs-dot");
      else placed.push(r);
    }
  }

  function fit() {
    const m = map.current;
    if (!m) return;
    const coords: [number, number][] = [];
    for (const a of data.current.arcs) {
      const f = coord({ code: a.from });
      const t = coord({ code: a.to });
      if (f && t) coords.push(...greatCircle(f, t, 16));
    }
    for (const p of data.current.points) {
      const c = coord(p);
      if (c) coords.push(c);
    }
    if (!coords.length) return;
    const b = new maplibregl.LngLatBounds(coords[0], coords[0]);
    coords.forEach((c) => b.extend(c));
    m.fitBounds(b, { padding: 64, maxZoom: 6, duration: 600 });
  }

  useEffect(() => {
    const m = map.current;
    if (!m || !ready) return;
    const h = () => declutter();
    m.on("moveend", h);
    m.on("zoomend", h);
    return () => {
      m.off("moveend", h);
      m.off("zoomend", h);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready]);

  useEffect(() => {
    if (ready && airportsLoaded) sync();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, airportsLoaded, arcs, points]);

  useEffect(() => {
    if (ready && airportsLoaded) fit();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, airportsLoaded, fitKey]);

  return <div ref={el} className={cn("h-72 w-full overflow-hidden rounded-lg border border-border bg-surface-2", className)} />;
}
