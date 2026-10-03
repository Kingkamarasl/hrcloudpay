from datetime import date
from decimal import Decimal
from unittest.mock import patch
from django.test import SimpleTestCase
from regional.paye import calculate_country_paye


class PAYEEngineTests(SimpleTestCase):
    def fake_rule(self, code, metadata, source='https://example.com'):
        return type('Rule', (), {'code': code, 'metadata': metadata, 'source_reference': source})

    @patch('regional.paye._rule')
    def test_nigeria_2026_bands(self, rule):
        rule.return_value = self.fake_rule('paye_2026', {
            'bands': [
                {'upper':'800000','rate':'0'}, {'upper':'3000000','rate':'15'},
                {'upper':'12000000','rate':'18'}, {'upper':'25000000','rate':'21'},
                {'upper':'50000000','rate':'23'}, {'upper':None,'rate':'25'},
            ]
        })
        result = calculate_country_paye('NG', Decimal('1000000'), Decimal('1000000'), date(2026,6,30))
        self.assertEqual(result['annualized_gross'], '12000000.00')
        self.assertEqual(result['annual_tax'], '1950000.00')
        self.assertEqual(result['period_tax'], '162500.00')

    @patch('regional.paye._rule')
    def test_liberia_zero_band(self, rule):
        rule.return_value = self.fake_rule('lr', {
            'bands': [
                {'upper':'70000','rate':'0'}, {'upper':'200000','rate':'5'},
                {'upper':'800000','rate':'15'}, {'upper':None,'rate':'25'},
            ]
        })
        result = calculate_country_paye('LR', Decimal('5000'), Decimal('5000'), date(2026,6,30))
        self.assertEqual(result['annualized_gross'], '60000.00')
        self.assertEqual(result['annual_tax'], '0.00')
        self.assertEqual(result['period_tax'], '0.00')
