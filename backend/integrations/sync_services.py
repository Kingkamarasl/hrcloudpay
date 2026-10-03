from decimal import Decimal
from django.db import transaction
from django.utils import timezone
from accounts.audit import audit
from payroll.models import PayrollRun
from .models import IntegrationConnection, SyncJob, SyncConflict, ExternalRecord, AccountingMapping, SyncSchedule
from .oauth import quickbooks_accounts, xero_accounts, quickbooks_create_journal, xero_create_manual_journal

PROVIDER_CAPABILITIES={
 'quickbooks': {'accounts':True,'journal_export':True},
 'xero': {'accounts':True,'journal_export':True},
 'microsoft365': {'users':True},
}

def _connection(company, provider):
    return IntegrationConnection.objects.filter(company=company, provider=provider, status='connected').first()

def sync_accounting_catalog(connection, actor=None, request=None):
    provider=connection.provider
    if provider=='quickbooks':
        data=quickbooks_accounts(connection); records=data.get('QueryResponse',{}).get('Account',[])
        entity='account'
    elif provider=='xero':
        data=xero_accounts(connection); records=data.get('Accounts',[])
        entity='account'
    else: raise ValueError('Accounting catalog sync is available for QuickBooks and Xero only.')
    for item in records:
        ext=str(item.get('Id') or item.get('AccountID') or '')
        if ext:
            ExternalRecord.objects.update_or_create(connection=connection,entity_type=entity,external_id=ext,defaults={'metadata':item,'last_synced_at':timezone.now()})
    connection.last_synced_at=timezone.now(); connection.save(update_fields=['last_synced_at','updated_at'])
    result={'records':len(records),'entity_type':entity}
    if actor: audit(actor=actor,action='integration.accounting_catalog_synced',message=f'{provider} accounting catalog synchronized.',company=connection.company,target_type='IntegrationConnection',target_id=connection.id,metadata=result,request=request)
    return result

def build_payroll_journal(run, mapping):
    payslips=list(run.payslips.select_related('employee'))
    gross=sum((p.gross_salary for p in payslips), Decimal('0'))
    tax=sum((p.tax_amount for p in payslips), Decimal('0'))
    contributions=sum((p.total_contributions for p in payslips), Decimal('0'))
    other=sum((p.total_other_deductions for p in payslips), Decimal('0'))
    net=sum((p.net_salary for p in payslips), Decimal('0'))
    if gross<=0: raise ValueError('Payroll run has no positive gross payroll to export.')
    required={'payroll_expense_account_id':mapping.payroll_expense_account_id,'payroll_liability_account_id':mapping.payroll_liability_account_id,'net_pay_account_id':mapping.net_pay_account_id}
    missing=[k for k,v in required.items() if not v]
    if missing: raise ValueError('Configure payroll accounting mappings before exporting: '+', '.join(missing))
    return {'gross':gross,'tax':tax,'contributions':contributions,'other':other,'net':net,'accounts':required}

def export_payroll_to_quickbooks(run, connection, mapping):
    totals=build_payroll_journal(run,mapping); a=totals['accounts']
    lines=[
      {'Description':'Payroll expense','Amount':float(totals['gross']),'DetailType':'JournalEntryLineDetail','JournalEntryLineDetail':{'PostingType':'Debit','AccountRef':{'value':a['payroll_expense_account_id']}}},
      {'Description':'Net payroll payable','Amount':float(totals['net']),'DetailType':'JournalEntryLineDetail','JournalEntryLineDetail':{'PostingType':'Credit','AccountRef':{'value':a['net_pay_account_id']}}},
    ]
    liabilities=totals['tax']+totals['contributions']+totals['other']
    if liabilities>0: lines.append({'Description':'Payroll liabilities','Amount':float(liabilities),'DetailType':'JournalEntryLineDetail','JournalEntryLineDetail':{'PostingType':'Credit','AccountRef':{'value':a['payroll_liability_account_id']}}})
    payload={'TxnDate':str(run.period_end),'PrivateNote':f'HRCloudPay payroll run #{run.id} {run.period_start} to {run.period_end}','Line':lines}
    return quickbooks_create_journal(connection,payload)

def export_payroll_to_xero(run, connection, mapping):
    totals=build_payroll_journal(run,mapping); a=totals['accounts']
    lines=[
      {'AccountCode':a['payroll_expense_account_id'],'Description':'Payroll expense','TaxType':'NONE','Amount':float(totals['gross']),'IsTaxable':False},
      {'AccountCode':a['net_pay_account_id'],'Description':'Net payroll payable','TaxType':'NONE','Amount':float(-totals['net']),'IsTaxable':False},
    ]
    liabilities=totals['tax']+totals['contributions']+totals['other']
    if liabilities>0: lines.append({'AccountCode':a['payroll_liability_account_id'],'Description':'Payroll liabilities','TaxType':'NONE','Amount':float(-liabilities),'IsTaxable':False})
    payload={'ManualJournals':[{'Date':str(run.period_end),'Narration':f'HRCloudPay payroll run #{run.id} {run.period_start} to {run.period_end}','Status':'POSTED','JournalLines':lines}]}
    return xero_create_manual_journal(connection,payload)

def run_scheduled_sync(connection, actor=None):
    if connection.provider in ('quickbooks','xero'):
        result=sync_accounting_catalog(connection,actor=actor)
        return result
    if connection.provider=='microsoft365': return {'delegated_to':'existing_microsoft_user_sync'}
    return {'skipped':True}
