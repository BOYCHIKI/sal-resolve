# ADR-009: Seller accounts and two-step sign-in

**Status:** Accepted, implemented 2026-11-04
**Date:** 2026-11-04
**Scope:** Who is allowed to see a business's deals and disputes, and to approve what goes to PayPal.
**Constraint:** No new service or library. Python's standard library, Postgres and the existing web server only.

## 1. Why

Until now the API answered as one configured demo merchant. Anyone who could reach the web app acted as that
business, and every approval was recorded as `operator:demo`. A product that approves evidence sent to PayPal needs
to know who pressed the button.

## 2. Decisions

### D1: Passwords with scrypt, codes and tokens with SHA-256

- Passwords are hashed with scrypt (`hashlib.scrypt`, N=2^15, r=8, p=1, a 16-byte salt each). This costs about 64 MB
  and a tenth of a second per try.
- Session tokens, agent tokens and recovery codes are random and long, so a SHA-256 of each is enough.
- Nothing secret is logged or returned twice. Recovery codes appear once, when two-step sign-in is turned on.
- A new password needs 12 to 128 characters, at least four different characters, and must not contain the email
  name. A short list of common passwords is refused too.

### D2: One narrow way across tenants

Signing in happens before SAL knows the tenant, and every account table is behind forced RLS. Even the table owner
can't read across tenants.

- `login_emails` maps an email's SHA-256 to its merchant and user. It has no grants at all.
- Three `SECURITY DEFINER` functions reach it:
  - `auth_find_account` answers which account an email belongs to, and nothing else.
  - `auth_create_merchant` creates a business only for the tenant the caller has already set.
  - `auth_register_login` adds an email only for an account in the caller's tenant.
- The password hash and everything else are then read under RLS, in the tenant the lookup named.

### D3: Sessions name their tenant, like agent tokens

- A session token reads `salsess.<merchant id>.<secret>`. The merchant id only picks the tenant. The token proves
  nothing until the secret's hash is found there, so a token moved to another tenant opens nothing.
- A session ends after 30 idle minutes, and after 12 hours at most.
- Signing out ends one session. Changing the password, or turning on two-step sign-in, ends every other session.
- The API takes the session from `x-sal-session`. It accepts the header only from the SAL web server, through the
  internal token in production.
- Every approval, send and confirmation now records `user:<id>` instead of `operator:demo`.

### D4: The browser never holds a token it can read

- The web server keeps the token in an httpOnly, SameSite=Lax cookie. In production the cookie is also Secure and
  named with the `__Host-` prefix.
- Middleware asks the API about the session on every working screen. A missing, ended, idle or forged token sends
  the seller to sign in, and the stale cookie is removed.
- The `next` address after signing in may only be a path on this site.

### D5: Two-step sign-in with an authenticator app (RFC 6238)

- It is optional, and offered right after sign-up.
- The password alone opens only a 5-minute pending session, which no business route accepts. The code trades it for
  a new token, so the token seen before the code is never the one that is used.
- A code's time step is accepted once: a replayed code is refused.
- Each of 10 recovery codes works once.
- Turning two-step sign-in off needs both the password and a current code.

### D6: Guessing is slowed and looks the same

- A wrong email, a wrong password and a locked account give the same answer. A missing account is still checked
  against a dummy hash, so the timing doesn't tell either.
- Five wrong passwords or codes in a row lock the account for 1 minute, doubling each time up to 60 minutes. The
  right password resets the count.
- Per address, 20 failed sign-ins a minute and 5 new accounts an hour, counted in each API process like the agent
  limit.

## 3. Alternatives rejected

- **An outside identity provider (Auth0, Clerk, Supabase Auth).** It is one more service, account and secret, and
  sign-in would leave SAL's own tenant model.
- **Passkeys (WebAuthn).** They are stronger, but need a library on both sides. They are a good next step after
  authenticator codes.
- **Email magic links.** SAL has no mail service, and a mailbox becomes the only key.
- **A cross-tenant service role for sign-in.** It would read every account. The lookup table plus three narrow
  functions read one row.
- **Keeping the demo merchant as a fallback without sign-in.** A setting that quietly opens all data is the kind that
  ends up on in production.

## 4. Limits

- Rate limits are counted per API process. A deployment with several processes needs a shared counter.
- No password reset by email (no mail service). An operator can add an account to a business with
  `python -m app.accounts add-user`.
- Authenticator secrets are stored as written, protected by RLS and database access. Encrypting them with a key held
  outside the database is the next step.
- One person per business so far. Roles inside a business (viewer, approver) are not built.
- The PayPal sandbox account is configured once, for the demo merchant. A new business signs in to empty screens.
