// Step-up MFA challenge for sensitive actions.
//
// Approving a payroll run, recording payment, or approving a salary change is
// refused by the backend with 403 and a `code: "mfa_required"` body until the
// current session has cleared a TOTP challenge recently. `withStepUp` turns
// that refusal into a one-time code prompt and replays the original request
// once, so those call sites stay a single ordinary `api.post(...)`.

import { api } from '../api/client';

export const MFA_STEP_UP_ENDPOINT = '/auth/security/mfa/step-up/';

function isStepUpRequired(error) {
  return Boolean(
    error &&
    error.status === 403 &&
    error.data &&
    error.data.code === 'mfa_required',
  );
}

function enrolmentRequired(error) {
  return Boolean(error?.data?.enrollment_required);
}

// Module-level so nested calls (a page firing two guarded actions) share one
// prompt instead of stacking dialogs.
let activePrompt = null;

function promptForCode(enrolmentNeeded) {
  if (activePrompt) return activePrompt;

  activePrompt = new Promise((resolve) => {
    const message = enrolmentNeeded
      ? 'This action needs two-factor authentication. Enable MFA in Security settings, then try again.'
      : 'Enter the 6-digit code from your authenticator app to confirm this action.';

    let input;
    const backdrop = document.createElement('div');
    backdrop.className = 'modal-overlay';
    backdrop.setAttribute('role', 'dialog');
    backdrop.setAttribute('aria-modal', 'true');
    backdrop.setAttribute('aria-label', 'Confirm with MFA');

    backdrop.innerHTML = `
      <div className="modal-content" style="max-width:26rem">
        <div className="modal-head">
          <h2>Confirm this action</h2>
        </div>
        <div className="modal-body">
          <p class="step-up-message">${message}</p>
          ${enrolmentNeeded ? '' : '<label class="field-label" for="mfa-step-up-code">Authentication code</label><input id="mfa-step-up-code" class="input" inputmode="numeric" autocomplete="one-time-code" maxlength="6" placeholder="000000" />'}

          <p class="step-up-error" role="alert" hidden></p>
        </div>
        <div class="modal-foot">
          <button type="button" class="btn btn-ghost" data-step-up="cancel">Cancel</button>
          ${enrolmentNeeded ? '' : '<button type="button" class="btn btn-primary" data-step-up="confirm">Confirm</button>'}

        </div>
      </div>`;

    const close = (value) => {
      backdrop.remove();
      activePrompt = null;
      resolve(value);
    };

    backdrop.addEventListener('mousedown', (event) => {
      if (event.target === backdrop) close(null);
    });
    backdrop.querySelector('[data-step-up="cancel"]').addEventListener('click', () => close(null));

    const errorLine = backdrop.querySelector('.step-up-error');
    const submit = async () => {
      const code = (input?.value || '').trim();
      if (!/^\d{6}$/.test(code)) {
        errorLine.textContent = 'Enter the 6-digit code from your authenticator app.';
        errorLine.hidden = false;
        return;
      }
      try {
        await api.post(MFA_STEP_UP_ENDPOINT, { code });
        close('confirmed');
      } catch (err) {
        errorLine.textContent = err?.message || 'That code was not accepted.';
        errorLine.hidden = false;
        if (input) input.value = '';
      }
    };

    const confirmButton = backdrop.querySelector('[data-step-up="confirm"]');
    if (confirmButton) {
      confirmButton.addEventListener('click', submit);
      if (input) {
        input.addEventListener('keydown', (event) => {
          if (event.key === 'Enter') submit();
        });
        setTimeout(() => input.focus(), 0);
      }
    } else {
      // Enrollment required: only "understood" is possible, so the modal is
      // purely informational and resolves to a cancellation.
      close(null);
    }

    document.body.appendChild(backdrop);
  });

  return activePrompt;
}

/**
 * Run `action`; if the backend demands a fresh MFA challenge, prompt for a code
 * and retry once. Throws the original error if the user cancels or the code is
 * refused, so callers still surface a real failure.
 */
export async function withStepUp(action) {
  try {
    return await action();
  } catch (error) {
    if (!isStepUpRequired(error)) throw error;

    const result = await promptForCode(enrolmentRequired(error));
    if (result !== 'confirmed') throw error;

    return action();
  }
}
