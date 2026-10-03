# Milestone 47 — AI Knowledge Document Lifecycle & Security

HRCloudPay AI knowledge now supports controlled document lifecycle management and role-based knowledge access.

## Implemented

- Active / processing / failed / archived lifecycle states.
- Document version number and version group UUID.
- Uploading a document with the same title automatically archives the previous active version and creates the next version.
- Archive and restore actions for authorized knowledge managers.
- Last indexed timestamp and processing error tracking.
- Per-document access roles: owner, admin, hr, manager, employee.
- Semantic RAG and keyword fallback now filter out archived/inactive documents.
- AI chatbot RAG retrieval respects the document's allowed roles.
- Reindexing only processes active documents.
- Audit events for document lifecycle and access-control changes.
- Dashboard knowledge panel displays version, lifecycle status, chunk count and access roles.

## Security model

Knowledge is still company/tenant scoped first. A user must belong to the company and have a role included in the document's `allowed_roles` list before the document can be retrieved by AI search/RAG.

Management remains restricted to platform-approved company HR roles (`owner`, `admin`, `hr`). Platform AI provider credentials remain centrally controlled by Platform Admin as established in Milestone 43.

## Migration

```bash
cd backend
python manage.py migrate
```

## Notes

Deleting a document remains a hard-delete action for now. Archiving should be preferred when historical traceability is required. A future retention/legal-hold phase can add immutable retention rules and object-storage lifecycle controls.
