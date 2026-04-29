-- ============================================================
-- Lakebase (PostgreSQL) Schema for Multi-Tenant Genie Proxy
-- ============================================================

-- Client Registry
CREATE TABLE client_registry (
    id SERIAL PRIMARY KEY,
    tenant_id VARCHAR(255) UNIQUE NOT NULL,
    display_name VARCHAR(255) NOT NULL,
    sp_app_id VARCHAR(255) UNIQUE NOT NULL,
    sp_display_name VARCHAR(255) NOT NULL,
    genie_space_id VARCHAR(255),                      -- NULL → use workspace global
    tier VARCHAR(50) DEFAULT 'standard',
    rate_limit_per_min INTEGER DEFAULT 3,
    status VARCHAR(50) NOT NULL DEFAULT 'active',     -- active | rotating | deactivated
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- SP Credentials (encrypted with AES-256-GCM)
CREATE TABLE sp_credentials (
    id SERIAL PRIMARY KEY,
    label VARCHAR(255) UNIQUE NOT NULL,           -- e.g., 'genie-shared-sp'
    client_id_encrypted TEXT NOT NULL,
    client_secret_encrypted TEXT NOT NULL,
    workspace_url VARCHAR(500) NOT NULL,
    is_admin BOOLEAN DEFAULT false,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Audit Log
CREATE TABLE audit_log (
    id BIGSERIAL PRIMARY KEY,
    tenant_id VARCHAR(255) NOT NULL,
    client_ip INET,
    question TEXT NOT NULL,
    genie_space_id VARCHAR(255),
    genie_conversation_id VARCHAR(255),
    genie_message_id VARCHAR(255),
    status VARCHAR(50) NOT NULL,                  -- pending, completed, failed, rate_limited
    latency_ms INTEGER,
    rows_returned INTEGER,
    error_message TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Token Cache (optional — for multi-instance deployments)
-- For single-instance, use in-memory cache instead
CREATE TABLE token_cache (
    tenant_id VARCHAR(255) PRIMARY KEY,
    access_token TEXT NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes
CREATE INDEX idx_client_registry_status ON client_registry(status);
CREATE INDEX idx_client_registry_sp_app ON client_registry(sp_app_id);
CREATE INDEX idx_client_tenant ON client_registry(tenant_id);
CREATE INDEX idx_audit_tenant_time ON audit_log(tenant_id, created_at DESC);
CREATE INDEX idx_audit_created ON audit_log(created_at DESC);
CREATE INDEX idx_audit_status ON audit_log(status);
CREATE INDEX idx_token_expires ON token_cache(expires_at);

-- Updated_at trigger
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER client_registry_updated_at
    BEFORE UPDATE ON client_registry
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();
