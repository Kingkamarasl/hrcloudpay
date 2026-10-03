from django.contrib import admin
from unfold.admin import ModelAdmin
from .models import *
for model in [SecuritySession,MFADevice,RecoveryCode,SecurityEvent,SecurityIncident,ThreatIndicator,RiskSignal,DeviceTrust,AccessRole,AccessRequest,PAMSession,SSOProvider,SCIMCredential,AccessReview,AccessCertification,DLPPolicy,DLPEvent,ResponsePlaybook,ResponseAction]:
    admin.site.register(model, ModelAdmin)
