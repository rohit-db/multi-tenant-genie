# Swappable Domain Layer

The active demo domain is selected by the `DOMAIN` env var (default: `travel`).

## To add a new domain

1. Copy `domain/travel/` to `domain/<your-name>/`.
2. Edit `schema.sql` to declare the tables Genie will query.
3. Edit `seed.py` to populate synthetic data per tenant.
4. Edit `sample_questions.json` with prompts that fit your schema.
5. Set `DOMAIN=<your-name>` in `.env.local` (local dev) or `app.yaml` (production).

The proxy and UI never reference your domain's table names directly — they
fetch sample questions and the row-filter column via the API.
