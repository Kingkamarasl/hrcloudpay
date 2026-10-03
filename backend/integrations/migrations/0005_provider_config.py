from django.db import migrations, models
class Migration(migrations.Migration):
    dependencies=[('integrations','0004_webhook_index')]
    operations=[migrations.CreateModel(name='IntegrationProviderConfig',fields=[
        ('id',models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name='ID')),
        ('provider',models.CharField(choices=[('quickbooks','QuickBooks Online'),('microsoft365','Microsoft 365'),('xero','Xero')],max_length=40,unique=True)),
        ('enabled',models.BooleanField(default=False)),('client_id',models.CharField(blank=True,max_length=255)),('encrypted_client_secret',models.TextField(blank=True)),
        ('environment',models.CharField(choices=[('sandbox','Sandbox'),('production','Production')],default='production',max_length=20)),('configured_at',models.DateTimeField(blank=True,null=True)),('updated_at',models.DateTimeField(auto_now=True))])]
