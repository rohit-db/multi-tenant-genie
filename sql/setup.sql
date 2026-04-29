-- ============================================================
-- Multi-Tenant Genie Demo — UC objects
-- ============================================================
-- Run via: databricks sql query --profile <profile> --file setup.sql
-- OR execute statement-by-statement via the scripts/seed_demo.py bootstrapper.
-- ============================================================

-- Schema
CREATE SCHEMA IF NOT EXISTS ${catalog}.${schema}
COMMENT 'Multi-tenant Genie SP-management demo';

-- Tenant registry (admin-facing view of who exists)
CREATE TABLE IF NOT EXISTS ${catalog}.${schema}.tenants (
    tenant_id STRING NOT NULL,
    tenant_name STRING NOT NULL,
    sp_app_id STRING NOT NULL,
    sp_display_name STRING NOT NULL,
    status STRING NOT NULL,               -- active | rotating | deactivated
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL
) USING DELTA
TBLPROPERTIES (delta.enableChangeDataFeed = true)
COMMENT 'One row per onboarded client organization';

-- SP-to-tenant mapping (the row-filter join target)
-- Intentionally minimal so the row-filter query is fast.
CREATE TABLE IF NOT EXISTS ${catalog}.${schema}.sp_tenant_mapping (
    sp_app_id STRING NOT NULL,
    tenant_id STRING NOT NULL,
    active BOOLEAN NOT NULL
) USING DELTA
COMMENT 'Lookup table joined in the tenant row filter';

-- Audit log of admin + query operations (app-layer, since SP identity masks user)
CREATE TABLE IF NOT EXISTS ${catalog}.${schema}.audit_log (
    event_time TIMESTAMP NOT NULL,
    actor STRING,                         -- human admin who clicked the button
    tenant_id STRING,
    action STRING,                        -- onboard | rotate | deactivate | query
    sp_app_id STRING,
    question STRING,
    latency_ms INT,
    status STRING,
    detail STRING
) USING DELTA;

-- ============================================================
-- Row filter (Pattern A — SP-per-org)
-- ============================================================
-- session_user() returns the SP's application_id when the caller
-- authenticated via OAuth M2M. We look it up in the mapping table
-- and only keep rows whose tenant_id is allowed for that SP.
--
-- Admins (members of the ${admin_group} group) bypass the filter.
-- ============================================================
CREATE OR REPLACE FUNCTION ${catalog}.${schema}.tenant_row_filter(tenant_id STRING)
RETURN
  is_account_group_member('${admin_group}')
  OR EXISTS (
    SELECT 1
    FROM ${catalog}.${schema}.sp_tenant_mapping m
    WHERE m.sp_app_id = session_user()
      AND m.active = true
      AND m.tenant_id = tenant_row_filter.tenant_id
  );

