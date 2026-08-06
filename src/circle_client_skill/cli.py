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


def cmd_spaces(args: argparse.Namespace) -> None:
    settings = load_settings(Path(args.env_file))
    result = CircleClient(settings, timeout=args.timeout).list_spaces()
    spaces = result.get("records", result) if isinstance(result, dict) else result
    print(json.dumps({"success": True, "count": len(spaces), "spaces": spaces}, ensure_ascii=False, indent=2))


def cmd_list_posts(args: argparse.Namespace) -> None:
    settings = load_settings(Path(args.env_file))
    result = CircleClient(settings, timeout=args.timeout).list_posts(
        space_id=args.space_id, page=args.page, per_page=args.per_page
    )
    records = result.get("records", [])
    print(json.dumps({
        "success": True,
        "count": result.get("count", len(records)),
        "page": result.get("page", args.page),
        "per_page": result.get("per_page", args.per_page),
        "has_next_page": result.get("has_next_page"),
        "posts": [{"id": p.get("id"), "name": p.get("name"), "slug": p.get("slug"),
                    "published_at": p.get("published_at"), "community_member_id": p.get("community_member_id")}
                   for p in records],
    }, ensure_ascii=False, indent=2))


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
        print(json.dumps(preflight, ensure_ascii=False, indent=2))
        return
    result = client.create_post(
        space_id=args.space_id, name=args.name, user_id=args.user_id, status=args.status
    )
    print(json.dumps({"success": True, "dry_run": False, "post": result}, ensure_ascii=False, indent=2))


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
        print(json.dumps(preflight, ensure_ascii=False, indent=2))
        return
    result = client.update_post(
        space_id=args.space_id, slug=args.slug, post_id=args.post_id, name=args.name, user_id=args.user_id
    )
    print(json.dumps({"success": True, "dry_run": False, "post": result}, ensure_ascii=False, indent=2))


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
        print(json.dumps(preflight, ensure_ascii=False, indent=2))
        return
    client.delete_post(space_id=args.space_id, slug=args.slug)
    print(json.dumps({"success": True, "dry_run": False, "deleted": True, "slug": args.slug}, ensure_ascii=False, indent=2))


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
        print(json.dumps(preflight, ensure_ascii=False, indent=2))
        return
    result = client.create_comment(post_id=args.post_id, text=args.text)
    print(json.dumps({"success": True, "dry_run": False, "comment": result}, ensure_ascii=False, indent=2))


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
        print(json.dumps(preflight, ensure_ascii=False, indent=2))
        return
    result = client.upload_image(args.file)
    direct_upload = result.get("direct_upload", {})
    print(json.dumps({
        "success": True,
        "dry_run": False,
        "signed_id": result.get("signed_id"),
        "url": direct_upload.get("url"),
    }, ensure_ascii=False, indent=2))


def cmd_chat_send(args: argparse.Namespace) -> None:
    if args.execute and args.confirm != "CHAT-SEND":
        raise ValueError("Live execution requires --confirm CHAT-SEND")
    settings = load_settings(Path(args.env_file))
    client = CircleClient(settings, timeout=args.timeout)
    if not args.execute:
        preflight = {
            "success": True,
            "dry_run": True,
            "operation": "chat_send",
            "chat_room_uuid": args.room_uuid,
            "participant_id": args.participant_id,
            "text": args.text[:100],
            "parent_message_id": args.parent_message_id,
            "csrf_present": bool(settings.csrf_token),
        }
        print(json.dumps(preflight, ensure_ascii=False, indent=2))
        return
    result = client.send_chat_message(
        chat_room_uuid=args.room_uuid,
        chat_room_participant_id=args.participant_id,
        text=args.text,
        parent_message_id=args.parent_message_id,
    )
    print(json.dumps({"success": True, "dry_run": False, "message": result}, ensure_ascii=False, indent=2))


def cmd_list_chat_messages(args: argparse.Namespace) -> None:
    settings = load_settings(Path(args.env_file))
    result = CircleClient(settings, timeout=args.timeout).list_chat_messages(
        chat_room_uuid=args.room_uuid,
        previous_per_page=args.previous_per_page,
        next_per_page=args.next_per_page,
        before_creation_uuid=args.before_creation_uuid,
    )
    records = result.get("records", [])
    print(json.dumps({
        "success": True,
        "total_count": result.get("total_count", len(records)),
        "messages": [{"id": m.get("id"), "body": m.get("body"), "created_at": m.get("created_at"),
                       "chat_room_participant_id": m.get("chat_room_participant_id"),
                       "parent_message_id": m.get("parent_message_id"),
                       "chat_thread_id": m.get("chat_thread_id"),
                       "replies_count": m.get("replies_count")}
                      for m in records],
    }, ensure_ascii=False, indent=2))


def cmd_list_chat_replies(args: argparse.Namespace) -> None:
    settings = load_settings(Path(args.env_file))
    replies = CircleClient(settings, timeout=args.timeout).fetch_chat_replies(
        chat_room_uuid=args.room_uuid,
        parent_message_id=args.parent_message_id,
        per_page=args.per_page,
    )
    print(json.dumps({
        "success": True,
        "count": len(replies),
        "replies": [{"id": m.get("id"), "body": m.get("body"), "created_at": m.get("created_at"),
                      "parent_message_id": m.get("parent_message_id")}
                     for m in replies],
    }, ensure_ascii=False, indent=2))


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

    spaces = subparsers.add_parser("spaces", help="List all visible spaces")
    spaces.add_argument("--timeout", type=float, default=30)
    spaces.set_defaults(handler=cmd_spaces)

    list_posts = subparsers.add_parser("list-posts", help="List posts in a space")
    list_posts.add_argument("-s", "--space-id", type=int, required=True)
    list_posts.add_argument("--page", type=int, default=1)
    list_posts.add_argument("--per-page", type=int, default=24)
    list_posts.add_argument("--timeout", type=float, default=30)
    list_posts.set_defaults(handler=cmd_list_posts)

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
    chat_send.add_argument("--room-uuid", required=True)
    chat_send.add_argument("--participant-id", type=int, required=True)
    chat_send.add_argument("--text", required=True)
    chat_send.add_argument("--parent-message-id", type=int, default=None)
    chat_send.add_argument("--execute", action="store_true")
    chat_send.add_argument("--confirm")
    chat_send.add_argument("--timeout", type=float, default=30)
    chat_send.set_defaults(handler=cmd_chat_send)

    list_chat = subparsers.add_parser("list-chat-messages", help="List messages in a chat room")
    list_chat.add_argument("--room-uuid", required=True)
    list_chat.add_argument("--previous-per-page", type=int, default=0, help="Number of older messages to fetch")
    list_chat.add_argument("--next-per-page", type=int, default=50, help="Number of newer messages to fetch")
    list_chat.add_argument("--before-creation-uuid", default=None, help="Cursor for pagination")
    list_chat.add_argument("--timeout", type=float, default=30)
    list_chat.set_defaults(handler=cmd_list_chat_messages)

    list_replies = subparsers.add_parser("list-chat-replies", help="List thread replies for a message")
    list_replies.add_argument("--room-uuid", required=True)
    list_replies.add_argument("--parent-message-id", type=int, required=True)
    list_replies.add_argument("--per-page", type=int, default=50)
    list_replies.add_argument("--timeout", type=float, default=30)
    list_replies.set_defaults(handler=cmd_list_chat_replies)

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
