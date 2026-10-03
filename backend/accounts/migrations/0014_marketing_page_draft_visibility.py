from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('accounts', '0013_marketing_page_drafts')]

    operations = [
        migrations.AddField(
            model_name='marketingpage',
            name='draft_is_published',
            field=models.BooleanField(blank=True, null=True),
        ),
    ]
