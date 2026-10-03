from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('accounts', '0012_marketing_page')]

    operations = [
        migrations.AddField(
            model_name='marketingpage',
            name='draft_content',
            field=models.JSONField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='marketingpage',
            name='draft_name',
            field=models.CharField(blank=True, max_length=160),
        ),
    ]
