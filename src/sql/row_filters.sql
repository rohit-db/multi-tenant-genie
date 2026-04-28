-- ============================================================
-- Row-Level Security for Multi-Tenant Genie
-- ============================================================
-- Apply these to all tables that contain tenant-scoped data.
-- The filter uses current_oauth_custom_identity_claims() to read
-- the tenant_id from the JWT custom claim (Pattern B).
-- ============================================================

-- Generic tenant filter function (reuse across all tables)
CREATE OR REPLACE FUNCTION main.analytics.tenant_filter(tenant_id STRING)
RETURN IF(
    tenant_id = current_oauth_custom_identity_claims()
    OR is_account_group_member('admin'),
    true, false
);

-- Apply to tables
ALTER TABLE main.analytics.orders
SET ROW FILTER main.analytics.tenant_filter ON (tenant_id);

ALTER TABLE main.analytics.customers
SET ROW FILTER main.analytics.tenant_filter ON (tenant_id);

ALTER TABLE main.analytics.products
SET ROW FILTER main.analytics.tenant_filter ON (tenant_id);

ALTER TABLE main.analytics.transactions
SET ROW FILTER main.analytics.tenant_filter ON (tenant_id);


-- ============================================================
-- Alternative: Pattern A (SP-per-client) using session_user()
-- ============================================================

-- Mapping table: SP application_id → tenant_id
-- CREATE TABLE main.analytics.sp_tenant_mapping (
--     sp_application_id STRING NOT NULL,
--     tenant_id STRING NOT NULL
-- );
--
-- CREATE OR REPLACE FUNCTION main.analytics.sp_tenant_filter(tenant_id STRING)
-- RETURN IF(
--     EXISTS (
--         SELECT 1 FROM main.analytics.sp_tenant_mapping
--         WHERE sp_application_id = session_user()
--         AND tenant_id = sp_tenant_filter.tenant_id
--     )
--     OR is_account_group_member('admin'),
--     true, false
-- );


-- ============================================================
-- Column masking (optional — for sensitive fields)
-- ============================================================

-- CREATE OR REPLACE FUNCTION main.analytics.mask_email(
--     email STRING, tenant_id STRING
-- )
-- RETURN IF(
--     tenant_id = current_oauth_custom_identity_claims(),
--     email,
--     '***@***.com'
-- );
--
-- ALTER TABLE main.analytics.customers
-- SET COLUMN MASK main.analytics.mask_email ON (email) USING COLUMNS (tenant_id);


-- ============================================================
-- Verification queries
-- ============================================================

-- Run with a custom-claims token to verify:
-- SELECT current_oauth_custom_identity_claims() AS my_claim;
-- SELECT COUNT(*) FROM main.analytics.orders;  -- should show only your tenant's rows
-- SELECT * FROM main.analytics.orders LIMIT 10;
