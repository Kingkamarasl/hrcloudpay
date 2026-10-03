# Minimal migration to add plan field to Subscription
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [('accounts', '0022_billingplan')]

    operations = [
        migrations.AddField(
            model_name='subscription',
            name='plan',
            field=models.CharField(default='starter', max_length=20),
        ),
    ]