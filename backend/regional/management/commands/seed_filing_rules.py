from datetime import date
from django.core.management.base import BaseCommand
from regional.models import StatutoryFilingRule


RULES = [
    # Nigeria: JRB 2026 guideline says PAYE remittance by 10th following month
    ('NG','paye','PAYE remittance','Relevant State/FCT Tax Authority','tax','monthly',10,None,'https://www.jtb.gov.ng/assets/2026-pit-guidelines-TJG3n9-T.pdf','Employer PAYE remittance is due by the 10th of the following month. State/FCT administration may have local portal/process requirements.',date(2026,1,1)),
    ('NG','paye_annual_return','Employer annual PAYE return','Relevant State/FCT Tax Authority','tax','annual',31,1,'https://www.jtb.gov.ng/assets/2026-pit-guidelines-TJG3n9-T.pdf','Annual employer return for preceding year is due by 31 January under the 2026 JRB guidelines.',date(2026,1,1)),
    # Ghana
    ('GH','paye','PAYE return and payment','Ghana Revenue Authority','tax','monthly',15,None,'https://gra.gov.gh/domestic-tax/tax-types/paye/','Monthly PAYE return/payment due by the 15th of the following month.',date(2024,1,1)),
    ('GH','ssnit','SSNIT contribution payment','Social Security and National Insurance Trust','social_security','monthly',14,None,'https://www.ssnit.org.gh/become-an-employer/','SSNIT says the 13.5% remittance to the Trust is due within 14 days of the following month; contribution reports are submitted by month-end.',date(2024,1,1)),
    # Sierra Leone
    ('SL','nassit','NASSIT contribution payment','National Social Security and Insurance Trust','social_security','monthly',15,None,'https://www.nassit.org.sl/our-services/contributions','Total NASSIT contribution is due within 15 days after month-end.',date(2024,1,1)),
    # Liberia
    ('LR','paye','Payroll withholding / PIT','Liberia Revenue Authority','tax','monthly',10,None,'https://revenue.lra.gov.lr/domestic-tax/tax-education/','Personal income tax and withholding on wages/salary are due by the 10th of the succeeding month.',date(2024,1,1)),
    # Gambia
    ('GM','npf','National Provident Fund contribution','Social Security & Housing Finance Corporation','social_security','monthly',15,None,'https://www.sshfc.gm/national-provident-fund','NPF contributions are due by the 15th of the month following the salary/wage month.',date(2024,1,1)),
    ('GM','fps','Federated Pension Scheme contribution','Social Security & Housing Finance Corporation','pension','monthly',15,None,'https://www.sshfc.gm/federated-pension-scheme','FPS contributions are due by the 15th of the month following the salary/wage month.',date(2024,1,1)),
]


class Command(BaseCommand):
    help = 'Seed effective-dated statutory filing calendar rules for the supported country packs.'

    def handle(self, *args, **options):
        for country, code, name, authority, filing_type, frequency, due_day, due_month, source, notes, effective_from in RULES:
            obj, created = StatutoryFilingRule.objects.update_or_create(
                country_code=country, code=code, effective_from=effective_from,
                defaults={
                    'name': name, 'authority': authority, 'filing_type': filing_type,
                    'frequency': frequency, 'due_day': due_day, 'due_month': due_month,
                    'source_reference': source, 'notes': notes, 'is_active': True,
                },
            )
            self.stdout.write(f"{'Created' if created else 'Updated'} {obj}")
        # The ten packs added on 2026-10-01 have no verified filing rule at all.
        # Saying so is the point: an operator who runs this command expecting a
        # calendar for their country needs to know the command did not produce
        # one because the data does not exist, not that it was forgotten.
        from regional.countries.registry import COUNTRY_PACKS
        missing = sorted(
            code for code in COUNTRY_PACKS
            if not StatutoryFilingRule.objects.filter(country_code=code).exists()
        )
        if missing:
            self.stdout.write(self.style.WARNING(
                'No verified filing calendar seeded for: %s. The filing calendar '
                'for these countries is empty because the deadlines have not been '
                'verified, not because anything is missing from this command. '
                'Deadlines must be taken from each country\'s revenue and social '
                'security authority and added here with a source reference; '
                'HRCloudPay does not infer them.'
                % ', '.join(missing)
            ))
