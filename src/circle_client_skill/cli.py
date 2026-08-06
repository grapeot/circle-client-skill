from __future__ import annotations

import argparse
import contextlib
import json
import re
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
    build_settings_from_cookies,
    jwt_expiration,
    load_settings,
    parse_curl,
    save_settings,
)
from .formatters import (
    format_auth_status,
    format_chat_messages_table,
    format_count,
    format_fetch_summary,
    format_mutation_dryrun,
    format_mutation_result,
    format_post_card,
    format_posts_table,
    format_space_card,
    format_spaces_table,
    format_unreplied_table,
)
from .render import render_csv, render_html, render_markdown


def _print_json(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def _resolve_room_uuid(client: CircleClient, args: argparse.Namespace) -> str:
    if args.room_uuid:
        return args.room_uuid
    space = client.get_space(args.space_id)
    room_uuid = space.get("chat_room_uuid")
    if not isinstance(room_uuid, str) or not room_uuid:
        raise ValueError(f"Space {args.space_id} has no chat_room_uuid")
    return room_uuid


def _directional_page_sizes(args: argparse.Namespace) -> tuple[int, int]:
    if args.direction == "next":
        return 0, args.next_per_page or args.previous_per_page
    return args.previous_per_page or args.next_per_page, 0


def _safe_error_message(message: str) -> str:
    message = re.sub(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+", "Bearer ***", message)
    return re.sub(
        r"(?i)([\"']?(?:authorization|cookie|x-csrf-token|csrf_token)[\"']?\s*[:=]\s*)"
        r"([\"']?)[^\"'\s,}\]]+",
        r"\1\2***",
        message,
    )


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
    expiration = jwt_expiration(settings.authorization) if settings.authorization else None
    now = datetime.now(UTC)
    status = {
        "configured": True,
        "host": urlsplit(settings.notifications_url).netloc,
        "cookie_present": bool(settings.cookie),
        "csrf_present": bool(settings.csrf_token),
        "jwt_present": bool(settings.authorization),
        "jwt_expires_at": expiration.isoformat() if expiration else None,
        "jwt_expired": expiration <= now if expiration else None,
    }
    print(json.dumps(status, ensure_ascii=False, indent=2) if args.json else format_auth_status(status))


def cmd_configure_browser(args: argparse.Namespace) -> None:
    """Open a visible browser, let the user log in, extract cookies to .env."""
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        raise ConfigurationError(
            "Playwright is not installed. Install with: uv pip install -e '.[browser]' "
            "then run: python -m playwright install chromium"
        ) from None

    import asyncio

    async def _run() -> dict:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=False)
            context = await browser.new_context()
            page = await context.new_page()
            await page.goto(args.url, wait_until="domcontentloaded")

            print(
                json.dumps(
                    {
                        "action": "browser_opened",
                        "url": args.url,
                        "message": "Please log in to your Circle community. "
                        "When you see the feed page, the script will continue automatically.",
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                flush=True,
            )

            # Wait until the user is logged in (URL changes away from login page)
            # Circle SSO redirects to /feed or /c/ after login
            with contextlib.suppress(Exception):
                await page.wait_for_url(
                    lambda url: "login" not in url and "sign_in" not in url,
                    timeout=300000,  # 5 minutes
                )

            # Give the page a moment to settle
            await page.wait_for_load_state("domcontentloaded")
            await asyncio.sleep(2)

            # Extract cookies via CDP
            cookies = await context.cookies()
            # Match by root domain: strip leading "www." or "." for comparison
            target_domain = urlsplit(args.url).netloc
            # Also match parent domain (e.g., www.community.example.com → community.example.com)
            root_domain = target_domain.removeprefix("www.")
            relevant = [
                c for c in cookies
                if target_domain in c.get("domain", "")
                or root_domain in c.get("domain", "")
                or c.get("domain", "").lstrip(".") in (target_domain, root_domain)
            ]
            if not relevant:
                raise ConfigurationError(
                    f"No cookies found for {target_domain}. Make sure you are logged in."
                )

            cookie_header = "; ".join(f'{c["name"]}={c["value"]}' for c in relevant)
            csrf = next((c for c in relevant if c["name"] == "csrf_token"), None)
            csrf_value = csrf["value"] if csrf else None

            # Get user agent from the page
            user_agent = await page.evaluate("() => navigator.userAgent")

            # Try to get frontend version from meta tag or window
            frontend_version = await page.evaluate(
                "() => window.CIRCLE_APP_VERSION || "
                "document.documentElement.getAttribute('data-circle-frontend-version') || null"
            )

            # Extract community_id from localStorage (PunditUserContext)
            community_id = await page.evaluate(
                "() => { try { "
                "const ctx = JSON.parse(localStorage.getItem('V1-PunditUserContext') || '{}'); "
                "const c = ctx.state?.current_community || ctx.current_community || {}; "
                "return String(c.id || ''); "
                "} catch(e) { return ''; } }"
            )
            community_id = community_id or None

            await browser.close()

            return {
                "cookie_header": cookie_header,
                "csrf_token": csrf_value,
                "user_agent": user_agent,
                "frontend_version": frontend_version,
                "community_id": community_id,
                "cookie_count": len(relevant),
            }

    result = asyncio.run(_run())

    settings = build_settings_from_cookies(
        community_url=args.url,
        cookie_header=result["cookie_header"],
        csrf_token=result["csrf_token"],
        user_agent=result["user_agent"],
        frontend_version=result["frontend_version"],
        community_id=result["community_id"],
    )
    env_path = Path(args.env_file)
    save_settings(settings, env_path)

    print(
        json.dumps(
            {
                "success": True,
                "env_file": str(env_path.resolve()),
                "host": urlsplit(args.url).netloc,
                "cookie_count": result["cookie_count"],
                "csrf_saved": bool(result["csrf_token"]),
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
    summary = {
        "success": True,
        "output": str(output.resolve()),
        "count": document["count"],
        "pages_fetched": document["source"]["pages_fetched"],
        "per_page": document["source"]["per_page"],
    }
    if args.json:
        _print_json(summary)
    else:
        print(format_fetch_summary({**summary, "host": document["source"]["host"], "output": args.output}))


def cmd_count(args: argparse.Namespace) -> None:
    settings = load_settings(Path(args.env_file))
    result = CircleClient(settings, timeout=args.timeout).get_notification_count()
    if args.json:
        _print_json({"success": True, "count": result["count"]})
    else:
        print(format_count(result["count"]))


def cmd_reset_count(args: argparse.Namespace) -> None:
    if args.execute and args.confirm != "RESET-COUNT":
        raise ValueError("Live execution requires --confirm RESET-COUNT")
    settings = load_settings(Path(args.env_file))
    result = CircleClient(settings, timeout=args.timeout).reset_notification_count(
        execute=args.execute
    )
    if args.json:
        _print_json(result)
    elif result.get("dry_run"):
        print(format_mutation_dryrun(result))
    else:
        print(format_mutation_result(result, "reset-count"))


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


def cmd_spaces(args: argparse.Namespace) -> None:
    settings = load_settings(Path(args.env_file))
    result = CircleClient(settings, timeout=args.timeout).list_spaces()
    spaces = result.get("records", result) if isinstance(result, dict) else result
    if args.json:
        _print_json({"success": True, "count": len(spaces), "spaces": spaces})
    else:
        print(format_spaces_table(spaces))


def cmd_get_space(args: argparse.Namespace) -> None:
    settings = load_settings(Path(args.env_file))
    space = CircleClient(settings, timeout=args.timeout).get_space(args.space_id)
    print(json.dumps(space, ensure_ascii=False, indent=2) if args.json else format_space_card(space))


def cmd_list_posts(args: argparse.Namespace) -> None:
    settings = load_settings(Path(args.env_file))
    result = CircleClient(settings, timeout=args.timeout).list_posts(
        space_id=args.space_id, page=args.page, per_page=args.per_page
    )
    records = result.get("records", [])
    if args.full:
        posts = records
    else:
        posts = [{"id": p.get("id"), "name": p.get("name"), "slug": p.get("slug"),
                    "published_at": p.get("published_at"), "community_member_id": p.get("community_member_id")}
                   for p in records]
    if args.json:
        _print_json({
            "success": True,
            "count": result.get("count", len(records)),
            "page": result.get("page", args.page),
            "per_page": result.get("per_page", args.per_page),
            "has_next_page": result.get("has_next_page"),
            "posts": posts,
        })
    else:
        print(format_posts_table(records, args.full))


def cmd_get_post(args: argparse.Namespace) -> None:
    settings = load_settings(Path(args.env_file))
    result = CircleClient(settings, timeout=args.timeout).get_post(
        space_id=args.space_id, slug=args.slug
    )
    post = result if isinstance(result, dict) else {}
    if args.json and args.extract_text:
        tiptap = post.get("tiptap_body", {})
        tiptap_body = tiptap.get("body", tiptap)
        def _extract_text(node: object) -> str:
            if isinstance(node, dict):
                if "text" in node:
                    return str(node["text"])
                parts = []
                for c in node.get("content", []):
                    parts.append(_extract_text(c))
                return "".join(parts)
            if isinstance(node, list):
                return "".join(_extract_text(n) for n in node)
            return ""
        post = {
            "id": post.get("id"),
            "name": post.get("name"),
            "slug": post.get("slug"),
            "space_id": post.get("space_id"),
            "space_name": post.get("space_name"),
            "community_member_id": post.get("community_member_id"),
            "published_at": post.get("published_at"),
            "body_text": _extract_text(tiptap_body),
        }
    if args.json:
        _print_json({"success": True, "post": post})
    else:
        print(format_post_card(post))


def cmd_create_post(args: argparse.Namespace) -> None:
    if args.execute and args.confirm != "CREATE-POST":
        raise ValueError("Live execution requires --confirm CREATE-POST")
    settings = load_settings(Path(args.env_file))
    client = CircleClient(settings, timeout=args.timeout)
    if not args.execute:
        preflight = {
            "success": True,
            "dry_run": True,
            "operation": "create_post",
            "space_id": args.space_id,
            "name": args.name,
            "user_id": args.user_id,
            "csrf_present": bool(settings.csrf_token),
            "cookie_present": bool(settings.cookie),
        }
        print(json.dumps(preflight, ensure_ascii=False, indent=2) if args.json else format_mutation_dryrun(preflight))
        return
    result = client.create_post(
        space_id=args.space_id, name=args.name, user_id=args.user_id, status=args.status
    )
    payload = {"success": True, "dry_run": False, "post": result}
    if args.json:
        _print_json(payload)
    else:
        print(format_mutation_result({"post": {"space_id": args.space_id, **result}}, "create-post"))


def cmd_update_post(args: argparse.Namespace) -> None:
    if args.execute and args.confirm != "UPDATE-POST":
        raise ValueError("Live execution requires --confirm UPDATE-POST")
    settings = load_settings(Path(args.env_file))
    client = CircleClient(settings, timeout=args.timeout)
    if not args.execute:
        preflight = {
            "success": True,
            "dry_run": True,
            "operation": "update_post",
            "space_id": args.space_id,
            "post_id": args.post_id,
            "slug": args.slug,
            "name": args.name,
            "user_id": args.user_id,
            "csrf_present": bool(settings.csrf_token),
        }
        print(json.dumps(preflight, ensure_ascii=False, indent=2) if args.json else format_mutation_dryrun(preflight))
        return
    result = client.update_post(
        space_id=args.space_id, slug=args.slug, post_id=args.post_id, name=args.name, user_id=args.user_id
    )
    payload = {"success": True, "dry_run": False, "post": result}
    if args.json:
        _print_json(payload)
    else:
        print(format_mutation_result({"post": {"space_id": args.space_id, **result}}, "update-post"))


def cmd_delete_post(args: argparse.Namespace) -> None:
    if args.execute and args.confirm != "DELETE-POST":
        raise ValueError("Live execution requires --confirm DELETE-POST")
    settings = load_settings(Path(args.env_file))
    client = CircleClient(settings, timeout=args.timeout)
    if not args.execute:
        preflight = {
            "success": True,
            "dry_run": True,
            "operation": "delete_post",
            "space_id": args.space_id,
            "slug": args.slug,
            "csrf_present": bool(settings.csrf_token),
        }
        print(json.dumps(preflight, ensure_ascii=False, indent=2) if args.json else format_mutation_dryrun(preflight))
        return
    client.delete_post(space_id=args.space_id, slug=args.slug)
    payload = {"success": True, "dry_run": False, "deleted": True, "slug": args.slug}
    print(json.dumps(payload, ensure_ascii=False, indent=2) if args.json else format_mutation_result(payload, "delete-post"))


def cmd_reply_post(args: argparse.Namespace) -> None:
    if args.execute and args.confirm != "REPLY-POST":
        raise ValueError("Live execution requires --confirm REPLY-POST")
    settings = load_settings(Path(args.env_file))
    client = CircleClient(settings, timeout=args.timeout)
    if not args.execute:
        preflight = {
            "success": True,
            "dry_run": True,
            "operation": "reply_post",
            "post_id": args.post_id,
            "text": args.text[:100],
            "csrf_present": bool(settings.csrf_token),
        }
        print(json.dumps(preflight, ensure_ascii=False, indent=2) if args.json else format_mutation_dryrun(preflight))
        return
    result = client.create_comment(post_id=args.post_id, text=args.text)
    payload = {"success": True, "dry_run": False, "comment": result}
    if args.json:
        _print_json(payload)
    else:
        print(format_mutation_result({"comment": result, "post_id": args.post_id}, "reply-post"))


def cmd_upload_image(args: argparse.Namespace) -> None:
    if args.execute and args.confirm != "UPLOAD-IMAGE":
        raise ValueError("Live execution requires --confirm UPLOAD-IMAGE")
    settings = load_settings(Path(args.env_file))
    client = CircleClient(settings, timeout=args.timeout)
    if not args.execute:
        preflight = {
            "success": True,
            "dry_run": True,
            "operation": "upload_image",
            "file": args.file,
            "csrf_present": bool(settings.csrf_token),
        }
        print(json.dumps(preflight, ensure_ascii=False, indent=2) if args.json else format_mutation_dryrun(preflight))
        return
    result = client.upload_image(args.file)
    direct_upload = result.get("direct_upload", {})
    payload = {
        "success": True,
        "dry_run": False,
        "signed_id": result.get("signed_id"),
        "url": direct_upload.get("url"),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2) if args.json else format_mutation_result(payload, "upload-image"))


def cmd_chat_send(args: argparse.Namespace) -> None:
    if args.execute and args.confirm != "CHAT-SEND":
        raise ValueError("Live execution requires --confirm CHAT-SEND")
    settings = load_settings(Path(args.env_file))
    client = CircleClient(settings, timeout=args.timeout)
    room_uuid = _resolve_room_uuid(client, args)
    if not args.execute:
        preflight = {
            "success": True,
            "dry_run": True,
            "operation": "chat_send",
            "chat_room_uuid": room_uuid,
            "participant_id": args.participant_id,
            "text": args.text[:100],
            "parent_message_id": args.parent_message_id,
            "csrf_present": bool(settings.csrf_token),
        }
        print(json.dumps(preflight, ensure_ascii=False, indent=2) if args.json else format_mutation_dryrun(preflight))
        return
    result = client.send_chat_message(
        chat_room_uuid=room_uuid,
        chat_room_participant_id=args.participant_id,
        text=args.text,
        parent_message_id=args.parent_message_id,
    )
    payload = {"success": True, "dry_run": False, "message": result}
    if args.json:
        _print_json(payload)
    else:
        print(format_mutation_result({"message": result, "chat_room_uuid": room_uuid}, "chat-send"))


def cmd_list_chat_messages(args: argparse.Namespace) -> None:
    settings = load_settings(Path(args.env_file))
    client = CircleClient(settings, timeout=args.timeout)
    room_uuid = _resolve_room_uuid(client, args)
    previous_per_page, next_per_page = _directional_page_sizes(args)
    result = client.list_chat_messages(
        chat_room_uuid=room_uuid,
        previous_per_page=previous_per_page,
        next_per_page=next_per_page,
        cursor=args.cursor,
    )
    records = result.get("records", [])
    print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else format_chat_messages_table(records, result))


def cmd_list_chat_replies(args: argparse.Namespace) -> None:
    settings = load_settings(Path(args.env_file))
    client = CircleClient(settings, timeout=args.timeout)
    room_uuid = _resolve_room_uuid(client, args)
    previous_per_page, next_per_page = _directional_page_sizes(args)
    result = client.fetch_chat_replies(
        chat_room_uuid=room_uuid,
        parent_message_id=args.parent_message_id,
        previous_per_page=previous_per_page,
        next_per_page=next_per_page,
        cursor=args.cursor,
    )
    records = result.get("records", [])
    print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else format_chat_messages_table(records, result))


def _find_unreplied(roots: list[dict], member_id: int, limit: int) -> list[dict]:
    if limit < 1:
        raise ValueError("limit must be positive")
    unreplied = []
    for root in roots:
        participants = root.get("thread_participants_preview") or []
        participated = any(
            isinstance(participant, dict)
            and participant.get("community_member_id") == member_id
            for participant in participants
        )
        if not participated:
            unreplied.append(root)
    unreplied.sort(key=lambda message: str(message.get("created_at") or ""), reverse=True)
    return unreplied[:limit]


def cmd_unreplied(args: argparse.Namespace) -> None:
    settings = load_settings(Path(args.env_file))
    client = CircleClient(settings, timeout=args.timeout)
    room_uuid = _resolve_room_uuid(client, args)
    messages = _find_unreplied(
        client.scan_chat_roots(room_uuid),
        args.member_id,
        args.limit,
    )
    print(json.dumps(messages, ensure_ascii=False, indent=2) if args.json else format_unreplied_table(messages))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="circle-client",
        description="Unofficial local-first Circle member notification client",
    )
    parser.add_argument("--env-file", default=".env", help="Local credential file")
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output complete raw JSON instead of compact human/AI-friendly text",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    configure = subparsers.add_parser("configure", help="Import browser Copy as cURL")
    sources = configure.add_mutually_exclusive_group(required=True)
    sources.add_argument("--from-clipboard", action="store_true")
    sources.add_argument("--stdin", action="store_true")
    sources.add_argument("--file")
    configure.set_defaults(handler=cmd_configure)

    configure_browser = subparsers.add_parser(
        "configure-browser",
        help="Open a visible browser, let user log in, extract cookies to .env",
    )
    configure_browser.add_argument(
        "--url",
        default="https://app.circle.so",
        help="Circle community URL to navigate to (default: https://app.circle.so)",
    )
    configure_browser.set_defaults(handler=cmd_configure_browser)

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

    spaces = subparsers.add_parser("spaces", help="List all visible spaces")
    spaces.add_argument("--timeout", type=float, default=30)
    spaces.set_defaults(handler=cmd_spaces)

    get_space = subparsers.add_parser("get-space", help="Get one space with chat metadata")
    get_space.add_argument("-s", "--space-id", type=int, required=True)
    get_space.add_argument("--timeout", type=float, default=30)
    get_space.set_defaults(handler=cmd_get_space)

    list_posts = subparsers.add_parser("list-posts", help="List posts in a space")
    list_posts.add_argument("-s", "--space-id", type=int, required=True)
    list_posts.add_argument("--page", type=int, default=1)
    list_posts.add_argument("--per-page", type=int, default=24)
    list_posts.add_argument("--full", action="store_true", help="Return full post records (including body)")
    list_posts.add_argument("--timeout", type=float, default=30)
    list_posts.set_defaults(handler=cmd_list_posts)

    get_post = subparsers.add_parser("get-post", help="Get a single post by slug with full content")
    get_post.add_argument("-s", "--space-id", type=int, required=True)
    get_post.add_argument("--slug", required=True, help="Post slug (from list-posts)")
    get_post.add_argument("--extract-text", action="store_true",
                          help="Extract plain text from tiptap_body instead of returning raw JSON")
    get_post.add_argument("--timeout", type=float, default=30)
    get_post.set_defaults(handler=cmd_get_post)

    create_post = subparsers.add_parser("create-post", help="Create a post (dry-run by default)")
    create_post.add_argument("-s", "--space-id", type=int, required=True)
    create_post.add_argument("--name", required=True)
    create_post.add_argument("--user-id", type=int, required=True)
    create_post.add_argument("--status", default="published")
    create_post.add_argument("--execute", action="store_true")
    create_post.add_argument("--confirm")
    create_post.add_argument("--timeout", type=float, default=30)
    create_post.set_defaults(handler=cmd_create_post)

    update_post = subparsers.add_parser("update-post", help="Update a post (dry-run by default)")
    update_post.add_argument("-s", "--space-id", type=int, required=True)
    update_post.add_argument("--post-id", type=int, required=True)
    update_post.add_argument("--slug", required=True)
    update_post.add_argument("--name", required=True)
    update_post.add_argument("--user-id", type=int, required=True)
    update_post.add_argument("--execute", action="store_true")
    update_post.add_argument("--confirm")
    update_post.add_argument("--timeout", type=float, default=30)
    update_post.set_defaults(handler=cmd_update_post)

    delete_post = subparsers.add_parser("delete-post", help="Delete a post (dry-run by default)")
    delete_post.add_argument("-s", "--space-id", type=int, required=True)
    delete_post.add_argument("--slug", required=True)
    delete_post.add_argument("--execute", action="store_true")
    delete_post.add_argument("--confirm")
    delete_post.add_argument("--timeout", type=float, default=30)
    delete_post.set_defaults(handler=cmd_delete_post)

    reply_post = subparsers.add_parser("reply-post", help="Reply to a post (dry-run by default)")
    reply_post.add_argument("--post-id", type=int, required=True)
    reply_post.add_argument("--text", required=True)
    reply_post.add_argument("--execute", action="store_true")
    reply_post.add_argument("--confirm")
    reply_post.add_argument("--timeout", type=float, default=30)
    reply_post.set_defaults(handler=cmd_reply_post)

    upload_image = subparsers.add_parser("upload-image", help="Upload an image (dry-run by default)")
    upload_image.add_argument("-f", "--file", required=True)
    upload_image.add_argument("--execute", action="store_true")
    upload_image.add_argument("--confirm")
    upload_image.add_argument("--timeout", type=float, default=30)
    upload_image.set_defaults(handler=cmd_upload_image)

    chat_send = subparsers.add_parser("chat-send", help="Send a chat message (dry-run by default)")
    chat_send_room = chat_send.add_mutually_exclusive_group(required=True)
    chat_send_room.add_argument("--room-uuid")
    chat_send_room.add_argument("--space-id", type=int)
    chat_send.add_argument("--participant-id", type=int, required=True)
    chat_send.add_argument("--text", required=True)
    chat_send.add_argument("--parent-message-id", type=int, default=None)
    chat_send.add_argument("--execute", action="store_true")
    chat_send.add_argument("--confirm")
    chat_send.add_argument("--timeout", type=float, default=30)
    chat_send.set_defaults(handler=cmd_chat_send)

    list_chat = subparsers.add_parser("list-chat-messages", help="List messages in a chat room")
    list_chat_room = list_chat.add_mutually_exclusive_group(required=True)
    list_chat_room.add_argument("--room-uuid")
    list_chat_room.add_argument("--space-id", type=int)
    list_chat.add_argument("--cursor", type=int, default=None, help="Numeric message id cursor")
    list_chat.add_argument("--direction", choices=("previous", "next"), default="previous")
    list_chat.add_argument("--previous-per-page", type=int, default=50, help="Number of older messages to fetch")
    list_chat.add_argument("--next-per-page", type=int, default=0, help="Number of newer messages to fetch")
    list_chat.add_argument("--timeout", type=float, default=30)
    list_chat.set_defaults(handler=cmd_list_chat_messages)

    list_replies = subparsers.add_parser("list-chat-replies", help="List thread replies for a message")
    list_replies_room = list_replies.add_mutually_exclusive_group(required=True)
    list_replies_room.add_argument("--room-uuid")
    list_replies_room.add_argument("--space-id", type=int)
    list_replies.add_argument("--parent-message-id", type=int, required=True)
    list_replies.add_argument("--cursor", type=int, default=None, help="Numeric message id cursor")
    list_replies.add_argument("--direction", choices=("previous", "next"), default="next")
    list_replies.add_argument("--previous-per-page", type=int, default=0)
    list_replies.add_argument("--next-per-page", type=int, default=50)
    list_replies.add_argument("--timeout", type=float, default=30)
    list_replies.set_defaults(handler=cmd_list_chat_replies)

    unreplied = subparsers.add_parser("unreplied", help="List root messages not replied to by a member")
    unreplied_room = unreplied.add_mutually_exclusive_group(required=True)
    unreplied_room.add_argument("--room-uuid")
    unreplied_room.add_argument("--space-id", type=int)
    unreplied.add_argument("--member-id", type=int, required=True)
    unreplied.add_argument("--limit", type=int, default=50)
    unreplied.add_argument("--timeout", type=float, default=30)
    unreplied.set_defaults(handler=cmd_unreplied)

    # Accept the global flag after a subcommand too, matching the documented examples.
    for subparser in subparsers.choices.values():
        subparser.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help=argparse.SUPPRESS)

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
        error = _safe_error_message(str(exc))
        payload = {"success": False, "error": error, "error_type": type(exc).__name__}
        if isinstance(exc, CircleClientError) and exc.status_code is not None:
            payload["status_code"] = exc.status_code
        if args.json:
            print(json.dumps(payload, ensure_ascii=False), file=sys.stderr)
        else:
            print(f"Error: {error}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
