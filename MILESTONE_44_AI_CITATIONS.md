# Milestone 44 — AI Knowledge Citations in Chat

HRCloudPay AI now integrates tenant-scoped semantic knowledge retrieval directly into the normal dashboard chatbot response flow.

## What changed

- Chat retrieval prefers NVIDIA embeddings and falls back to keyword retrieval when embeddings are unavailable.
- Only active knowledge belonging to the authenticated user's company is retrieved.
- Retrieved knowledge is numbered (`[1]`, `[2]`, etc.) and supplied to NVIDIA with explicit citation instructions.
- Assistant messages persist citation metadata and source snippets.
- The dashboard chatbot renders a Sources section beneath answers that used company knowledge.
- Existing verified HRCloudPay tool results remain separate from knowledge citations.
- AIMessage now stores extensible JSON metadata for future tool/citation telemetry.

## Security

- No cross-company knowledge retrieval.
- Knowledge is still read-only.
- The AI provider configuration remains controlled centrally by Platform Admin.
- Source snippets are limited before being returned to the browser.

## Migration

```bash
cd backend
python manage.py migrate
```

## Frontend

The chatbot displays citations inline when the model references company knowledge. A production frontend build should be run in the normal development environment after installing the project's npm dependencies.
