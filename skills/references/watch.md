# Chat change detection

`circle-client watch-diff --target chat:9000000 --member-id 9000001 --participant-id 9000002 --state data/watch_state.json`

GET-only command; JSON output contains `events`, `changed`, `base_digest` and
`next_state`. Never sends notifications or advances state. Keep all outputs private.
Use the existing `--env-file` credential contract.

Events: new roots (excluding your own) and replies by others in threads you
authored a root/reply in. Participation uses actual message authors, never preview
members. Verify the per-room participant ID against your community member ID using
the room participants response. IDs are not interchangeable across rooms.
Edits/deletes are not alerts. Output includes plain text and space/message URLs.

A missing checkpoint establishes a silent baseline. Corrupt or identity-mismatched
state fails closed. Root and reply pagination are bounded to 100 progressing pages;
incomplete or non-progressing scans fail closed. `total_count` is not interpreted as root count. Multiple
GETs may be necessary; a one-call scan is not guaranteed.

Private consumers use `watch.scan`, `load_state`, and `commit(path, result)`.
Hold a consumer lock across scan/delivery/commit. Commit only after successful
delivery (or a successful no-event scan), using the original result, not a rescan.
Checkpoint commit compares the base digest and atomically replaces a 0600 file.
Persist pending delivery before sending; retry ambiguous sends only with the same
payload and provider idempotency key. Exactly-once delivery across files and email
is not guaranteed. Interactive scans do not consume the scheduled consumer's diff.

Only chat targets are implemented. Multiple chat targets can share a checkpoint
through `scan(targets=[...])`; checkpoints bind community URL and member ID.
Lesson rooms may reuse this engine with another room resolver. Posts need a
separate model. Scheduling and mail transport remain caller-owned.

## Notification channels (why polling)

Observed 2026-10-21 against help.circle.so (October 2026 docs) and a live
community. Re-check before relying on it; Circle changes these settings.

- Chat spaces have no email channel. In a member's notification settings the
  chat row's email column is disabled. The only selectable options are new
  messages -> push, and Mentions -> in-app + push. In-app notifications for chat
  are mention-only; the web app otherwise shows passive sidebar badges and a
  Threads badge (the sidebar may not refresh until the page reloads).
- So the only proactive channel for chat activity is mobile push (branded or
  generic Circle app).
- There is no native event trigger for new chat-space messages: workflow
  messaging triggers only cover "Admin received a direct message", and custom
  push in the branded app is a manual or scheduled broadcast, not event-driven.
  External polling (`watch-diff`) is the workable path.
- Read-only inspection: member preferences via
  `GET /internal_api/notification_preferences` (per-space rows live under
  `space_groups[].space_members[]`; their `id` is a space-membership id, not a
  space id). Space defaults via `GET /internal_api/spaces/<id>`:
  `default_notification_setting` (email), `default_in_app_notification_setting`,
  `default_mobile_notification_setting`, `mention_notifications_enabled`.
- Admin UI for space defaults: Community -> Spaces -> hover a space -> ... ->
  Edit space -> Options -> New message notifications; saving asks whether to
  apply to all members or new members only. Members can override defaults in
  their own settings.
- A space's default view shows only a recent window of roots; paginate fully
  before treating a count as the total.
