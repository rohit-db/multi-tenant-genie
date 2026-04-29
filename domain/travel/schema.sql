-- Travel-domain tables (swappable). Tenant_id is the row-filter column.
CREATE TABLE IF NOT EXISTS ${catalog}.${schema}.bookings (
    booking_id STRING NOT NULL,
    tenant_id STRING NOT NULL,
    traveler_name STRING,
    origin STRING,
    destination STRING,
    route STRING,
    supplier STRING,
    cabin_class STRING,
    amount_usd DOUBLE,
    booked_at TIMESTAMP
) USING DELTA
COMMENT 'Synthetic travel bookings, tenant-scoped via UC row filter';

CREATE TABLE IF NOT EXISTS ${catalog}.${schema}.customers (
    tenant_id STRING NOT NULL,
    customer_segment STRING,
    industry STRING,
    headquartered_in STRING,
    active_travelers INT
) USING DELTA;

ALTER TABLE ${catalog}.${schema}.bookings
  SET ROW FILTER ${catalog}.${schema}.tenant_row_filter ON (tenant_id);

ALTER TABLE ${catalog}.${schema}.customers
  SET ROW FILTER ${catalog}.${schema}.tenant_row_filter ON (tenant_id);
