# Authentication lifecycle

- `renew_tokens()`: treats a token as unusable if missing or `expires_on` is
  unparseable/past.
- `update_tokens(grant_type)`: password grant needs `username`/`password`;
  refresh grant needs `refresh_token`. Unicommerce's refresh tokens expire
  every 30 days — on `invalid_grant` from a refresh attempt, the connector
  automatically falls back to a fresh password-grant login rather than
  failing outright.
- Unicommerce sometimes returns auth failures as **HTTP 500 with a
  non-standard error shape** instead of proper OAuth error fields —
  `_auth_error_detail()` knows to look in `errors[].errorParams.Exception`
  for the real message in that case.
- Two concurrent token-refresh attempts (e.g. cron + a manual test) can race
  into a timestamp-mismatch error; this is retried once against a freshly
  reloaded document copy, copying only the four token fields.

Never edit `access_token` / `refresh_token` / `expires_on` / `token_type` by
hand — they are fully auto-managed.
