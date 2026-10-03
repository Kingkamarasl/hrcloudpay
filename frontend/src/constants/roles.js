/**
 * The company role vocabulary, mirroring `accounts.models.ROLE_CHOICES`.
 *
 * This list previously said 'manager' - a role no user can hold - and omitted the
 * real 'finance' and 'department_manager' roles. That made it impossible to grant
 * a department manager access to a knowledge document, and hid the Knowledge
 * Center nav link from every real manager. Keep it in step with the backend.
 */
export const COMPANY_ROLES = [
  'owner',
  'admin',
  'hr',
  'finance',
  'department_manager',
  'employee',
];

/** Friendly labels for the access checkboxes. */
export const ROLE_LABELS = {
  owner: 'Owner',
  admin: 'Admin',
  hr: 'HR manager',
  finance: 'Finance manager',
  department_manager: 'Department manager',
  employee: 'Employee',
};

/** Roles that may manage company knowledge documents. */
export const KNOWLEDGE_MANAGER_ROLES = ['owner', 'admin', 'hr'];

/** Roles that may generate, read and review AI drafts. */
export const DRAFT_MANAGER_ROLES = ['owner', 'admin', 'hr', 'finance'];

export const hasRole = (role, allowed) => Boolean(role) && allowed.includes(role);

export const canManageKnowledge = (role) => hasRole(role, KNOWLEDGE_MANAGER_ROLES);

export const canManageDrafts = (role) => hasRole(role, DRAFT_MANAGER_ROLES);
