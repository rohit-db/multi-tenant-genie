// ============================================================================
// Brand — the "your own skin" layer.
//
// This folder is the single place to rebrand the product. Swap these values
// and the --brand* CSS variables in ./theme.css and the entire customer-facing
// surface re-skins. The embedded Genie keeps its own indigo identity on
// purpose, to read as "Databricks Genie, inside your product."
// ============================================================================

export const BRAND = {
  name: "SkyDesk",
  fullName: "SkyDesk Analytics",
  tagline: "Corporate travel, intelligently analyzed.",
  // One-liner used on the marketing/login surface.
  pitch:
    "Embedded analytics for your travel program — ask questions in plain English, explore live dashboards, all on your own governed data.",
  // Honest framing for the demo: what's under the hood.
  poweredBy: "Powered by Databricks · Unity Catalog · Genie",
  accent: "#0284c7", // sky-600 — mirror of the --brand CSS var in theme.css
} as const;
