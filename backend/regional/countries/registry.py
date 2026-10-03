from dataclasses import dataclass


@dataclass(frozen=True)
class CountryPack:
    code: str
    name: str
    currency: str
    timezone: str
    payroll_frequencies: tuple[str, ...]
    employee_identifiers: tuple[str, ...]
    compliance_domains: tuple[str, ...]
    integration_tags: tuple[str, ...]
    employee_fields: tuple[tuple[str, str, bool], ...]
    # The statutory contribution rule codes this pack expects to compute.
    #
    # `compliance_domains` says which parts of payroll compliance a country's
    # labour law touches. That is a statement about the *jurisdiction*, and it
    # is broader than what any software can calculate. This field is the
    # narrower, checkable promise: "for a company in this country, HRCloudPay
    # applies these contribution codes."
    #
    # The two are deliberately not the same list. Nigeria's domains include
    # `nhf`, `nsitf` and `itf`, which are real deductions under the NHF Act,
    # the NSITF Act and the ITF Act respectively - but HRCloudPay seeds only
    # the pension rule, so it deducts none of the other three. Listing them here
    # would have made every Nigerian payroll run unapprovable, which would be a
    # different and equally wrong failure. So this list records what is
    # actually applied, and `compliance_domains` remains the honest statement of
    # what the law requires.
    contribution_codes: tuple[str, ...] = ()

    # The country requires mandatory employer/employee contributions, but the
    # name of the scheme collecting them has not been confirmed against the
    # authority. `contribution_coverage_gap` still raises a blocking gap for
    # such a pack; it just cannot say which fund.
    #
    # This is the third state, and it exists because naming a scheme from memory
    # is its own kind of fabrication. A wrong scheme name does not merely omit a
    # fact - it tells a payroll officer to chase the wrong fund, which is worse
    # than saying the name is not yet confirmed. Burundi and DR Congo are both
    # in this state: sources describe their contribution *branches* but
    # disagree on the name of the body that collects them (DR Congo is reported
    # as both CNSS and CNPS), so neither name was written down.
    contributions_unverified: bool = False

    # The country's official languages, as ISO 639 codes. Two-letter where a
    # 639-1 code exists (fr, pt, ar, en), three-letter where none does - `nso`
    # for Northern Sotho, `kab` for Kabyle and `zgh` for Standard Moroccan
    # Tamazight are 639-2 codes, because ISO 639-1 has no equivalent for any of
    # the three. Every code here was checked against the ISO 639-2 code list.
    #
    # Morocco's official Amazigh is `zgh`, the individual language the 2011
    # constitution names, rather than `ber` - the ISO 639-2 *collective* for
    # Berber languages, which covers far more than the one language Morocco
    # made official. Algeria's is `kab`, Kabyle, which is the standard its own
    # Tamazight institutions use; note that `tzm` (Central Atlas Tamazight) is
    # an ISO 639-3 code and does not appear in the 639-2 list at all.
    #
    # Two countries here designate no official language in law: Eritrea names
    # Tigrinya, Arabic and English as working languages, and Ethiopia gives
    # Amharic federal working-language status rather than sole officialdom. For
    # those the list records the languages the state actually runs on, which is
    # the fact a payroll office in either country needs.
    #
    # This is a fact about the jurisdiction and is never used to serve a
    # translated interface. This build has no translation catalogs, no
    # `LocaleMiddleware` and no `gettext` calls, so HRCloudPay's interface and
    # generated reports are English in every country. The field exists so the
    # compliance view can state that plainly - statutory filings in a
    # French-speaking country are filed in French - instead of leaving a
    # French-speaking employer to infer a capability the product does not have.
    official_languages: tuple[str, ...] = ()

    # The country's name in its own language, where it differs from `name`.
    #
    # A convenience label only. It is never rendered in place of the English
    # name and it is never sent to a statutory authority: the language an
    # authority form is filed in is part of the per-country report work, and no
    # report template exists for any of the countries added 2026-10-02.
    localized_name: str = ''

COUNTRY_PACKS = {
    'NG': CountryPack(
        'NG', 'Nigeria', 'NGN', 'Africa/Lagos', ('monthly',),
        ('tin', 'national_id', 'passport', 'social_security_number'),
        ('paye', 'pension', 'nhf', 'nsitf', 'itf'),
        ('quickbooks', 'xero', 'microsoft365'),
        (('tin','Tax Identification Number',False),('national_id','National ID Number',False),('passport','Passport Number',False),('social_security_number','Social Security Number',False)),
        ('pension',),
        False,
        ('en',),
        '',
    ),
    'GH': CountryPack(
        'GH', 'Ghana', 'GHS', 'Africa/Accra', ('monthly',),
        ('tin', 'national_id', 'passport', 'social_security_number'),
        ('paye', 'ssnit', 'tier2', 'tier3'),
        ('quickbooks', 'xero', 'microsoft365'),
        (('tin','Tax Identification Number',False),('national_id','National ID Number',False),('passport','Passport Number',False),('social_security_number','Social Security Number',False)),
        ('ssnit',),
        False,
        ('en',),
        '',
    ),
    'SL': CountryPack(
        'SL', 'Sierra Leone', 'SLE', 'Africa/Freetown', ('monthly',),
        ('tin', 'national_id', 'passport', 'social_security_number'),
        ('paye', 'nassit', 'minimum_wage'),
        ('quickbooks', 'xero', 'microsoft365'),
        (('tin','Tax Identification Number',False),('national_id','National ID Number',False),('passport','Passport Number',False),('social_security_number','Social Security Number',False)),
        ('nassit',),
        False,
        ('en',),
        '',
    ),
    'LR': CountryPack(
        'LR', 'Liberia', 'LRD', 'Africa/Monrovia', ('monthly',),
        ('tin', 'national_id', 'passport', 'social_security_number'),
        ('paye', 'nasscorp'),
        ('quickbooks', 'xero', 'microsoft365'),
        (('tin','Tax Identification Number',False),('national_id','National ID Number',False),('passport','Passport Number',False),('social_security_number','Social Security Number',False)),
        ('nasscorp_nps', 'nasscorp_eis'),
        False,
        ('en',),
        '',
    ),
    'GM': CountryPack(
        'GM', 'The Gambia', 'GMD', 'Africa/Banjul', ('monthly',),
        ('tin', 'national_id', 'passport', 'social_security_number'),
        ('paye', 'npf', 'fps', 'iicf'),
        ('quickbooks', 'xero', 'microsoft365'),
        (('tin','Tax Identification Number',False),('national_id','National ID Number',False),('passport','Passport Number',False),('social_security_number','Social Security Number',False)),
        ('npf', 'iicf'),
        False,
        ('en',),
        '',
    ),
    'KE': CountryPack(
        'KE', 'Kenya', 'KES', 'Africa/Nairobi', ('monthly',),
        ('tin', 'national_id', 'passport', 'social_security_number'),
        ('paye', 'nssf', 'shif', 'itf', 'housing_fund'),
        ('quickbooks', 'xero', 'microsoft365'),
        (('tin','Tax Identification Number',False),('national_id','National ID Number',False),('passport','Passport Number',False),('social_security_number','Social Security Number',False)),
        ('nssf', 'shif'),
        False,
        ('en','sw',),
        '',
    ),
    'TZ': CountryPack(
        'TZ', 'Tanzania', 'TZS', 'Africa/Dar_es_Salaam', ('monthly',),
        ('tin', 'national_id', 'passport', 'social_security_number'),
        ('paye', 'nssf', 'psssf'),
        ('quickbooks', 'xero', 'microsoft365'),
        (('tin','Tax Identification Number',False),('national_id','National ID Number',False),('passport','Passport Number',False),('social_security_number','Social Security Number',False)),
        ('nssf', 'psssf'),
        False,
        ('sw','en',),
        '',
    ),
    'UG': CountryPack(
        'UG', 'Uganda', 'UGX', 'Africa/Kampala', ('monthly',),
        ('tin', 'national_id', 'passport', 'social_security_number'),
        ('paye', 'nssf'),
        ('quickbooks', 'xero', 'microsoft365'),
        (('tin','Tax Identification Number',False),('national_id','National ID Number',False),('passport','Passport Number',False),('social_security_number','Social Security Number',False)),
        ('nssf',),
        False,
        ('en','sw',),
        '',
    ),
    'RW': CountryPack(
        'RW', 'Rwanda', 'RWF', 'Africa/Kigali', ('monthly',),
        ('tin', 'national_id', 'passport', 'social_security_number'),
        ('paye', 'rssb'),
        ('quickbooks', 'xero', 'microsoft365'),
        (('tin','Tax Identification Number',False),('national_id','National ID Number',False),('passport','Passport Number',False),('social_security_number','Social Security Number',False)),
        ('rssb',),
        False,
        ('rw','fr','en','sw',),
        '',
    ),
    'ZM': CountryPack(
        'ZM', 'Zambia', 'ZMW', 'Africa/Lusaka', ('monthly',),
        ('tin', 'national_id', 'passport', 'social_security_number'),
        ('paye', 'napsa', 'workers_compensation'),
        ('quickbooks', 'xero', 'microsoft365'),
        (('tin','Tax Identification Number',False),('national_id','National ID Number',False),('passport','Passport Number',False),('social_security_number','Social Security Number',False)),
        ('napsa',),
        False,
        ('en',),
        '',
    ),
    'ZW': CountryPack(
        'ZW', 'Zimbabwe', 'ZWG', 'Africa/Harare', ('monthly',),
        ('tin', 'national_id', 'passport', 'social_security_number'),
        ('paye', 'nssa', 'workers_compensation'),
        ('quickbooks', 'xero', 'microsoft365'),
        (('tin','Tax Identification Number',False),('national_id','National ID Number',False),('passport','Passport Number',False),('social_security_number','Social Security Number',False)),
        ('nssa',),
        False,
        ('en','sn','nd',),
        '',
    ),
    'BW': CountryPack(
        'BW', 'Botswana', 'BWP', 'Africa/Gaborone', ('monthly',),
        ('tin', 'national_id', 'passport', 'social_security_number'),
        ('paye', 'bwc'),
        ('quickbooks', 'xero', 'microsoft365'),
        (('tin','Tax Identification Number',False),('national_id','National ID Number',False),('passport','Passport Number',False),('social_security_number','Social Security Number',False)),
        ('bwc',),
        False,
        ('en','tn',),
        '',
    ),
    'NA': CountryPack(
        'NA', 'Namibia', 'NAD', 'Africa/Windhoek', ('monthly',),
        ('tin', 'national_id', 'passport', 'social_security_number'),
        ('paye', 'fnb', 'seo', 'socfo'),
        ('quickbooks', 'xero', 'microsoft365'),
        (('tin','Tax Identification Number',False),('national_id','National ID Number',False),('passport','Passport Number',False),('social_security_number','Social Security Number',False)),
        ('fnb',),
        False,
        ('en',),
        '',
    ),
    'ZA': CountryPack(
        'ZA', 'South Africa', 'ZAR', 'Africa/Johannesburg', ('monthly',),
        ('tin', 'national_id', 'passport', 'social_security_number'),
        ('paye', 'uif', 'sdl', 'medical_aid', 'pension'),
        ('quickbooks', 'xero', 'microsoft365'),
        (('tin','Tax Identification Number',False),('national_id','National ID Number',False),('passport','Passport Number',False),('social_security_number','Social Security Number',False)),
        ('uif',),
        False,
        ('af','en','nso','nr','ss','st','tn','ts','ve','xh','zu',),
        '',
    ),
    'EG': CountryPack(
        'EG', 'Egypt', 'EGP', 'Africa/Cairo', ('monthly',),
        ('tin', 'national_id', 'passport', 'social_security_number'),
        ('paye', 'social_insurance'),
        ('quickbooks', 'xero', 'microsoft365'),
        (('tin','Tax Identification Number',False),('national_id','National ID Number',False),('passport','Passport Number',False),('social_security_number','Social Security Number',False)),
        ('social_insurance',),
        False,
        ('ar',),
        '',
    ),
    'AO': CountryPack(
        'AO', 'Angola', 'AOA', 'Africa/Luanda', ('monthly',),
        ('tin', 'national_id', 'passport', 'social_security_number'),
        ('paye', 'social_security'),
        ('quickbooks', 'xero', 'microsoft365'),
        (('tin','Tax Identification Number',False),('national_id','National ID Number',False),('passport','Passport Number',False),('social_security_number','Social Security Number',False)),
        (),
        True,
        ('pt',),
        '',
    ),
    'BF': CountryPack(
        'BF', 'Burkina Faso', 'XOF', 'Africa/Ouagadougou', ('monthly',),
        ('tin', 'national_id', 'passport', 'social_security_number'),
        ('paye', 'social_security'),
        ('quickbooks', 'xero', 'microsoft365'),
        (('tin','Tax Identification Number',False),('national_id','National ID Number',False),('passport','Passport Number',False),('social_security_number','Social Security Number',False)),
        ('cnss',),
        False,
        ('fr',),
        '',
    ),
    'BJ': CountryPack(
        'BJ', 'Benin', 'XOF', 'Africa/Porto-Novo', ('monthly',),
        ('tin', 'national_id', 'passport', 'social_security_number'),
        ('paye', 'social_security'),
        ('quickbooks', 'xero', 'microsoft365'),
        (('tin','Tax Identification Number',False),('national_id','National ID Number',False),('passport','Passport Number',False),('social_security_number','Social Security Number',False)),
        (),
        True,
        ('fr',),
        'Bénin',
    ),
    'BI': CountryPack(
        'BI', 'Burundi', 'BIF', 'Africa/Bujumbura', ('monthly',),
        ('tin', 'national_id', 'passport', 'social_security_number'),
        ('paye', 'social_security'),
        ('quickbooks', 'xero', 'microsoft365'),
        (('tin','Tax Identification Number',False),('national_id','National ID Number',False),('passport','Passport Number',False),('social_security_number','Social Security Number',False)),
        (),
        True,
        ('fr',),
        '',
    ),
    'CD': CountryPack(
        'CD', 'DR Congo', 'CDF', 'Africa/Kinshasa', ('monthly',),
        ('tin', 'national_id', 'passport', 'social_security_number'),
        ('paye', 'social_security'),
        ('quickbooks', 'xero', 'microsoft365'),
        (('tin','Tax Identification Number',False),('national_id','National ID Number',False),('passport','Passport Number',False),('social_security_number','Social Security Number',False)),
        (),
        True,
        ('fr',),
        'République démocratique du Congo',
    ),
    'CF': CountryPack(
        'CF', 'Central African Republic', 'XAF', 'Africa/Bangui', ('monthly',),
        ('tin', 'national_id', 'passport', 'social_security_number'),
        ('paye', 'social_security'),
        ('quickbooks', 'xero', 'microsoft365'),
        (('tin','Tax Identification Number',False),('national_id','National ID Number',False),('passport','Passport Number',False),('social_security_number','Social Security Number',False)),
        (),
        True,
        ('fr','sg',),
        'République centrafricaine',
    ),
    'CG': CountryPack(
        'CG', 'Republic of the Congo', 'XAF', 'Africa/Brazzaville', ('monthly',),
        ('tin', 'national_id', 'passport', 'social_security_number'),
        ('paye', 'social_security'),
        ('quickbooks', 'xero', 'microsoft365'),
        (('tin','Tax Identification Number',False),('national_id','National ID Number',False),('passport','Passport Number',False),('social_security_number','Social Security Number',False)),
        ('cnss',),
        False,
        ('fr',),
        'République du Congo',
    ),
    'CI': CountryPack(
        'CI', "Côte d'Ivoire", 'XOF', 'Africa/Abidjan', ('monthly',),
        ('tin', 'national_id', 'passport', 'social_security_number'),
        ('paye', 'social_security'),
        ('quickbooks', 'xero', 'microsoft365'),
        (('tin','Tax Identification Number',False),('national_id','National ID Number',False),('passport','Passport Number',False),('social_security_number','Social Security Number',False)),
        ('cnps',),
        False,
        ('fr',),
        '',
    ),
    'CM': CountryPack(
        'CM', 'Cameroon', 'XAF', 'Africa/Douala', ('monthly',),
        ('tin', 'national_id', 'passport', 'social_security_number'),
        ('paye', 'social_security'),
        ('quickbooks', 'xero', 'microsoft365'),
        (('tin','Tax Identification Number',False),('national_id','National ID Number',False),('passport','Passport Number',False),('social_security_number','Social Security Number',False)),
        ('cnps',),
        False,
        ('fr','en',),
        'Cameroun',
    ),
    'CV': CountryPack(
        'CV', 'Cabo Verde', 'CVE', 'Atlantic/Cape_Verde', ('monthly',),
        ('tin', 'national_id', 'passport', 'social_security_number'),
        ('paye', 'social_security'),
        ('quickbooks', 'xero', 'microsoft365'),
        (('tin','Tax Identification Number',False),('national_id','National ID Number',False),('passport','Passport Number',False),('social_security_number','Social Security Number',False)),
        (),
        True,
        ('pt',),
        '',
    ),
    'DJ': CountryPack(
        'DJ', 'Djibouti', 'DJF', 'Africa/Djibouti', ('monthly',),
        ('tin', 'national_id', 'passport', 'social_security_number'),
        ('paye', 'social_security'),
        ('quickbooks', 'xero', 'microsoft365'),
        (('tin','Tax Identification Number',False),('national_id','National ID Number',False),('passport','Passport Number',False),('social_security_number','Social Security Number',False)),
        (),
        True,
        ('fr','ar',),
        '',
    ),
    'DZ': CountryPack(
        'DZ', 'Algeria', 'DZD', 'Africa/Algiers', ('monthly',),
        ('tin', 'national_id', 'passport', 'social_security_number'),
        ('paye', 'social_security'),
        ('quickbooks', 'xero', 'microsoft365'),
        (('tin','Tax Identification Number',False),('national_id','National ID Number',False),('passport','Passport Number',False),('social_security_number','Social Security Number',False)),
        (),
        True,
        ('ar','kab',),
        'Algérie',
    ),
    'ER': CountryPack(
        'ER', 'Eritrea', 'ERN', 'Africa/Asmara', ('monthly',),
        ('tin', 'national_id', 'passport', 'social_security_number'),
        ('paye', 'social_security'),
        ('quickbooks', 'xero', 'microsoft365'),
        (('tin','Tax Identification Number',False),('national_id','National ID Number',False),('passport','Passport Number',False),('social_security_number','Social Security Number',False)),
        (),
        True,
        ('ti','ar','en',),
        'Érythrée',
    ),
    'ET': CountryPack(
        'ET', 'Ethiopia', 'ETB', 'Africa/Addis_Ababa', ('monthly',),
        ('tin', 'national_id', 'passport', 'social_security_number'),
        ('paye', 'social_security'),
        ('quickbooks', 'xero', 'microsoft365'),
        (('tin','Tax Identification Number',False),('national_id','National ID Number',False),('passport','Passport Number',False),('social_security_number','Social Security Number',False)),
        (),
        True,
        ('am',),
        'Éthiopie',
    ),
    'GA': CountryPack(
        'GA', 'Gabon', 'XAF', 'Africa/Libreville', ('monthly',),
        ('tin', 'national_id', 'passport', 'social_security_number'),
        ('paye', 'social_security'),
        ('quickbooks', 'xero', 'microsoft365'),
        (('tin','Tax Identification Number',False),('national_id','National ID Number',False),('passport','Passport Number',False),('social_security_number','Social Security Number',False)),
        ('cnss',),
        False,
        ('fr',),
        '',
    ),
    'GN': CountryPack(
        'GN', 'Guinea', 'GNF', 'Africa/Conakry', ('monthly',),
        ('tin', 'national_id', 'passport', 'social_security_number'),
        ('paye', 'social_security'),
        ('quickbooks', 'xero', 'microsoft365'),
        (('tin','Tax Identification Number',False),('national_id','National ID Number',False),('passport','Passport Number',False),('social_security_number','Social Security Number',False)),
        (),
        True,
        ('fr',),
        'Guinée',
    ),
    'GQ': CountryPack(
        'GQ', 'Equatorial Guinea', 'XAF', 'Africa/Malabo', ('monthly',),
        ('tin', 'national_id', 'passport', 'social_security_number'),
        ('paye', 'social_security'),
        ('quickbooks', 'xero', 'microsoft365'),
        (('tin','Tax Identification Number',False),('national_id','National ID Number',False),('passport','Passport Number',False),('social_security_number','Social Security Number',False)),
        ('inseso',),
        False,
        ('fr','es','pt',),
        'Guinée équatoriale',
    ),
    'GW': CountryPack(
        'GW', 'Guinea-Bissau', 'XOF', 'Africa/Bissau', ('monthly',),
        ('tin', 'national_id', 'passport', 'social_security_number'),
        ('paye', 'social_security'),
        ('quickbooks', 'xero', 'microsoft365'),
        (('tin','Tax Identification Number',False),('national_id','National ID Number',False),('passport','Passport Number',False),('social_security_number','Social Security Number',False)),
        (),
        True,
        ('pt',),
        '',
    ),
    'KM': CountryPack(
        'KM', 'Comoros', 'KMF', 'Indian/Comoro', ('monthly',),
        ('tin', 'national_id', 'passport', 'social_security_number'),
        ('paye', 'social_security'),
        ('quickbooks', 'xero', 'microsoft365'),
        (('tin','Tax Identification Number',False),('national_id','National ID Number',False),('passport','Passport Number',False),('social_security_number','Social Security Number',False)),
        (),
        True,
        ('fr','ar',),
        'Comores',
    ),
    'LS': CountryPack(
        'LS', 'Lesotho', 'LSL', 'Africa/Maseru', ('monthly',),
        ('tin', 'national_id', 'passport', 'social_security_number'),
        ('paye', 'social_security'),
        ('quickbooks', 'xero', 'microsoft365'),
        (('tin','Tax Identification Number',False),('national_id','National ID Number',False),('passport','Passport Number',False),('social_security_number','Social Security Number',False)),
        (),
        True,
        ('en','st',),
        '',
    ),
    'LY': CountryPack(
        'LY', 'Libya', 'LYD', 'Africa/Tripoli', ('monthly',),
        ('tin', 'national_id', 'passport', 'social_security_number'),
        ('paye', 'social_security'),
        ('quickbooks', 'xero', 'microsoft365'),
        (('tin','Tax Identification Number',False),('national_id','National ID Number',False),('passport','Passport Number',False),('social_security_number','Social Security Number',False)),
        (),
        True,
        ('ar',),
        'Libye',
    ),
    'MA': CountryPack(
        'MA', 'Morocco', 'MAD', 'Africa/Casablanca', ('monthly',),
        ('tin', 'national_id', 'passport', 'social_security_number'),
        ('paye', 'social_security'),
        ('quickbooks', 'xero', 'microsoft365'),
        (('tin','Tax Identification Number',False),('national_id','National ID Number',False),('passport','Passport Number',False),('social_security_number','Social Security Number',False)),
        ('cnss',),
        False,
        # Arabic and Amazigh are Morocco's two official languages - Berber became
        # official in the 2011 constitution and was implemented in 2019. `zgh` is
        # ISO 639-2 "Standard Moroccan Tamazight", the individual language the
        # constitution names, not the `ber` collective for Berber languages.
        # French is NOT official despite being the language of its
        # administration, courts, banks and business, so it is deliberately
        # absent here; it is recorded only as this pack's own-language name.
        ('ar', 'zgh'),
        'Maroc',
    ),
    'MG': CountryPack(
        'MG', 'Madagascar', 'MGA', 'Indian/Antananarivo', ('monthly',),
        ('tin', 'national_id', 'passport', 'social_security_number'),
        ('paye', 'social_security'),
        ('quickbooks', 'xero', 'microsoft365'),
        (('tin','Tax Identification Number',False),('national_id','National ID Number',False),('passport','Passport Number',False),('social_security_number','Social Security Number',False)),
        ('cnaps',),
        False,
        ('mg','fr',),
        '',
    ),
    'ML': CountryPack(
        'ML', 'Mali', 'XOF', 'Africa/Bamako', ('monthly',),
        ('tin', 'national_id', 'passport', 'social_security_number'),
        ('paye', 'social_security'),
        ('quickbooks', 'xero', 'microsoft365'),
        (('tin','Tax Identification Number',False),('national_id','National ID Number',False),('passport','Passport Number',False),('social_security_number','Social Security Number',False)),
        (),
        True,
        ('fr',),
        '',
    ),
    'MR': CountryPack(
        'MR', 'Mauritania', 'MRU', 'Africa/Nouakchott', ('monthly',),
        ('tin', 'national_id', 'passport', 'social_security_number'),
        ('paye', 'social_security'),
        ('quickbooks', 'xero', 'microsoft365'),
        (('tin','Tax Identification Number',False),('national_id','National ID Number',False),('passport','Passport Number',False),('social_security_number','Social Security Number',False)),
        (),
        True,
        ('ar',),
        '',
    ),
    'MU': CountryPack(
        'MU', 'Mauritius', 'MUR', 'Indian/Mauritius', ('monthly',),
        ('tin', 'national_id', 'passport', 'social_security_number'),
        ('paye', 'social_security'),
        ('quickbooks', 'xero', 'microsoft365'),
        (('tin','Tax Identification Number',False),('national_id','National ID Number',False),('passport','Passport Number',False),('social_security_number','Social Security Number',False)),
        (),
        True,
        ('en','fr',),
        '',
    ),
    'MW': CountryPack(
        'MW', 'Malawi', 'MWK', 'Africa/Blantyre', ('monthly',),
        ('tin', 'national_id', 'passport', 'social_security_number'),
        ('paye', 'social_security'),
        ('quickbooks', 'xero', 'microsoft365'),
        (('tin','Tax Identification Number',False),('national_id','National ID Number',False),('passport','Passport Number',False),('social_security_number','Social Security Number',False)),
        (),
        True,
        ('en','ny',),
        '',
    ),
    'MZ': CountryPack(
        'MZ', 'Mozambique', 'MZN', 'Africa/Maputo', ('monthly',),
        ('tin', 'national_id', 'passport', 'social_security_number'),
        ('paye', 'social_security'),
        ('quickbooks', 'xero', 'microsoft365'),
        (('tin','Tax Identification Number',False),('national_id','National ID Number',False),('passport','Passport Number',False),('social_security_number','Social Security Number',False)),
        (),
        True,
        ('pt',),
        'Moçambique',
    ),
    'NE': CountryPack(
        'NE', 'Niger', 'XOF', 'Africa/Niamey', ('monthly',),
        ('tin', 'national_id', 'passport', 'social_security_number'),
        ('paye', 'social_security'),
        ('quickbooks', 'xero', 'microsoft365'),
        (('tin','Tax Identification Number',False),('national_id','National ID Number',False),('passport','Passport Number',False),('social_security_number','Social Security Number',False)),
        (),
        True,
        ('fr',),
        '',
    ),
    'SC': CountryPack(
        'SC', 'Seychelles', 'SCR', 'Indian/Mahe', ('monthly',),
        ('tin', 'national_id', 'passport', 'social_security_number'),
        ('paye', 'social_security'),
        ('quickbooks', 'xero', 'microsoft365'),
        (('tin','Tax Identification Number',False),('national_id','National ID Number',False),('passport','Passport Number',False),('social_security_number','Social Security Number',False)),
        (),
        True,
        ('fr','en',),
        '',
    ),
    'SD': CountryPack(
        'SD', 'Sudan', 'SDG', 'Africa/Khartoum', ('monthly',),
        ('tin', 'national_id', 'passport', 'social_security_number'),
        ('paye', 'social_security'),
        ('quickbooks', 'xero', 'microsoft365'),
        (('tin','Tax Identification Number',False),('national_id','National ID Number',False),('passport','Passport Number',False),('social_security_number','Social Security Number',False)),
        (),
        True,
        ('ar','en',),
        '',
    ),
    'SN': CountryPack(
        'SN', 'Senegal', 'XOF', 'Africa/Dakar', ('monthly',),
        ('tin', 'national_id', 'passport', 'social_security_number'),
        ('paye', 'social_security'),
        ('quickbooks', 'xero', 'microsoft365'),
        (('tin','Tax Identification Number',False),('national_id','National ID Number',False),('passport','Passport Number',False),('social_security_number','Social Security Number',False)),
        ('cnss',),
        False,
        ('fr',),
        'Sénégal',
    ),
    'SO': CountryPack(
        'SO', 'Somalia', 'SOS', 'Africa/Mogadishu', ('monthly',),
        ('tin', 'national_id', 'passport', 'social_security_number'),
        ('paye', 'social_security'),
        ('quickbooks', 'xero', 'microsoft365'),
        (('tin','Tax Identification Number',False),('national_id','National ID Number',False),('passport','Passport Number',False),('social_security_number','Social Security Number',False)),
        (),
        True,
        ('so','ar',),
        '',
    ),
    'SS': CountryPack(
        'SS', 'South Sudan', 'SSP', 'Africa/Juba', ('monthly',),
        ('tin', 'national_id', 'passport', 'social_security_number'),
        ('paye', 'social_security'),
        ('quickbooks', 'xero', 'microsoft365'),
        (('tin','Tax Identification Number',False),('national_id','National ID Number',False),('passport','Passport Number',False),('social_security_number','Social Security Number',False)),
        (),
        True,
        ('en',),
        '',
    ),
    'ST': CountryPack(
        'ST', 'São Tomé and Príncipe', 'STN', 'Africa/Sao_Tome', ('monthly',),
        ('tin', 'national_id', 'passport', 'social_security_number'),
        ('paye', 'social_security'),
        ('quickbooks', 'xero', 'microsoft365'),
        (('tin','Tax Identification Number',False),('national_id','National ID Number',False),('passport','Passport Number',False),('social_security_number','Social Security Number',False)),
        (),
        True,
        ('pt',),
        'São Tomé-et-Príncipe',
    ),
    'SZ': CountryPack(
        'SZ', 'Eswatini', 'SZL', 'Africa/Mbabane', ('monthly',),
        ('tin', 'national_id', 'passport', 'social_security_number'),
        ('paye', 'social_security'),
        ('quickbooks', 'xero', 'microsoft365'),
        (('tin','Tax Identification Number',False),('national_id','National ID Number',False),('passport','Passport Number',False),('social_security_number','Social Security Number',False)),
        (),
        True,
        ('en','ss',),
        '',
    ),
    'TD': CountryPack(
        'TD', 'Chad', 'XAF', 'Africa/Ndjamena', ('monthly',),
        ('tin', 'national_id', 'passport', 'social_security_number'),
        ('paye', 'social_security'),
        ('quickbooks', 'xero', 'microsoft365'),
        (('tin','Tax Identification Number',False),('national_id','National ID Number',False),('passport','Passport Number',False),('social_security_number','Social Security Number',False)),
        (),
        True,
        ('fr','ar',),
        'Tchad',
    ),
    'TG': CountryPack(
        'TG', 'Togo', 'XOF', 'Africa/Lome', ('monthly',),
        ('tin', 'national_id', 'passport', 'social_security_number'),
        ('paye', 'social_security'),
        ('quickbooks', 'xero', 'microsoft365'),
        (('tin','Tax Identification Number',False),('national_id','National ID Number',False),('passport','Passport Number',False),('social_security_number','Social Security Number',False)),
        (),
        True,
        ('fr',),
        '',
    ),
    'TN': CountryPack(
        'TN', 'Tunisia', 'TND', 'Africa/Tunis', ('monthly',),
        ('tin', 'national_id', 'passport', 'social_security_number'),
        ('paye', 'social_security'),
        ('quickbooks', 'xero', 'microsoft365'),
        (('tin','Tax Identification Number',False),('national_id','National ID Number',False),('passport','Passport Number',False),('social_security_number','Social Security Number',False)),
        (),
        True,
        ('ar',),
        'Tunisie',
    ),
}


def get_country_pack(code: str) -> CountryPack:
    try:
        return COUNTRY_PACKS[code.upper()]
    except KeyError:
        raise ValueError(f'Unsupported country code: {code}')
