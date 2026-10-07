from django.conf import settings
from hrcloudpay.email_backend import send_mail_logging_failure
from django.db import transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
import hashlib
import hmac
import json
from rest_framework import status
from rest_framework.permissions import IsAdminUser, IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework.permissions import BasePermission
from rest_framework.views import APIView
import uuid

from .models import Company, User, PLAN_EMPLOYEE_LIMITS
from hrcloudpay.pricing_sync import derived_content
from .platform_models import SiteBranding
from django.urls import reverse
from hrcloudpay.site_icons import (
    APPLE_TOUCH_ICON_SIZE, FAVICON_MAX_EDGE, MAX_UPLOAD_BYTES,
    SiteIconError, normalise_site_icon,
)
from .platform_models import AuditLog, PlatformNotification, Subscription, SuspensionEvent, SupportTicket, PaymentProviderConfig, PaymentEvent, PaymentTransaction, BillingInvoice, FeatureFlag, MarketingPage, BillingPlan
from .audit_chain import verify_chain
from .audit import audit
from .marketing_schema import (
    MAX_REPEATED,
    MAX_SECTIONS,
    SECTION_TYPES,
    blank_content,
    is_valid_slug,
    validate_content,
)
from .serializers import PlatformCompanyCreateSerializer, PlatformCompanySerializer, PlatformUserSerializer
from .billing import PLAN_LABELS, PLAN_PRICES, PLAN_USER_LIMITS, subscription_state, start_trial
from .permissions import IsOwnerOrAdminOnly
from .secrets import encrypt_secret, decrypt_secret



class IsPlatformSecretsAdmin(BasePermission):
    message = 'Only a platform superuser may manage payment provider secrets.'
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.is_superuser)


def usage_for(company):
    employee_count = company.employees.count()
    user_count = company.users.filter(is_active=True).count()
    limit = company.employee_limit
    return {
        'employees': employee_count,
        'employee_limit': limit,
        'employee_utilization_percent': round((employee_count / limit) * 100, 1) if limit else None,
        'active_users': user_count,
        'departments': company.departments.filter(is_active=True).count() if hasattr(company, 'departments') else 0,
        'payroll_configured': company.payroll_configured,
    }


class PlatformDashboardView(APIView):
    permission_classes = [IsAdminUser]
    def get(self, request):
        companies = Company.objects.all(); users = User.objects.all()
        return Response({
            'companies_total': companies.count(), 'companies_active': companies.filter(is_active=True).count(),
            'companies_pending': companies.filter(is_active=False).count(), 'companies_payroll_ready': companies.filter(payroll_configured=True).count(),
            'users_total': users.count(), 'users_active': users.filter(is_active=True).count(),
            'plans': {plan: companies.filter(plan=plan).count() for plan, _ in Company._meta.get_field('plan').choices},
            'subscriptions': {status: Subscription.objects.filter(status=status).count() for status, _ in Subscription.STATUS_CHOICES},
            'revenue_monthly': sum((s.monthly_price for s in Subscription.objects.filter(status__in=('trial','active'))), 0),
            'payment_providers_enabled': PaymentProviderConfig.objects.filter(enabled=True).count(),
            'open_tickets': SupportTicket.objects.exclude(status='resolved').count(),
            'recent_companies': PlatformCompanySerializer(companies.order_by('-created_at')[:8], many=True).data,
        })


class PlatformCompaniesView(APIView):
    permission_classes = [IsAdminUser]
    def get(self, request):
        qs = Company.objects.all().annotate(user_count=Count('users', distinct=True), employee_count=Count('employees', distinct=True)).order_by('-created_at')
        search = request.query_params.get('search', '').strip(); status_filter = request.query_params.get('status', '').strip(); plan = request.query_params.get('plan', '').strip()
        if search: qs = qs.filter(Q(name__icontains=search) | Q(email__icontains=search) | Q(country__icontains=search))
        if status_filter == 'active': qs = qs.filter(is_active=True)
        elif status_filter == 'pending': qs = qs.filter(is_active=False)
        if plan: qs = qs.filter(plan=plan)
        return Response(PlatformCompanySerializer(qs, many=True).data)
    def post(self, request):
        serializer = PlatformCompanyCreateSerializer(data=request.data); serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            result = serializer.save()
            sub, created_sub = Subscription.objects.get_or_create(company=result['company'], defaults={'status': 'trial', 'currency': 'USD'})
            if created_sub: start_trial(sub, 14)
            audit(request.user, 'create', f"Created company {result['company'].name}", result['company'], 'company', result['company'].id)
        return Response({'company': PlatformCompanySerializer(result['company']).data, 'owner': PlatformUserSerializer(result['owner']).data,
                         'activation_url': result['activation_url'], 'message': 'Company created successfully.'}, status=status.HTTP_201_CREATED)


class PlatformCompanyDetailView(APIView):
    permission_classes = [IsAdminUser]
    def patch(self, request, company_id):
        company = get_object_or_404(Company, id=company_id)
        allowed = {'name','country','email','phone','plan','payroll_configured'}; changed=[]
        for field in allowed:
            if field in request.data:
                if field == 'plan':
                    new_plan = request.data[field]
                    valid_plans = dict(Company._meta.get_field('plan').choices)
                    if new_plan not in valid_plans:
                        return Response({'plan':'Invalid plan.'}, status=400)
                    new_limit = PLAN_EMPLOYEE_LIMITS.get(new_plan)
                    current_count = company.employees.count()
                    if new_limit is not None and current_count > new_limit:
                        return Response({'plan': f'Cannot downgrade: this company currently has {current_count} employees, above the {new_limit}-employee limit.'}, status=400)
                if field == 'email' and Company.objects.filter(email__iexact=request.data[field]).exclude(id=company.id).exists():
                    return Response({'email':'A company with this email already exists.'}, status=400)
                setattr(company, field, request.data[field]); changed.append(field)
        if changed:
            company.save(update_fields=changed + ['updated_at']); audit(request.user,'update',f"Updated company {company.name}",company,'company',company.id,{'fields':changed})
        return Response(PlatformCompanySerializer(company).data)


class PlatformCompanyActivationView(APIView):
    permission_classes = [IsAdminUser]
    def post(self, request, company_id):
        company = get_object_or_404(Company, id=company_id); company.is_active=True; company.save(update_fields=['is_active','updated_at'])
        SuspensionEvent.objects.filter(company=company, ended_at__isnull=True).update(ended_at=timezone.now()); audit(request.user,'activate',f"Activated {company.name}",company,'company',company.id)
        return Response({'message':'Company activated.','company':PlatformCompanySerializer(company).data})


class PlatformCompanySuspensionView(APIView):
    permission_classes = [IsAdminUser]
    def post(self, request, company_id):
        company=get_object_or_404(Company,id=company_id); reason=(request.data.get('reason') or 'Administrative suspension').strip(); notes=request.data.get('notes','')
        company.is_active=False; company.save(update_fields=['is_active','updated_at'])
        SuspensionEvent.objects.filter(company=company, ended_at__isnull=True).update(ended_at=timezone.now())
        SuspensionEvent.objects.create(company=company, reason=reason, notes=notes, suspended_by=request.user)
        audit(request.user,'suspend',f"Suspended {company.name}: {reason}",company,'company',company.id,{'reason':reason})
        return Response({'message':'Company suspended.','company':PlatformCompanySerializer(company).data})


class PlatformCompanyResendActivationView(APIView):
    permission_classes=[IsAdminUser]
    def post(self,request,company_id):
        company=get_object_or_404(Company,id=company_id)
        if company.is_active: return Response({'detail':'Company is already active.'},status=400)
        company.activation_token=uuid.uuid4(); company.save(update_fields=['activation_token','updated_at'])
        activation_url=f"{settings.FRONTEND_URL}/activate/{company.id}/{company.activation_token}"
        sent=send_mail_logging_failure('Activate your HRCloudPay company account',f'Activate your HRCloudPay account here:\n\n{activation_url}',settings.DEFAULT_FROM_EMAIL,[company.email],what='platform company activation')
        audit(request.user,'system',f"Regenerated activation for {company.name}",company,'company',company.id)
        # The return value used to be discarded and the response said "emailed"
        # unconditionally, so a completely broken mail server produced the same
        # green confirmation as a working one - and the activation_url was handed
        # over alongside it, which is enough to keep an operator activating
        # companies by hand and concluding the mail path was fine.
        #
        # A 503 is right here even though the token was regenerated: the caller
        # asked for an email and did not get one. The link is still returned so a
        # platform admin is not blocked by a mail outage - it is simply labelled
        # as not having been sent.
        if not sent:
            return Response({
                'detail':('The activation link was regenerated but the email was '
                          'NOT delivered. Check `docker compose logs backend` for '
                          'the reason, then fix SMTP under PLATFORM -> Email / SMTP.'),
                'emailed': False,
                'activation_url': activation_url,
            },status=503)
        return Response({'message':'A new activation link has been generated and emailed.','emailed':True,'activation_url':activation_url})


class PlatformUsersView(APIView):
    permission_classes=[IsAdminUser]
    def get(self,request):
        qs=User.objects.select_related('company').order_by('-date_joined'); search=request.query_params.get('search','').strip()
        if search: qs=qs.filter(Q(username__icontains=search)|Q(email__icontains=search)|Q(company__name__icontains=search))
        return Response(PlatformUserSerializer(qs,many=True).data)


class PlatformUserDetailView(APIView):
    permission_classes=[IsAdminUser]

    # Relations that make a hard delete unacceptable, and why.
    #
    # A User is referenced by 53 relations. Fifteen of them CASCADE, so a delete
    # silently destroys MFA devices, recovery codes, security sessions, PAM
    # sessions, AI conversations and the Django admin log. Thirty more SET_NULL,
    # which is worse than it sounds: `AuditLog.actor` sits on an append-only
    # compliance log, and `PayrollRun.approved_by` names the person who approved
    # a regulated payroll run. Deleting either of those users would leave a
    # payroll approval with no approver and an audit entry with no actor, and
    # nothing anywhere would report an error.
    #
    # `ai.AIDraft.created_by` and `ai.KnowledgeDocument.created_by` are PROTECT,
    # so a naive delete raises ProtectedError and surfaces as a 500.
    #
    # So the normal way to remove someone's access is to deactivate them, which
    # revokes it immediately: security.authentication.SecurityCookieAuthentication
    # refuses the session cookie belonging to an inactive user, so an existing
    # login stops working at once rather than at session expiry. A hard delete is
    # only for a user with no regulated history at all - a test account, or a
    # signup that should never have existed.
    DELETE_BLOCKERS = (
        ('payroll.PayrollRun', 'approved_by', 'approved payroll',
         'Payroll approvals are statutory records and must keep the name of the '
         'approver. Deactivate this user instead, or reassign the payroll run.'),
        ('accounts.AuditLog', 'actor', 'audit-log entries',
         'The audit log is append-only and must keep its actor. Deactivate this '
         'user instead.'),
        ('ai.AIDraft', 'created_by', 'AI drafts',
         'AI drafts are company HR documents and are protected from deletion. '
         'Archive the drafts, or deactivate this user instead.'),
        ('ai.AIDraft', 'reviewed_by', 'reviewed AI drafts',
         'AI drafts are company HR documents and are protected from deletion. '
         'Reassign the reviewer, or deactivate this user instead.'),
        ('ai.KnowledgeDocument', 'created_by', 'knowledge-base documents',
         'Knowledge documents are protected from deletion so their chunks stay '
         'traceable. Archive the document, or deactivate this user instead.'),
    )

    @staticmethod
    def _delete_blockers(user):
        """Which regulated records name this user, with counts."""
        from django.apps import apps
        found = []
        for model_label, field_name, description, why in PlatformUserDetailView.DELETE_BLOCKERS:
            model = apps.get_model(model_label)
            count = model.objects.filter(**{field_name: user}).count()
            if count:
                found.append({
                    'what': description,
                    'model': model_label,
                    'field': field_name,
                    'count': count,
                    'why': why,
                })
        return found

    def delete(self, request, user_id):
        user = get_object_or_404(User, id=user_id)

        if user.id == request.user.id:
            return Response({
                'detail': 'You cannot delete your own account. Another platform '
                          'administrator can do it if it is genuinely needed.'
            }, status=400)

        if user.is_superuser and User.objects.filter(
            is_superuser=True, is_active=True
        ).count() <= 1:
            return Response({
                'detail': 'This is the last active superuser. Deleting it would '
                          'leave nobody able to administer the platform. Promote '
                          'another superuser first.'
            }, status=400)

        # Checked before asking for confirmation, so an administrator is never
        # made to type a username for a deletion that is going to be refused.
        blockers = self._delete_blockers(user)
        if blockers:
            return Response({
                'detail': (
                    f'{user.username} cannot be deleted: they are named on '
                    f'regulated records. Deactivating the account removes their '
                    f'access immediately and keeps the history intact.'
                ),
                'blockers': blockers,
                'alternative': {'action': 'deactivate', 'is_active': False},
            }, status=409)

        # A hard delete is irreversible, and not recoverable from any backup
        # taken before it, so it requires retyping the exact username. Compared
        # case-sensitively on purpose: this is a deliberate speed bump, and
        # accepting a near-miss would defeat the point of having it.
        confirm = str(request.data.get('confirm_username') or '')
        if confirm != user.username:
            return Response({
                'detail': 'Type the exact username to confirm this deletion.',
                'expected_username': user.username,
            }, status=400)

        username = user.username
        company_name = user.company.name if user.company else None
        company_id = user.company_id
        target_id = user.id

        with transaction.atomic():
            # Recorded inside the transaction and *before* the delete, so the
            # record of the deletion commits atomically with the deletion itself.
            # It names the target by id, which is what an audit trail wants: a
            # reference to a row that no longer exists, rather than a silently
            # absent entry.
            audit(request.user, 'delete', f'Deleted user {username}', user.company,
                  'user', target_id,
                  {'username': username, 'company': company_name, 'company_id': company_id},
                  request=request)
            # Revoked explicitly as well as relying on the CASCADE from
            # security.SecuritySession. If that FK were ever changed to SET_NULL -
            # a plausible edit to "preserve security history" - a deleted user
            # would keep a working cookie, and this line is what stops that from
            # being silent. Imported here because security.models imports
            # accounts, so a module-level import would be circular.
            from security.models import SecuritySession
            SecuritySession.objects.filter(user=user).update(revoked_at=timezone.now())
            user.delete()

        return Response({
            'detail': f'User {username} was deleted.',
            'deleted_user_id': target_id,
        })

    def patch(self,request,user_id):
        user=get_object_or_404(User,id=user_id)
        if user.id==request.user.id and request.data.get('is_active') is False: return Response({'detail':'You cannot deactivate your own platform admin account.'},status=400)
        if 'is_active' in request.data: user.is_active=bool(request.data['is_active'])
        if 'role' in request.data and user.role!='owner':
            if request.data['role'] not in ('admin','hr','finance','department_manager','employee','owner'): return Response({'detail':'Invalid role.'},status=400)
            user.role=request.data['role']
        user.save(update_fields=['is_active','role']); audit(request.user,'update',f"Updated user {user.username}",user.company,'user',user.id)
        return Response(PlatformUserSerializer(user).data)


class PlatformUsageView(APIView):
    permission_classes=[IsAdminUser]
    def get(self,request):
        companies=Company.objects.order_by('-created_at')
        return Response([{'company': c.name, 'company_id': c.id, 'plan': c.plan, **usage_for(c)} for c in companies])


class PlatformSubscriptionsView(APIView):
    permission_classes=[IsAdminUser]
    def get(self,request):
        subs=Subscription.objects.select_related('company').all()
        return Response([{'id':s.id,'company_id':s.company_id,'company_name':s.company.name,'plan':s.company.plan,'status':s.status,'billing_cycle':s.billing_cycle,'monthly_price':str(s.monthly_price),'currency':s.currency,'renews_at':s.renews_at,'trial_ends_at':s.trial_ends_at,'grace_ends_at':s.grace_ends_at,'provider':s.provider,'provider_plan_id':s.provider_plan_id} for s in subs])
    def post(self,request):
        company=get_object_or_404(Company,id=request.data.get('company_id'))
        sub, _ = Subscription.objects.get_or_create(company=company)
        before = {'status': sub.status, 'billing_cycle': sub.billing_cycle, 'monthly_price': str(sub.monthly_price), 'currency': sub.currency, 'provider': sub.provider}
        for f in ('status','billing_cycle','monthly_price','currency','external_customer_id','external_subscription_id','renews_at','trial_ends_at','grace_ends_at','provider','provider_plan_id'):
            if f in request.data: setattr(sub,f,request.data[f])
        if request.data.get('status') == 'trial' and not sub.trial_ends_at: start_trial(sub, int(request.data.get('trial_days', 14)))
        else:
            if 'grace_days' in request.data:
                sub.grace_ends_at = timezone.now() + timezone.timedelta(days=int(request.data.get('grace_days') or 0))
            if request.data.get('status') == 'active':
                sub.grace_ends_at = None
            sub.save()
        audit(request.user,'update',f"Updated subscription for {company.name}",company,'subscription',sub.id,{'before':before,'after':{'status':sub.status,'billing_cycle':sub.billing_cycle,'monthly_price':str(sub.monthly_price),'currency':sub.currency,'provider':sub.provider}})
        return Response({'message':'Subscription updated.','state':subscription_state(company)})


class PlatformOnboardingView(APIView):
    permission_classes=[IsAdminUser]
    def get(self,request):
        result=[]
        for c in Company.objects.order_by('-created_at'):
            owner=c.users.filter(role='owner').first()
            checks={'company_profile':bool(c.name and c.email),'owner_account':bool(owner),'payroll_setup':c.payroll_configured,'active':c.is_active,'subscription':hasattr(c,'subscription')}
            result.append({'company_id':c.id,'company_name':c.name,'checks':checks,'completion_percent':round(sum(checks.values())/len(checks)*100)})
        return Response(result)


class PlatformAuditLogsView(APIView):
    permission_classes=[IsAdminUser]
    def get(self,request):
        qs=AuditLog.objects.select_related('actor','company').all()
        action=request.query_params.get('action','').strip()
        company_id=request.query_params.get('company_id','').strip()
        target_type=request.query_params.get('target_type','').strip()
        if action: qs=qs.filter(action=action)
        if company_id: qs=qs.filter(company_id=company_id)
        if target_type: qs=qs.filter(target_type=target_type)
        qs=qs[:500]
        return Response([{'id':x.id,'action':x.action,'message':x.message,'actor':x.actor.username if x.actor else 'System','company':x.company.name if x.company else 'Platform','target_type':x.target_type,'target_id':x.target_id,'metadata':x.metadata,'created_at':x.created_at} for x in qs])


class PlatformNotificationsView(APIView):
    permission_classes=[IsAdminUser]
    def get(self,request):
        return Response([{'id':n.id,'title':n.title,'message':n.message,'level':n.level,'company_id':n.company_id,'company_name':n.company.name if n.company else 'All companies','is_active':n.is_active,'created_at':n.created_at} for n in PlatformNotification.objects.select_related('company').all()[:100]])
    def post(self,request):
        n=PlatformNotification.objects.create(title=request.data['title'],message=request.data['message'],level=request.data.get('level','info'),company_id=request.data.get('company_id') or None,created_by=request.user)
        audit(request.user,'system',f"Created platform notification: {n.title}",n.company,'notification',n.id); return Response({'id':n.id},status=201)


class PlatformSupportView(APIView):
    permission_classes=[IsAdminUser]
    def get(self,request):
        qs=SupportTicket.objects.select_related('company','created_by','assigned_to')[:100]
        return Response([{'id':t.id,'company_id':t.company_id,'company_name':t.company.name,'subject':t.subject,'description':t.description,'status':t.status,'priority':t.priority,'created_by':t.created_by.username if t.created_by else None,'assigned_to':t.assigned_to.username if t.assigned_to else None,'created_at':t.created_at,'updated_at':t.updated_at} for t in qs])
    def post(self,request):
        company=get_object_or_404(Company,id=request.data.get('company_id'))
        t=SupportTicket.objects.create(company=company,subject=request.data['subject'],description=request.data['description'],priority=request.data.get('priority','normal'),created_by=request.user)
        audit(request.user,'create',f"Created support ticket {t.subject}",company,'support_ticket',t.id); return Response({'id':t.id},status=201)


class PlatformAnalyticsView(APIView):
    permission_classes=[IsAdminUser]
    def get(self,request):
        companies=list(Company.objects.all()); total=max(len(companies),1)
        active=sum(c.is_active for c in companies)
        ready=sum(c.payroll_configured for c in companies)
        employee_total=sum(c.employees.count() for c in companies)
        return Response({'active_rate':round(active/total*100,1),'payroll_ready_rate':round(ready/total*100,1),'employees_total':employee_total,
                         'plan_distribution':{p:sum(c.plan==p for c in companies) for p,_ in Company._meta.get_field('plan').choices},
                         'company_growth': [{'month': (timezone.now()-timezone.timedelta(days=30*i)).strftime('%Y-%m'),'companies': Company.objects.filter(created_at__year=(timezone.now()-timezone.timedelta(days=30*i)).year,created_at__month=(timezone.now()-timezone.timedelta(days=30*i)).month).count()} for i in range(6)]})


class PlatformBillingPlansView(APIView):
    permission_classes=[IsAdminUser]
    def get(self, request):
        plans = BillingPlan.objects.all()
        return Response([
            {
                'id': p.plan,
                'name': p.name,
                'monthly_price': str(p.monthly_price),
                'annual_price': str(p.annual_price),
                'employee_limit': p.employee_limit,
                'user_limit': p.user_limit,
                'ai_enabled': p.ai_enabled,
                'highlight': p.highlight,
                'active': p.active,
                'order': p.order,
            }
            for p in plans
        ])

    def put(self, request):
        """Update plan configuration."""
        plan_id = request.data.get('plan')
        if not plan_id:
            return Response({'detail': 'plan is required'}, status=400)
        plan = BillingPlan.objects.filter(plan=plan_id).first()
        if not plan:
            return Response({'detail': 'Plan not found'}, status=404)
        # Updatable fields
        updatable = ['name', 'monthly_price', 'annual_price', 'employee_limit', 'user_limit', 'ai_enabled', 'highlight', 'active', 'order']
        for field in updatable:
            if field in request.data:
                setattr(plan, field, request.data[field])
        plan.save()
        return Response({'detail': 'Plan updated', 'plan': {
            'id': plan.plan,
            'name': plan.name,
            'monthly_price': str(plan.monthly_price),
            'annual_price': str(plan.annual_price),
            'employee_limit': plan.employee_limit,
            'user_limit': plan.user_limit,
            'ai_enabled': plan.ai_enabled,
            'highlight': plan.highlight,
            'active': plan.active,
            'order': plan.order,
        }})


class PlatformPaymentProvidersView(APIView):
    def get_permissions(self):
        return [IsAdminUser()] if self.request.method == 'GET' else [IsPlatformSecretsAdmin()]

    def get(self, request):
        rows=[]
        for p,label in PaymentProviderConfig.PROVIDERS:
            obj=PaymentProviderConfig.objects.filter(provider=p).first()
            rows.append({'provider':p,'name':label,'enabled':bool(obj and obj.enabled),'environment':obj.environment if obj else 'test','public_key':obj.public_key if obj else '','has_secret':bool(obj and obj.encrypted_secret_key),'has_webhook_secret':bool(obj and obj.webhook_secret),'configured_at':obj.configured_at if obj else None})
        return Response(rows)
    def post(self, request):
        provider=request.data.get('provider')
        if provider not in dict(PaymentProviderConfig.PROVIDERS): return Response({'detail':'Unsupported payment provider.'},status=400)
        obj,_=PaymentProviderConfig.objects.get_or_create(provider=provider)
        for f in ('enabled','environment','public_key'):
            if f in request.data: setattr(obj,f,request.data[f])
        if 'secret_key' in request.data and request.data['secret_key']:
            obj.encrypted_secret_key=encrypt_secret(request.data['secret_key'])
        if 'webhook_secret' in request.data and request.data['webhook_secret']:
            obj.webhook_secret=encrypt_secret(request.data['webhook_secret'])
        if request.data.get('enabled') and not obj.encrypted_secret_key: return Response({'detail':'A secret/API key is required before enabling this provider.'},status=400)
        obj.configured_at=timezone.now(); obj.save()
        audit(request.user,'security',f"Updated {obj.get_provider_display()} payment provider settings",None,'payment_provider',obj.id,{'enabled':obj.enabled,'environment':obj.environment})
        return Response({'message':'Payment provider settings saved.','provider':provider,'enabled':obj.enabled,'has_secret':bool(obj.encrypted_secret_key)})


class PlatformPaymentProviderToggleView(APIView):
    permission_classes=[IsPlatformSecretsAdmin]
    def post(self, request, provider):
        obj=get_object_or_404(PaymentProviderConfig,provider=provider)
        enabled=bool(request.data.get('enabled'))
        if enabled and not obj.encrypted_secret_key: return Response({'detail':'Configure an API secret before enabling this provider.'},status=400)
        obj.enabled=enabled; obj.save(update_fields=['enabled','updated_at'])
        audit(request.user,'security',f"{'Enabled' if enabled else 'Disabled'} {obj.get_provider_display()} payments",None,'payment_provider',obj.id,{'enabled':enabled})
        return Response({'enabled':obj.enabled})


class PlatformSubscriptionStatusView(APIView):
    permission_classes=[IsAdminUser]
    def get(self, request, company_id):
        company=get_object_or_404(Company,id=company_id)
        return Response({'company_id':company.id,'company':company.name,'plan':company.plan,'state':subscription_state(company),'employee_limit':company.employee_limit,'user_limit':PLAN_USER_LIMITS.get(company.plan)})


def _verify_paddle_webhook(config, raw, headers, tolerance=300):
    """Verify the Paddle-Signature header (ts=...;h1=...) using the webhook secret.

    h1 is an HMAC-SHA256 hex digest of ``{ts}:{raw_body}`` using the webhook
    secret key. The timestamp is checked against the current time (with a
    generous window so retried deliveries are still accepted) to prevent replay.
    """
    signature = headers.get('Paddle-Signature') or ''
    secret = decrypt_secret(config.webhook_secret) if config.webhook_secret else ''
    if not signature or not secret:
        return False
    parts = {}
    for item in signature.split(';'):
        if '=' in item:
            key, value = item.split('=', 1)
            parts[key] = value
    timestamp = parts.get('ts', '')
    h1 = parts.get('h1', '')
    try:
        ts = int(timestamp)
    except (TypeError, ValueError):
        return False
    if abs(int(timezone.now().timestamp()) - ts) > tolerance:
        return False
    expected = hmac.new(secret.encode(), f'{timestamp}:{raw.decode("utf-8")}'.encode(), hashlib.sha256).hexdigest()
    return bool(h1) and bool(expected) and hmac.compare_digest(expected, h1)


def _paddle_subscription_for(data):
    """Resolve a Subscription from a Paddle webhook payload (transaction or subscription event)."""
    subscription_id = str(data.get('subscription_id') or data.get('id') or '')
    sub = Subscription.objects.filter(external_subscription_id=subscription_id, provider='paddle').select_related('company').first()
    if sub:
        return sub
    reference = ((data.get('custom_data') or {}).get('internal_reference') or '')
    if reference:
        tx = PaymentTransaction.objects.filter(provider='paddle', reference=reference).select_related('subscription').first()
        if tx and tx.subscription:
            return tx.subscription
    return None


class PaymentWebhookView(APIView):
    authentication_classes=[]
    permission_classes=[]
    def post(self, request, provider):
        config = PaymentProviderConfig.objects.filter(provider=provider, enabled=True).first()
        if not config:
            return Response({'detail':'Payment provider is not enabled.'}, status=404)
        from .secrets import decrypt_secret
        secret = decrypt_secret(config.webhook_secret) if config.webhook_secret else ''
        raw = request.body
        if provider == 'flutterwave':
            signature = request.headers.get('Verif-Hash') or request.headers.get('verif-hash') or ''
            if not signature or not secret or not hmac.compare_digest(signature, secret):
                return Response({'detail':'Invalid webhook signature.'},status=401)
        elif provider == 'paystack':
            signature = request.headers.get('X-Paystack-Signature', '')
            signing_secret = decrypt_secret(config.webhook_secret) if config.webhook_secret else decrypt_secret(config.encrypted_secret_key)
            expected = hmac.new(signing_secret.encode(), raw, hashlib.sha512).hexdigest() if signing_secret else ''
            if not signature or not hmac.compare_digest(signature, expected): return Response({'detail':'Invalid webhook signature.'},status=401)
        elif provider == 'stripe':
            signature = request.headers.get('Stripe-Signature', '')
            webhook_secret = decrypt_secret(config.webhook_secret) if config.webhook_secret else ''
            if not signature or not webhook_secret:
                return Response({'detail':'Stripe webhook signing secret is not configured.'},status=401)
            try:
                parts = dict(item.split('=', 1) for item in signature.split(',') if '=' in item)
                timestamp = parts.get('t', '')
                signatures = [value for key,value in (item.split('=', 1) for item in signature.split(',') if '=' in item) if key == 'v1']
                signed_payload = f'{timestamp}.{raw.decode("utf-8")}'
                expected = hmac.new(webhook_secret.encode(), signed_payload.encode(), hashlib.sha256).hexdigest()
                if not timestamp or abs(int(timezone.now().timestamp()) - int(timestamp)) > 300 or not any(hmac.compare_digest(expected, candidate) for candidate in signatures):
                    raise ValueError('invalid signature')
            except (ValueError, TypeError):
                return Response({'detail':'Invalid Stripe webhook signature.'},status=401)
        elif provider == 'paddle':
            if not _verify_paddle_webhook(config, raw, request.headers):
                return Response({'detail':'Invalid Paddle webhook signature.'},status=401)
        event_type = request.data.get('event') or request.data.get('type') or request.data.get('event_type') or ''
        data = request.data.get('data') or {}
        event_id = str(request.data.get('webhook_id') or request.data.get('event_id') or request.headers.get('X-Event-ID') or data.get('id') or uuid.uuid4().hex)
        event, created = PaymentEvent.objects.get_or_create(event_id=event_id, defaults={'provider':provider,'event_type':event_type,'payload':request.data})
        if not created:
            return Response({'received':True,'duplicate':True})
        if provider == 'flutterwave':
            tx_ref = data.get('tx_ref')
            tx = PaymentTransaction.objects.filter(reference=tx_ref).first() if tx_ref else None
            if event_type == 'charge.completed':
                try:
                    from .payment_services import verify_transaction, activate_from_verified_payment
                    verified = verify_transaction(data.get('id'))
                    if not tx:
                        subscription_id = str(data.get('subscription_id') or data.get('subscription') or '')
                        sub = Subscription.objects.filter(external_subscription_id=subscription_id, provider='flutterwave').select_related('company').first() if subscription_id else None
                        if not sub:
                            email = ((data.get('customer') or {}).get('email') or '').lower()
                            sub = Subscription.objects.filter(company__users__email__iexact=email, provider='flutterwave').select_related('company').first()
                        if sub and tx_ref:
                            from decimal import Decimal
                            tx = PaymentTransaction.objects.create(
                                company=sub.company, subscription=sub, provider='flutterwave', reference=tx_ref,
                                provider_transaction_id='', plan=sub.company.plan, billing_cycle=sub.billing_cycle,
                                amount=Decimal(str(data.get('amount', '0'))), currency=str(data.get('currency') or sub.currency).upper(),
                                status='pending', metadata={'recurring': True},
                            )
                    if tx:
                        activate_from_verified_payment(tx, verified)
                        event.status = 'processed'
                except Exception as exc:
                    event.status = 'verification_failed'
                    event.payload = {**request.data, '_error': str(exc)}
            elif event_type in ('charge.failed', 'charge.failed.completed'):
                email = ((data.get('customer') or {}).get('email') or '').lower()
                sub = Subscription.objects.filter(company__users__email__iexact=email, provider='flutterwave').first()
                if sub:
                    sub.status='past_due'; sub.grace_ends_at=timezone.now()+timezone.timedelta(days=7); sub.failed_payment_count = (sub.failed_payment_count or 0) + 1; sub.save(update_fields=['status','grace_ends_at','failed_payment_count','updated_at'])
                    event.status='processed'
            elif event_type == 'subscription.cancelled':
                email = ((data.get('customer') or {}).get('email') or '').lower()
                sub = Subscription.objects.filter(company__users__email__iexact=email, provider='flutterwave').first()
                if sub:
                    sub.status='cancelled'; sub.cancelled_at=timezone.now(); sub.save(update_fields=['status','cancelled_at','updated_at'])
                    event.status='processed'
        if provider == 'paddle':
            if event_type in ('transaction.completed', 'transaction.paid', 'transaction.billed'):
                try:
                    from .payment_services import paddle_activate_from_verified
                    tx = None
                    transaction_id = str(data.get('id') or '')
                    reference = ((data.get('custom_data') or {}).get('internal_reference') or '')
                    if transaction_id:
                        tx = PaymentTransaction.objects.filter(provider='paddle', provider_transaction_id=transaction_id).first()
                    if not tx and reference:
                        tx = PaymentTransaction.objects.filter(provider='paddle', reference=reference).first()
                    if not tx:
                        # Renewal payment for an active subscription: no local
                        # PaymentTransaction exists yet, so derive one from the
                        # subscription before activating.
                        sub = _paddle_subscription_for(data)
                        if sub:
                            from decimal import Decimal
                            totals = (data.get('details') or {}).get('totals') or {}
                            amount = Decimal(str(totals['grand_total'])) / Decimal('100') if totals.get('grand_total') is not None else sub.monthly_price
                            tx = PaymentTransaction.objects.create(
                                company=sub.company, subscription=sub, provider='paddle',
                                reference=reference or f'HCP-{uuid.uuid4().hex[:24].upper()}',
                                provider_transaction_id=transaction_id, plan=sub.company.plan,
                                billing_cycle=sub.billing_cycle, amount=amount,
                                currency=str(data.get('currency_code') or sub.currency).upper(),
                                status='pending', metadata={'recurring': True},
                            )
                    if tx:
                        ok = paddle_activate_from_verified(tx, data)
                        event.status = 'processed' if ok else 'verification_failed'
                except Exception as exc:
                    event.status = 'verification_failed'
                    event.payload = {**request.data, '_error': str(exc)}
            elif event_type == 'subscription.activated':
                # The subscription entity has no transaction totals; activation
                # itself is authoritative that billing succeeded.
                try:
                    sub = None
                    subscription_id = str(data.get('id') or '')
                    if subscription_id:
                        sub = Subscription.objects.filter(external_subscription_id=subscription_id).first()
                    if not sub:
                        reference = ((data.get('custom_data') or {}).get('internal_reference') or '')
                        if reference:
                            pending_tx = PaymentTransaction.objects.filter(provider='paddle', reference=reference, status='paid').select_related('subscription').first()
                            if pending_tx:
                                sub = pending_tx.subscription
                    if sub:
                        now = timezone.now()
                        sub.status = 'active'
                        sub.provider = 'paddle'
                        sub.external_subscription_id = str(data.get('id') or sub.external_subscription_id or '')
                        if not sub.current_period_start:
                            sub.current_period_start = now
                            sub.current_period_end = now + timezone.timedelta(days=30 if sub.billing_cycle == 'monthly' else 365)
                            sub.renews_at = sub.current_period_end
                        sub.cancelled_at = None
                        sub.grace_ends_at = None
                        sub.cancel_at_period_end = False
                        sub.cancellation_reason = ''
                        sub.last_payment_at = sub.last_payment_at or now
                        sub.save()
                        event.status = 'processed'
                except Exception as exc:
                    event.status = 'verification_failed'
                    event.payload = {**request.data, '_error': str(exc)}
            elif event_type in ('transaction.payment_failed', 'subscription.past_due'):
                sub = _paddle_subscription_for(data)
                if sub:
                    sub.status = 'past_due'
                    sub.grace_ends_at = timezone.now() + timezone.timedelta(days=7)
                    sub.failed_payment_count = (sub.failed_payment_count or 0) + 1
                    sub.save(update_fields=['status', 'grace_ends_at', 'failed_payment_count', 'updated_at'])
                    event.status = 'processed'
            elif event_type == 'subscription.canceled':
                sub = _paddle_subscription_for(data)
                if sub:
                    sub.status = 'cancelled'
                    sub.cancelled_at = timezone.now()
                    sub.cancel_at_period_end = False
                    sub.save(update_fields=['status', 'cancelled_at', 'cancel_at_period_end', 'updated_at'])
                    event.status = 'processed'
        event.save(update_fields=['status','payload'])
        return Response({'received':True})


class CompanyBillingCancelView(APIView):
    permission_classes = [IsAuthenticated, IsOwnerOrAdminOnly]
    def post(self, request):
        company = request.user.company
        sub = getattr(company, 'subscription', None)
        if not sub: return Response({'detail': 'No subscription is configured.'}, status=400)
        if sub.status in ('cancelled','expired'): return Response({'detail': 'Subscription is already cancelled.'}, status=400)
        reason = str(request.data.get('reason') or 'Cancelled by company administrator')[:255]
        sub.cancel_at_period_end = True
        sub.cancellation_reason = reason
        sub.save(update_fields=['cancel_at_period_end','cancellation_reason','updated_at'])
        audit(request.user, 'account_status', f'Scheduled subscription cancellation for {company.name}', company, 'subscription', sub.id, {'reason': reason, 'renews_at': sub.renews_at})
        return Response({'message':'Cancellation scheduled. Your plan stays active until the end of the current billing period.','subscription': {'cancel_at_period_end': sub.cancel_at_period_end, 'renews_at': sub.renews_at}})


class CompanyBillingReactivateView(APIView):
    permission_classes = [IsAuthenticated, IsOwnerOrAdminOnly]
    def post(self, request):
        company = request.user.company
        sub = getattr(company, 'subscription', None)
        if not sub: return Response({'detail': 'No subscription is configured.'}, status=400)
        if not sub.cancel_at_period_end: return Response({'message':'Subscription is already set to continue.','cancel_at_period_end':False})
        sub.cancel_at_period_end = False
        sub.cancellation_reason = ''
        sub.save(update_fields=['cancel_at_period_end','cancellation_reason','updated_at'])
        audit(request.user, 'account_status', f'Reactivated subscription for {company.name}', company, 'subscription', sub.id)
        return Response({'message':'The scheduled cancellation has been removed. Your plan will continue as normal.','cancel_at_period_end':False})


class CompanyBillingInvoicesView(APIView):
    permission_classes = [IsAuthenticated, IsOwnerOrAdminOnly]
    def get(self, request):
        company = request.user.company
        rows = BillingInvoice.objects.filter(company=company).select_related('transaction')[:50]
        return Response([{'number':x.number,'plan':x.plan,'billing_cycle':x.billing_cycle,'amount':str(x.amount),'currency':x.currency,'status':x.status,'issued_at':x.issued_at,'paid_at':x.paid_at,'period_start':x.period_start,'period_end':x.period_end,'reference':x.transaction.reference if x.transaction else ''} for x in rows])


class BillingPlansView(APIView):
    permission_classes = [IsAuthenticated]
    def get(self, request):
        from .billing import PLAN_PRICES, PLAN_USER_LIMITS
        return Response([{'id':p,'name':name,'monthly_price':str(PLAN_PRICES[p]),'annual_price':str(PLAN_PRICES[p]*10),'employee_limit':PLAN_EMPLOYEE_LIMITS[p],'user_limit':PLAN_USER_LIMITS[p]} for p,name in Company._meta.get_field('plan').choices])


class CompanyBillingView(APIView):
    permission_classes = [IsAuthenticated, IsOwnerOrAdminOnly]
    def get(self, request):
        company=request.user.company
        if not company: return Response({'detail':'No company is attached to this account.'}, status=400)
        sub=getattr(company,'subscription',None)
        txs=PaymentTransaction.objects.filter(company=company)[:20]
        pending = PaymentTransaction.objects.filter(company=company, provider='paddle', status='pending').order_by('-created_at').first()
        return Response({'state':subscription_state(company),'pending_reference':pending.reference if pending else None,'subscription':{'id':sub.id,'plan':company.plan,'status':sub.status,'provider':sub.provider,'billing_cycle':sub.billing_cycle,'monthly_price':str(sub.monthly_price),'currency':sub.currency,'renews_at':sub.renews_at,'trial_ends_at':sub.trial_ends_at,'grace_ends_at':sub.grace_ends_at,'current_period_start':sub.current_period_start,'current_period_end':sub.current_period_end,'cancel_at_period_end':sub.cancel_at_period_end,'cancellation_reason':sub.cancellation_reason,'last_payment_at':sub.last_payment_at,'failed_payment_count':sub.failed_payment_count} if sub else None,'transactions':[{'reference':x.reference,'plan':x.plan,'billing_cycle':x.billing_cycle,'amount':str(x.amount),'currency':x.currency,'status':x.status,'created_at':x.created_at,'paid_at':x.paid_at} for x in txs]})


class CompanyBillingCheckoutView(APIView):
    permission_classes = [IsAuthenticated, IsOwnerOrAdminOnly]
    def post(self, request):
        company=request.user.company
        if not company: return Response({'detail':'No company is attached to this account.'}, status=400)
        plan=request.data.get('plan')
        cycle=request.data.get('billing_cycle','monthly')
        if plan not in dict(Company._meta.get_field('plan').choices): return Response({'detail':'Invalid plan.'},status=400)
        if plan == 'enterprise': return Response({'detail':'Enterprise plans require a sales agreement.'},status=400)
        if plan != company.plan:
            new_limit = PLAN_EMPLOYEE_LIMITS.get(plan)
            if new_limit is not None and company.employees.count() > new_limit:
                return Response({'detail':f'Cannot downgrade to {plan}: this company currently has {company.employees.count()} employees.'},status=400)
            new_user_limit = PLAN_USER_LIMITS.get(plan)
            if new_user_limit is not None and company.users.filter(is_active=True).count() > new_user_limit:
                return Response({'detail':f'Cannot downgrade to {plan}: this company currently has more than {new_user_limit} active users.'},status=400)
        if cycle not in ('monthly','annual'): return Response({'detail':'Invalid billing cycle.'},status=400)
        provider = str(request.data.get('provider') or '').lower()
        paddle_enabled = PaymentProviderConfig.objects.filter(provider='paddle', enabled=True).exists()
        flw_enabled = PaymentProviderConfig.objects.filter(provider='flutterwave', enabled=True).exists()
        if provider:
            if provider not in ('paddle', 'flutterwave'):
                return Response({'detail':'Unsupported payment provider.'},status=400)
            if provider == 'paddle' and not paddle_enabled:
                return Response({'detail':'Paddle is not enabled by the platform administrator.'},status=400)
            if provider == 'flutterwave' and not flw_enabled:
                return Response({'detail':'Flutterwave is not enabled by the platform administrator.'},status=400)
        else:
            # When the platform enables Paddle it becomes the default checkout
            # provider; otherwise the existing Flutterwave behaviour is kept.
            provider = 'paddle' if paddle_enabled else ('flutterwave' if flw_enabled else '')
            if not provider:
                return Response({'detail':'No payment provider is enabled.'},status=400)
        try:
            if provider == 'paddle':
                from .payment_services import paddle_initialize_checkout
                result = paddle_initialize_checkout(company, request.user, plan, cycle, request.data.get('currency') or 'USD')
            else:
                from .payment_services import initialize_checkout
                result = initialize_checkout(company, request.user, plan, cycle, request.data.get('currency') or 'USD')
            result['provider'] = provider
        except Exception as exc:
            return Response({'detail':str(exc)},status=502)
        return Response(result)


class CompanyBillingVerifyView(APIView):
    permission_classes = [IsAuthenticated, IsOwnerOrAdminOnly]
    def post(self, request):
        reference=request.data.get('reference')
        transaction_id=request.data.get('transaction_id')
        tx=PaymentTransaction.objects.filter(reference=reference, company=request.user.company).first()
        if not tx: return Response({'detail':'Payment transaction not found.'},status=404)
        # Paddle's hosted checkout returns to the success page without query
        # parameters; fall back to the transaction id captured at creation.
        if not transaction_id:
            transaction_id = tx.provider_transaction_id or ''
        if not transaction_id: return Response({'detail':'transaction_id is required.'},status=400)
        try:
            if tx.provider == 'paddle':
                from .payment_services import paddle_verify_transaction, paddle_activate_from_verified
                data=paddle_verify_transaction(transaction_id)
                ok=paddle_activate_from_verified(tx,data)
            else:
                from .payment_services import verify_transaction, activate_from_verified_payment
                data=verify_transaction(transaction_id)
                ok=activate_from_verified_payment(tx,data)
        except Exception as exc:
            return Response({'detail':str(exc)},status=502)
        if not ok: return Response({'detail':'Payment could not be verified.'},status=400)
        return Response({'message':'Payment verified and subscription activated.','state':subscription_state(request.user.company)})



class PlatformCompany360View(APIView):
    permission_classes = [IsAdminUser]
    def get(self, request, company_id):
        company = get_object_or_404(Company, id=company_id)
        sub = Subscription.objects.filter(company=company).first()
        usage = usage_for(company)
        users = list(User.objects.filter(company=company).order_by('username').values('id','username','email','role','is_active','date_joined'))
        transactions = list(PaymentTransaction.objects.filter(company=company).order_by('-created_at')[:25].values('reference','provider_transaction_id','plan','billing_cycle','amount','currency','status','paid_at','created_at'))
        tickets = list(SupportTicket.objects.filter(company=company).order_by('-updated_at')[:10].values('id','subject','status','priority','created_at','updated_at','resolved_at'))
        audit_rows = list(AuditLog.objects.filter(company=company).order_by('-created_at')[:15].values('id','action','message','created_at','actor__username'))
        return Response({
            'company': PlatformCompanySerializer(company).data,
            'usage': usage,
            'subscription': {
                'id': sub.id, 'plan': sub.company.plan, 'status': sub.status, 'provider': sub.provider,
                'billing_cycle': sub.billing_cycle, 'monthly_price': str(sub.monthly_price), 'currency': sub.currency,
                'started_at': sub.started_at, 'renews_at': sub.renews_at, 'trial_ends_at': sub.trial_ends_at,
                'grace_ends_at': sub.grace_ends_at, 'external_subscription_id': sub.external_subscription_id,
            } if sub else None,
            'users': users, 'transactions': transactions, 'tickets': tickets, 'audit': audit_rows,
        })


class PlatformPaymentTransactionsView(APIView):
    permission_classes = [IsAdminUser]
    def get(self, request):
        qs = PaymentTransaction.objects.select_related('company','subscription').order_by('-created_at')
        provider = request.query_params.get('provider')
        state = request.query_params.get('status')
        search = request.query_params.get('search','').strip()
        if provider: qs = qs.filter(provider=provider)
        if state: qs = qs.filter(status=state)
        if search: qs = qs.filter(Q(reference__icontains=search) | Q(company__name__icontains=search) | Q(company__email__icontains=search))
        rows=[]
        for tx in qs[:250]:
            rows.append({'id':tx.id,'company_id':tx.company_id,'company_name':tx.company.name,'reference':tx.reference,'provider':tx.provider,'provider_transaction_id':tx.provider_transaction_id,'plan':tx.plan,'billing_cycle':tx.billing_cycle,'amount':str(tx.amount),'currency':tx.currency,'status':tx.status,'paid_at':tx.paid_at,'created_at':tx.created_at})
        return Response(rows)


class PlatformSystemHealthView(APIView):
    permission_classes = [IsAdminUser]

    # Full chain verification is O(rows); the health endpoint samples instead.
    AUDIT_HEALTH_SAMPLE = 200

    @staticmethod
    def _verify_audit_chain():
        """Recompute the chain digest for a bounded sample of records.

        This replaces a check that only tested for blank hashes, which could
        not detect a modified record. A sample is honest about its scope:
        `manage.py verify_audit_chain` is the exhaustive check.
        """
        from accounts.audit_chain import verify_chain
        try:
            result = verify_chain(limit=PlatformSystemHealthView.AUDIT_HEALTH_SAMPLE, max_errors=5)
        except Exception as exc:
            return {'key':'audit','name':'Audit chain','status':'critical','detail':f'Audit chain could not be verified: {exc}'}
        if not result['ok']:
            first = result['problems'][0]
            return {
                'key':'audit','name':'Audit chain','status':'critical',
                'detail':f"Audit chain integrity failure at sequence {first['sequence']}: {first['detail']} "
                         f"({len(result['problems'])} problem(s) in the first {result['checked']} record(s)). "
                         f"Run `manage.py verify_audit_chain` for the full result.",
                'problems': result['problems'],
            }
        return {
            'key':'audit','name':'Audit chain','status':'healthy',
            'detail':f"Integrity hashes recomputed and matched for the first {result['checked']} record(s) "
                     f"of {result['head_sequence']} in the chain. Run `manage.py verify_audit_chain` to verify the whole chain.",
            'sampled': result['checked'],
            'chain_length': result['head_sequence'],
        }

    @staticmethod
    def _check_storage():
        """Where uploaded files actually go, and whether that place survives.

        Nothing else in this view could answer that. S3 support is complete and
        switches on when AWS_STORAGE_BUCKET_NAME is set; with it unset every
        upload lands in the container's MEDIA_ROOT, which a redeploy replaces
        wholesale. Nothing errors, no upload fails, and the console reports
        healthy right up until the contracts and national ID scans a tenant
        uploaded are gone.

        So the check is about the destination, not about whether writing works:
        writing to local disk always works, and works perfectly, right up to
        the rebuild.
        """
        from django.conf import settings
        from django.core.files.storage import default_storage

        backend = default_storage.__class__.__name__
        bucket = getattr(settings, 'AWS_STORAGE_BUCKET_NAME', '')

        if bucket:
            return {
                'key': 'storage', 'name': 'File storage', 'status': 'healthy',
                'detail': f'Uploads are stored in the S3 bucket {bucket}, which '
                          f'survives a redeploy.',
                'backend': backend, 'bucket': bucket,
            }

        detail = (
            'Uploads are stored on this container\'s local disk. Every employee '
            'contract, document and ID scan is deleted by the next rebuild. Set '
            'AWS_STORAGE_BUCKET_NAME (plus AWS_S3_REGION_NAME and the access '
            'key) to move them to object storage.'
        )
        if settings.DEBUG:
            return {
                'key': 'storage', 'name': 'File storage', 'status': 'warning',
                'detail': 'Local disk storage, which is expected in development.',
                'backend': backend, 'bucket': None,
            }
        return {
            'key': 'storage', 'name': 'File storage', 'status': 'critical',
            'detail': detail, 'backend': backend, 'bucket': None,
        }

    def get(self, request):
        from django.db import connection
        checks=[]
        try:
            with connection.cursor() as cursor:
                cursor.execute('SELECT 1')
                cursor.fetchone()
            checks.append({'key':'database','name':'Database','status':'healthy','detail':'Database connection is responding.'})
        except Exception as exc:
            checks.append({'key':'database','name':'Database','status':'critical','detail':str(exc)})
        checks.append(self._check_storage())
        providers = PaymentProviderConfig.objects.filter(enabled=True)
        checks.append({'key':'payments','name':'Payment providers','status':'healthy' if providers.exists() else 'warning','detail':f'{providers.count()} provider(s) enabled.'})
        checks.append({'key':'webhooks','name':'Webhook processing','status':'healthy' if PaymentEvent.objects.filter(status='received').count() < 25 else 'warning','detail':f"{PaymentEvent.objects.filter(status='received').count()} unprocessed event(s)."})
        audit_check = self.__class__._verify_audit_chain()
        checks.append(audit_check)
        checks.append({'key':'subscriptions','name':'Subscription operations','status':'warning' if Subscription.objects.filter(status='past_due').exists() else 'healthy','detail':f"{Subscription.objects.filter(status='past_due').count()} past-due subscription(s)."})
        return Response({'status':'healthy' if all(x['status']=='healthy' for x in checks) else 'attention_required','checks':checks,'generated_at':timezone.now()})


class PlatformSecurityCenterView(APIView):
    permission_classes = [IsAdminUser]
    def get(self, request):
        failed = AuditLog.objects.filter(action='login_failed').count()
        security = AuditLog.objects.filter(action__in=['security','permission_change','account_status']).order_by('-created_at')[:30]
        active_staff = User.objects.filter(is_staff=True,is_active=True).count()
        superusers = User.objects.filter(is_superuser=True,is_active=True).count()
        total_records = AuditLog.objects.count()
        verified = verify_chain(limit=200, max_errors=5)
        return Response({
            'failed_logins_total':failed,
            'active_staff_admins':active_staff,
            'active_superusers':superusers,
            # A row count is not immutability, so the record count and the
            # independently recomputed digest check are reported separately.
            'audit_records_total':total_records,
            'audit_chain_verified':verified['ok'],
            'audit_chain_verified_sample':verified['checked'],
            'audit_chain_length':verified['head_sequence'],
            'audit_chain_problems':verified['problems'],
            'recent_events':[{'id':x.id,'action':x.action,'message':x.message,'actor':x.actor.username if x.actor else 'System','company':x.company.name if x.company else 'Platform','created_at':x.created_at} for x in security],
        })


class PlatformFeatureFlagsView(APIView):
    permission_classes = [IsAdminUser]
    def get(self, request):
        from .features import ensure_default_flags
        ensure_default_flags()
        return Response([{'id':x.id,'key':x.key,'name':x.name,'description':x.description,'enabled':x.enabled,'rollout_percent':x.rollout_percent,'environment':x.environment,'updated_at':x.updated_at} for x in FeatureFlag.objects.all()])
    def post(self, request):
        key=request.data.get('key','').strip().lower(); name=request.data.get('name','').strip()
        if not key or not name: return Response({'detail':'key and name are required.'},status=400)
        environment=request.data.get('environment','all')
        if environment not in dict(FeatureFlag.ENVIRONMENTS):
            return Response({'detail':'Invalid feature flag environment.'},status=400)
        try:
            flag=FeatureFlag.objects.create(key=key,name=name,description=request.data.get('description',''),enabled=bool(request.data.get('enabled',False)),rollout_percent=max(0,min(100,int(request.data.get('rollout_percent',100)))),environment=environment)
        except Exception as exc: return Response({'detail':str(exc)},status=400)
        audit(request.user,'system',f'Created feature flag {flag.key}',None,'feature_flag',flag.id,{'enabled':flag.enabled})
        return Response({'id':flag.id,'key':flag.key,'name':flag.name,'description':flag.description,'enabled':flag.enabled,'rollout_percent':flag.rollout_percent,'environment':flag.environment},status=201)


class PlatformFeatureFlagDetailView(APIView):
    permission_classes = [IsAdminUser]
    def patch(self, request, flag_id):
        flag=get_object_or_404(FeatureFlag,id=flag_id)
        for field in ('name','description'):
            if field in request.data: setattr(flag,field,request.data[field])
        if 'environment' in request.data:
            if request.data['environment'] not in dict(FeatureFlag.ENVIRONMENTS):
                return Response({'detail':'Invalid feature flag environment.'},status=400)
            flag.environment=request.data['environment']
        if 'enabled' in request.data: flag.enabled=bool(request.data['enabled'])
        if 'rollout_percent' in request.data: flag.rollout_percent=max(0,min(100,int(request.data['rollout_percent'])))
        flag.save()
        audit(request.user,'system',f'Updated feature flag {flag.key}',None,'feature_flag',flag.id,{'enabled':flag.enabled,'rollout_percent':flag.rollout_percent})
        return Response({'id':flag.id,'key':flag.key,'name':flag.name,'description':flag.description,'enabled':flag.enabled,'rollout_percent':flag.rollout_percent,'environment':flag.environment})


class PlatformSupportDetailView(APIView):
    permission_classes=[IsAdminUser]
    def patch(self, request, ticket_id):
        ticket=get_object_or_404(SupportTicket,id=ticket_id)
        valid_status={value for value,_ in SupportTicket.STATUS}
        valid_priority={value for value,_ in SupportTicket.PRIORITY}
        if 'status' in request.data and request.data['status'] not in valid_status:
            return Response({'status':'Invalid support ticket status.'},status=400)
        if 'priority' in request.data and request.data['priority'] not in valid_priority:
            return Response({'priority':'Invalid support ticket priority.'},status=400)
        if 'status' in request.data: ticket.status=request.data['status']
        if 'priority' in request.data: ticket.priority=request.data['priority']
        if 'assigned_to' in request.data:
            assigned_id=request.data['assigned_to']
            ticket.assigned_to=None if assigned_id in (None,'',0,'0') else get_object_or_404(User,id=assigned_id,is_staff=True)
        if ticket.status=='resolved' and not ticket.resolved_at: ticket.resolved_at=timezone.now()
        if ticket.status!='resolved': ticket.resolved_at=None
        ticket.save()
        audit(request.user,'update',f'Updated support ticket {ticket.id}',ticket.company,'support_ticket',ticket.id,{'status':ticket.status,'priority':ticket.priority,'assigned_to':ticket.assigned_to_id})
        return Response({'id':ticket.id,'status':ticket.status,'priority':ticket.priority,'assigned_to':ticket.assigned_to_id,'resolved_at':ticket.resolved_at})


class PlatformGlobalSearchView(APIView):
    permission_classes=[IsAdminUser]
    def get(self,request):
        q=request.query_params.get('q','').strip()
        if len(q)<2: return Response({'companies':[],'users':[],'transactions':[],'tickets':[]})
        companies=Company.objects.filter(Q(name__icontains=q)|Q(email__icontains=q)|Q(country__icontains=q))[:8]
        users=User.objects.filter(Q(username__icontains=q)|Q(email__icontains=q)|Q(company__name__icontains=q))[:8]
        txs=PaymentTransaction.objects.filter(Q(reference__icontains=q)|Q(company__name__icontains=q))[:8]
        tickets=SupportTicket.objects.filter(Q(subject__icontains=q)|Q(company__name__icontains=q))[:8]
        return Response({'companies':[{'id':x.id,'name':x.name,'email':x.email} for x in companies],'users':[{'id':x.id,'username':x.username,'email':x.email,'company':x.company.name if x.company else 'Platform'} for x in users],'transactions':[{'id':x.id,'reference':x.reference,'company':x.company.name,'status':x.status,'amount':str(x.amount),'currency':x.currency} for x in txs],'tickets':[{'id':x.id,'subject':x.subject,'company':x.company.name,'status':x.status} for x in tickets]})


class PublicMarketingPageView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, slug):
        page = get_object_or_404(MarketingPage, slug=slug, is_published=True)
        # Prices and capacity are derived from the billing tables on the way
        # out, so the pricing page cannot advertise a plan it would refuse to
        # sell. See hrcloudpay.pricing_sync for why the stored row is left alone.
        content = derived_content(page.content)
        return Response({'slug': page.slug, 'name': page.name, 'content': content, 'updated_at': page.updated_at})


class PlatformMarketingPagesView(APIView):
    permission_classes = [IsAdminUser]
    schema = None  # Exclude from drf-spectacular OpenAPI generation

    def get(self, request):
        pages = MarketingPage.objects.select_related('updated_by').all()
        return Response({
            'pages': [self.serialize(page) for page in pages],
            # The section schema travels with the page list so the admin editor
            # builds its form from the same definitions the validator uses.
            # Duplicating these in JSX is how a field ends up accepted by the
            # backend and missing from the form the admin actually sees.
            'schema': self.get_marketing_schema(),
        })

    @staticmethod
    def get_marketing_schema():
        return {
            'sections': {
                name: {
                    'label': definition['label'],
                    'hint': definition['hint'],
                    'fields': {
                        field: {'kind': kind, 'limit': limit}
                        for field, (kind, limit) in definition['fields'].items()
                    },
                    'repeated': (
                        {
                            'key': repeated['key'],
                            'item_label': repeated['item_label'],
                            'fields': {
                                field: {'kind': kind, 'limit': limit}
                                for field, (kind, limit) in repeated['fields'].items()
                            },
                            'item_list': repeated.get('item_list'),
                            'item_extra': repeated.get('item_extra'),
                        }
                        if (repeated := definition.get('repeated')) else None
                    ),
                    'notes': (
                        {
                            'key': notes['key'],
                            'item_label': notes['item_label'],
                            'fields': {
                                field: {'kind': kind, 'limit': limit}
                                for field, (kind, limit) in notes['fields'].items()
                            },
                        }
                        if (notes := definition.get('notes')) else None
                    ),
                }
                for name, definition in SECTION_TYPES.items()
            },
            'max_sections': MAX_SECTIONS,
            'max_repeated': MAX_REPEATED,
        }

    def post(self, request):
        """Create a page.

        Without this the only way to add a slug to the content system was a
        migration or a shell, so "manage pages" meant "edit the two that happen
        to exist". Content is validated here as well as on patch, because a page
        created with a section type the public renderer cannot draw would break
        the first visitor who loads it.
        """
        slug = (request.data.get('slug') or '').strip()
        name = str(request.data.get('name') or '').strip()

        errors = {}
        if not is_valid_slug(slug):
            errors['slug'] = (
                'Use lowercase letters, numbers and single hyphens, up to 80 '
                'characters (for example: payroll-product).'
            )
        elif MarketingPage.objects.filter(slug=slug).exists():
            errors['slug'] = 'A page with this slug already exists.'
        if not name or len(name) > 160:
            errors['name'] = 'A name is required, 160 characters or fewer.'

        if 'content' in request.data:
            content, blocking, _ = validate_content(request.data.get('content'))
            if blocking:
                errors['content'] = blocking
        else:
            # Start from a hero so a newly created page renders a headline
            # rather than a blank band.
            content = blank_content()

        if errors:
            return Response(errors, status=400)

        with transaction.atomic():
            page = MarketingPage.objects.create(
                slug=slug,
                name=name,
                content=content,
                is_published=bool(request.data.get('is_published', False)),
                updated_by=request.user,
            )
        audit(request.user, 'create', f'Created marketing page {page.slug}',
              None, 'marketing_page', page.slug)
        return Response(self.serialize(page), status=201)

    @staticmethod
    def serialize(page):
        return {
            'slug': page.slug,
            'name': page.name,
            'content': page.content,
            'draft_content': page.draft_content,
            'draft_name': page.draft_name,
            'draft_is_published': page.draft_is_published,
            'has_draft': page.draft_content is not None or bool(page.draft_name),
            'is_published': page.is_published,
            'updated_at': page.updated_at,
            'updated_by': page.updated_by.username if page.updated_by else None,
        }


class PlatformMarketingPageDetailView(APIView):
    permission_classes = [IsAdminUser]

    def patch(self, request, slug):
        page = get_object_or_404(MarketingPage, slug=slug)
        action_name = request.data.get('action', 'save_draft')
        if action_name == 'publish':
            if page.draft_content is not None:
                page.content = page.draft_content
            if page.draft_name:
                page.name = page.draft_name
            if page.draft_is_published is not None:
                page.is_published = page.draft_is_published
            elif 'is_published' in request.data:
                page.is_published = bool(request.data['is_published'])
            page.draft_content = None
            page.draft_name = ''
            page.draft_is_published = None
            page.updated_by = request.user
            page.save(update_fields=['content', 'name', 'draft_content', 'draft_name', 'draft_is_published', 'is_published', 'updated_by', 'updated_at'])
            audit(request.user, 'update', f'Published marketing page {page.slug}', None, 'marketing_page', page.slug, {'action': 'publish'})
            return Response(PlatformMarketingPagesView.serialize(page))
        if action_name == 'discard_draft':
            if page.draft_is_published is not None:
                page.is_published = page.draft_is_published
            elif 'is_published' in request.data:
                page.is_published = bool(request.data['is_published'])
            page.draft_content = None
            page.draft_name = ''
            page.draft_is_published = None
            page.updated_by = request.user
            page.save(update_fields=['draft_content', 'draft_name', 'draft_is_published', 'updated_by', 'updated_at'])
            audit(request.user, 'update', f'Discarded draft for marketing page {page.slug}', None, 'marketing_page', page.slug, {'action': 'discard_draft'})
            return Response(PlatformMarketingPagesView.serialize(page))

        # Content is validated against the schema rather than merely checked for
        # being a dict. An unknown section type used to be accepted here, stored
        # as a draft, and then published - after which the public renderer had no
        # branch to draw it and the page rendered with a hole in it. Validation
        # also refuses links the content path would render as a live `href`.
        content, blocking, _ = validate_content(
            request.data.get(
                'content',
                page.draft_content if page.draft_content is not None else page.content,
            )
        )
        if blocking:
            return Response({'content': blocking}, status=400)
        name = str(request.data.get('name', page.draft_name or page.name)).strip()
        if not name or len(name) > 160:
            return Response({'name': 'Name is required and must be 160 characters or fewer.'}, status=400)
        page.draft_content = content
        page.draft_name = name
        page.draft_is_published = bool(request.data.get('is_published', page.draft_is_published if page.draft_is_published is not None else page.is_published))
        page.updated_by = request.user
        page.save(update_fields=['draft_content', 'draft_name', 'draft_is_published', 'updated_by', 'updated_at'])
        audit(request.user, 'update', f'Saved draft for marketing page {page.slug}', None, 'marketing_page', page.slug, {'action': 'save_draft'})
        return Response(PlatformMarketingPagesView.serialize(page))

    def delete(self, request, slug):
        """Remove a page entirely.

        The homepage slug is protected. Deleting it would not raise an error -
        `Home.jsx` swallows the 404 and falls back to its hardcoded copy - so
        the managed layer would quietly disappear from the site with nothing in
        the logs to point at the cause. Failing loudly is the better behaviour.
        """
        if slug == 'home':
            return Response(
                {
                    'slug': 'The homepage cannot be deleted. Unpublish it '
                            'instead if you want to stop serving managed content.'
                },
                status=400,
            )
        page = get_object_or_404(MarketingPage, slug=slug)
        # The delete and its audit record commit together. If the audit write
        # fails, the page is not removed either - a public page that vanished
        # with no trace of who removed it is worse than a failed request.
        with transaction.atomic():
            page.delete()
            audit(request.user, 'delete', f'Deleted marketing page {slug}',
                  None, 'marketing_page', slug)
        return Response({'deleted': slug})

class PlatformSiteBrandingView(APIView):
    """Upload or clear the site's favicon and iOS home-screen icon.

    Both files are re-encoded through ``hrcloudpay.site_icons`` before being
    stored, so what is persisted is exactly what will be served: a PNG at a sane
    size with no EXIF or ICC payload. Storing the normalised form rather than the
    raw upload means the validation performed here is the validation that
    actually holds - there is no second, unchecked path from disk to browser.
    """

    permission_classes = [IsAdminUser]

    def _state(self, request):
        branding = SiteBranding.objects.first()
        return {
            'has_favicon': bool(branding and branding.favicon),
            'has_apple_touch_icon': bool(branding and branding.apple_touch_icon),
            'favicon_url': request.build_absolute_uri(reverse('site-favicon')),
            'apple_touch_icon_url': request.build_absolute_uri(
                reverse('site-apple-touch-icon')
            ),
            'updated_at': branding.updated_at if branding else None,
            'updated_by': (
                branding.updated_by.username
                if branding and branding.updated_by else None
            ),
            'limits': {
                'max_upload_bytes': MAX_UPLOAD_BYTES,
                'favicon_max_edge': FAVICON_MAX_EDGE,
                'apple_touch_icon_size': APPLE_TOUCH_ICON_SIZE,
                'accepted_formats': 'PNG, JPEG, WebP, GIF or ICO (SVG is refused)',
            },
        }

    def get(self, request):
        return Response(self._state(request))

    def post(self, request):
        from django.core.files.base import ContentFile

        branding, _created = SiteBranding.objects.get_or_create(pk=1)

        # Re-encoded up front so that a bad second file does not leave the first
        # one already replaced.
        prepared = {}
        for field, apple in (('favicon', False), ('apple_touch_icon', True)):
            upload = request.FILES.get(field)
            if upload is None:
                continue
            try:
                png = normalise_site_icon(upload.read(), apple_touch=apple)
            except SiteIconError as exc:
                return Response({'detail': str(exc), 'field': field}, status=400)
            prepared[field] = png

        if not prepared:
            return Response(
                {'detail': 'No file was uploaded. Send the icon as the '
                           '`favicon` or `apple_touch_icon` field.'},
                status=400,
            )

        with transaction.atomic():
            for field, png in prepared.items():
                # Replaced rather than accumulated. Skipping this leaves an
                # orphan object in the bucket on every re-upload, which stays
                # invisible until someone looks at a storage bill.
                previous = getattr(branding, field)
                if previous:
                    previous.delete(save=False)
                # The extension is fixed because these bytes are a PNG produced
                # a moment ago; keeping the uploader's name would misrepresent
                # what is stored.
                stem = 'favicon' if field == 'favicon' else 'apple-touch-icon'
                setattr(branding, field, ContentFile(png, name=f'{stem}.png'))
            branding.updated_by = request.user
            branding.save()

        audit(request.user, 'update', 'Updated site branding (site icon).', None,
              'site_branding', branding.id,
              {'fields': sorted(prepared.keys())}, request=request)
        return Response(self._state(request))

    def delete(self, request):
        which = request.query_params.get('field', 'favicon')
        if which not in ('favicon', 'apple_touch_icon'):
            return Response({'detail': f'Unknown field {which!r}.'}, status=400)

        branding = SiteBranding.objects.first()
        if branding is None or not getattr(branding, which):
            return Response({'detail': 'Nothing to remove.'}, status=400)

        getattr(branding, which).delete(save=False)
        setattr(branding, which, None)
        branding.updated_by = request.user
        branding.save(update_fields=[which, 'updated_by', 'updated_at'])

        audit(request.user, 'delete', f'Removed site icon: {which}.', None,
              'site_branding', branding.id, {'field': which}, request=request)
        return Response(self._state(request))


class PlatformAIConfigView(APIView):
    permission_classes = [IsPlatformSecretsAdmin]

    def get(self, request):
        from ai.models import AIProviderConfig
        from ai.providers import as_catalogue, get_spec
        config = AIProviderConfig.objects.filter(is_active=True).first() or AIProviderConfig.objects.first()
        if not config:
            return Response({
                'configured': False, 'provider': 'nvidia_nim',
                'providers': as_catalogue(), 'embeddings_configured': False,
            })
        # Reported so the console can say, before anyone indexes a knowledge
        # base, whether the thing that can embed is configured at all. The
        # active provider may be OpenRouter, which cannot embed.
        embedder = AIProviderConfig.objects.filter(
            provides_embeddings=True).exclude(api_key_encrypted='').first()
        spec = get_spec(config.provider)
        return Response({
            'configured': bool(config.api_key_encrypted),
            'provider': config.provider,
            'providers': as_catalogue(),
            'provides_embeddings': config.provides_embeddings,
            'embeddings_configured': bool(embedder),
            'embeddings_provider': embedder.display_name if embedder else None,
            'provider_notes': spec.notes,
            'model_examples': list(spec.model_examples),
            'display_name': config.display_name,
            'chat_api_url': config.chat_api_url,
            'embeddings_api_url': config.embeddings_api_url,
            'chat_model': config.chat_model,
            'embedding_model': config.embedding_model,
            'temperature': config.temperature,
            'max_tokens': config.max_tokens,
            'request_timeout_seconds': config.request_timeout_seconds,
            'is_active': config.is_active,
            'api_key_set': bool(config.api_key_encrypted),
            'updated_at': config.updated_at,
        })

    def post(self, request):
        from ai.models import AIProviderConfig
        from ai.nvidia import chat_completion, NVIDIAError
        from ai.providers import PROVIDERS, get_spec
        config = AIProviderConfig.objects.first()
        if not config:
            config = AIProviderConfig()
        # Choosing a provider applies its endpoints, models and capability
        # flag. `config.provider = 'nvidia_nim'` used to run unconditionally
        # on every save, so the field was not merely hidden from the console -
        # the database could not hold any other answer.
        #
        # Only on an actual change, and only to fields the request did not
        # also send: an operator who picked a model must not have it
        # overwritten by the preset the next time they save an unrelated field.
        requested = str(request.data.get('provider') or '').strip()
        if requested and requested in PROVIDERS and requested != config.provider:
            spec = get_spec(requested)
            config.provider = requested
            config.display_name = spec.label
            config.provides_embeddings = spec.provides_embeddings
            for field, value in (
                    ('chat_api_url', spec.chat_api_url),
                    ('embeddings_api_url', spec.embeddings_api_url),
                    ('chat_model', spec.default_chat_model),
                    ('embedding_model', spec.default_embedding_model)):
                if field not in request.data:
                    setattr(config, field, value)
        for field in ('display_name', 'chat_api_url', 'embeddings_api_url', 'chat_model', 'embedding_model'):
            if field in request.data:
                value = str(request.data.get(field) or '').strip()
                # A provider with no embeddings endpoint must not keep the
                # previous provider's URL: it would look configured, and the
                # knowledge base would post to a host that never had the path.
                if field == 'embeddings_api_url' and not config.provides_embeddings:
                    value = ''
                setattr(config, field, value)
        for field in ('temperature', 'max_tokens', 'request_timeout_seconds'):
            if field in request.data:
                try:
                    value = float(request.data[field]) if field == 'temperature' else int(request.data[field])
                except (TypeError, ValueError):
                    return Response({'detail': f'Invalid {field}.'}, status=400)
                setattr(config, field, value)
        if 'is_active' in request.data:
            config.is_active = bool(request.data['is_active'])
        api_key = str(request.data.get('api_key') or '').strip()
        if api_key:
            config.set_api_key(api_key)
        # Activating one row deactivates the others, in the same transaction
        # as the save. Resolution is `.filter(is_active=True).first()`, so two
        # actives left the winner to whichever row the database happened to
        # return - not reproducible between a query and its replica, and with
        # nothing in the interface indicating a choice had been made.
        #
        # Enforced here rather than as a unique constraint because is_active
        # defaults to True, which makes such a constraint mean a second row
        # can never be created at all - it broke a data migration that moves
        # rows onto live models.
        with transaction.atomic():
            if config.is_active:
                AIProviderConfig.objects.exclude(pk=config.pk).filter(
                    is_active=True).update(is_active=False)
            config.save()
        # The AI provider configuration is site-wide and has no company, so the audit
        # row must not be given one. Passing `config` here assigned a non-Company to
        # AuditLog.company and raised ValueError, which surfaced as a 500 *after* the
        # save had already committed - the admin saw a failure for a change that
        # actually succeeded. Matches PlatformAITestView below.
        audit(request.user, 'platform_ai_config', 'Updated NVIDIA AI configuration.', None, 'ai_provider_config', config.id, {'api_key_changed': bool(api_key), 'chat_model': config.chat_model, 'embedding_model': config.embedding_model})
        return self.get(request)


class PlatformAITestView(APIView):
    permission_classes = [IsPlatformSecretsAdmin]

    def post(self, request):
        from ai.nvidia import chat_completion, NVIDIAError
        try:
            result = chat_completion([
                {'role': 'system', 'content': 'You are a connection test. Reply with exactly: HRCloudPay NVIDIA AI connection successful.'},
                {'role': 'user', 'content': 'Test the configured AI connection.'},
            ], max_tokens=60, temperature=0)
            content = result.get('choices', [{}])[0].get('message', {}).get('content', '').strip()
            audit(request.user, 'platform_ai_test', 'Tested NVIDIA AI connection.', None, 'ai_provider_config', None, {'success': True})
            return Response({'success': True, 'message': content or 'NVIDIA AI connection successful.'})
        except NVIDIAError as exc:
            audit(request.user, 'platform_ai_test', 'NVIDIA AI connection test failed.', None, 'ai_provider_config', None, {'success': False})
            return Response({'success': False, 'detail': str(exc)}, status=503)


class PlatformEmailConfigView(APIView):
    """Read or update the site-wide SMTP settings.

    The SMTP password is write-only. GET reports `password_set` and never the
    value; POST accepts a new one and leaves the stored secret untouched when
    the field is absent or blank, so a form that does not re-send the password
    on every save does not wipe it.

    The audit row records `password_changed` as a boolean for the same reason -
    an audit trail is read by more people than the settings screen, and a
    credential in it is a credential leaked.
    """

    permission_classes = [IsPlatformSecretsAdmin]

    def _state(self):
        from .platform_models import EmailConfig

        config = EmailConfig.objects.first()
        if not config:
            return {
                'configured': False,
                'in_use': False,
                'host': '',
                'port': 587,
                'username': '',
                'password_set': False,
                'use_tls': True,
                'use_ssl': False,
                'from_email': '',
                'timeout_seconds': 30,
                'is_active': False,
                'updated_at': None,
                'updated_by': None,
            }
        return {
            'configured': bool(config.host),
            # What the running app will actually do right now. `configured` alone
            # is not enough: a saved-but-inactive row looks complete on the form
            # while mail still goes to the console.
            'in_use': config.usable,
            'host': config.host,
            'port': config.port,
            'username': config.username,
            'password_set': config.password_set,
            'use_tls': config.use_tls,
            'use_ssl': config.use_ssl,
            'from_email': config.from_email,
            'timeout_seconds': config.timeout_seconds,
            'is_active': config.is_active,
            'updated_at': config.updated_at,
            'updated_by': config.updated_by.username if config.updated_by else None,
        }

    def get(self, request):
        return Response(self._state())

    def post(self, request):
        from .platform_models import EmailConfig

        data = request.data
        errors = {}

        host = data.get('host')
        if host is not None:
            host = str(host).strip()
            if host and len(host) > 255:
                errors['host'] = 'Host name is too long.'

        port = data.get('port')
        parsed_port = None
        if port is not None and str(port).strip() != '':
            try:
                parsed_port = int(port)
            except (TypeError, ValueError):
                errors['port'] = 'Port must be a whole number.'
            else:
                if not 1 <= parsed_port <= 65535:
                    errors['port'] = 'Port must be between 1 and 65535.'

        timeout = data.get('timeout_seconds')
        parsed_timeout = None
        if timeout is not None and str(timeout).strip() != '':
            try:
                parsed_timeout = int(timeout)
            except (TypeError, ValueError):
                errors['timeout_seconds'] = 'Timeout must be a whole number of seconds.'
            else:
                if not 1 <= parsed_timeout <= 300:
                    errors['timeout_seconds'] = 'Timeout must be between 1 and 300 seconds.'

        use_tls = data.get('use_tls')
        use_ssl = data.get('use_ssl')
        if use_tls is not None and use_ssl is not None:
            if bool(use_tls) and bool(use_ssl):
                # smtplib cannot do both: SMTP_SSL is already encrypted, and
                # starttls() on that socket raises. Catching it here beats a
                # 500 on the first send after saving.
                errors['use_ssl'] = (
                    'Choose either STARTTLS or SSL, not both. SSL is usually '
                    'port 465; STARTTLS is usually port 587.'
                )

        from_email = data.get('from_email')
        if from_email is not None:
            from_email = str(from_email).strip()
            if from_email and '@' not in from_email:
                errors['from_email'] = 'Enter a valid email address.'

        password = str(data.get('password') or '').strip()

        if errors:
            return Response({'detail': 'Please correct the highlighted fields.',
                             'errors': errors}, status=400)

        config = EmailConfig.objects.first() or EmailConfig()
        if host is not None:
            config.host = host
        if parsed_port is not None:
            config.port = parsed_port
        if data.get('username') is not None:
            config.username = str(data.get('username')).strip()
        if from_email is not None:
            config.from_email = from_email
        if use_tls is not None:
            config.use_tls = bool(use_tls)
        if use_ssl is not None:
            config.use_ssl = bool(use_ssl)
        if parsed_timeout is not None:
            config.timeout_seconds = parsed_timeout
        if password:
            config.set_password(password)
        if 'is_active' in data:
            config.is_active = bool(data.get('is_active'))

        # Activating with no host would leave the app reporting a working
        # configuration while every message went to the console.
        if config.is_active and not config.host:
            return Response({
                'detail': 'Enter an SMTP host before activating.',
                'errors': {'host': 'Required before this configuration can be used.'},
            }, status=400)

        config.updated_by = request.user
        config.save()

        audit(
            request.user, 'platform_email_config',
            'Updated site email configuration.', None,
            'email_config', config.id,
            {
                'host': config.host,
                'port': config.port,
                'use_tls': config.use_tls,
                'use_ssl': config.use_ssl,
                'is_active': config.is_active,
                # Boolean, never the value.
                'password_changed': bool(password),
            },
        )
        return Response(self._state())


class PlatformEmailTestView(APIView):
    """Send one real message through the configured SMTP server.

    Without this, a wrong password is discovered when a customer cannot
    activate their account rather than while an admin is watching a test send.
    """

    permission_classes = [IsPlatformSecretsAdmin]

    def post(self, request):
        # send_mail, not send_mail_logging_failure: this screen exists precisely to
        # surface the exception, so it must not swallow one.
        from django.core.mail import send_mail

        from .platform_models import EmailConfig

        recipient = str(request.data.get('to') or request.user.email or '').strip()
        if not recipient or '@' not in recipient:
            return Response({'detail': 'Provide a valid recipient address.',
                             'errors': {'to': 'A valid email address is required.'}},
                            status=400)

        config = EmailConfig.objects.first()
        if config is None or not config.usable:
            return Response({
                'detail': ('Email is not active yet. Save an SMTP host and tick '
                           '"use these settings for sending" first.'),
            }, status=400)

        subject = 'HRCloudPay email configuration test'
        body = (
            'This message confirms that HRCloudPay can send mail through the '
            'SMTP settings a platform administrator saved.\n\n'
            'If you are reading it, the configuration works.\n'
        )

        # Deliberately routed through send_mail, and therefore through
        # settings.EMAIL_BACKEND, which is the exact path an activation mail
        # takes. Constructing PlatformEmailBackend directly - as this used to -
        # proved the stored credentials worked and nothing more, so the test
        # went green on a deployment where every real send failed. A green
        # result here now means the application's own mail path works.
        try:
            sent = send_mail(
                subject=subject,
                message=body,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[recipient],
                fail_silently=False,
            )
        except Exception as exc:
            audit(
                request.user, 'platform_email_test',
                'Site email configuration test failed.', None,
                'email_config', config.id,
                {'success': False, 'error_type': type(exc).__name__},
            )
            # The exception text can contain the server's response, which is
            # useful to the admin and contains no credential, so it is returned
            # rather than swallowed.
            return Response({'success': False, 'detail': str(exc)}, status=503)

        audit(
            request.user, 'platform_email_test',
            'Sent a site email configuration test.', None,
            'email_config', config.id,
            {'success': True, 'recipient': recipient, 'messages_sent': sent},
        )
        return Response({'success': True, 'messages_sent': sent,
                         'detail': f'Test message accepted for {recipient}.'})
