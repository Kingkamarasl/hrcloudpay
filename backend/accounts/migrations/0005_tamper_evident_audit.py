from django.db import migrations, models

def backfill_hash_chain(apps, schema_editor):
    import hashlib, json
    from django.db import connection
    AuditLog = apps.get_model('accounts', 'AuditLog')
    State = apps.get_model('accounts', 'AuditChainState')
    state = State.objects.create(key='global', last_sequence=0, last_hash='0' * 64)
    previous = state.last_hash
    sequence = 0
    for log in AuditLog.objects.order_by('created_at', 'id').iterator():
        sequence += 1
        payload = {
            'sequence': sequence, 'previous_hash': previous, 'actor_id': log.actor_id, 'company_id': log.company_id,
            'action': log.action, 'target_type': log.target_type, 'target_id': log.target_id, 'message': log.message,
            'metadata': log.metadata or {}, 'request_id': getattr(log, 'request_id', ''), 'user_agent': getattr(log, 'user_agent', ''),
            'created_at': log.created_at.isoformat(),
        }
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()
        AuditLog.objects.filter(pk=log.pk).update(chain_sequence=sequence, previous_hash=previous, integrity_hash=digest)
        previous = digest
    state.last_sequence = sequence; state.last_hash = previous
    state.save(update_fields=['last_sequence','last_hash'])


class Migration(migrations.Migration):
    dependencies = [('accounts','0004_expand_audit_actions')]
    operations = [
        migrations.AlterField(
            model_name='auditlog', name='action',
            field=models.CharField(max_length=30, choices=[
                ('create','Create'),('update','Update'),('delete','Delete'),('activate','Activate'),('suspend','Suspend'),
                ('login','Login'),('logout','Logout'),('login_failed','Login failed'),('invite','Invite'),('permission_change','Permission change'),
                ('salary_change','Salary change'),('termination','Termination'),('contract_change','Contract change'),
                ('payroll_process','Payroll process'),('payroll_approve','Payroll approval'),('payroll_payment','Payroll payment'),
                ('system','System'),('security','Security event'),('account_status','Account status'),('data_export','Data export'),('disciplinary_action','Disciplinary action'),('leave_approve','Leave approval'),('leave_reject','Leave rejection')
            ], default='system')
        ),
        migrations.CreateModel(
            name='AuditChainState',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('key', models.CharField(default='global', max_length=32, unique=True)),
                ('last_sequence', models.BigIntegerField(default=0)),
                ('last_hash', models.CharField(default='0000000000000000000000000000000000000000000000000000000000000000', max_length=64)),
            ],
        ),
        migrations.AddField(model_name='auditlog', name='request_id', field=models.CharField(blank=True, max_length=64)),
        migrations.AddField(model_name='auditlog', name='user_agent', field=models.CharField(blank=True, max_length=500)),
        migrations.AddField(model_name='auditlog', name='chain_sequence', field=models.BigIntegerField(editable=False, null=True)),
        migrations.AddField(model_name='auditlog', name='previous_hash', field=models.CharField(blank=True, editable=False, max_length=64)),
        migrations.AddField(model_name='auditlog', name='integrity_hash', field=models.CharField(blank=True, editable=False, max_length=64)),
        migrations.AddIndex(model_name='auditlog', index=models.Index(fields=['company','-created_at'], name='accounts_audit_company_created_idx')),
        migrations.AddIndex(model_name='auditlog', index=models.Index(fields=['action','-created_at'], name='accounts_audit_action_created_idx')),
        migrations.AddIndex(model_name='auditlog', index=models.Index(fields=['target_type','target_id'], name='accounts_audit_target_idx')),
        migrations.RunPython(backfill_hash_chain, migrations.RunPython.noop),
    ]
