from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import UTC, datetime
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from .client import CircleClient, CircleClientError
from .config import (
    ConfigurationError,
    jwt_expiration,
    load_settings,
    parse_curl,
    save_settings,
)
from .render import render_csv, render_html, render_markdown


def _read_curl(args: argparse.Namespace) -> str:
    if args.from_clipboard:
        try:
            return subprocess.run(
                ["pbpaste"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout
        except (FileNotFoundError, subprocess.CalledProcessError) as exc:
            raise ConfigurationError("Could not read the macOS clipboard") from exc
    if args.stdin:
        return sys.stdin.read()
    if args.file:
        return Path(args.file).read_text(encoding="utf-8")
    raise ConfigurationError("Choose --from-clipboard, --stdin, or --file")


def cmd_configure(args: argparse.Namespace) -> None:
    settings = parse_curl(_read_curl(args))
    env_path = Path(args.env_file)
    save_settings(settings, env_path)
    expiration = jwt_expiration(settings.authorization)
    print(
        json.dumps(
            {
                "success": True,
                "env_file": str(env_path.resolve()),
                "host": urlsplit(settings.notifications_url).netloc,
                "cookie_saved": bool(settings.cookie),
                "jwt_expires_at": expiration.isoformat() if expiration else None,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def cmd_auth_status(args: argparse.Namespace) -> None:
    settings = load_settings(Path(args.env_file))
    expiration = jwt_expiration(settings.authorization)
    now = datetime.now(UTC)
    print(
        json.dumps(
            {
                "configured": True,
                "host": urlsplit(settings.notifications_url).netloc,
                "cookie_present": bool(settings.cookie),
                "jwt_expires_at": expiration.isoformat() if expiration else None,
                "jwt_expired": expiration <= now if expiration else None,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def cmd_fetch(args: argparse.Namespace) -> None:
    settings = load_settings(Path(args.env_file))
    document = CircleClient(settings, timeout=args.timeout).fetch_notifications(
        group=args.group,
        per_page=args.per_page,
        max_pages=args.max_pages,
        stop_after_consecutive_read=args.stop_after_consecutive_read,
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "success": True,
                "output": str(output.resolve()),
                "count": document["count"],
                "pages_fetched": document["source"]["pages_fetched"],
                "per_page": document["source"]["per_page"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def cmd_count(args: argparse.Namespace) -> None:
    settings = load_settings(Path(args.env_file))
    result = CircleClient(settings, timeout=args.timeout).get_notification_count()
    print(json.dumps({"success": True, "count": result["count"]}, ensure_ascii=False, indent=2))


def cmd_reset_count(args: argparse.Namespace) -> None:
    if args.execute and args.confirm != "RESET-COUNT":
        raise ValueError("Live execution requires --confirm RESET-COUNT")
    settings = load_settings(Path(args.env_file))
    result = CircleClient(settings, timeout=args.timeout).reset_notification_count(
        execute=args.execute
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


def cmd_render(args: argparse.Namespace) -> None:
    input_path = Path(args.input)
    document = json.loads(input_path.read_text(encoding="utf-8"))
    output = Path(args.output) if args.output else input_path.with_suffix(f".{args.format}")
    output.parent.mkdir(parents=True, exist_ok=True)
    if args.format == "md":
        output.write_text(render_markdown(document), encoding="utf-8")
    elif args.format == "csv":
        render_csv(document, output)
    else:
        output.write_text(render_html(document), encoding="utf-8")
    print(
        json.dumps(
            {
                "success": True,
                "output": str(output.resolve()),
                "format": args.format,
                "count": len(document.get("notifications", [])),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def cmd_serve(args: argparse.Namespace) -> None:
    directory = Path(args.directory).resolve()
    if not directory.is_dir():
        raise ValueError(f"Directory not found: {directory}")
    handler = partial(SimpleHTTPRequestHandler, directory=str(directory))
    server = ThreadingHTTPServer((args.host, args.port), handler)
    print(
        json.dumps(
            {
                "success": True,
                "url": f"http://{args.host}:{args.port}/",
                "directory": str(directory),
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="circle-client",
        description="Unofficial local-first Circle member notification client",
    )
    parser.add_argument("--env-file", default=".env", help="Local credential file")
    subparsers = parser.add_subparsers(dest="command", required=True)

    configure = subparsers.add_parser("configure", help="Import browser Copy as cURL")
    sources = configure.add_mutually_exclusive_group(required=True)
    sources.add_argument("--from-clipboard", action="store_true")
    sources.add_argument("--stdin", action="store_true")
    sources.add_argument("--file")
    configure.set_defaults(handler=cmd_configure)

    auth_status = subparsers.add_parser("auth-status", help="Show masked credential status")
    auth_status.set_defaults(handler=cmd_auth_status)

    fetch = subparsers.add_parser("fetch", help="Fetch all notification pages")
    fetch.add_argument("--group", default="inbox")
    fetch.add_argument("--per-page", type=int, default=100)
    fetch.add_argument("--max-pages", type=int, default=500)
    fetch.add_argument(
        "--stop-after-consecutive-read",
        type=int,
        default=100,
        help="Stop at the practical unread frontier; use 0 for a full history scan",
    )
    fetch.add_argument("--timeout", type=float, default=30)
    fetch.add_argument("--output", default="data/notifications.json")
    fetch.set_defaults(handler=cmd_fetch)

    count = subparsers.add_parser("count", help="Read the current new-notification count")
    count.add_argument("--timeout", type=float, default=30)
    count.set_defaults(handler=cmd_count)

    reset_count = subparsers.add_parser(
        "reset-count",
        help="Reset the new-notification badge count; dry-run unless --execute is supplied",
    )
    reset_count.add_argument("--execute", action="store_true")
    reset_count.add_argument("--confirm")
    reset_count.add_argument("--timeout", type=float, default=30)
    reset_count.set_defaults(handler=cmd_reset_count)

    render = subparsers.add_parser("render", help="Render a fetch artifact")
    render.add_argument("--input", required=True)
    render.add_argument("--format", choices=("md", "csv", "html"), default="md")
    render.add_argument("--output")
    render.set_defaults(handler=cmd_render)

    serve = subparsers.add_parser("serve", help="Serve rendered artifacts over HTTP")
    serve.add_argument("--directory", default="data")
    serve.add_argument("--host", default="0.0.0.0")
    serve.add_argument("--port", type=int, default=8765)
    serve.set_defaults(handler=cmd_serve)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    try:
        args.handler(args)
    except (
        ConfigurationError,
        CircleClientError,
        ValueError,
        OSError,
        json.JSONDecodeError,
    ) as exc:
        payload = {"success": False, "error": str(exc), "error_type": type(exc).__name__}
        if isinstance(exc, CircleClientError) and exc.status_code is not None:
            payload["status_code"] = exc.status_code
        print(json.dumps(payload, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
