
from django.db import migrations, models
import django.db.models.deletion

class Migration(migrations.Migration):
    dependencies = [
        ('accounts', '0010_company_address'),
        ('payroll', '0004_overtime_advances'),
    ]
    operations = [
        migrations.CreateModel(
            name='PublicHoliday',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('date', models.DateField()),
                ('name', models.CharField(max_length=120)),
                ('company', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='public_holidays', to='accounts.company')),
            ],
            options={'ordering': ['date'], 'unique_together': {('company', 'date')}},
        ),
    ]
