# Milestone 36 — HRCloudPay AI (NVIDIA NIM)

This milestone adds the first production-shaped HRCloudPay AI layer using NVIDIA's hosted NIM API.

## Current implementation

- Django `ai` app with tenant-scoped AI conversations and messages.
- NVIDIA hosted NIM client using the OpenAI-compatible `/v1/chat/completions` endpoint.
- Default chat model: `nvidia/nemotron-3-super-120b-a12b`. Configured in the database, not the environment — see Setup.
- React `/ai` page and sidebar navigation.
- Conversation history scoped to the authenticated company and user.
- Initial company context is deliberately limited to company name, country, plan, role and employee count.
- AI actions are not allowed to modify payroll, employee, attendance, leave or compliance records in this milestone.
- AI usage is written to the existing audit trail.

## Setup

1. Create an NVIDIA Developer account and generate an API key from NVIDIA's API Catalog.
2. Run migrations:

```bash
cd backend
python manage.py migrate
```

3. Sign in as a superuser and open **Platform admin → AI settings**. Enter the API key, then save. The key is encrypted with a key derived from Django's `SECRET_KEY` and stored in the single `AIProviderConfig` row; it is never read from the environment and never reaches React.

4. Start Django and the React development server as usual.
5. Sign in and open `/ai`. Use **Test connection** in AI settings to confirm the configured model is live before relying on it.

### Choosing a model

Model ids are **not** configured through environment variables — an earlier version of this document described `NVIDIA_API_KEY` / `NVIDIA_API_URL` / `NVIDIA_AI_MODEL`, none of which the application has ever read. Only the AI settings form and the field defaults in `ai/models.py` set them.

Verify a model before choosing it. NVIDIA's `/v1/models` catalog is not a reliable signal: several listed entries have no serving function behind them and answer HTTP 404 on a real request. The assistant also depends on **function calling**, so a model that returns prose instead of a `tool_calls` entry is not usable regardless of its catalogue listing.

## Security boundary

The NVIDIA API key is server-side only. React never receives it. Company context is assembled by Django, and conversation queries require the authenticated user's company and user.

The next AI milestone should add explicit, permission-checked HRCloudPay tools (employee lookup, leave, attendance, payroll summaries, contract expiry, etc.) rather than granting the model unrestricted database access.

## NVIDIA usage note

NVIDIA documents hosted NIM endpoints as free for Developer Program prototyping, research, development and testing. Production use serving real end users requires the applicable NVIDIA AI Enterprise licensing. See NVIDIA's current NIM FAQ before deploying customer-facing AI.
