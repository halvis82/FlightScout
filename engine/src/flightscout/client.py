"""Client for the web app's /api/v1. Used by the CLI, the MCP server and the
tracker so everything found locally shows up in the browser."""

from __future__ import annotations

from typing import Any

import httpx

from . import config


class NotLoggedIn(RuntimeError):
    pass


class Client:
    def __init__(self, api_url: str | None = None, token: str | None = None, tracker_key: str | None = None):
        cfg = config.load()
        self.base = (api_url or cfg.get("api_url") or "").rstrip("/")
        self.token = token or cfg.get("token")
        self.tracker_key = tracker_key or cfg.get("tracker_key")

    @property
    def ready(self) -> bool:
        return bool(self.base and (self.token or self.tracker_key))

    def _req(self, method: str, path: str, **kw) -> Any:
        if not self.base:
            raise NotLoggedIn("No web app configured. Run `flightscout login --url <site> --token <token>`.")
        headers = kw.pop("headers", {})
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if self.tracker_key:
            headers["x-tracker-key"] = self.tracker_key
        r = httpx.request(method, f"{self.base}/api/v1{path}", headers=headers, timeout=60, **kw)
        if r.status_code == 401:
            raise NotLoggedIn("The web app rejected the token. Create a new one in Settings, API tokens.")
        r.raise_for_status()
        return r.json() if r.content else None

    # user endpoints
    def me(self): return self._req("GET", "/me")
    def places(self): return self._req("GET", "/places")
    def add_place(self, **body): return self._req("POST", "/places", json=body)
    def delete_place(self, pid: str): return self._req("DELETE", f"/places/{pid}")
    def watches(self): return self._req("GET", "/watches")
    def watch(self, wid: str): return self._req("GET", f"/watches/{wid}")
    def add_watch(self, **body): return self._req("POST", "/watches", json=body)
    def update_watch(self, wid: str, **body): return self._req("PATCH", f"/watches/{wid}", json=body)
    def delete_watch(self, wid: str): return self._req("DELETE", f"/watches/{wid}")
    def history(self, wid: str): return self._req("GET", f"/watches/{wid}/history")
    def push_observations(self, wid: str, obs: list[dict]):
        return self._req("POST", f"/watches/{wid}/observations", json=obs)
    def save_result(self, kind: str, query: dict, payload: dict, origin: str = "cli"):
        return self._req("POST", "/results", json={"kind": kind, "query": query, "payload": payload, "origin": origin})

    # tracker endpoints
    def tracker_watches(self): return self._req("GET", "/tracker/watches")
    def tracker_push(self, wid: str, obs: list[dict]):
        return self._req("POST", "/tracker/observations", json={"watch_id": wid, "observations": obs})
