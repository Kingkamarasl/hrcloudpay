"""Safe, non-mutating AI-assisted HR document drafting."""
from .nvidia import chat, NVIDIAError

ALLOWED_ACTIONS = {
    'employment_letter': 'Draft a professional employment confirmation letter. Do not invent dates, salary, title, or legal claims; use placeholders for missing facts.',
    'warning_letter': 'Draft a neutral workplace warning-letter template. Do not assert misconduct as fact; use placeholders and recommend HR review.',
    'payroll_explanation': 'Draft a plain-language explanation of a payroll result using only the supplied verified figures. Do not recalculate or invent numbers.',
    'hr_report': 'Draft a concise HR report from the supplied verified data. Clearly label missing information and avoid unsupported conclusions.',
}


def draft_action(action_type, context):
    instruction = ALLOWED_ACTIONS.get(action_type)
    if not instruction:
        raise ValueError('Unsupported draft type.')
    if not isinstance(context, str) or len(context.strip()) > 12000:
        raise ValueError('Context is required and must be at most 12,000 characters.')
    prompt = f"{instruction}\n\nVerified context supplied by HRCloudPay:\n{context.strip()}\n\nReturn only the draft text."
    return chat([{'role': 'system', 'content': 'You are HRCloudPay AI. Draft only; never claim to have saved, sent, approved, or changed anything.'}, {'role': 'user', 'content': prompt}], max_tokens=1800)
