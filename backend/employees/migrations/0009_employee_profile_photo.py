
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('employees', '0008_employment_category_system_id'),
    ]

    operations = [
        migrations.AddField(
            model_name='employee',
            name='profile_photo',
            field=models.ImageField(
                blank=True,
                help_text='Employee profile picture',
                null=True,
                upload_to='employee_photos/%Y/%m/',
            ),
        ),
    ]
