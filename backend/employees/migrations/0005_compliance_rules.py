from django.db import migrations, models
import django.db.models.deletion

class Migration(migrations.Migration):
    dependencies = [('employees', '0004_employee_documents')]
    operations = [
        migrations.CreateModel(
            name='RequiredDocumentRule',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=200)),
                ('document_type', models.CharField(choices=[('identity','Identity Document'),('contract','Contract'),('certificate','Certificate'),('qualification','Qualification'),('policy','Policy / Acknowledgement'),('medical','Medical / Fitness'),('disciplinary','Disciplinary'),('other','Other')], max_length=30)),
                ('contract_type', models.CharField(blank=True, choices=[('full_time','Full-time'),('part_time','Part-time'),('contractor','Contractor'),('internship','Internship'),('temporary','Temporary')], max_length=20)),
                ('warning_days', models.PositiveIntegerField(default=30)),
                ('is_active', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('company', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='required_document_rules', to='accounts.company')),
                ('employee', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='document_requirements', to='employees.employee')),
            ],
            options={'ordering':['name']},
        ),
        migrations.AddConstraint(
            model_name='requireddocumentrule',
            constraint=models.UniqueConstraint(fields=('company','name','employee','contract_type'), name='unique_required_doc_rule_scope'),
        ),
    ]
