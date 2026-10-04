"""Read-only example probe: open a page, screenshot it, dump visible form controls.

    python -m circle_client_skill.probe --path /c/some-space --out data/probe --tag space

There is no allowlist flag: this script never lets a non-GET request reach the
community. Outputs (screenshot, controls, redacted request log) go under `--out`,
which should stay inside the gitignored `data/` directory.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ..config import ConfigurationError
from .session import ProbeSession

CONTROLS_JS = """() => {
  const sel = 'input, textarea, select, button, [role=switch], [role=combobox], [role=checkbox], [role=radio], [role=tab], [contenteditable=true]';
  const visible = (el) => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const labelOf = (el) => {
    const aria = el.getAttribute('aria-label'); if (aria) return aria;
    if (el.id) { const l = document.querySelector(`label[for="${CSS.escape(el.id)}"]`); if (l) return l.innerText.trim(); }
    let p = el.parentElement;
    for (let i = 0; i < 4 && p; i++, p = p.parentElement) { const t = (p.innerText || '').trim(); if (t && t.length < 200) return t.split('\\n')[0]; }
    return '';
  };
  return [...document.querySelectorAll(sel)]
    .filter(el => visible(el) && el.type !== 'hidden' && el.type !== 'password')
    .map(el => ({
      tag: el.tagName.toLowerCase(),
      type: el.getAttribute('type'),
      role: el.getAttribute('role'),
      name: el.getAttribute('name'),
      placeholder: el.getAttribute('placeholder'),
      label: labelOf(el).slice(0, 120),
      text: el.tagName === 'BUTTON' ? (el.innerText || '').trim().slice(0, 80) : null,
      checked: el.getAttribute('aria-checked') ?? (el.type === 'checkbox' || el.type === 'radio' ? el.checked : null),
      disabled: el.disabled === true || el.getAttribute('aria-disabled') === 'true',
    }));
}"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m circle_client_skill.probe", description=__doc__)
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument("--path", default="/", help="community-relative path to open")
    parser.add_argument("--out", type=Path, default=Path("data/probe"))
    parser.add_argument("--tag", default="probe")
    parser.add_argument("--settle-ms", type=int, default=5000)
    parser.add_argument("--no-screenshot", action="store_true")
    parser.add_argument("--no-controls", action="store_true")
    args = parser.parse_args(argv)

    summary: dict[str, object] = {}
    try:
        with ProbeSession(env_path=args.env_file) as probe:
            probe.page.goto(probe.url(args.path), wait_until="domcontentloaded", timeout=60000)
            probe.page.wait_for_timeout(args.settle_ms)
            outputs: list[str] = []
            if not args.no_screenshot:
                outputs.append(str(probe.screenshot(args.out / f"{args.tag}.png")))
            if not args.no_controls:
                controls = probe.page.evaluate(CONTROLS_JS)
                controls_path = args.out / f"{args.tag}_controls.json"
                controls_path.parent.mkdir(parents=True, exist_ok=True)
                controls_path.write_text(
                    json.dumps(probe.redactor.json(controls), ensure_ascii=False, indent=1),
                    encoding="utf-8",
                )
                outputs.append(str(controls_path))
            summary = {
                "path": args.path,
                "title": probe.page.title(),
                "logged_in": probe.looks_logged_in(),
            }
        outputs.extend(str(p) for p in probe.capture.dump(args.out, args.tag))
        summary["internal_api_requests"] = len(probe.capture.records)
        summary["blocked_writes"] = [f"{b.method} {b.url}" for b in probe.guard.blocked]
        summary["outputs"] = outputs
    except ConfigurationError as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 2
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
