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
- `renew_tokens()` runs on **every** `UnicommerceClient()` construction — a
  large pull run instantiates it thousands of times. The settings row is only
  saved when a token was actually fetched (`needs_token` true); a still-valid
  token is a pure no-op with no write at all. Saving unconditionally used to
  mean every client construction wrote to this one shared Settings row —
  real lock contention at scale, confirmed live (bench migrate and other jobs
  blocked waiting on it during a large sync).

Never edit `access_token` / `refresh_token` / `expires_on` / `token_type` by
hand — they are fully auto-managed.
