// Curated, deterministic "dashboards" for the Genie space — the equivalent of
// the saved/curated content a real Genie space surfaces. Every tile is plain
// SQL executed as the tenant Service Principal (UC row filter applies), so the
// numbers are provably tenant-scoped with no model in the loop.

export interface DashboardTile {
  title: string;
  description?: string;
  sql: string;
  /** Grid span on wide screens. */
  wide?: boolean;
}

export interface DashboardDef {
  id: string;
  title: string;
  description: string;
  /** lucide icon name resolved in the component. */
  icon: "gauge" | "route" | "building";
  tiles: DashboardTile[];
}

/**
 * Build the travel-domain dashboards for a fully-qualified `catalog.schema`.
 */
export function buildDashboards(fq: string): DashboardDef[] {
  const bookings = `${fq}.bookings`;
  return [
    {
      id: "overview",
      title: "Travel overview",
      description: "Headline KPIs, monthly trend, and cabin mix.",
      icon: "gauge",
      tiles: [
        {
          title: "Key metrics",
          wide: true,
          sql: `SELECT
  COUNT(*) AS bookings,
  ROUND(SUM(amount_usd), 0) AS total_spend_usd,
  ROUND(AVG(amount_usd), 0) AS avg_booking_usd,
  COUNT(DISTINCT traveler_name) AS travelers
FROM ${bookings}`,
        },
        {
          title: "Bookings + spend over time",
          description: "Monthly trend.",
          wide: true,
          sql: `SELECT DATE_FORMAT(booked_at, 'yyyy-MM') AS month,
       COUNT(*) AS bookings,
       ROUND(SUM(amount_usd), 0) AS spend_usd
FROM ${bookings}
GROUP BY DATE_FORMAT(booked_at, 'yyyy-MM')
ORDER BY month`,
        },
        {
          title: "Cabin class mix",
          description: "Share of bookings by cabin.",
          sql: `SELECT cabin_class, COUNT(*) AS bookings
FROM ${bookings}
GROUP BY cabin_class
ORDER BY bookings DESC`,
        },
        {
          title: "Bookings by route",
          description: "Top routes by volume.",
          sql: `SELECT route, COUNT(*) AS bookings
FROM ${bookings}
GROUP BY route
ORDER BY bookings DESC
LIMIT 8`,
        },
      ],
    },
    {
      id: "routes",
      title: "Routes & spend",
      description: "Where the travel budget goes.",
      icon: "route",
      tiles: [
        {
          title: "Top routes by spend",
          wide: true,
          sql: `SELECT route, ROUND(SUM(amount_usd), 0) AS spend_usd
FROM ${bookings}
GROUP BY route
ORDER BY spend_usd DESC
LIMIT 10`,
        },
        {
          title: "Top travelers by spend",
          sql: `SELECT traveler_name, ROUND(SUM(amount_usd), 0) AS spend_usd
FROM ${bookings}
GROUP BY traveler_name
ORDER BY spend_usd DESC
LIMIT 8`,
        },
        {
          title: "Avg booking by cabin",
          sql: `SELECT cabin_class, ROUND(AVG(amount_usd), 0) AS avg_usd
FROM ${bookings}
GROUP BY cabin_class
ORDER BY avg_usd DESC`,
        },
      ],
    },
    {
      id: "suppliers",
      title: "Suppliers",
      description: "Supplier concentration and spend.",
      icon: "building",
      tiles: [
        {
          title: "Top suppliers by bookings",
          wide: true,
          sql: `SELECT supplier, COUNT(*) AS bookings, ROUND(SUM(amount_usd), 0) AS spend_usd
FROM ${bookings}
GROUP BY supplier
ORDER BY bookings DESC
LIMIT 8`,
        },
        {
          title: "Supplier spend share",
          sql: `SELECT supplier, ROUND(SUM(amount_usd), 0) AS spend_usd
FROM ${bookings}
GROUP BY supplier
ORDER BY spend_usd DESC
LIMIT 6`,
        },
      ],
    },
  ];
}
