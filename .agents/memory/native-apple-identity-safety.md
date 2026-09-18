---
name: Native Apple identity safety
description: Durable security rules for Apple identity mapping, existing-account linking, token exchange, and account deletion.
---

# Native Apple identity safety

Use Apple's cryptographically verified stable subject as the identity key. A verified email can initialize a new account, including a private relay address, but must never replace subject-based lookup for returning users.

**Why:** Apple may omit name and email after first authorization, and trusting client-supplied profile data or matching email alone can create account-takeover or duplicate-account paths.

**How to apply:** verify signature, issuer, audience, expiry, and subject against Apple JWKS. Persist first-use profile data, store a sparse unique subject, and issue the normal WatchSmart access/refresh session.

Existing WatchSmart accounts are linked only after the existing account authenticates. The Apple token's verified email must match, and the Apple subject must not belong to another account.

**Why:** silent email merges are not sufficient proof that the person signing in with Apple controls the existing WatchSmart account.

**How to apply:** retain the fresh Apple credential briefly on-device, authenticate the existing account, then call an authenticated linking endpoint. Provide a way to cancel or recover from an expired link attempt.

Authorization-code exchanges must verify that Apple's returned identity token has the same subject as the identity token that began the request. Store revocation credentials only server-side and revoke Apple authorization before completing account deletion.

**Why:** an unbound authorization code can associate or revoke the wrong Apple identity, while local-only deletion does not satisfy Apple's token-revocation expectations.

**How to apply:** require server-side Team ID, Key ID, and private signing key; never expose Apple refresh credentials through user, admin, onboarding, or export serializers.