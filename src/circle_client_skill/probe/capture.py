"""Record the community's internal API traffic during a probe, redacted on write.

Listens on Playwright `request` / `response` events (protocol level, so it survives
full page reloads). Only XHR/fetch calls whose path contains `/internal_api/` are
kept. Request bodies of non-GET calls and, optionally, JSON response bodies of GET
calls are stored; everything goes through a `Redactor` before it is written.
"""

from __future__ import annotations

import contextlib
import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .redact import Redactor, redact_url

NOISE = re.compile(r"segment|pendo|analytics|sentry|intercom|datadog|hotjar|google", re.I)
API_MARKER = "/internal_api/"


class RequestCapture:
    def __init__(
        self,
        redactor: Redactor | None = None,
        *,
        host: str | None = None,
        save_bodies: bool = False,
        body_limit: int = 4000,
    ) -> None:
        self.redactor = redactor or Redactor()
        self.host = host.lower() if host else None
        self.save_bodies = save_bodies
        self.body_limit = body_limit
        self.records: list[dict[str, Any]] = []
        self.bodies: dict[str, Any] = {}

    def wants(self, request: Any) -> bool:
        url = request.url
        if API_MARKER not in url or NOISE.search(url):
            return False
        if request.resource_type not in ("xhr", "fetch"):
            return False
        return not (self.host and (urlsplit(url).hostname or "").lower() != self.host)

    def on_request(self, request: Any) -> None:
        if not self.wants(request):
            return
        entry: dict[str, Any] = {"method": request.method, "url": request.url}
        if request.method.upper() != "GET":
            entry["post_data"] = request.post_data
        self.records.append(entry)

    def on_response(self, response: Any) -> None:
        request = response.request
        if not self.wants(request):
            return
        for entry in reversed(self.records):
            if entry["url"] == response.url and "status" not in entry:
                entry["status"] = response.status
                break
        if self.save_bodies and request.method.upper() == "GET":
            # Non-JSON bodies, or bodies already discarded by the browser, are skipped.
            with contextlib.suppress(Exception):
                self.bodies[response.url] = response.json()

    def attach(self, target: Any) -> None:
        target.on("request", self.on_request)
        target.on("response", self.on_response)

    def redacted_records(self) -> list[dict[str, Any]]:
        out = []
        for entry in self.records:
            item: dict[str, Any] = {
                "method": entry["method"],
                "url": self.redactor.text(redact_url(entry["url"])),
            }
            if "status" in entry:
                item["status"] = entry["status"]
            if "post_data" in entry:
                item["post_data"] = self.redactor.body(entry["post_data"], self.body_limit)
            out.append(item)
        return out

    def redacted_bodies(self) -> dict[str, Any]:
        return {
            self.redactor.text(redact_url(url)): self.redactor.json(body)
            for url, body in self.bodies.items()
        }

    def dump(self, out_dir: Path, tag: str) -> list[Path]:
        """Write `<tag>_requests.json` (and `<tag>_bodies.json`) under `out_dir`."""
        out_dir.mkdir(parents=True, exist_ok=True)
        written = []
        requests_path = out_dir / f"{tag}_requests.json"
        requests_path.write_text(
            json.dumps(self.redacted_records(), ensure_ascii=False, indent=1), encoding="utf-8"
        )
        written.append(requests_path)
        if self.save_bodies:
            bodies_path = out_dir / f"{tag}_bodies.json"
            bodies_path.write_text(
                json.dumps(self.redacted_bodies(), ensure_ascii=False, indent=1), encoding="utf-8"
            )
            written.append(bodies_path)
        return written
