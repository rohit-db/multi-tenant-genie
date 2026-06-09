-- ============================================================
-- App-level users — the thin authentication layer that gates the
-- customer-facing product. This is the SaaS's OWN user directory
-- (distinct from Databricks workspace identity); each user maps to a
-- default tenant context and a role (user | operator).
-- ============================================================

CREATE TABLE app_users (
    id SERIAL PRIMARY KEY,
    email VARCHAR(255) UNIQUE NOT NULL,
    -- pbkdf2_sha256$<iterations>$<salt_b64>$<hash_b64>
    password_hash TEXT NOT NULL,
    display_name VARCHAR(255) NOT NULL,
    -- Default tenant context. NULL for operators (back-office, all tenants).
    tenant_id VARCHAR(255),
    role VARCHAR(50) NOT NULL DEFAULT 'user',   -- user | operator
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_login_at TIMESTAMPTZ
);

CREATE INDEX idx_app_users_email ON app_users(email);
CREATE INDEX idx_app_users_tenant ON app_users(tenant_id);
