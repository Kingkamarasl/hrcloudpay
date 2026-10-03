import hashlib, secrets
from datetime import timedelta
from django.contrib.auth import authenticate, login as django_login
from django.conf import settings
from django.http import JsonResponse
from django.middleware.csrf import get_token
from django.utils import timezone
from django.db import OperationalError, ProgrammingError
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from accounts.models import User
from accounts.serializers import UserSerializer
from accounts.secrets import encrypt_secret, decrypt_secret
from .models import *
from .permissions import IsITSecurityAdmin
from .step_up import RequiresFreshMfa, mfa_is_fresh
from .utils import *
from .geolocation import describe_ip
from .services import emit, detect_auth_burst, trust_score, create_incident, describe_session
from .login_lockout import check_locked, record_failure, record_success, lockout_message

def _session_response(request, user, mfa=False):
    """Create the HRCloudPay security session cookie.

    Development-only compatibility: if a local checkout has not yet applied the
    security migration, DEBUG=True falls back to Django's server-side session
    authentication so the application can still be bootstrapped. Production
    remains fail-closed and surfaces the database/configuration error instead
    of silently weakening authentication.
    """
    raw = new_secret()
    try:
        SecuritySession.objects.create(
            user=user,
            company=user.company,
            secret_hash=hash_value(raw),
            ip_address=client_ip(request),
            user_agent=request.META.get('HTTP_USER_AGENT','')[:2000],
            device_label=request.META.get('HTTP_USER_AGENT','')[:200],
            expires_at=timezone.now()+timedelta(hours=settings.SECURITY_SESSION_HOURS),
            mfa_verified=not mfa,
            # `mfa=True` means the caller just cleared a TOTP challenge, so
            # stamp it; a plain login is only MFA-verified by definition
            # (no second factor is enrolled) and must not count as a fresh
            # step-up for privileged actions.
            mfa_verified_at=timezone.now() if mfa else None,
        )
    except (OperationalError, ProgrammingError):
        if not settings.DEBUG:
            raise
        django_login(request, user)
        response = Response({'user': UserSerializer(user, context={'request': request}).data, 'mfa_required': mfa, 'auth_mode': 'django_session_dev_fallback'})
        response.set_cookie('csrftoken', get_token(request), secure=False, httponly=False, samesite='Lax')
        return response

    response = Response({'user': UserSerializer(user, context={'request': request}).data, 'mfa_required':mfa})
    response.set_cookie('hrcloudpay_session', raw, httponly=True, secure=not settings.DEBUG, samesite='Lax', max_age=settings.SECURITY_SESSION_HOURS*3600)
    response.set_cookie('csrftoken', get_token(request), secure=not settings.DEBUG, samesite='Lax')
    return response

class CSRFView(APIView):
    permission_classes=[AllowAny]
    authentication_classes=[]
    def get(self, request): return JsonResponse({'csrfToken': get_token(request)})

class SecureLoginView(APIView):
    permission_classes=[AllowAny]; authentication_classes=[]
    throttle_scope='login'
    def post(self, request):
        submitted=str(request.data.get('username','')).strip()
        ip=client_ip(request)
        # Per-IP throttle (ScopedRateThrottle) is already applied by DRF; these
        # two cover what a shared IP bucket cannot see - distributed attempts
        # against a single account, and a locked-out account being probed.
        for kind,value in (('username',submitted),('ip',ip)):
            remaining=check_locked(kind,value)
            if remaining:
                return Response({'detail':lockout_message(remaining),'locked_for':remaining},status=429,headers={'Retry-After':str(remaining)})
        user=authenticate(username=submitted, password=request.data.get('password',''))
        if not user:
            # Per-account lockout: rotating source addresses cannot reset this.
            remaining=max(record_failure('username',submitted), record_failure('ip',ip))
            body={'detail':'Invalid username or password.'}
            if remaining:
                body={'detail':lockout_message(remaining),'locked_for':remaining}
            try:
                # Security telemetry must never turn an invalid credential into a
                # server error. This is especially important during first-time
                # local bootstrap when security migrations may not yet exist.
                emit(request,'login_failed','medium','Failed login attempt',metadata={'username':submitted[:150]})
            except (OperationalError, ProgrammingError):
                if not settings.DEBUG:
                    raise
            return Response(body,status=429 if remaining else 401,headers={'Retry-After':str(remaining)} if remaining else None)
        if not user.is_active: return Response({'detail':'Account is disabled.'},status=403)
        # Cleared only after the credential actually validated, so a disabled
        # account still counts as a failure and cannot be probed.
        record_success('username',submitted); record_success('ip',ip)
        # Same development-only bootstrap tolerance as emit() and _session_response()
        # below: a checkout that has not applied the security migration must still be
        # able to reach the public login endpoint. This reverse lookup was unguarded,
        # so a missing `security_mfadevice` table raised OperationalError and turned
        # EVERY sign-in into a 500 - with no way to log in to diagnose it. Production
        # still re-raises rather than silently treating the account as MFA-free.
        try:
            device=getattr(user,'mfa_device',None)
        except (OperationalError, ProgrammingError):
            if not settings.DEBUG:
                raise
            device=None
        if device and device.enabled:
            challenge=secrets.token_urlsafe(32)
            request.session['mfa_challenge_hash']=hash_value(challenge); request.session['mfa_challenge_user']=user.id; request.session.set_expiry(300)
            response=Response({'mfa_required':True,'challenge_required':True})
            response.set_cookie('hrcloudpay_mfa_challenge',challenge,httponly=True,secure=not settings.DEBUG,samesite='Lax',max_age=300)
            return response
        try:
            emit(request,'login','low',f'User {user.username} authenticated',user.company,user)
        except (OperationalError, ProgrammingError):
            if not settings.DEBUG:
                raise
        return _session_response(request,user)

class SecureRegisterView(APIView):
    permission_classes=[AllowAny]; authentication_classes=[]
    def post(self,request):
        from accounts.serializers import RegisterSerializer
        serializer=RegisterSerializer(data=request.data); serializer.is_valid(raise_exception=True); result=serializer.save(); user=result['user']
        emit(request,'registration','low','New company registration',user.company,user)
        return _session_response(request,user)

class MFAVerifyView(APIView):
    permission_classes=[AllowAny]; authentication_classes=[]
    # A 6-digit TOTP is only 1e6 combinations, so an unthrottled verify
    # endpoint is code-stuffable even when login itself is limited.
    throttle_scope='mfa'
    def post(self,request):
        raw=request.COOKIES.get('hrcloudpay_mfa_challenge',''); expected=request.session.get('mfa_challenge_hash'); user_id=request.session.get('mfa_challenge_user')
        if not raw or not expected or hash_value(raw)!=expected or not user_id: return Response({'detail':'MFA challenge expired.'},status=401)
        user=User.objects.filter(id=user_id,is_active=True).first(); device=getattr(user,'mfa_device',None) if user else None
        if not user or not device or not verify_totp(decrypt_secret(device.secret_encrypted),request.data.get('code','')):
            # Counted against the account as well as the per-IP scope, so a
            # rotating pool of addresses cannot grind through the TOTP space.
            remaining=record_failure('username',user.username if user else '')
            body={'detail':'Invalid MFA code.'}
            if remaining: body={'detail':lockout_message(remaining),'locked_for':remaining}
            return Response(body,status=429 if remaining else 401,headers={'Retry-After':str(remaining)} if remaining else None)
        record_success('username',user.username)
        request.session.flush(); emit(request,'mfa_verified','medium','MFA challenge verified',user.company,user); response=_session_response(request,user,mfa=True); response.delete_cookie('hrcloudpay_mfa_challenge'); return response

class MFAStepUpView(APIView):
    """Re-confirm MFA on an already-authenticated session.

    Used when a step-up-protected action returns 403 ``mfa_required``. On
    success the current session is stamped as freshly verified, so the pending
    action can be retried without a full sign-in.
    """
    permission_classes=[IsAuthenticated]
    throttle_scope='mfa'
    def post(self,request):
        session=getattr(request,'auth',None)
        if not isinstance(session,SecuritySession):
            return Response({'detail':'Step-up verification requires an active HRCloudPay session.'},status=400)
        device=getattr(request.user,'mfa_device',None)
        if not device or not device.enabled:
            return Response({'detail':'Enable two-factor authentication before confirming this action.','enrollment_required':True},status=403)
        if not verify_totp(decrypt_secret(device.secret_encrypted),request.data.get('code','')):
            remaining=record_failure('username',request.user.username)
            body={'detail':'Invalid MFA code.'}
            if remaining: body={'detail':lockout_message(remaining),'locked_for':remaining}
            return Response(body,status=429 if remaining else 400,headers={'Retry-After':str(remaining)} if remaining else None)
        record_success('username',request.user.username)
        session.mfa_verified=True; session.mfa_verified_at=timezone.now(); session.save(update_fields=['mfa_verified','mfa_verified_at'])
        emit(request,'mfa_step_up','medium','MFA re-confirmed for a sensitive action',request.user.company,request.user)
        return Response({'mfa_verified':True,'mfa_verified_at':session.mfa_verified_at})

class SecureLogoutView(APIView):
    permission_classes=[IsAuthenticated]
    def post(self, request):
        session=getattr(request,'auth',None)
        if isinstance(session,SecuritySession): session.revoked_at=timezone.now(); session.save(update_fields=['revoked_at'])
        emit(request,'logout','low','User logged out',request.user.company,request.user)
        r=Response(status=204); r.delete_cookie('hrcloudpay_session'); return r

class MeSecurityView(APIView):
    permission_classes=[IsAuthenticated]
    def get(self,request):
        session=getattr(request,'auth',None); return Response({'user_id':request.user.id,'trust_score':trust_score(request.user,session=session),'mfa_enabled':bool(getattr(request.user,'mfa_device',None) and request.user.mfa_device.enabled),'session_id':str(session.id) if isinstance(session,SecuritySession) else None})

class SessionView(APIView):
    permission_classes=[IsAuthenticated]
    def get(self,request):
        qs=SecuritySession.objects.filter(user=request.user).order_by('-last_seen_at')
        return Response([{'id':str(s.id),'ip':s.ip_address,'country':s.country,'device':s.device_label,'created_at':s.created_at,'last_seen_at':s.last_seen_at,'expires_at':s.expires_at,'active':s.active,'mfa_verified':s.mfa_verified} for s in qs])
    def delete(self,request):
        SecuritySession.objects.filter(user=request.user,revoked_at__isnull=True).update(revoked_at=timezone.now())
        return Response({'revoked':'all'})

class ConnectionView(APIView):
    """Describe the caller's own connection and session: address, country, ISP, session security.

    Scoped to the request that is being served, so it can only ever describe the
    caller - there is no parameter to inspect anyone else's. ``describe_ip`` never
    raises, so a geolocation provider outage returns the address with an empty
    location rather than failing the request.

    ``?refresh=1`` re-runs the geolocation lookup instead of serving the 24-hour
    cache. That is rate limited per user, and when the limit is hit the cached
    answer comes back with ``refresh_throttled`` set rather than a silent no-op.
    """
    permission_classes=[IsAuthenticated]
    def get(self,request):
        force = request.query_params.get('refresh','').strip().lower() in ('1','true','yes')
        data = describe_ip(client_ip(request), force_refresh=force, user_id=request.user.id)
        data['session'] = describe_session(request)
        response = Response(data)
        # Per-user and per-request, so a shared cache or CDN must never store it.
        response['Cache-Control'] = 'no-store, private'
        return response

class MFAView(APIView):
    permission_classes=[IsAuthenticated]
    def get(self,request): return Response({'enabled':bool(getattr(request.user,'mfa_device',None) and request.user.mfa_device.enabled),'required':bool(getattr(request.user,'mfa_device',None) and request.user.mfa_device.required)})
    def post(self,request):
        action=request.data.get('action','setup')
        device=getattr(request.user,'mfa_device',None)
        if action=='setup':
            # Re-running setup must not silently strip an active factor. This
            # used to overwrite the secret and set enabled=False with no
            # check at all, so anyone holding a live session cookie could
            # downgrade the account to MFA-less and then phish the code.
            if device and device.enabled:
                if not verify_totp(decrypt_secret(device.secret_encrypted),request.data.get('code','')):
                    return Response({'detail':'Re-enter your current MFA code to replace the authenticator app.','code_required':True},status=403)
            secret=totp_secret(); MFADevice.objects.update_or_create(user=request.user,defaults={'secret_encrypted':encrypt_secret(secret),'enabled':False}); return Response({'secret':secret,'otpauth_uri':f'otpauth://totp/HRCloudPay:{request.user.username}?secret={secret}&issuer=HRCloudPay'})
        if not device: return Response({'detail':'MFA setup required.'},status=400)
        if not verify_totp(decrypt_secret(device.secret_encrypted),request.data.get('code','')): return Response({'detail':'Invalid MFA code.'},status=400)
        if action=='disable':
            device.enabled=False; device.save(update_fields=['enabled','updated_at']); emit(request,'mfa_disabled','high','MFA disabled',request.user.company,request.user); return Response({'enabled':False})
        device.enabled=True; device.save(update_fields=['enabled','updated_at']); emit(request,'mfa_enabled','medium','MFA enabled',request.user.company,request.user); return Response({'enabled':True})

class SecurityDashboardView(APIView):
    permission_classes=[IsAuthenticated, IsITSecurityAdmin]
    def get(self,request):
        company=request.user.company
        return Response({'events':list(SecurityEvent.objects.filter(company=company).values('id','event_type','severity','message','created_at')[:50]),'incidents':list(SecurityIncident.objects.filter(company=company).values('id','title','severity','status','opened_at')[:25]),'signals':list(RiskSignal.objects.filter(company=company).values('id','signal_type','score','created_at')[:50]),'sessions':SecuritySession.objects.filter(company=company,revoked_at__isnull=True,expires_at__gt=timezone.now()).count(),'devices':DeviceTrust.objects.filter(company=company).count()})

class ThreatDetectionView(APIView):
    permission_classes=[IsAuthenticated, IsITSecurityAdmin]
    def post(self,request):
        signal=detect_auth_burst(request.user.company)
        return Response({'detected':bool(signal),'signal_id':str(signal.id) if signal else None})

class DeviceTrustView(APIView):
    permission_classes=[IsAuthenticated]
    def get(self,request):
        qs=DeviceTrust.objects.filter(company=request.user.company,user=request.user)
        if request.user.role in ('owner','admin'): qs=DeviceTrust.objects.filter(company=request.user.company)
        return Response([{'id':str(x.id),'user_id':x.user_id,'label':x.label,'state':x.state,'last_ip':x.last_ip,'last_seen_at':x.last_seen_at} for x in qs])
    def patch(self,request,pk):
        if request.user.role not in ('owner','admin'): return Response({'detail':'Security administrator access required.'},403)
        d=DeviceTrust.objects.get(id=pk,company=request.user.company); d.state=request.data.get('state',d.state); d.label=request.data.get('label',d.label); d.approved_by=request.user; d.save(); emit(request,'device_trust_changed','medium',f'Device {d.id} set to {d.state}',request.user.company,request.user,{'device_id':str(d.id),'state':d.state}); return Response({'id':str(d.id),'state':d.state})

class PAMView(APIView):
    permission_classes=[IsAuthenticated, IsITSecurityAdmin]
    def get(self,request):
        qs=AccessRequest.objects.filter(company=request.user.company).select_related('requester','target_user').order_by('-created_at')
        return Response([{'id':str(x.id),'requester':x.requester.username,'target_user':x.target_user.username,'permissions':x.requested_permissions,'reason':x.reason,'status':x.status,'expires_at':x.expires_at} for x in qs])
    def post(self,request):
        target=User.objects.get(id=request.data.get('target_user'),company=request.user.company); expires=timezone.now()+timedelta(minutes=min(int(request.data.get('duration_minutes',60)),240)); x=AccessRequest.objects.create(company=request.user.company,requester=request.user,target_user=target,requested_permissions=request.data.get('permissions',[]),reason=request.data.get('reason',''),expires_at=expires); emit(request,'pam_access_requested','high','Privileged access requested',request.user.company,request.user,{'request_id':str(x.id)}); return Response({'id':str(x.id),'status':x.status},201)

class PAMApproveView(APIView):
    permission_classes=[IsAuthenticated, IsITSecurityAdmin, RequiresFreshMfa]
    def post(self,request,pk):
        x=AccessRequest.objects.get(id=pk,company=request.user.company)
        if x.requester_id==request.user.id: return Response({'detail':'Requester cannot approve their own elevation.'},403)
        if x.status!='pending' or x.expires_at<=timezone.now(): return Response({'detail':'Request is no longer approvable.'},400)
        x.status='approved'; x.approved_by=request.user; x.save(update_fields=['status','approved_by']); s=PAMSession.objects.create(company=x.company,user=x.target_user,access_request=x,permissions=x.requested_permissions,expires_at=x.expires_at); emit(request,'pam_access_approved','critical','Privileged access approved',x.company,request.user,{'request_id':str(x.id),'session_id':str(s.id)}); return Response({'session_id':str(s.id),'expires_at':s.expires_at})

class IncidentView(APIView):
    permission_classes=[IsAuthenticated, IsITSecurityAdmin]
    def get(self,request):
        return Response(list(SecurityIncident.objects.filter(company=request.user.company).values('id','title','severity','status','summary','opened_at','resolved_at')[:100]))
    def patch(self,request,pk):
        i=SecurityIncident.objects.get(id=pk,company=request.user.company); i.status=request.data.get('status',i.status); i.severity=request.data.get('severity',i.severity); i.summary=request.data.get('summary',i.summary); i.assigned_to_id=request.data.get('assigned_to',i.assigned_to_id); i.resolved_at=timezone.now() if i.status=='resolved' else i.resolved_at; i.save(); emit(request,'incident_updated','medium','Security incident updated',i.company,request.user,{'incident_id':str(i.id)}); return Response({'id':str(i.id),'status':i.status})

class DLPView(APIView):
    permission_classes=[IsAuthenticated]
    def post(self,request):
        company=request.user.company; count=int(request.data.get('object_count',1)); blocked=count>=100 and request.data.get('external_share',False)
        e=DLPEvent.objects.create(company=company,user=request.user,event_type=request.data.get('event_type','export'),object_type=request.data.get('object_type','unknown'),object_count=count,blocked=blocked,metadata=request.data.get('metadata',{}))
        if blocked: emit(request,'dlp_blocked','high','Potential data loss operation blocked',company,request.user,{'dlp_event_id':e.id,'object_count':count}); create_incident(company,'Potential data loss event','high','A bulk external sharing/export operation was blocked.',[{'dlp_event':e.id}])
        return Response({'blocked':blocked,'event_id':e.id})

class GovernanceView(APIView):
    permission_classes=[IsAuthenticated, IsITSecurityAdmin]
    def get(self,request):
        c=request.user.company
        return Response({'roles':list(AccessRole.objects.filter(company=c).values('id','name','permissions','privileged')),'reviews':list(AccessReview.objects.filter(company=c).values('id','name','status','due_at')),'certifications':list(AccessCertification.objects.filter(review__company=c).values('id','user_id','decision','reason','decided_at')[:100]),'sso':list(SSOProvider.objects.filter(company=c).values('id','name','provider_type','domain','enabled')),'scim':list(SCIMCredential.objects.filter(company=c).values('id','label','active','created_at','last_used_at'))})
    def post(self,request):
        c=request.user.company; action=request.data.get('action')
        if action=='role':
            name=str(request.data.get('name','')).strip(); perms=request.data.get('permissions',[]); privileged=bool(request.data.get('privileged',False))
            if any(str(x).startswith('platform.') for x in perms): return Response({'detail':'Tenant roles cannot grant platform-level permissions.'},400)
            r=AccessRole.objects.create(company=c,name=name,permissions=perms,privileged=privileged); emit(request,'role_created','medium','Custom security role created',c,request.user,{'role_id':r.id}); return Response({'id':r.id,'name':r.name},201)
        if action=='sso':
            config=encrypt_config(request.data.get('config',{})); p=SSOProvider.objects.create(company=c,provider_type=request.data.get('provider_type','oidc'),name=request.data.get('name','SSO'),domain=request.data.get('domain',''),config_encrypted=config,group_role_mapping=request.data.get('group_role_mapping',{}),enabled=False); emit(request,'sso_provider_configured','medium','SSO provider configured',c,request.user,{'provider_id':p.id}); return Response({'id':p.id,'enabled':p.enabled},201)
        if action=='scim':
            raw=new_secret(); x=SCIMCredential.objects.create(company=c,token_hash=hash_value(raw),label=request.data.get('label','SCIM')); emit(request,'scim_credential_created','high','SCIM credential created',c,request.user,{'credential_id':x.id}); return Response({'id':x.id,'token':raw},201)
        if action=='review':
            due=timezone.now()+timedelta(days=int(request.data.get('days',30))); r=AccessReview.objects.create(company=c,name=request.data.get('name','Access Review'),due_at=due); users=User.objects.filter(company=c,is_active=True); AccessCertification.objects.bulk_create([AccessCertification(review=r,user=u,permissions_snapshot=[u.role]) for u in users]); emit(request,'access_review_created','medium','Access review campaign created',c,request.user,{'review_id':r.id}); return Response({'id':r.id,'certifications':users.count()},201)
        return Response({'detail':'Unsupported governance action.'},400)

class GovernanceCertificationView(APIView):
    permission_classes=[IsAuthenticated, IsITSecurityAdmin]
    def patch(self,request,pk):
        cert=AccessCertification.objects.select_related('review').get(id=pk,review__company=request.user.company); decision=request.data.get('decision')
        if decision not in dict(AccessCertification.DECISIONS): return Response({'detail':'Invalid decision.'},400)
        cert.decision=decision; cert.reason=request.data.get('reason',''); cert.decided_by=request.user; cert.decided_at=timezone.now(); cert.save(update_fields=['decision','reason','decided_by','decided_at']); emit(request,'access_certification_decided','high' if decision=='revoked' else 'medium','Access certification decision recorded',request.user.company,request.user,{'certification_id':cert.id,'decision':decision}); return Response({'decision':cert.decision})
