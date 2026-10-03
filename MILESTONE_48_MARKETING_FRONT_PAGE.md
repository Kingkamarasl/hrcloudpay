# Milestone 48 — Marketing Front Page & Product Positioning

HRCloudPay's public homepage has been refreshed to market the current product as an integrated **People + Payroll + AI + Knowledge + Compliance** platform.

## Purpose

The previous homepage primarily introduced HR and payroll functionality. As HRCloudPay has gained AI, Employee 360°, document intelligence, knowledge retrieval, security, audit, and compliance capabilities, the public site now communicates those capabilities as one product story.

## Homepage messaging

### Hero

The hero positions HRCloudPay as:

> The intelligent operating system for people, payroll & HR

The default supporting message explains that payroll, Employee 360°, attendance, leave, compliance, documents, and the AI HR assistant live in one secure workspace.

The primary conversion path is **Start for free** and the secondary path is **Explore the platform**.

The hero also contains a product-style workspace preview showing:

- workforce metrics
- payroll readiness
- HRCloud AI availability
- company-knowledge context
- payroll overview
- a conversational HR knowledge example
- a verified source indicator

## Core marketing pillars

The homepage now presents six product pillars:

1. **Payroll** — company-specific pay rules, review stages, statutory configuration, and approval history.
2. **Employee 360°** — contracts, documents, warnings, attendance, leave, employment status, and history.
3. **AI HR assistant** — role-aware HR questions with company knowledge and citations.
4. **Document intelligence** — extraction, organization, indexing, and page/section-aware document search.
5. **Compliance & audit** — role-aware access, audit events, and compliance evidence.
6. **Connected operations** — integrations, reporting, multi-country workflows, and future automation foundations.

## AI marketing section

The homepage explains four safe AI workflows:

- **Ask** — natural-language questions about permitted HR information.
- **Find** — retrieval from approved company knowledge.
- **Cite** — source context for knowledge-grounded answers.
- **Draft** — AI-assisted HR document drafts that remain subject to human review.

The messaging deliberately avoids presenting AI as an unrestricted decision-maker. Permissions, tenant boundaries, deterministic HR tools, source grounding, and human review remain part of the product story.

## Document intelligence positioning

The homepage highlights the document workflow introduced through Milestones 45–47:

- PDF/DOCX extraction
- OCR support
- page and section metadata
- semantic indexing
- company knowledge retrieval
- document versions
- lifecycle states
- role-based access
- archive/restore
- reindexing

The marketing visual demonstrates an active document version and knowledge status without exposing real customer data.

## Employee 360° positioning

Employee 360° is presented as an operational employee record rather than a display-only profile. The marketing language covers:

- employee information
- contracts
- HR documents
- warning letters
- attendance
- leave
- employment status
- employment history
- related operational activity

## Audience messaging

The homepage includes audience-specific value propositions for:

- **Founders & leaders** — workforce visibility and operational signals.
- **HR & People teams** — employee records, policies, documents, leave, attendance, and workflows.
- **Finance teams** — payroll preparation, review, approval, payment evidence, and reconciliation.
- **Managers & employees** — focused, role-appropriate information and actions.

## Product onboarding story

The homepage uses a three-step narrative:

1. **Set up your company** — country context, currency, pay frequency, statutory configuration, roles, and access rules.
2. **Bring your people and knowledge** — employees, contracts, HR documents, policies, and company knowledge.
3. **Run payroll and HR together** — payroll, attendance, leave, documents, approvals, compliance, and self-service.

## Platform Admin marketing content

The homepage continues to support the existing managed marketing-page system. The hero can be supplied by the platform's marketing-page API, while the frontend maintains safe defaults so the public page remains usable if the API is unavailable.

This preserves the existing Platform Admin marketing content workflow rather than hard-coding every campaign message into the frontend.

## SEO and conversion

The homepage refresh is designed around:

- clear product positioning above the fold
- feature-led discovery
- AI differentiation
- trust/security messaging
- audience segmentation
- strong registration CTA
- links into platform, security, and product experiences
- concise language suitable for search snippets and social sharing

## Design direction

The page keeps the established HRCloudPay premium marketing system while adding product UI previews, AI visuals, feature cards, trust signals, and responsive layouts. The visual language is intended to feel like a modern B2B SaaS product rather than a generic corporate website.

## Important implementation notes

- Marketing copy must not imply that AI can independently approve payroll, terminate employees, change salaries, or perform other sensitive HR actions.
- Customer-specific information is not used in marketing visuals.
- AI claims should remain consistent with the implemented permission, tenant-isolation, citation, lifecycle, and human-review controls.
- The homepage should be reviewed whenever major product capabilities change so that the public marketing promise stays aligned with the actual product.

## Validation

The Milestone 48 source bundle was updated with the marketing homepage implementation and this documentation.

For a normal development environment, validate with:

```bash
cd frontend
npm ci
npm run build
```

If the backend is included in the deployment:

```bash
cd backend
python manage.py check
python manage.py test
```
