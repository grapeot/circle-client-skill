# Circle paywall and trial subscription playbook

Optional playbook for an agent that already has a human-visible browser and HTTP tools. It covers an isolated test paywall, a normal owner checkout, an independent readback, a genuine-trial extension, and cleanup. It is not a `circle-client` command and not a billing system.

## Scope and authorization

No `circle-client paywall-*` or billing command exists. Do not add one. `circle-client open-browser --path / --port 9333 --profile-dir data/visible_browser/profile_billing_test` opens a visible Chrome; connect Playwright to the CDP endpoint it prints. That member cookie and CSRF session does not grant an Admin API token. Admin calls use `https://app.circle.so/api/admin/v2` with `Authorization: Token <admin token>`, supplied only for that authorized call. Do not write the token, cookies, card data, or personal billing records into this repo. The public spec also lists a `host` header scheme. If a known-good token still fails, stop and inspect that requirement. Do not fall through to another write.

Browser and API writes need current authorization for that exact action. Inspect and propose the bound IDs and the intended change first. The human owner completes card entry and 3DS. Do not touch card inputs, and do not treat an invitation as a normal checkout. The snippets below are request templates, not scripts to run on their own.

## Objects

A paywall (`9000001`) is the checkout offer. A price (`9000011`) is one charging option on it; yearly, quarterly, and one-time prices can coexist, and another currency may be a separate paywall. A new test paywall with one yearly price does not add a price to an existing offer. A subscription (`9000002`) is one member's agreement, with its own `trial_ends_at` and `renews_at`. Circle integer IDs are not Stripe IDs (`price_EXAMPLE`, `sub_EXAMPLE`). On the Circle record the processor id is `processor_id`; the list filter is `subscription_processor_id`. The price field is `paywall_price_id`, not `price_id`.

On a card-backed renewing trial, the next renewal date is the first scheduled nonzero annual charge. The zero-dollar paid invoice is trial setup, not annual money collected. A saved card may sit on the Stripe customer. Circle's admin subscription schema has no `default_payment_method`; a null value on the Stripe subscription alone does not prove the card is missing. Record only a boolean. An archived paywall can still show a nested price with `status: active`. Count active paywalls separately. Do not infer an active offer from `price.status`.

## What was verified

Verified once, on one owner-controlled trial, with synthetic IDs here: GUI creation of a new paywall and one yearly price, 14-day free trial, no upfront amount, card required, self-cancel, test space only. Normal owner checkout stored a payment method and produced a zero-dollar setup invoice. Circle's admin list stayed empty for a few minutes while the Stripe trial and that invoice were already visible, then the Circle row appeared. GUI Extend trial worked. `PATCH` `extend_trial` of 15 days then worked on the same Circle and Stripe subscription and the same price, with `renewing: true`, the customer-level payment method still present, and no new invoice or nonzero charge. `POST` cancel with `ends_at: now` returned 200; Circle was canceled with `renewing: false`, and Stripe was canceled. `PUT` archive returned 200, and a later read showed the paywall `inactive` while its price could still be `active`.

That does not prove multi-member isolation, a paid subscription, a refund that keeps the subscription, `change_billing_date`, a personalized first-charge date before card submit, or an actual future nonzero charge.

| Capability | Status |
|---|---|
| Isolated paywall, card-backed 14-day trial, $0 setup invoice | Live-verified, one owner, test space only |
| Circle list lag of a few minutes after Stripe already shows the trial | Live-verified |
| GUI Extend trial, then `extend_trial` on the same subscription and price | Live-verified; calendar day only |
| Cancel `ends_at: now`, then archive to paywall `inactive` | Live-verified; price may stay `active` |
| `change_billing_date`, paid refund that keeps the subscription, `at_period_end` | Documented only |
| Checkout showing a personal first-charge date before card submit; a real nonzero renewal charge | Not proven |

## Visible GUI

Go to Payments, Paywalls, Create paywall on `https://example.circle.so`. Use a test name, an ASCII slug, and a USD price such as $1 annually: 14-day free trial, no upfront fee, require card, allow self-cancel. Grant only a test space. Do not attach all spaces, production groups, courses, or workflows, and do not advertise the link as a private access gate. Publish only with owner authorization. Publish enables checkout; it does not enroll the owner. Reload the editor, then open the public or native checkout the editor exposes. Confirm it shows $0 today, then the trial, then the renewal amount. Do not invent a checkout path. The owner uses Checkout or Start your free trial. Do not operate the card fields.

After an exact subscription match, open Payments, Subscriptions, that row, More actions, Extend trial. Pick a later date, read the review text, and confirm. Do not use Change plan or Change billing cycle; those can prorate or charge upfront. The Extend trial help article caps the new end date at two years ahead. Do not assume either API operation accepts or enforces that horizon. The same article describes a Stripe dashboard extend. This experiment did not use it. Do not write Stripe without separate authorization.

Switches may expose `arialabel` rather than `aria-label`, and a hidden input may intercept the click. Click the visible `role=switch`. The amount field is cents-masked: `1` became $0.01 and failed validation; `100` became $1.00. Read the displayed value before submit. The date field is a read-only Flatpickr input. Use `.flatpickr-monthDropdown-months` and a scoped `.flatpickr-day[aria-label="December 3, 2030"]`. The portal can be `aria-hidden` under the modal. Confirm the review text. Do not clear `readonly` or set the DOM value.

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

`{"operation":"change_billing_date","billing_date":"2030-12-18"}` is the documented body for an eligible paid or active subscription. This trial experiment did not validate it. The operation summary says an ineligible selected operation returns 401 before input validation, while the 401 example body still says the token is invalid. Read the body. Do not refresh the token, resend, or switch operations. 422 covers invalid input, a missing trial anchor, mobile-platform rejection, or a billing-date service failure.

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

Independent search and list results are the authority, not a toast. Do not GET `/paywalls/{id}`. Before cleanup, the same IDs, `paywall_price_id`, currency, `interval: yearly`, and `amount_in_cents` are unchanged; status is `trial` and `renewing` is true; `trial_ends_at` and `renews_at` agree with the provider on the target calendar day; the latest invoice is still the zero-dollar setup invoice. Keep evidence in a private gitignored file: selected IDs, current and target calendar days, source timezone, raw timestamps, operation, HTTP status, zero versus nonzero money, and cleanup state. Never store secrets or card data.

A per-member date change does not prove checkout can show that person's first charge before enrollment. A shared trial length applies only to new subscriptions; editing the paywall trial does not rewrite existing ones. A short bootstrap trial plus a later extension must disclose the intended date and must not leave a failed extension able to charge early. This experiment does not implement that path. Trial status adds no extra entitlement. A paid annual refund that keeps the subscription and then calls `change_billing_date` is a separate authorized experiment.

## Official references

- https://api-headless.circle.so/api/admin/v2/swagger.yaml
- https://help.circle.so/p/payments/paywall-trials/offer-paywall-trials
- https://help.circle.so/p/payments/paywall-trials/extend-trial-duration-for-paywall-subscriptions
- https://help.circle.so/p/payments/paywall-management/change-billing-cycle-or-plan-for-member-subscriptions
- https://help.circle.so/p/payments/paywall-management/refund-member-payments
