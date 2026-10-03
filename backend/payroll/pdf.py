from io import BytesIO
from decimal import Decimal

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

LABEL_BG = colors.HexColor('#eef2ff')
BOX_BORDER = colors.HexColor('#94a3b8')
SECTION_BG = colors.HexColor('#1e3a8a')
TOTAL_BG = colors.HexColor('#dcfce7')
NET_PAY_BG = colors.HexColor('#0f766e')


def _money(value):
    return f"{Decimal(str(value or 0)):,.2f}"


def build_payslip_pdf(payslip, copy_label='EMPLOYEE COPY'):
    """
    Payslip laid out as a two-column boxed statement: company/employee
    header grid, side-by-side EARNINGS and DEDUCTIONS boxes with an
    Hrs./Units column, a highlighted NET PAY bar, and CURRENT PERIOD /
    ADDITIONAL INFO boxes with a signature line - the standard shape
    used on payslips across the region, populated entirely from this
    company's own data (nothing hardcoded to one employer or country).
    """
    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer, pagesize=A4,
        rightMargin=16 * mm, leftMargin=16 * mm, topMargin=14 * mm, bottomMargin=14 * mm,
    )
    styles = getSampleStyleSheet()
    copy_style = ParagraphStyle(
        'CopyBanner', parent=styles['Normal'], fontSize=10, alignment=1,
        textColor=colors.HexColor('#b45309'), spaceAfter=6,
    )
    small = ParagraphStyle('Small', parent=styles['Normal'], fontSize=8, textColor=colors.HexColor('#64748b'))

    employee = payslip.employee
    company = payslip.payroll_run.company
    breakdown = payslip.breakdown if isinstance(payslip.breakdown, dict) else {}
    currency = breakdown.get('currency', '') or ''
    contract = employee.current_contract
    employment_type = contract.get_contract_type_display() if contract else employee.get_employment_status_display()

    story = []
    from accounts.pdf_utils import company_logo_image
    logo = company_logo_image(company)
    if logo is not None:
        story.append(logo)
    story.append(Paragraph(company.name, styles['Title']))
    if getattr(company, 'address', '') or getattr(company, 'country', ''):
        story.append(Paragraph(' — '.join(filter(None, [company.address, company.country])), styles['Normal']))
    story += [Paragraph(copy_label, copy_style), Spacer(1, 4)]

    header_rows = [
        ['Co. Name', company.name, 'Co. Address', getattr(company, 'address', '') or '-', 'Payment Dt.', str(payslip.payroll_run.period_end)],
        ['Emp Code', employee.employee_code, 'Pay Point', employee.pay_point or '-', '', ''],
        ['Emp Name', employee.full_name, 'Department', employee.effective_department or '-', 'Statutory No', getattr(employee, 'id_card_no', '') or '-'],
        ['Emp Address', employee.email, 'Position', employee.job_title or '-', 'Basic Salary', _money(payslip.base_salary)],
        ['National ID', employee.id_card_no or '-', 'Type', employment_type, '', ''],
    ]
    header_table = Table(header_rows, colWidths=[24 * mm, 42 * mm, 24 * mm, 42 * mm, 24 * mm, 24 * mm])
    header_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), LABEL_BG),
        ('BACKGROUND', (2, 0), (2, -1), LABEL_BG),
        ('BACKGROUND', (4, 0), (4, -1), LABEL_BG),
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTNAME', (2, 0), (2, -1), 'Helvetica-Bold'),
        ('FONTNAME', (4, 0), (4, -1), 'Helvetica-Bold'),
        ('GRID', (0, 0), (-1, -1), 0.4, BOX_BORDER),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('PADDING', (0, 0), (-1, -1), 4.5),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    story += [header_table, Spacer(1, 10)]

    # EARNINGS box - Description / Hrs.Units / Amount, matching the reference layout
    earnings_rows = [['EARNINGS', '', ''], ['Description', 'Hrs./Units', 'Amount'],
                      ['Basic Pay', '', _money(payslip.base_salary)]]
    for item in breakdown.get('allowances', []):
        earnings_rows.append([item.get('name', ''), item.get('units', '') or '', _money(item.get('amount'))])
    earnings_rows.append(['Total Earnings', '', _money(payslip.gross_salary)])

    earnings_table = Table(earnings_rows, colWidths=[38 * mm, 22 * mm, 22 * mm])
    earnings_table.setStyle(TableStyle([
        ('SPAN', (0, 0), (2, 0)),
        ('BACKGROUND', (0, 0), (-1, 0), SECTION_BG),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 1), 'Helvetica-Bold'),
        ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
        ('BACKGROUND', (0, -1), (-1, -1), TOTAL_BG),
        ('GRID', (0, 0), (-1, -1), 0.4, BOX_BORDER),
        ('ALIGN', (1, 1), (2, -1), 'RIGHT'),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('PADDING', (0, 0), (-1, -1), 4.5),
    ]))

    # DEDUCTIONS box
    deduction_rows = [['DEDUCTIONS', '', ''], ['Description', 'Hrs./Units', 'Amount']]
    if payslip.tax_amount:
        deduction_rows.append(['Tax (WHT)', '', _money(payslip.tax_amount)])
    for item in breakdown.get('statutory_contributions', []):
        deduction_rows.append([item.get('name', ''), '', _money(item.get('employee_share'))])
    for item in breakdown.get('other_deductions', []):
        deduction_rows.append([item.get('name', ''), '', _money(item.get('amount'))])
    total_deductions = (
        Decimal(str(payslip.tax_amount or 0))
        + Decimal(str(payslip.total_contributions or 0))
        + Decimal(str(payslip.total_other_deductions or 0))
    )
    deduction_rows.append(['Total Deductions', '', _money(total_deductions)])

    deductions_table = Table(deduction_rows, colWidths=[38 * mm, 22 * mm, 22 * mm])
    deductions_table.setStyle(TableStyle([
        ('SPAN', (0, 0), (2, 0)),
        ('BACKGROUND', (0, 0), (-1, 0), SECTION_BG),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 1), 'Helvetica-Bold'),
        ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
        ('BACKGROUND', (0, -1), (-1, -1), TOTAL_BG),
        ('GRID', (0, 0), (-1, -1), 0.4, BOX_BORDER),
        ('ALIGN', (1, 1), (2, -1), 'RIGHT'),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('PADDING', (0, 0), (-1, -1), 4.5),
    ]))

    side_by_side = Table([[earnings_table, deductions_table]], colWidths=[86 * mm, 86 * mm])
    side_by_side.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP')]))
    story += [side_by_side, Spacer(1, 10)]

    net_pay_table = Table(
        [[f'NET PAY ({currency})' if currency else 'NET PAY', _money(payslip.net_salary)]],
        colWidths=[116 * mm, 56 * mm],
    )
    net_pay_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), NET_PAY_BG),
        ('TEXTCOLOR', (0, 0), (-1, -1), colors.white),
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 12),
        ('ALIGN', (1, 0), (1, 0), 'RIGHT'),
        ('PADDING', (0, 0), (-1, -1), 8),
        ('GRID', (0, 0), (-1, -1), 0.4, BOX_BORDER),
    ]))
    story += [net_pay_table, Spacer(1, 10)]

    # CURRENT PERIOD (employer-side statutory contributions) + signature line
    employer_total = sum(
        Decimal(str(item.get('employer_share', 0))) for item in breakdown.get('statutory_contributions', [])
    )
    period_rows = [['CURRENT PERIOD', '']]
    for item in breakdown.get('statutory_contributions', []):
        if Decimal(str(item.get('employer_share', 0))) > 0:
            period_rows.append([f"{item.get('name', '')} (Employer)", _money(item.get('employer_share'))])
    period_rows.append(['Total Employer Cont.', _money(employer_total)])
    period_table = Table(period_rows, colWidths=[45 * mm, 41 * mm])
    period_table.setStyle(TableStyle([
        ('SPAN', (0, 0), (1, 0)),
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#f1f5f9')),
        ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
        ('GRID', (0, 0), (-1, -1), 0.4, BOX_BORDER),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('PADDING', (0, 0), (-1, -1), 4.5),
    ]))
    signature_table = Table([['Name / Surname / Signature / Date'], ['']], colWidths=[86 * mm], rowHeights=[7 * mm, 12 * mm])
    signature_table.setStyle(TableStyle([
        ('GRID', (0, 0), (-1, -1), 0.4, BOX_BORDER),
        ('FONTSIZE', (0, 0), (-1, -1), 7.5),
        ('PADDING', (0, 0), (-1, -1), 4.5),
    ]))
    left_stack = Table([[period_table], [Spacer(1, 4)], [signature_table]], colWidths=[86 * mm])

    additional_rows = [
        ['ADDITIONAL INFO', ''],
        ['Gross Pay', _money(payslip.gross_salary)],
        ['Account Number', employee.bank_account_number or '-'],
        ['Payment Status', 'Paid' if payslip.paid_at else 'Unpaid'],
    ]
    additional_table = Table(additional_rows, colWidths=[45 * mm, 41 * mm])
    additional_table.setStyle(TableStyle([
        ('SPAN', (0, 0), (1, 0)),
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#f1f5f9')),
        ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('GRID', (0, 0), (-1, -1), 0.4, BOX_BORDER),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('PADDING', (0, 0), (-1, -1), 4.5),
    ]))

    info_row = Table([[left_stack, additional_table]], colWidths=[86 * mm, 86 * mm])
    info_row.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP')]))
    story += [info_row, Spacer(1, 12), Paragraph(f'Generated by {company.name} via HRCloudPay · {copy_label}', small)]

    document.build(story)
    return buffer.getvalue()
