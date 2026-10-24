# Circle paywall and trial subscription playbook

Optional playbook for an agent that already has a human-visible browser and HTTP tools. It covers an isolated test paywall, a normal owner checkout, an independent readback, a genuine-trial extension, an owner-authorized full refund of a recurring transaction, a separately authorized billing-date follow-up, and cleanup. It is not a `circle-client` command and not a billing system.

## Scope and authorization

No `circle-client paywall-*`, billing, or refund command exists. Do not add one. `circle-client open-browser --path / --port 9333 --profile-dir data/visible_browser/profile_billing_test` opens a visible Chrome; connect Playwright to the CDP endpoint it prints. That member cookie and CSRF session does not grant an Admin API token. Admin calls use `https://app.circle.so/api/admin/v2` with `Authorization: Token <admin token>`, supplied only for that authorized call. Do not write the token, cookies, card data, or personal billing records into this repo. The public spec also lists a `host` header scheme. If a known-good token still fails, stop and inspect that requirement. Do not fall through to another write.

Browser and API writes need current authorization for that exact action. Inspect and propose the bound IDs and the intended change first. The human owner completes card entry and 3DS. Do not touch card inputs, and do not treat an invitation as a normal checkout. The snippets below are request templates, not scripts to run on their own.

## Objects

A paywall (`9000001`) is the checkout offer. A price (`9000011`) is one charging option on it; yearly, quarterly, and one-time prices can coexist, and another currency may be a separate paywall. A new test paywall with one yearly price does not add a price to an existing offer. A subscription (`9000002`) is one member's agreement (`member@example.invalid`), with its own `trial_ends_at` and `renews_at`. Circle integer IDs are not Stripe IDs (`price_EXAMPLE`, `sub_EXAMPLE`, `in_EXAMPLE`, `ch_EXAMPLE`, `re_EXAMPLE`). On the Circle record the processor id is `processor_id`; the list filter is `subscription_processor_id`. The price field is `paywall_price_id`, not `price_id`.

On a card-backed renewing trial, the next renewal date is the first scheduled nonzero annual charge. The zero-dollar paid invoice is trial setup, not annual money collected. A saved card may sit on the Stripe customer. Circle's admin subscription schema has no `default_payment_method`; a null value on the Stripe subscription alone does not prove the card is missing. Record only a boolean. An archived paywall can still show a nested price with `status: active`. Count active paywalls separately. Do not infer an active offer from `price.status`.

For a paid recurring charge, readback authority on a refund is the Stripe charge (`ch_EXAMPLE`) and refund (`re_EXAMPLE`), plus the exact Circle transaction row and subscription row (`9000002` / `sub_EXAMPLE`). The Stripe invoice (`in_EXAMPLE`) can remain `paid` with its historical amount; invoice status is neither refund success nor refund failure.

## What was verified

Verified once, on one owner-controlled trial, with synthetic IDs here: GUI creation of a new paywall and one yearly price, 14-day free trial, no upfront amount, card required, self-cancel, test space only. Normal owner checkout stored a payment method and produced a zero-dollar setup invoice. Circle's admin list stayed empty for a few minutes while the Stripe trial and that invoice were already visible, then the Circle row appeared. GUI Extend trial worked. `PATCH` `extend_trial` of 15 days then worked on the same Circle and Stripe subscription and the same price, with `renewing: true`, the customer-level payment method still present, and no new invoice or nonzero charge. `POST` cancel with `ends_at: now` returned 200; Circle was canceled with `renewing: false`, and Stripe was canceled. `PUT` archive returned 200, and a later read showed the paywall `inactive` while its price could still be `active`.

Verified once, on one owner-authorized full refund of one recurring annual charge (not a trial setup invoice and not a one-time course charge), with synthetic IDs here: in Circle `Payments`, `Transactions`, opening the exact recurring-payment row menu (`More actions` observed live; Circle help documents `More options` three dots beside the row) and choosing `Refund payment` opened `Refund a payment`. The row and displayed amount were bound first. `Confirm refund` was clicked once, and only after a later explicit owner authorization. Circle transaction status became `Refunded`. On Stripe, the charge (`ch_EXAMPLE`) had `refunded: true` and `amount_refunded` equal to the full charge amount, and a separate refund object (`re_EXAMPLE`) had `status: succeeded`. The original annual subscription (`9000002` / `sub_EXAMPLE`) stayed `active` with `cancel_at: null`, `cancel_at_period_end: false`, and unchanged price (`price_EXAMPLE`), currency, yearly interval, quantity, and next renewal date. An independent one-time course payment stayed paid and unrefunded. No billing date was changed because the existing next charge was already later than the independent course coverage end.

Separately authorized billing-date follow-ups after full recurring refunds were subsequently live-verified in bounded member flows: the original subscriptions and independent course payments were retained, Circle stayed `active` and renewing, Stripe became `trialing`, and a zero-dollar draft adjustment invoice appeared. See the follow-up section below for the exact preconditions and readback.

Those passes do not prove that every transaction refund leaves every subscription active, nor do they prove general multi-member isolation, `at_period_end`, cancellation with `refund_type`, partial refunds, chargebacks, automatic customer refund emails, bank-statement arrival timing, Stripe processing-fee return, a personalized first-charge date before card submit, or an actual future nonzero renewal charge on the test trial.

| Capability | Status |
|---|---|
| Isolated paywall, card-backed 14-day trial, $0 setup invoice | Live-verified, one owner, test space only |
| Circle list lag of a few minutes after Stripe already shows the trial | Live-verified |
| GUI Extend trial, then `extend_trial` on the same subscription and price | Live-verified; calendar day only |
| Cancel `ends_at: now`, then archive to paywall `inactive` | Live-verified; price may stay `active` |
| Full Circle transaction refund of one recurring annual charge keeping the subscription `active` and an independent course charge paid | Live-verified once, one owner-authorized recurring charge; read back subscription every time |
| Separately authorized `change_billing_date` after a full recurring refund, retaining the original subscription and price | Live-verified in bounded member flows; dual-system readback required |
| `at_period_end`, cancel with `refund_type`, partial refund (`Partial refunded`), Circle payout fee return, Stripe customer refund email setting, 5-10 day bank arrival estimate | Documented only |
| Checkout showing a personal first-charge date before card submit; a real future nonzero renewal charge; Stripe processing-fee return on refund | Not proven |

## Visible GUI

Go to Payments, Paywalls, Create paywall on `https://example.circle.so`. Use a test name, an ASCII slug, and a USD price such as $1 annually: 14-day free trial, no upfront fee, require card, allow self-cancel. Grant only a test space. Do not attach all spaces, production groups, courses, or workflows, and do not advertise the link as a private access gate. Publish only with owner authorization. Publish enables checkout; it does not enroll the owner. Reload the editor, then open the public or native checkout the editor exposes. Confirm it shows $0 today, then the trial, then the renewal amount. Do not invent a checkout path. The owner uses Checkout or Start your free trial. Do not operate the card fields.

After an exact subscription match, open Payments, Subscriptions, that row, More actions, Extend trial. Pick a later date, read the review text, and confirm. Do not use Change plan or Change billing cycle; those can prorate or charge upfront. The Extend trial help article caps the new end date at two years ahead. Do not assume either API operation accepts or enforces that horizon. The same article describes a Stripe dashboard extend. This experiment did not use it. Do not write Stripe without separate authorization.

Switches may expose `arialabel` rather than `aria-label`, and a hidden input may intercept the click. Click the visible `role=switch`. The amount field is cents-masked: `1` became $0.01 and failed validation; `100` became $1.00. Read the displayed value before submit. The date field is a read-only Flatpickr input. Use `.flatpickr-monthDropdown-months` and a scoped `.flatpickr-day[aria-label="December 3, 2030"]`. The portal can be `aria-hidden` under the modal. Confirm the review text. Do not clear `readonly` or set the DOM value.

## Recurring transaction refund

To refund a recurring subscription charge without canceling the subscription, use the Circle transaction refund path: `Payments`, `Transactions`, the exact recurring-payment row, the row menu, then `Refund payment`. The live pass observed the row menu label `More actions`; Circle help documents `More options` (three dots) beside the row, then `Refund payment`. Match the visible menu item whose label is `Refund payment`. Do not choose `Cancel`, `Change billing date`, `Change billing cycle`, or `Change plan` from that menu. When the goal is to preserve an independently paid one-time course, target the recurring subscription charge, not the one-time course charge.

Before `Confirm refund`, preflight every binding field and require all of them to match the intended recurring annual charge. Opening the dialog is inspection, not the write: exact member identity (`member@example.invalid`, never a partial email), currency, displayed amount, transaction timestamp, linked invoice (`in_EXAMPLE`) and charge (`ch_EXAMPLE`), trial versus annual labels, and one-time course versus recurring labels. A zero-dollar trial setup invoice is not this charge. An older canceled row is not this charge.

The `Refund a payment` dialog displays customer identity, transaction timestamp, `Amount paid`, `Refund amount`, `Reason`, and `Confirm refund`. Circle help states that the refund amount defaults to the original transaction amount, can be lowered for a partial refund, and cannot exceed the original transaction amount; partial refunds were not tested here. Circle help states that the reason is internal and invisible to members. Do not put secrets into the reason field, and do not prescribe a required reason string. Bind the exact row and displayed refund amount, stop before `Confirm refund`, and click `Confirm refund` once only after a later explicit owner authorization for that exact refund. Click once only; never issue a second confirmation click.

Operational UI constraints from the live pass (do not use these as a license to probe secrets):
- Transaction counters and rows can briefly show zeros while data is loading. Do not treat skeleton or loading state as an empty ledger.
- A hidden `Search` field exists. Filter with the visible `E-mail` control, or scope an already-visible exact table row. Do not type into the hidden `Search` field.
- Expand `Filters` before interacting with filter inputs: the `E-mail` control can report as CSS-visible while still covered by the collapsed filter panel. Open it, enter the address into the visible `Search e-mail` field, click `Apply`, and match the exact row without force-clicks.
- If an overlay or header intercepts a click, set a normal desktop viewport and inspect the interceptor. Do not force-click.
- After the confirm click, a generic visible `dialog` role can match both the refund modal and a success toast. A subsequent strict-locator failure does not mean the refund failed. Do not click `Confirm refund` again. Inspect the exact transaction row and perform an independent Stripe charge and refund readback.
- Never print hidden inputs, form `outerHTML`, cookies, CSRF tokens, or unredacted network payloads. Keep logs redacted.

Readback must check the Circle transaction row, the Circle and Stripe subscription (`9000002` / `sub_EXAMPLE`), the Stripe charge (`ch_EXAMPLE`), and the Stripe refund (`re_EXAMPLE`). On the verified pass, the Circle transaction status became `Refunded` (Circle help labels partial refunds `Partial refunded`, which was not observed), `ch_EXAMPLE` showed `refunded: true` with `amount_refunded` equal to the full charge amount (for example, `100` cents as a shape example, not a verified charge amount), and `re_EXAMPLE` showed `status: succeeded`. The invoice (`in_EXAMPLE`) can remain `paid` with its historical amount; do not treat invoice status as refund readback. If an embedded refund list is absent on the charge, a separately authorized read of refunds for `ch_EXAMPLE` is a read-only check, not a second refund. Do not resend a refund because a list is missing or a locator failed.

Do not assume every transaction refund leaves every subscription active. Always read the subscription back after the refund. If the subscription canceled, stop and report; do not recreate it or collect another payment without new authorization. On the original refund-only pass, the existing next renewal date was already later than the independent course coverage end, so no billing date was moved. Never move a later existing billing date earlier to match coverage; a refund by itself does not authorize `change_billing_date`.

### Separately authorized billing-date follow-up

Changing a subscription's next billing date after a full refund of an exact recurring transaction requires separate, explicit authorization. This follow-up flow was live-verified in bounded member scenarios rather than as a guarantee across arbitrary subscriptions, and no financial mutation CLI has been added. Before applying a change, verify that the original subscription is active and renewing, the full refund for the recurring charge has succeeded, and any independent course payment remains paid and unrefunded. Resolve the exact Circle integer subscription ID (`9000002`) by listing subscriptions filtered with `subscription_processor_id=sub_EXAMPLE` and cross-checking the member, paywall, and price identities. Preserve the existing billing date if it is already later than the target; when a change is authorized and needed, set a fixed target no earlier than both the independently validated coverage end and the existing next billing date, within the supported horizon. Send a single request to the Circle Admin API (`PATCH /community_member_subscriptions/9000002/billing_date` with JSON body `{"operation":"change_billing_date","billing_date":"YYYY-MM-DD"}`), then read back the live state before considering any retry.

In live verification, the Circle subscription stayed active and renewing (`status: active`, `renewing: true`) with both `renews_at` and `trial_ends_at` matching Stripe's updated `trial_end`, while the Stripe subscription status transitioned to `trialing`. The subscription kept the same price, currency, yearly billing interval, quantity, and customer payment method; the subscription-level `default_payment_method` field can be `null` when the payment method is stored on the customer record. Stripe created a zero-dollar draft adjustment invoice (`total`, `amount_due`, and `amount_paid` all `0`) without collecting any additional payment, while the earlier refunded charge's invoice can continue to report its status as `paid`.

The request accepts a calendar date (`YYYY-MM-DD`), not an exact second. The resulting renewal timestamp was observed at a non-midnight time on the target day; post-update verification must confirm both the source calendar date and that the full timestamp is at least the independently validated coverage end. Do not infer member entitlement from a `trialing` Stripe status alone, and do not treat this observed state transition as a guarantee of future charge execution, bank settlement behavior, or Stripe fee handling.

Official Circle help boundaries (documented, not re-proven unless noted above):
- A refund issued in Circle returns Circle's transaction fees in the payout, whereas a refund issued in the Stripe dashboard does not return those Circle transaction fees. The help text does not state that Stripe processing fees are returned; do not imply that they are.
- A transaction refund is distinct from canceling a subscription and choosing a prorated or full refund of the last subscription payment. That cancel path takes effect immediately and was not used. Full refund of a one-time fee paywall purchase removes access unlocked by that one-time paywall.
- Customer refund email notifications are controlled by the paywall-connected Stripe account under `Settings`, `Customer emails`, `Payments`, `Refunds`. Do not assume a notification was sent, and do not send one as part of this runbook.
- Stripe refunds the original payment method. Circle help states that the amount may take 5 to 10 days to appear on a bank statement; that is an unverified estimate, not a guarantee.
- Admins issue refunds. A member self-cancel expires at period end without a refund. A chargeback is handed to Stripe. None of those alternate paths were tested here.
- Circle help states that changing the billing date keeps the subscription active, places it on a trial until the new date, and charges on that date, with a two-year horizon in the help article. The API state transition was observed in the separately authorized follow-up above; the GUI billing-date action and actual future collection were not tested in that follow-up. Do not assume the API enforces the help-article horizon.

## Admin API templates

Base: `https://app.circle.so/api/admin/v2`. `per_page` max is 100. Paginate.

```bash
# Paywall search. `name` is a partial filter and can return unrelated rows.
# `paywall_id` is an include list. This endpoint has no `query` parameter.
curl -sS "$BASE/paywalls/search?paywall_id=9000001&per_page=100" \
  -H "Authorization: Token $CIRCLE_ADMIN_TOKEN"

# Subscription list. `query` here is free text. `member_email` is a partial match.
curl -sS "$BASE/community_member_subscriptions?paywall_ids=9000001&per_page=100&page=1" \
  -H "Authorization: Token $CIRCLE_ADMIN_TOKEN"
curl -sS "$BASE/community_member_subscriptions?subscription_processor_id=sub_EXAMPLE&per_page=100" \
  -H "Authorization: Token $CIRCLE_ADMIN_TOKEN"
```

`$CIRCLE_ADMIN_TOKEN` is a shell placeholder, not a `circle-client` setting. Identity is an exact match on community, `community_member_id`, `paywall_id`, `paywall_price_id`, and `processor_id`. A partial email is not proof. If Circle's list is empty while Stripe already shows the trial, re-read at most four times, about a minute apart. If it is still absent after several minutes, stop and report uncertainty. Do not select an older canceled row or start another checkout.

```bash
# Genuine-trial increment. 15 is a shape example, not a value to copy.
curl -sS -X PATCH "$BASE/community_member_subscriptions/9000002/billing_date" \
  -H "Authorization: Token $CIRCLE_ADMIN_TOKEN" -H "Content-Type: application/json" \
  -d '{"operation":"extend_trial","days_to_extend":15}'
```

`days_to_extend` must be a positive integer. Each accepted call adds days, so it is not idempotent. Read the current end, compare it with one fixed target calendar day, and if that day is already reached, stop. A date-level no-op check is not a second write. Otherwise send only the remaining whole-day increment. If the response is lost, GET the list before any resend. If something else changed the row, replan. Do not shorten the trial to reset cleanup. Both the GUI and `extend_trial` landed on the selected calendar day, but the clock time was not midnight and not the previous timestamp plus an exact number of seconds. Check the calendar day in the source timezone. The spec parses `billing_date` as a calendar date (`YYYY-MM-DD`); that is not a second-level guarantee.

`{"operation":"change_billing_date","billing_date":"2030-12-18"}` illustrates the absolute-date body, not a target to copy. Select a real later date within the supported horizon. This operation was validated in the separately authorized paid-refund follow-up, not in the original trial-only experiment. The operation summary says an ineligible selected operation returns 401 before input validation, while the 401 example body still says the token is invalid. Read the body. Do not refresh the token, resend, or switch operations. 422 covers invalid input, a missing trial anchor, mobile-platform rejection, or a billing-date service failure.

```bash
# Authorized free-trial cleanup only. Omit refund_type. Do not DELETE the paywall.
curl -sS -X POST "$BASE/community_member_subscriptions/9000002/cancel" \
  -H "Authorization: Token $CIRCLE_ADMIN_TOKEN" -H "Content-Type: application/json" \
  -d '{"ends_at":"now"}'
curl -sS -X PUT "$BASE/paywalls/9000001/archive" \
  -H "Authorization: Token $CIRCLE_ADMIN_TOKEN"
```

Cancel `ends_at` is `now` or `at_period_end`. This experiment used `now` on the free trial only. `at_period_end` and `refund_type` (`prorated` or `full`) were not tested. After cancel, read Circle and Stripe when authorized: this subscription is canceled, `renewing` is false, and no other subscription changed. Archive returns 200 with `{success, message}`, not the paywall object. It applies to an already-active paywall and irreversibly discards kept upsell offers where this paywall is host or target. Read back with `GET /paywalls/search?paywall_id=9000001` and confirm paywall `status` is `inactive`. There is no GET `/paywalls/{id}`; that path is DELETE and is not cleanup. Do not delete the account, change other memberships, remove the saved card, or treat archive as cancellation.

## Readback and production gap

Independent search and list results are the authority, not a toast. Do not GET `/paywalls/{id}`. In the trial-only branch, before cleanup the same IDs, `paywall_price_id`, currency, `interval: yearly`, and `amount_in_cents` are unchanged; status is `trial` and `renewing` is true; `trial_ends_at` and `renews_at` agree with the provider on the target calendar day; the latest invoice is still the zero-dollar setup invoice. The paid-refund follow-up instead retained Circle `active` with Stripe `trialing` and produced a zero-dollar draft adjustment invoice. Keep evidence in a private gitignored file: selected IDs, current and target calendar days, source timezone, raw timestamps, operation, HTTP status, zero versus nonzero money, and cleanup state. Never store secrets or card data.

A per-member date change does not prove checkout can show that person's first charge before enrollment. A shared trial length applies only to new subscriptions; editing the paywall trial does not rewrite existing ones. A short bootstrap trial plus a later extension must disclose the intended date and must not leave a failed extension able to charge early. This experiment does not implement that path. Trial status adds no extra entitlement. The original refund-only pass did not change the billing date; the separately authorized follow-up did. Do not apply the trial-only branch's zero-dollar setup invoice to the refunded charge or its later adjustment invoice.

## Official references

- https://api-headless.circle.so/api/admin/v2/swagger.yaml
- https://help.circle.so/p/payments/paywall-trials/offer-paywall-trials
- https://help.circle.so/p/payments/paywall-trials/extend-trial-duration-for-paywall-subscriptions
- https://help.circle.so/p/payments/paywall-management/change-billing-cycle-or-plan-for-member-subscriptions
- https://help.circle.so/p/payments/paywall-management/refund-member-payments
