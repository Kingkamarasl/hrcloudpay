from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion

class Migration(migrations.Migration):
    dependencies = [('regional','0003_statutory_compliance_pack')]
    operations = [
        migrations.AddField(model_name='statutoryfiling', name='reviewed_at', field=models.DateTimeField(blank=True,null=True)),
        migrations.AddField(model_name='statutoryfiling', name='reviewed_by', field=models.ForeignKey(blank=True,null=True,on_delete=django.db.models.deletion.SET_NULL,related_name='reviewed_statutory_filings',to=settings.AUTH_USER_MODEL)),
        migrations.AddField(model_name='statutoryfiling', name='approved_at', field=models.DateTimeField(blank=True,null=True)),
        migrations.AddField(model_name='statutoryfiling', name='approved_by', field=models.ForeignKey(blank=True,null=True,on_delete=django.db.models.deletion.SET_NULL,related_name='approved_statutory_filings',to=settings.AUTH_USER_MODEL)),
        migrations.AddField(model_name='statutoryfiling', name='submitted_at', field=models.DateTimeField(blank=True,null=True)),
        migrations.AddField(model_name='statutoryfiling', name='submitted_by', field=models.ForeignKey(blank=True,null=True,on_delete=django.db.models.deletion.SET_NULL,related_name='submitted_statutory_filings',to=settings.AUTH_USER_MODEL)),
        migrations.AddField(model_name='statutoryfiling', name='submission_reference', field=models.CharField(blank=True,max_length=160)),
        migrations.AddField(model_name='statutoryfiling', name='closed_at', field=models.DateTimeField(blank=True,null=True)),
        migrations.CreateModel(name='StatutoryFilingPayment', fields=[
            ('id',models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name='ID')),
            ('amount',models.DecimalField(decimal_places=2,default=0,max_digits=16)),('payment_date',models.DateField(blank=True,null=True)),
            ('method',models.CharField(blank=True,max_length=40)),('transaction_reference',models.CharField(blank=True,max_length=160)),
            ('status',models.CharField(choices=[('pending','Pending'),('paid','Paid'),('failed','Failed'),('reversed','Reversed')],default='pending',max_length=20)),
            ('receipt_reference',models.CharField(blank=True,max_length=160)),('notes',models.TextField(blank=True)),
            ('created_at',models.DateTimeField(auto_now_add=True)),('updated_at',models.DateTimeField(auto_now=True)),
            ('filing',models.OneToOneField(on_delete=django.db.models.deletion.CASCADE,related_name='payment_record',to='regional.statutoryfiling')),
            ('recorded_by',models.ForeignKey(blank=True,null=True,on_delete=django.db.models.deletion.SET_NULL,related_name='statutory_payment_records',to=settings.AUTH_USER_MODEL)),
        ]),
    ]
