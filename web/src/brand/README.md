# `brand/` — re-skin in one folder

The white-label layer. To turn this reference app into *your* product, edit
only the files here — nothing else in `web/src` hardcodes a brand.

| File | What to change |
|---|---|
| [`brand.ts`](brand.ts) | Product name, tagline, marketing pitch, "powered by" line, accent hex. |
| [`theme.css`](theme.css) | The four `--brand*` CSS variables (accent, strong, soft, foreground). Loaded from `main.tsx`. |
| [`BrandMark.tsx`](BrandMark.tsx) | The logo glyph. Swap the SVG for your mark. |

Everything imports from `@/brand`:

```ts
import { BRAND, BrandMark } from "@/brand";
```

Design note: the **embedded Genie** surface intentionally keeps Databricks'
own identity, so it reads as "Databricks Genie, inside your product." Only the
shell, login, and marketing surfaces consume `BRAND` / `--brand*`.
