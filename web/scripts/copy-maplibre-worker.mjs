// MapLibre 6 loads its tile worker from a file next to the library. Bundlers
// don't emit that file, so serve the worker (and the shared chunk it imports)
// from public/maplibre and point setWorkerUrl there. Runs on postinstall.
import { copyFileSync, mkdirSync } from "node:fs";

const src = "node_modules/maplibre-gl/dist";
mkdirSync("public/maplibre", { recursive: true });
for (const f of ["maplibre-gl-worker.mjs", "maplibre-gl-shared.mjs"]) copyFileSync(`${src}/${f}`, `public/maplibre/${f}`);
