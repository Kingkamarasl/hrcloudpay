from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [('ai', '0001_initial')]
    operations = [
        migrations.CreateModel(
            name='AIDraft',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('type', models.CharField(choices=[('employment_letter', 'Employment letter'), ('warning_letter', 'Warning letter'), ('payroll_explanation', 'Payroll explanation'), ('hr_report', 'HR report')], max_length=40)),
                ('title', models.CharField(blank=True, max_length=200)),
                ('context', models.TextField()),
                ('content', models.TextField()),
                ('status', models.CharField(choices=[('pending', 'Pending review'), ('approved', 'Approved for use'), ('rejected', 'Rejected')], default='pending', max_length=20)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('reviewed_at', models.DateTimeField(blank=True, null=True)),
                ('company', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='ai_drafts', to='accounts.company')),
                ('created_by', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='created_ai_drafts', to=settings.AUTH_USER_MODEL)),
                ('reviewed_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='reviewed_ai_drafts', to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ['-updated_at', '-id']},
        ),
        migrations.AddIndex(
            model_name='aidraft',
            index=models.Index(fields=['company', 'status', '-updated_at'], name='ai_aidraft_company_9a1b7f_idx'),
        ),
    ]
