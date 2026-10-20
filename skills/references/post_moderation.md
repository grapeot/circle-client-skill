# Post Moderation Reference

This contract covers moderating flagged `Post` items on a Circle community (`community.example.com`) via internal web endpoints. It does not use the Admin API or an LLM, performs no automatic policy decisions or `delete-post` calls, and grants no recurring approval authority. Every live moderation action requires explicit authorization.

## Authentication and Config

Commands require an admin browser session (`cookie` + `CSRF`) imported via existing tools and kept in a private `--env-file` (preserving per-account config isolation). Never paste credentials into chat or tracked files. `get-flagged-content` output is private.

## CLI Contract

```bash
# Read-only inspection: GET /internal_api/flagged_contents/11
.venv/bin/circle-client get-flagged-content 11

# Offline dry-run default (no GET or PATCH network calls)
.venv/bin/circle-client approve-post 11 --post-id 22 --space-id 33
.venv/bin/circle-client reject-post 11 --post-id 22 --space-id 33 --note "Synthetic review note"

# Live execution
.venv/bin/circle-client approve-post 11 --post-id 22 --space-id 33 --execute --confirm APPROVE-POST
.venv/bin/circle-client reject-post 11 --post-id 22 --space-id 33 --note "Synthetic review note" --execute --confirm REJECT-POST
```

- **Scope & arguments**: Supports `Post` content only (not comments, chat, or events). Positive integer IDs (`11`) and expected `--post-id 22` and `--space-id 33` are required.
- **Dry-run**: Default mode is strictly offline (no GET or PATCH) unless `--execute` and the matching `--confirm` token are passed.
- **Payloads**: Approve sends `PATCH /internal_api/flagged_contents/11/approve` with `{}`. Reject sends `PATCH /internal_api/flagged_contents/11/reject` with `{"action_reason_body": null}` when `--note` is omitted, or the note string when provided.

## Python Interface

For an initialized `CircleClient` instance:

```python
client.moderate_post(
    flagged_content_id=11,
    action="approve",  # or "reject"
    expected_post_id=22,
    expected_space_id=33,
    note=None,
    execute=False,
)
```

The library enforces target validation and readback; `execute=False` performs no network calls. CLI confirmation tokens are enforced by the CLI, not by the Python interface.

## Verification and Failure Recovery

1. **Pre-flight GET**: Live runs first call `GET /internal_api/flagged_contents/11` to validate the flagged record ID, `Post` type, post ID `22`, and space ID `33`. The separate `get-flagged-content` command returns full JSON including pending content. A pending `Post` may already show `status="published"`, while the moderation record has `status=null` and non-empty `flagged_for_approval_at`. Do not substitute `update-post` for moderation.
2. **Idempotency**: Before PATCH, if the record is already in the desired completed state, it returns `verified=true` and `already_moderated=true` without mutation. Opposite or inconsistent states error without reversal.
3. **Post-write readback**: PATCH ACK alone is insufficient; a GET readback verifies completion. Approve requires `status="approved"`, a cleared pending timestamp, and no `removed_at`. Reject requires `status="rejected"` and `removed_at` present; its `flagged_for_approval_at` may remain non-empty. Reject is moderation removal, not `delete-post`.
4. **Timeouts & concurrency**: If PATCH times out or fails, the client attempts one GET readback and succeeds only if the desired state is verified; otherwise it reports unknown/unconfirmed. Never blindly repeat PATCH. Serial repeats skip the write, but there is no cross-process lock or platform exactly-once guarantee. Calling applications must serialize concurrent actions and recheck content version before auto-approval; this skill implements no model, version check, or queue.

## Validation Scope

Validated against captured internal web requests and controlled test posts; internal APIs can change. Tests are offline synthetic with no real fixtures committed and do not independently cover arbitrary communities, notifications, or production effects.
