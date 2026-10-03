# Milestone 43 — Platform AI Configuration

All NVIDIA AI configuration is now controlled by the HRCloudPay site/platform administrator.

## Admin control center

Platform Admin → **AI / NVIDIA NIM** controls:
- NVIDIA API key
- Chat API URL
- Embeddings API URL
- Chat model
- Embedding model
- Temperature
- Max tokens
- Request timeout
- Enable/disable AI
- Connection test

Only platform superusers can read or modify these settings.

## Security

- The API key is encrypted at rest using a key derived from Django `SECRET_KEY`.
- The key is never returned to React after saving.
- Tenant/company users cannot modify provider settings.
- Configuration changes and connection tests are written to the platform audit log.
- The AI service no longer reads NVIDIA API credentials or model configuration from `.env`.

## Runtime behavior

The AI chatbot, tool calling, drafts, and semantic RAG all read the active configuration from the database. This means the site administrator can change models/endpoints without redeploying the application.

Run:

```bash
cd backend
python manage.py migrate
```
