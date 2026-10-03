import hashlib, io, os, subprocess, zipfile
from django.conf import settings
from .models import SecurityEvent

def sha256_bytes(data): return hashlib.sha256(data).hexdigest()
def validate_pdf(data): return data[:5] == b'%PDF-'
def validate_docx(data):
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            names=z.namelist(); return '[Content_Types].xml' in names and 'word/document.xml' in names and sum(i.file_size for i in z.infolist()) <= 50*1024*1024
    except zipfile.BadZipFile: return False

def malware_scan(data, filename='', company=None):
    if not getattr(settings,'DOCUMENT_MALWARE_SCANNING_ENABLED',False): return {'status':'not_configured','sha256':sha256_bytes(data)}
    path='/tmp/hrcloudpay-scan-'+hashlib.sha256(data).hexdigest()
    with open(path,'wb') as f: f.write(data)
    try:
        result=subprocess.run([settings.CLAMSCAN_PATH,'--no-summary',path],capture_output=True,text=True,timeout=30)
        infected=result.returncode==1
        return {'status':'infected' if infected else 'clean' if result.returncode==0 else 'error','sha256':sha256_bytes(data),'detail':result.stdout[-500:]}
    finally:
        try: os.unlink(path)
        except OSError: pass
