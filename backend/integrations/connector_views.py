from datetime import timedelta
import secrets
from django.db import transaction
from django.shortcuts import redirect
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from accounts.audit import audit
from accounts.permissions import IsCompanyActive, IsCompanyMember
from .models import IntegrationConnection, ImportJob, OAuthState, SyncJob
from .oauth import PROVIDERS, build_authorize_url, callback_uri, exchange_code, create_connection, fetch_provider_identity, fetch_microsoft_users
from .services import validate_rows


def can_manage(user):
    return bool(user and user.is_authenticated and user.role in ('owner','admin','hr'))

class OAuthStartView(APIView):
    permission_classes = [IsAuthenticated, IsCompanyMember, IsCompanyActive]
    def get(self, request, provider):
        if not can_manage(request.user): return Response({'detail':'Only owners, admins, or HR managers can connect integrations.'}, status=403)
        if provider not in PROVIDERS: return Response({'detail':'Unsupported OAuth provider.'}, status=404)
        raw_state = secrets.token_urlsafe(32)
        OAuthState.objects.filter(company=request.user.company, provider=provider, used_at__isnull=True, expires_at__lt=timezone.now()).delete()
        OAuthState.objects.create(company=request.user.company, created_by=request.user, provider=provider, state_hash=OAuthState.digest(raw_state), expires_at=timezone.now()+timedelta(minutes=10))
        try: url = build_authorize_url(provider, raw_state)
        except ValueError as exc: return Response({'detail':str(exc)}, status=400)
        return Response({'authorization_url':url})

class OAuthCallbackView(APIView):
    permission_classes = [AllowAny]
    def get(self, request, provider):
        frontend = getattr(__import__('django.conf', fromlist=['settings']).settings, 'FRONTEND_URL', '/')
        state = request.query_params.get('state','')
        code = request.query_params.get('code','')
        if not state or not code or provider not in PROVIDERS:
            return redirect(frontend.rstrip('/') + '/integrations?oauth=error&message=Invalid+OAuth+response')
        try:
            oauth_state = OAuthState.objects.select_related('company','created_by').get(state_hash=OAuthState.digest(state), provider=provider, used_at__isnull=True, expires_at__gt=timezone.now())
            token_data = exchange_code(provider, code)
            identity = fetch_provider_identity(provider, token_data)
            external_id = identity.get('id','') if isinstance(identity,dict) else ''
            display_name = identity.get('displayName','') if isinstance(identity,dict) else ''
            if provider == 'xero' and isinstance(identity,dict) and identity.get('connections'):
                first = identity['connections'][0]
                external_id = first.get('tenantId','')
                display_name = first.get('tenantName','')
            connection = create_connection(oauth_state.company, provider, token_data, oauth_state.created_by, external_id, display_name)
            oauth_state.used_at = timezone.now(); oauth_state.save(update_fields=['used_at'])
            audit(actor=oauth_state.created_by, action='integration.connected', message=f'{provider} integration connected.', company=oauth_state.company, target_type='IntegrationConnection', target_id=connection.id, metadata={'provider':provider,'external_account_id':external_id})
            return redirect(frontend.rstrip('/') + f'/integrations?oauth=success&provider={provider}')
        except Exception as exc:
            return redirect(frontend.rstrip('/') + f'/integrations?oauth=error&provider={provider}&message={str(exc)[:180]}')

class IntegrationDisconnectView(APIView):
    permission_classes = [IsAuthenticated, IsCompanyMember, IsCompanyActive]
    def post(self, request, provider):
        if not can_manage(request.user): return Response({'detail':'Not permitted.'}, status=403)
        connection = IntegrationConnection.objects.filter(company=request.user.company, provider=provider).first()
        if not connection: return Response({'detail':'Connection not found.'}, status=404)
        connection.status='disconnected'; connection.access_token=''; connection.refresh_token=''; connection.token_expires_at=None; connection.save()
        audit(actor=request.user, action='integration.disconnected', message=f'{provider} integration disconnected.', company=request.user.company, target_type='IntegrationConnection', target_id=connection.id, metadata={'provider':provider}, request=request)
        return Response({'status':'disconnected'})

class IntegrationSyncView(APIView):
    permission_classes = [IsAuthenticated, IsCompanyMember, IsCompanyActive]
    def post(self, request, provider):
        if not can_manage(request.user): return Response({'detail':'Not permitted.'}, status=403)
        connection = IntegrationConnection.objects.filter(company=request.user.company, provider=provider, status='connected').first()
        if not connection: return Response({'detail':'Connect this integration first.'}, status=400)
        if provider != 'microsoft365': return Response({'detail':f'{provider} OAuth connection is ready, but its data sync connector is the next provider-specific implementation.'}, status=202)
        sync = SyncJob.objects.create(connection=connection, created_by=request.user, direction='import', entity_type='employee', status='running', started_at=timezone.now())
        try:
            users = fetch_microsoft_users(connection)
            rows=[]
            for u in users:
                if not u.get('accountEnabled', True): continue
                name=(u.get('displayName') or '').strip()
                given=(u.get('givenName') or '').strip()
                surname=(u.get('surname') or '').strip()
                if not given or not surname:
                    parts=name.split(None,1); given=given or (parts[0] if parts else 'Imported'); surname=surname or (parts[1] if len(parts)>1 else 'User')
                email=(u.get('mail') or u.get('userPrincipalName') or '').strip()
                rows.append({'employee_code':f'M365-{u.get("id","")[:22]}','first_name':given,'last_name':surname,'email':email,'phone':u.get('mobilePhone') or '','job_title':u.get('jobTitle') or '','department':'','base_salary':'0.00','hire_date':'','employment_status':'active','id_card_no':''})
            validated=validate_rows(connection.company, rows)
            job=ImportJob.objects.create(company=connection.company,created_by=request.user,source_type='csv',filename='Microsoft 365 users',status='ready',entity_type='employee',headers=['employee_code','first_name','last_name','email','phone','job_title','department','base_salary','hire_date','employment_status','id_card_no'],mapping={},rows=validated,total_rows=len(validated),valid_rows=sum(not r['errors'] for r in validated),warning_rows=sum(bool(r['warnings']) for r in validated),error_rows=sum(bool(r['errors']) for r in validated),duplicate_rows=sum(bool(r.get('duplicate_employee_id')) for r in validated))
            connection.last_synced_at=timezone.now(); connection.status='connected'; connection.save(update_fields=['last_synced_at','status','updated_at'])
            sync.status='completed_with_warnings' if job.error_rows or job.warning_rows else 'completed'; sync.result={'users_found':len(users),'import_job_id':job.id,'valid_rows':job.valid_rows,'error_rows':job.error_rows,'warning_rows':job.warning_rows}; sync.completed_at=timezone.now(); sync.save()
            audit(actor=request.user, action='integration.synced', message=f'Microsoft 365 user sync found {len(users)} users.', company=request.user.company, target_type='SyncJob', target_id=sync.id, metadata=sync.result, request=request)
            return Response({'sync':{'id':sync.id,'status':sync.status,'result':sync.result},'import_job_id':job.id})
        except Exception as exc:
            connection.status='attention'; connection.save(update_fields=['status','updated_at'])
            sync.status='failed'; sync.error_message=str(exc)[:1000]; sync.completed_at=timezone.now(); sync.save()
            return Response({'detail':str(exc),'sync_id':sync.id}, status=502)

class AccountingCatalogSyncView(APIView):
    permission_classes=[IsAuthenticated, IsCompanyMember, IsCompanyActive]
    def post(self, request, provider):
        if not can_manage(request.user): return Response({'detail':'Not permitted.'}, status=403)
        from .sync_services import sync_accounting_catalog
        connection=IntegrationConnection.objects.filter(company=request.user.company,provider=provider,status='connected').first()
        if not connection: return Response({'detail':'Connect this integration first.'},status=400)
        try:
            result=sync_accounting_catalog(connection,actor=request.user,request=request)
            return Response({'catalog':result})
        except Exception as exc:
            connection.status='attention'; connection.save(update_fields=['status','updated_at'])
            return Response({'detail':str(exc)},status=502)

class AccountingMappingView(APIView):
    permission_classes=[IsAuthenticated, IsCompanyMember, IsCompanyActive]
    def get(self,request,provider):
        if not can_manage(request.user): return Response({'detail':'Not permitted.'},status=403)
        connection=IntegrationConnection.objects.filter(company=request.user.company,provider=provider).first()
        if not connection: return Response({'detail':'Connection not found.'},status=404)
        from .models import AccountingMapping
        m=AccountingMapping.objects.filter(connection=connection).first()
        return Response({'provider':provider,'mapping':{'payroll_expense_account_id':getattr(m,'payroll_expense_account_id',''),'payroll_liability_account_id':getattr(m,'payroll_liability_account_id',''),'net_pay_account_id':getattr(m,'net_pay_account_id',''),'employer_contribution_account_id':getattr(m,'employer_contribution_account_id','')}})
    def put(self,request,provider):
        if not can_manage(request.user): return Response({'detail':'Not permitted.'},status=403)
        connection=IntegrationConnection.objects.filter(company=request.user.company,provider=provider,status='connected').first()
        if not connection: return Response({'detail':'Connect this integration first.'},status=400)
        from .models import AccountingMapping
        m,_=AccountingMapping.objects.get_or_create(connection=connection)
        for f in ('payroll_expense_account_id','payroll_liability_account_id','net_pay_account_id','employer_contribution_account_id'):
            if f in request.data: setattr(m,f,str(request.data.get(f) or '').strip()[:255])
        m.save()
        audit(actor=request.user,action='integration.accounting_mapping_updated',message=f'{provider} accounting mapping updated.',company=request.user.company,target_type='AccountingMapping',target_id=m.id,metadata={'provider':provider},request=request)
        return Response({'status':'saved'})

class PayrollJournalExportView(APIView):
    permission_classes=[IsAuthenticated, IsCompanyMember, IsCompanyActive]
    def post(self,request,provider,payroll_id):
        if request.user.role not in ('owner','admin','finance'): return Response({'detail':'Only owners, admins, or finance users can export payroll journals.'},status=403)
        from payroll.models import PayrollRun
        from .models import AccountingMapping
        from .sync_services import export_payroll_to_quickbooks, export_payroll_to_xero
        run=PayrollRun.objects.filter(id=payroll_id,company=request.user.company).first()
        if not run: return Response({'detail':'Payroll run not found.'},status=404)
        if run.status not in ('approved','paid'): return Response({'detail':'Only approved or paid payroll runs can be exported.'},status=400)
        connection=IntegrationConnection.objects.filter(company=request.user.company,provider=provider,status='connected').first()
        if not connection: return Response({'detail':'Connect this integration first.'},status=400)
        mapping=AccountingMapping.objects.filter(connection=connection).first()
        if not mapping: return Response({'detail':'Configure accounting mappings first.'},status=400)
        try:
            result=export_payroll_to_quickbooks(run,connection,mapping) if provider=='quickbooks' else export_payroll_to_xero(run,connection,mapping)
            audit(actor=request.user,action='integration.payroll_exported',message=f'Payroll run #{run.id} exported to {provider}.',company=request.user.company,target_type='PayrollRun',target_id=run.id,metadata={'provider':provider},request=request)
            return Response({'provider':provider,'payroll_run_id':run.id,'result':result})
        except Exception as exc:
            return Response({'detail':str(exc)},status=502)

class IntegrationScheduleView(APIView):
    permission_classes=[IsAuthenticated, IsCompanyMember, IsCompanyActive]
    def get(self,request,provider):
        if not can_manage(request.user): return Response({'detail':'Not permitted.'},status=403)
        from .models import SyncSchedule
        c=IntegrationConnection.objects.filter(company=request.user.company,provider=provider).first()
        if not c: return Response({'detail':'Connection not found.'},status=404)
        s=SyncSchedule.objects.filter(connection=c).first()
        return Response({'enabled':getattr(s,'enabled',False),'interval_minutes':getattr(s,'interval_minutes',1440),'next_run_at':getattr(s,'next_run_at',None),'last_run_at':getattr(s,'last_run_at',None)})
    def put(self,request,provider):
        if not can_manage(request.user): return Response({'detail':'Not permitted.'},status=403)
        from .models import SyncSchedule
        from datetime import timedelta
        c=IntegrationConnection.objects.filter(company=request.user.company,provider=provider,status='connected').first()
        if not c: return Response({'detail':'Connect this integration first.'},status=400)
        enabled=bool(request.data.get('enabled',False)); interval=int(request.data.get('interval_minutes',1440))
        if interval < 60 or interval > 10080: return Response({'detail':'Interval must be between 60 minutes and 7 days.'},status=400)
        s,_=SyncSchedule.objects.get_or_create(connection=c); s.enabled=enabled; s.interval_minutes=interval; s.next_run_at=timezone.now()+timedelta(minutes=interval) if enabled else None; s.save()
        return Response({'enabled':s.enabled,'interval_minutes':s.interval_minutes,'next_run_at':s.next_run_at,'last_run_at':s.last_run_at})

class SyncConflictListView(APIView):
    permission_classes=[IsAuthenticated, IsCompanyMember, IsCompanyActive]
    def get(self,request):
        if not can_manage(request.user): return Response({'detail':'Not permitted.'},status=403)
        from .models import SyncConflict
        conflicts=SyncConflict.objects.filter(connection__company=request.user.company,resolution='pending')[:100]
        return Response([{'id':c.id,'provider':c.connection.provider,'entity_type':c.entity_type,'external_id':c.external_id,'local_object_type':c.local_object_type,'local_object_id':c.local_object_id,'external_data':c.external_data,'local_data':c.local_data} for c in conflicts])

class SyncConflictResolveView(APIView):
    permission_classes=[IsAuthenticated, IsCompanyMember, IsCompanyActive]
    def post(self,request,pk):
        if not can_manage(request.user): return Response({'detail':'Not permitted.'},status=403)
        from .models import SyncConflict
        c=SyncConflict.objects.filter(id=pk,connection__company=request.user.company).first()
        if not c: return Response({'detail':'Conflict not found.'},status=404)
        resolution=request.data.get('resolution')
        if resolution not in ('external','local','merged'): return Response({'detail':'Resolution must be external, local, or merged.'},status=400)
        c.resolution=resolution; c.resolved_by=request.user; c.resolved_at=timezone.now(); c.save(update_fields=['resolution','resolved_by','resolved_at'])
        audit(actor=request.user,action='integration.conflict_resolved',message=f'Integration conflict #{c.id} resolved as {resolution}.',company=request.user.company,target_type='SyncConflict',target_id=c.id,metadata={'resolution':resolution},request=request)
        return Response({'status':'resolved','resolution':resolution})
