import json
from datetime import datetime
from unittest import mock
from urllib.error import HTTPError, URLError

from django.test import SimpleTestCase

from biometrics.management.commands import adt_bridge


class AdmsParserTests(SimpleTestCase):
    def test_tab_payload(self):
        parsed = adt_bridge.parse_adms('1001\t2026-10-25 08:02:14\t0\t1')
        self.assertEqual(parsed['pin'], '1001')
        self.assertEqual(parsed['status'], 0)
        self.assertEqual(parsed['verify_mode'], 1)
        self.assertEqual(parsed['punch_time'], datetime(2026, 10, 25, 8, 2, 14))

    def test_tab_payload_with_zulu_timestamp(self):
        parsed = adt_bridge.parse_adms('1001\t2026-10-25T08:02:14Z\t1\t1')
        self.assertEqual(parsed['status'], 1)
        self.assertTrue(parsed['punch_time'].utcoffset().total_seconds() == 0)

    def test_tab_payload_without_verify_mode(self):
        parsed = adt_bridge.parse_adms('1001\t2026-10-25 08:02:14\t0')
        self.assertEqual(parsed['verify_mode'], 0)

    def test_kv_payload_keeps_timestamp_with_a_space(self):
        parsed = adt_bridge.parse_adms(
            'PIN=1001\tDateTime=2026-10-25 08:02:14\tStatus=0\tVerifyMode=1')
        self.assertEqual(parsed['pin'], '1001')
        self.assertEqual(parsed['punch_time'], datetime(2026, 10, 25, 8, 2, 14))

    def test_kv_payload_with_spaces_between_keys(self):
        parsed = adt_bridge.parse_adms(
            'PIN=1001 DateTime=2026-10-25 08:02:14 Status=1 VerifyMode=1')
        self.assertEqual(parsed['pin'], '1001')
        self.assertEqual(parsed['status'], 1)
        self.assertEqual(parsed['punch_time'], datetime(2026, 10, 25, 8, 2, 14))

    def test_garbage_is_rejected_instead_of_raising(self):
        self.assertIsNone(adt_bridge.parse_adms('not a punch'))
        self.assertIsNone(adt_bridge.parse_adms(''))
        self.assertIsNone(adt_bridge.parse_adms('1001\t2026-10-25 08:02:14\t'))
        self.assertIsNone(adt_bridge.parse_adms('1001\tnonsense\t0\t1'))

    def test_kv_payload_without_status_defaults_to_clock_in(self):
        parsed = adt_bridge.parse_adms('PIN=1001\tDateTime=2026-10-25 08:02:14')
        self.assertEqual(parsed['status'], 0)

    def test_kv_payload_with_bad_status_is_rejected(self):
        self.assertIsNone(adt_bridge.parse_adms(
            'PIN=1001\tDateTime=2026-10-25 08:02:14\tStatus=soon'))


class BridgeForwardTests(SimpleTestCase):
    def _response(self, body, status=201):
        response = mock.MagicMock()
        response.__enter__.return_value = response
        response.__exit__.return_value = False
        response.status = status
        response.read.return_value = json.dumps(body).encode('utf-8')
        return response

    def test_pin_is_forwarded_as_the_identifier_not_resolved_locally(self):
        response = self._response({'status': 'recorded', 'matched_by': 'code'})
        with mock.patch.object(adt_bridge, 'urlopen', return_value=response) as posted:
            outcome = adt_bridge.ingest_punch(
                '1001\t2026-10-25 08:02:14\t0\t1', 'ZK-001', 'secret')

        request = posted.call_args.args[0]
        body = json.loads(request.data)
        self.assertEqual(body['employee'], '1001')
        self.assertEqual(body['device_id'], 'ZK-001')
        self.assertEqual(body['punch_type'], 'in')
        self.assertEqual(
            {key.lower(): value for key, value in request.header_items()}
            .get('x-biometric-device-key'),
            'secret')
        self.assertEqual(outcome['status'], 'recorded')
        self.assertFalse(outcome['retryable'])

    def test_break_status_is_unknown_rather_than_a_clock_out(self):
        response = self._response({'status': 'recorded'})
        with mock.patch.object(adt_bridge, 'urlopen', return_value=response) as posted:
            adt_bridge.ingest_punch(
                '1001\t2026-10-25 12:02:14\t2\t1', 'ZK-001', 'secret')

        body = json.loads(posted.call_args.args[0].data)
        self.assertEqual(body['punch_type'], 'unknown')

    def test_missing_device_id_is_rejected_without_a_request(self):
        with mock.patch.object(adt_bridge, 'urlopen') as posted:
            outcome = adt_bridge.ingest_punch(
                '1001\t2026-10-25 08:02:14\t0\t1', '', 'secret')

        posted.assert_not_called()
        self.assertEqual(outcome['status'], 'rejected')
        self.assertFalse(outcome['retryable'])

    def test_unreadable_payload_is_rejected_without_a_request(self):
        with mock.patch.object(adt_bridge, 'urlopen') as posted:
            outcome = adt_bridge.ingest_punch('garbage', 'ZK-001', 'secret')

        posted.assert_not_called()
        self.assertEqual(outcome['status'], 'rejected')
        self.assertFalse(outcome['retryable'])

    def test_unreachable_api_is_retryable(self):
        with mock.patch.object(adt_bridge, 'urlopen', side_effect=URLError('down')):
            outcome = adt_bridge.ingest_punch(
                '1001\t2026-10-25 08:02:14\t0\t1', 'ZK-001', 'secret')

        self.assertTrue(outcome['retryable'])

    def test_api_client_error_is_not_retried(self):
        error = HTTPError('http://api/', 400, 'Bad Request', {}, None)
        error.read = lambda: b'{"detail": "punch_time is invalid"}'
        with mock.patch.object(adt_bridge, 'urlopen', side_effect=error):
            outcome = adt_bridge.ingest_punch(
                '1001\t2026-10-25 08:02:14\t0\t1', 'ZK-001', 'secret')

        self.assertFalse(outcome['retryable'])
        self.assertEqual(outcome['http_status'], 400)
        self.assertIn('punch_time is invalid', outcome['error'])

    def test_api_server_error_is_retried(self):
        error = HTTPError('http://api/', 503, 'Unavailable', {}, None)
        error.read = lambda: b''
        with mock.patch.object(adt_bridge, 'urlopen', side_effect=error):
            outcome = adt_bridge.ingest_punch(
                '1001\t2026-10-25 08:02:14\t0\t1', 'ZK-001', 'secret')

        self.assertTrue(outcome['retryable'])
        self.assertEqual(outcome['http_status'], 503)


class BridgeTokenTests(SimpleTestCase):
    def test_no_configured_token_allows_everything(self):
        self.assertTrue(adt_bridge.token_ok('', '', ''))

    def test_header_token(self):
        self.assertTrue(adt_bridge.token_ok('s3cret', 's3cret', ''))
        self.assertFalse(adt_bridge.token_ok('s3cret', 'wrong', ''))
        self.assertFalse(adt_bridge.token_ok('s3cret', '', ''))

    def test_query_token(self):
        self.assertTrue(adt_bridge.token_ok('s3cret', '', 'token=s3cret'))
        self.assertFalse(adt_bridge.token_ok('s3cret', '', 'token=wrong'))
