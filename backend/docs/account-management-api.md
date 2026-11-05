# Account management: backend and frontend handoff

The backend now supports inviting, listing, disabling, enabling and resetting staff accounts. The People screen displays the returned links, supports reactivation and shows account status. No email is sent automatically.

## API contract
All paths below start with `/api/v1`. Administrator requests require a login cookie and `users:manage`. All POST requests require an allowed `Origin` header. Responses are not cached.

| Method and path | Input | Result |
| --- | --- | --- |
| GET `/admin/users` | Optional `?active=true` or `?active=false` | `{items: [...]}`, including inactive users by default |
| POST `/admin/users` | `{username, displayName, capabilities}` | 201, `{user, credentialAction}` with activation link |
| POST `/admin/users/{id}/reset-credential` | `{}` | `{user, credentialAction}` with reset link |
| POST `/admin/users/{id}/deactivate` | `{}` | `{user, credentialAction: null}` |
| POST `/admin/users/{id}/reactivate` | `{}` | `{user, credentialAction}`; action may be null |
| POST `/auth/activate` | `{token, password}` | `{success: true}`; works for activation and reset, no login cookie required |

`user` includes existing identity fields plus `active`, `credentialsReady`, and `resetRequired`. `credentialAction` is `{purpose: "activation" | "reset", url, expiresAt}`. Display the returned URL immediately; the backend cannot retrieve it later. Treat the URL like a temporary password and share it privately with the intended person. A replacement link invalidates the previous one.

The password must be 12–128 characters. The default activation expiry is 24 hours; reset expiry is 30 minutes. Configure with `ACTIVATION_TOKEN_HOURS` and `RESET_TOKEN_MINUTES`. URLs use `ALLOWED_ORIGIN`, not the incoming Host header. On another computer, use the correct reachable frontend origin in configuration.

## Frontend integration (4 November 2026)

- The People screen displays each returned activation/reset link with a copy button and expiry. Links remain only in page memory.
- Inactive accounts have Reactivate or Issue new activation link actions. Pending and reset-required states are visible.
- Reset and deactivation ask for confirmation. Failed requests show errors without success messages. Self-management actions are hidden.
- Permission choices stay within one selected role, matching backend validation.
- Practitioner selectors request active accounts. The existing clinical-permission filter remains.
- The password-setting screen handles both activation and reset, then returns to login.
- Sign-out awaits server success, clears local state and performs a full navigation to login. Failure leaves a retryable error; cancel keeps the session.

## Behaviour and errors

- Creation stores an inactive account with no usable chosen password. Activation sets its first password and enables login.
- Issuing a reset immediately signs the person out and blocks the old password. The person must finish resetting before logging in again.
- Deactivation revokes login sessions and outstanding links. It preserves the user row, patient records and authorship of past notes.
- Reactivating an initialized account permits a fresh login; old sessions never return. A pending invitation gets a fresh activation link. An initialized account with an unfinished reset gets a fresh reset link.
- Administrators cannot deactivate themselves or reset their own credentials through these endpoints. Another administrator or the existing local maintenance commands can help.
- 401 means login required; 403 means permission/origin denied; 404 means target unavailable; 409 means duplicate username or incompatible account state; 422 means invalid fields; 400 means expired/used/unknown credential link; 429 means too many attempts.
- Credential redemption allows 30 attempts per client IP per 15-minute fixed window. Existing login limits are unchanged. Deployment behind a proxy must provide trustworthy client addresses.
- API capabilities do not grant access to individual patients. Existing patient-access checks still apply.

## Storage and maintenance

`0004_account_credentials` adds account-state flags and a table for hashed, expiring, single-use tokens. Existing accounts keep their current access. Run `alembic upgrade head` on every teammate's database before starting the updated backend.

Password hashes use the existing Argon2 implementation. Raw link tokens and passwords are not written into audit records. Successful account changes and their audit records commit together. User row locks coordinate reset/deactivation/redemption. Terminal maintenance commands also revoke old links and sessions.

The first administrator can still be created locally:

```sh
python -m app.manage create-user --username admin --name "Clinic Admin" --role admin
```

It prompts for a password. Do not commit passwords, links, secret keys or `.env` files.

## Validation

The automated suite covers permissions, invitations, replay/expiry, duplicate usernames, password validation, reset revocation, reactivation, listing and rate limits alongside previous backend tests. A separate PostgreSQL check confirmed that simultaneous redemption of one token yields exactly one success. Browser integration checks cover the new admin controls and sign-out with the real FastAPI backend.
