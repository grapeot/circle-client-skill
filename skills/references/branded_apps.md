# Circle Branded App: custom screens and navigation

Use this reference when adding a link, Custom HTML screen, or embedded tool to a Circle Branded App, changing its placement in navigation, or testing Circle identity handoff. This workflow uses the visible App Builder; there is no Circle Client CLI command for editing the Builder.

## Establish what success looks like

- **Placement:** Identify the actual destination on the device. In the legacy Builder, **Show in → Home** adds a tab at the top of Home, not a persistent bottom-nav item. If the requested destination is the bottom bar, confirm the live Builder exposes a bottom-navigation editor with the requested screen as a destination. If it does not, report the blocker; do not silently substitute a Home tab.
- **Audience:** A member outside the test group cannot see or open a restricted screen; the intended tester can. Check this after a fresh sign-in or a full app restart. The browser preview can show the layout, but it cannot prove what a real device or a given member receives.
- **Scope:** Read back the saved placement and access group. Compare existing navigation, screen names, and onboarding against the baseline. Have a way to remove the test screen and restore the original preview setting before making the first write.

## Work in the live Builder

Use `circle-client open-browser` with a dedicated profile. Keep the visible browser open across editing and saving so unsaved state and confirmation dialogs stay available. In **Branded App → Manage screens**, inspect the available navigation surfaces and take a private baseline of the current configuration. For an embed, use a **Custom HTML** screen and edit its **Body**. Preview mobile layout, sizing, scrolling, and the back path. Do not try to force an unavailable placement through unpublished API calls.

**Admin preview is not a sufficient access boundary.** Circle documents that it should apply changes only to admins. In a live check, a non-admin test account still saw a newly saved tab after an Admin Preview save; removing the tab and restarting the app restored the prior navigation. Treat a successful save toast, preview badge, or admin-only browser session as evidence of the admin operation, not of member isolation.

Prefer a separate test community with its own branded build, if available. In production, use a dedicated access group containing only the intended testers, with no space grants, paywall linkage, or automatic membership. Set **Access control → Access groups** on the screen before the first save. **Not in navigation** only hides an entry; it is not an access check. If the Builder cannot attach the group before saving, stop rather than saving an unrestricted version to fill in later.

Obtain explicit authorization for the specific preview write and any access-group creation or membership changes before performing them. A request to inspect or demonstrate existing behavior does not authorize writes. Save only through the intended preview action. If the saved group or placement cannot be confirmed or differs from the intended configuration, restore the baseline and stop.

Test the excluded account before opening the screen as an allowed tester. If the excluded account can see the entry or open it through an available direct route, immediately restore the baseline, recheck the device, and stop. If a direct-route check cannot be performed, state that limit rather than claiming full isolation. Releasing the change to general members is separate from preview validation and requires explicit live release authorization.

## Optional: Circle member login for an embedded app

Use Circle's signed `window.circleUser.identityToken` on a supported custom screen. Send it only to the intended HTTPS verifier; use the documented URL-fragment handoff for an iframe, clear the fragment promptly, and never log, record, or include the token in a query string. The app server verifies RS256 with Circle's fixed public key endpoint, `iss`, the expected community `aud`, and expiry. Treat unsigned fields from `window.circleUser` as display-only. After verification, use a unique, verified identity mapping to find the app account; never infer authorization from the email alone. Missing, invalid, expired, or unmapped credentials must not open the protected app. Test both real-token success and failure; synthetic or Builder-only checks are not evidence of real mobile token delivery.

When requested, deliver a short real-device recording with dead time removed and a few screenshots showing placement and the end state. Exclude verification codes, raw tokens, private member data, and unrelated screens. State what actually passed, with the device/build and tested account role; keep captures private unless sharing is authorized.

## Official references

- [Create and manage custom screens and navigation](https://help.circle.so/p/branded-apps/branded-apps/create-and-manage-custom-screens-and-navigation-for-branded-apps)
- [Add your own app to a branded app custom screen](https://help.circle.so/p/branded-apps/branded-apps/add-your-own-app-to-a-branded-app-custom-screen)
