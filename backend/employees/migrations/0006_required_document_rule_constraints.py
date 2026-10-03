from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):
    dependencies = [
        ('employees', '0005_compliance_rules'),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name='requireddocumentrule',
            name='unique_required_doc_rule_scope',
        ),
        migrations.AddConstraint(
            model_name='requireddocumentrule',
            constraint=models.UniqueConstraint(
                condition=Q(employee__isnull=False),
                fields=('company', 'name', 'employee', 'contract_type'),
                name='unique_required_doc_rule_employee_scope',
            ),
        ),
        migrations.AddConstraint(
            model_name='requireddocumentrule',
            constraint=models.UniqueConstraint(
                condition=Q(employee__isnull=True),
                fields=('company', 'name', 'contract_type'),
                name='unique_required_doc_rule_company_scope',
            ),
        ),
    ]
