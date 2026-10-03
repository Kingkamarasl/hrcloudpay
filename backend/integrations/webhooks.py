import base64, hashlib, hmac, json
from django.conf import settings
from django.http import HttpResponse
from django.utils import timezone
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from .models import IntegrationConnection, SyncEvent

def _secret(name): return getattr(settings,name,'') or ''
def _valid(raw, signature, secret):
    if not secret or not signature: return False
    expected=base64.b64encode(hmac.new(secret.encode(),raw,hashlib.sha256).digest()).decode()
    return hmac.compare_digest(expected,signature)

class ProviderWebhookView(APIView):
    permission_classes=[AllowAny]
    authentication_classes=[]
    def post(self,request,provider):
        raw=request.body
        if provider=='quickbooks':
            if not _valid(raw,request.META.get('HTTP_INTUIT_SIGNATURE',''),_secret('QUICKBOOKS_WEBHOOK_VERIFIER')): return HttpResponse('invalid signature',status=401)
        elif provider=='xero':
            if not _valid(raw,request.META.get('HTTP_X_XERO_SIGNATURE',''),_secret('XERO_WEBHOOK_KEY')): return HttpResponse('invalid signature',status=401)
        else: return HttpResponse('unsupported',status=404)
        try: payload=json.loads(raw.decode() or '{}')
        except Exception: return HttpResponse('invalid json',status=400)
        notifications=payload.get('eventNotifications') if provider=='quickbooks' else payload.get('events')
        notifications=notifications or []
        created=0
        for item in notifications:
            realm=str(item.get('realmId') or '')
            ext=str(item.get('id') or item.get('eventId') or '')
            connections=IntegrationConnection.objects.filter(provider=provider,status='connected')
            if realm: connections=connections.filter(external_account_id=realm)
            for connection in connections[:1]:
                provider_event_id=ext or hashlib.sha256(json.dumps(item,sort_keys=True).encode()).hexdigest()
                obj,_=SyncEvent.objects.get_or_create(connection=connection,provider_event_id=provider_event_id,event_type=str(item.get('operation') or item.get('eventType') or 'unknown'),defaults={'entity_type':str(item.get('name') or item.get('resource') or ''),'external_id':str(item.get('id') or ''),'payload':item})
                created += int(_)
        return Response({'received':True,'events_recorded':created})
