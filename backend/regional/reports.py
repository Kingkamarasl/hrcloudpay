"""Country-specific statutory report definitions and row builders."""
from decimal import Decimal

COUNTRY_REPORTS = {
    'NG': [
        {'code':'ng_paye_monthly','name':'Nigeria PAYE Monthly Employee Schedule','authority':'Relevant State Internal Revenue Service','format':'xlsx','filing_code':'paye'},
        {'code':'ng_pension','name':'Nigeria Pension Contribution Schedule','authority':'PENCOM / PFA','format':'xlsx','filing_code':'pension'},
    ],
    'GH': [
        {'code':'gh_paye_dt107a','name':'Ghana PAYE Employee Schedule (DT 107A mapping)','authority':'Ghana Revenue Authority','format':'xlsx','filing_code':'paye'},
        {'code':'gh_ssnit','name':'Ghana SSNIT Contribution Schedule','authority':'SSNIT','format':'xlsx','filing_code':'ssnit'},
    ],
    'SL': [
        {'code':'sl_paye_monthly','name':'Sierra Leone PAYE Monthly Schedule','authority':'National Revenue Authority','format':'xlsx','filing_code':'paye'},
        {'code':'sl_nassit','name':'Sierra Leone NASSIT Contribution Schedule (SS4A mapping)','authority':'NASSIT','format':'xlsx','filing_code':'nassit'},
    ],
    'LR': [
        {'code':'lr_paye_withholding','name':'Liberia Payroll Withholding Schedule','authority':'Liberia Revenue Authority','format':'xlsx','filing_code':'paye'},
        {'code':'lr_nasscorp','name':'Liberia NASSCORP Payroll Contribution Schedule','authority':'NASSCORP','format':'xlsx','filing_code':'nasscorp_nps'},
    ],
    'GM': [
        {'code':'gm_paye','name':'The Gambia PAYE Payroll Schedule','authority':'Gambia Revenue Authority','format':'xlsx','filing_code':'paye'},
        {'code':'gm_npf','name':'The Gambia NPF Contribution Schedule','authority':'SSHFC','format':'xlsx','filing_code':'npf'},
        {'code':'gm_fps','name':'The Gambia FPS Contribution Schedule','authority':'SSHFC','format':'xlsx','filing_code':'fps'},
        {'code':'gm_iicf','name':'The Gambia IICF Contribution Schedule','authority':'SSHFC','format':'xlsx','filing_code':'iicf'},
    ],
}


def _identifier(employee, *keys):
    profile = getattr(employee, 'statutory_profile', None)
    ids = getattr(profile, 'identifiers', {}) if profile else {}
    for key in keys:
        value = ids.get(key)
        if value not in (None, ''):
            return value
    return ''


def report_rows(report_code, payroll_run):
    try:
        country = payroll_run.company.country_profile.country_code
    except Exception:
        raise ValueError('Company country profile is not configured.')
    rows = []
    for payslip in payroll_run.payslips.select_related('employee', 'employee__statutory_profile').all():
        e = payslip.employee
        statutory = getattr(e, 'statutory_profile', None)
        ids = getattr(statutory, 'identifiers', {}) if statutory else {}
        breakdown = payslip.breakdown or {}
        contributions = {str(x.get('code')): x for x in (breakdown.get('statutory_contributions') or [])}
        paye = Decimal(str(payslip.tax_amount or 0))
        row = {
            'employee_code': e.employee_code,
            'employee_name': e.full_name,
            'id_card_no': e.id_card_no or '',
            'tax_id': _identifier(e, 'tin', 'tax_id'),
            'gross_salary': payslip.gross_salary,
            'base_salary': payslip.base_salary,
            'paye': paye,
            'tax_region': getattr(statutory, 'tax_region', '') if statutory else '',
            'bank_name': getattr(statutory, 'bank_name', '') if statutory else '',
            'account_number': e.bank_account_number or '',
            'country': country,
        }
        if report_code.startswith('ng_'):
            row.update(tin=_identifier(e,'tin'), nin=_identifier(e,'nin'), pension_pin=_identifier(e,'pension_pin'), pfa=_identifier(e,'pfa'), employee_pension=_share(contributions,'pension','employee_share'), employer_pension=_share(contributions,'pension','employer_share'))
        elif report_code.startswith('gh_'):
            row.update(tin=_identifier(e,'tin'), ghana_card=_identifier(e,'ghana_card'), ssnit_number=_identifier(e,'ssnit'), employee_ssnit=_share(contributions,'ssnit','employee_share'), employer_ssnit=_share(contributions,'ssnit','employer_share'), tier2=_share(contributions,'tier2','employee_share'), tier3=_share(contributions,'tier3','employee_share'))
        elif report_code.startswith('sl_'):
            row.update(tin=_identifier(e,'tin'), nin=_identifier(e,'nin'), nassit_number=_identifier(e,'nassit'), employee_nassit=_share(contributions,'nassit','employee_share'), employer_nassit=_share(contributions,'nassit','employer_share'))
        elif report_code.startswith('lr_'):
            row.update(tin=_identifier(e,'tin'), national_id=_identifier(e,'national_id'), nasscorp_number=_identifier(e,'nasscorp'), employee_nps=_share(contributions,'nasscorp_nps','employee_share'), employer_nps=_share(contributions,'nasscorp_nps','employer_share'), employer_eis=_share(contributions,'nasscorp_eis','employer_share'))
        elif report_code.startswith('gm_'):
            row.update(tin=_identifier(e,'tin'), national_id=_identifier(e,'national_id'), sshfc_number=_identifier(e,'sshfc'), npf_employee=_share(contributions,'npf','employee_share'), npf_employer=_share(contributions,'npf','employer_share'), fps_employer=_share(contributions,'fps','employer_share'), iicf_employer=_share(contributions,'iicf','employer_share'))
        rows.append(row)
    return rows


def _share(contributions, code, key):
    line = contributions.get(code)
    if not line:
        return Decimal('0.00')
    return Decimal(str(line.get(key, '0')))


def columns(report_code):
    common = [('employee_code','Employee Code'),('employee_name','Employee Name'),('gross_salary','Gross Salary'),('base_salary','Basic/Base Salary'),('paye','PAYE')]
    if report_code == 'ng_paye_monthly': return common + [('tin','TIN'),('nin','NIN'),('tax_region','Tax State'),('bank_name','Bank'),('account_number','Account Number')]
    if report_code == 'ng_pension': return [('employee_code','Employee Code'),('employee_name','Employee Name'),('pension_pin','Pension PIN'),('pfa','PFA'),('base_salary','Monthly Emoluments'),('employee_pension','Employee Pension'),('employer_pension','Employer Pension')]
    if report_code == 'gh_paye_dt107a': return common + [('tin','TIN'),('ghana_card','Ghana Card'),('tax_region','Tax Region'),('employee_ssnit','Employee SSNIT')]
    if report_code == 'gh_ssnit': return [('employee_code','Employee Code'),('employee_name','Employee Name'),('ssnit_number','SSNIT Number'),('base_salary','Basic Salary'),('employee_ssnit','Employee 5.5%'),('employer_ssnit','Employer 13%')]
    if report_code == 'sl_paye_monthly': return common + [('tin','TIN'),('nassit_number','NASSIT Number'),('tax_region','Tax Region')]
    if report_code == 'sl_nassit': return [('employee_code','Staff Number'),('employee_name','Full Name'),('nassit_number','Social Security Number'),('base_salary','Salary/Earnings'),('employee_nassit','Employee 5%'),('employer_nassit','Employer 10%')]
    if report_code == 'lr_paye_withholding': return common + [('tin','TIN'),('national_id','National ID'),('tax_region','Tax Region')]
    if report_code == 'lr_nasscorp': return [('employee_code','Staff Number'),('employee_name','Employee Name'),('nasscorp_number','NASSCORP Number'),('gross_salary','Earnings'),('employee_nps','Employee NPS 4%'),('employer_nps','Employer NPS 4%'),('employer_eis','Employer EIS 2%')]
    if report_code == 'gm_paye': return common + [('tin','TIN'),('national_id','National ID'),('tax_region','Region')]
    if report_code == 'gm_npf': return [('employee_code','Staff Number'),('employee_name','Employee Name'),('sshfc_number','Social Security Number'),('base_salary','Basic Salary'),('npf_employee','Employee 5%'),('npf_employer','Employer 10%')]
    if report_code == 'gm_fps': return [('employee_code','Staff Number'),('employee_name','Employee Name'),('sshfc_number','Social Security Number'),('gross_salary','Gross Salary'),('fps_employer','Employer FPS 15%')]
    if report_code == 'gm_iicf': return [('employee_code','Staff Number'),('employee_name','Employee Name'),('sshfc_number','Social Security Number'),('gross_salary','Gross Salary'),('iicf_employer','Employer IICF')]
    raise ValueError('Unknown statutory report')
