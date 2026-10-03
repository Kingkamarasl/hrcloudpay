# Milestone 49 — Knowledge Center & AI Experience 2.0

HRCloudPay now exposes AI knowledge as a first-class workspace instead of keeping document management inside the chatbot.

## Delivered
- Dedicated `/knowledge` Knowledge Center.
- Search and lifecycle filtering.
- Active, processing, failed and archived states.
- Version and chunk visibility.
- Role-aware access badges.
- PDF/DOCX upload and indexing workflow.
- Archive, restore and reindex actions.
- Document detail drawer with processing metadata.
- Dashboard navigation renamed to AI Copilot / Knowledge Center.

## Security
All existing company scoping and role checks remain enforced by Django. AI retrieval continues to use active documents and allowed roles only.
