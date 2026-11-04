-- Seller accounts, sessions and two-step sign-in (ADR-009). Run as sal_migrator. Same tenant pattern as 0001/0016.
--
-- Signing in happens before SAL knows the tenant, and every account table is behind RLS. One narrow way across:
-- login_emails maps an email's SHA-256 to its merchant and user, has no grants at all, and is reached only through
-- the two SECURITY DEFINER functions below. The password hash and everything else stay under RLS.

CREATE TABLE users (
  id                   uuid PRIMARY KEY,
  merchant_id          uuid NOT NULL REFERENCES merchants(id),
  email                text NOT NULL CHECK (char_length(email) BETWEEN 3 AND 254),
  password_hash        text NOT NULL CHECK (password_hash LIKE 'scrypt$%'),
  totp_secret          text CHECK (totp_secret ~ '^[A-Z2-7]{32}$'),      -- set when two-step sign-in is set up
  totp_enabled         boolean NOT NULL DEFAULT false,
  totp_last_step       bigint,                                           -- a code is accepted once
  failed_logins        integer NOT NULL DEFAULT 0 CHECK (failed_logins >= 0),
  locked_until         timestamptz,
  password_changed_at  timestamptz NOT NULL DEFAULT now(),
  created_at           timestamptz NOT NULL DEFAULT now(),
  UNIQUE (id, merchant_id),
  CHECK (NOT totp_enabled OR totp_secret IS NOT NULL)
);

-- SessionStage: MFA_PENDING (password right, code still owed, minutes to live), ACTIVE
CREATE TABLE user_sessions (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  merchant_id   uuid NOT NULL REFERENCES merchants(id),
  user_id       uuid NOT NULL,
  token_hash    text NOT NULL UNIQUE CHECK (token_hash ~ '^[0-9a-f]{64}$'),
  stage         text NOT NULL CHECK (stage IN ('MFA_PENDING', 'ACTIVE')),
  user_agent    text CHECK (char_length(user_agent) <= 300),
  created_at    timestamptz NOT NULL DEFAULT now(),
  last_seen_at  timestamptz NOT NULL DEFAULT now(),
  expires_at    timestamptz NOT NULL,
  revoked_at    timestamptz,
  FOREIGN KEY (user_id, merchant_id) REFERENCES users (id, merchant_id)
);
CREATE INDEX user_sessions_user_idx ON user_sessions (merchant_id, user_id) WHERE revoked_at IS NULL;

CREATE TABLE recovery_codes (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  merchant_id  uuid NOT NULL REFERENCES merchants(id),
  user_id      uuid NOT NULL,
  code_hash    text NOT NULL CHECK (code_hash ~ '^[0-9a-f]{64}$'),
  used_at      timestamptz,
  FOREIGN KEY (user_id, merchant_id) REFERENCES users (id, merchant_id)
);

ALTER TABLE users          ENABLE ROW LEVEL SECURITY; ALTER TABLE users          FORCE ROW LEVEL SECURITY;
ALTER TABLE user_sessions  ENABLE ROW LEVEL SECURITY; ALTER TABLE user_sessions  FORCE ROW LEVEL SECURITY;
ALTER TABLE recovery_codes ENABLE ROW LEVEL SECURITY; ALTER TABLE recovery_codes FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON users
  USING (merchant_id = (SELECT current_merchant_id())) WITH CHECK (merchant_id = (SELECT current_merchant_id()));
CREATE POLICY tenant_isolation ON user_sessions
  USING (merchant_id = (SELECT current_merchant_id())) WITH CHECK (merchant_id = (SELECT current_merchant_id()));
CREATE POLICY tenant_isolation ON recovery_codes
  USING (merchant_id = (SELECT current_merchant_id())) WITH CHECK (merchant_id = (SELECT current_merchant_id()));

GRANT SELECT, INSERT ON users TO sal_app;
GRANT UPDATE (password_hash, totp_secret, totp_enabled, totp_last_step, failed_logins, locked_until,
              password_changed_at) ON users TO sal_app;
GRANT SELECT, INSERT ON user_sessions TO sal_app;
GRANT UPDATE (stage, last_seen_at, expires_at, revoked_at) ON user_sessions TO sal_app;
GRANT SELECT, INSERT, DELETE ON recovery_codes TO sal_app;
GRANT UPDATE (used_at) ON recovery_codes TO sal_app;

-- ---------------------------------------------------------------- the one way across tenants
CREATE TABLE login_emails (
  email_hash   text PRIMARY KEY CHECK (email_hash ~ '^[0-9a-f]{64}$'),
  merchant_id  uuid NOT NULL REFERENCES merchants(id),
  user_id      uuid NOT NULL UNIQUE
);
REVOKE ALL ON login_emails FROM PUBLIC;   -- no runtime role reads or writes it directly

-- Which account an email belongs to. Says nothing else; the caller then reads the account under RLS.
CREATE FUNCTION auth_find_account(p_email_hash text) RETURNS TABLE (merchant_id uuid, user_id uuid)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
  SELECT l.merchant_id, l.user_id FROM login_emails l WHERE l.email_hash = p_email_hash
$$;

-- A new business. Only for the tenant the caller has already set, so it can't create one on another's behalf.
CREATE FUNCTION auth_create_merchant(p_merchant_id uuid, p_name text) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
BEGIN
  IF p_merchant_id IS DISTINCT FROM current_merchant_id() THEN
    RAISE EXCEPTION 'tenant mismatch' USING ERRCODE = 'insufficient_privilege';
  END IF;
  IF char_length(btrim(p_name)) NOT BETWEEN 1 AND 120 THEN
    RAISE EXCEPTION 'business name must be 1 to 120 characters' USING ERRCODE = 'check_violation';
  END IF;
  INSERT INTO merchants (id, name) VALUES (p_merchant_id, btrim(p_name));
END $$;

-- Make an account's email usable for signing in. The account must already exist in the caller's tenant.
CREATE FUNCTION auth_register_login(p_email_hash text, p_user_id uuid) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM users u WHERE u.id = p_user_id AND u.merchant_id = current_merchant_id()) THEN
    RAISE EXCEPTION 'no such account in this tenant' USING ERRCODE = 'insufficient_privilege';
  END IF;
  INSERT INTO login_emails (email_hash, merchant_id, user_id) VALUES (p_email_hash, current_merchant_id(), p_user_id);
END $$;

REVOKE ALL ON FUNCTION auth_find_account(text), auth_create_merchant(uuid, text), auth_register_login(text, uuid)
  FROM PUBLIC;
GRANT EXECUTE ON FUNCTION auth_find_account(text), auth_create_merchant(uuid, text), auth_register_login(text, uuid)
  TO sal_app;
