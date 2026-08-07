# iOS subscription recovery and push release

Production stays on the current app, web build, and backend until the coordinated release gate. Backend push is disabled unless `PUSH_NOTIFICATIONS_ENABLED=true`; native Firebase initialization is disabled unless `DV_FIREBASE_ENABLED=true` at build time; Apple auth fails closed unless `APPLE_CLIENT_IDS` is configured.

## Part 2 — owner inputs

Sign in with Apple configuration completed:

- Team ID: `63M8Q266G9`
- Primary App ID: `com.vervetogether.dreamvalley`
- Services ID: `com.vervetogether.dreamvalley.web`
- Web domain: `dreamvalley.app`
- Return URL: `https://dreamvalley.app/restore`
- Private Email Relay source: `dreamvalley.app` (SPF passed)
- Sign in with Apple Key ID: `2HJTFA236Z`
- Private key filename: `AuthKey_2HJTFA236Z.p8` (stored outside the repository)
- Firebase project: `DreamValley` (`dreamvalley-cc387`)
- Production APNs Key ID: `3533UCA8TB`
- APNs key filename: `AuthKey_3533UCA8TB.p8` (stored outside the repository)
- Existing backend Firebase project: `dreamvalley-81fe6` (unchanged)
- Push Firebase project: `dreamvalley-cc387`
- Push credential: deploy the dedicated sender JSON outside the repository and set `FIREBASE_PUSH_CREDENTIALS_PATH` to its absolute server path.
- RevenueCat iOS public SDK key: `appl_uZdATDyrcCrIKUUDsmCvvaClwTs`; use for `DV_REVENUECAT_KEY_IOS` and backend `REVENUECAT_PUBLIC_API_KEY`.
- Existing service account to grant send-only cross-project access: `firebase-adminsdk-fbsvc@dreamvalley-81fe6.iam.gserviceaccount.com`

- Apple Developer: confirm Team ID, bundle ID, primary App ID, Services ID, verified web domains, return URLs, Sign in with Apple key ID, and provide the `.p8` key through the deployment secret store.
- Apple relay: register the sending domain and address, then confirm SPF/DKIM so `@privaterelay.appleid.com` recovery mail is delivered.
- Push: provide APNs key ID and `.p8`, create or confirm the Firebase iOS app, download `GoogleService-Info.plist`, and upload the APNs key to Firebase Cloud Messaging.
- RevenueCat: provide the public SDK/API key, confirm the webhook authorization secret, products, entitlement name, and production App Store connection.
- Release: choose the next marketing version/build number, approve notification wording, complete App Store privacy declarations, and provide Puneeth’s third premium email for the one-time repair.

## Part 3 — controlled release

1. Deploy the backward-compatible backend with Apple client IDs configured and push still disabled.
2. Deploy the web build; old production native clients continue using email restore and existing purchase bridges.
3. Add Sign in with Apple and Push Notifications capabilities, add `GoogleService-Info.plist`, build with `DV_FIREBASE_ENABLED=true`, and distribute through internal TestFlight.
4. Verify new purchase, same-device restore, cross-device Apple restore, email fallback, Stripe email capture, anonymous RevenueCat transfer, push opt-in/off, token refresh, notification open routing, and Emberlight chrome.
5. Submit the coordinated iOS build, then enable backend push only after the App Store version is available. Rollback is `PUSH_NOTIFICATIONS_ENABLED=false`, web rollback, and leaving the backward-compatible backend deployed.
