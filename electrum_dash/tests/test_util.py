import unittest
from electrum_dash.util import format_satoshis, parse_URI

from . import SequentialTestCase


class TestUtil(SequentialTestCase):

    def test_format_satoshis(self):
        result = format_satoshis(1234)
        expected = "0.00001234"
        self.assertEqual(expected, result)

    def test_format_satoshis_negative(self):
        result = format_satoshis(-1234)
        expected = "-0.00001234"
        self.assertEqual(expected, result)

    def test_format_fee(self):
        result = format_satoshis(1700/1000, 0, 0)
        expected = "1.7"
        self.assertEqual(expected, result)

    def test_format_fee_precision(self):
        result = format_satoshis(1666/1000, 0, 0, precision=6)
        expected = "1.666"
        self.assertEqual(expected, result)

        result = format_satoshis(1666/1000, 0, 0, precision=1)
        expected = "1.7"
        self.assertEqual(expected, result)

    def test_format_satoshis_whitespaces(self):
        result = format_satoshis(12340, whitespaces=True)
        expected = "     0.0001234 "
        self.assertEqual(expected, result)

        result = format_satoshis(1234, whitespaces=True)
        expected = "     0.00001234"
        self.assertEqual(expected, result)

    def test_format_satoshis_whitespaces_negative(self):
        result = format_satoshis(-12340, whitespaces=True)
        expected = "    -0.0001234 "
        self.assertEqual(expected, result)

        result = format_satoshis(-1234, whitespaces=True)
        expected = "    -0.00001234"
        self.assertEqual(expected, result)

    def test_format_satoshis_diff_positive(self):
        result = format_satoshis(1234, is_diff=True)
        expected = "+0.00001234"
        self.assertEqual(expected, result)

    def test_format_satoshis_diff_negative(self):
        result = format_satoshis(-1234, is_diff=True)
        expected = "-0.00001234"
        self.assertEqual(expected, result)

    def _do_test_parse_URI(self, uri, expected):
        result = parse_URI(uri)
        self.assertEqual(expected, result)

    def test_parse_URI_address(self):
        self._do_test_parse_URI('dash:XfTA9qgYmaEHfWhUakwcoTtyquez8SowY1',
                                {'address': 'XfTA9qgYmaEHfWhUakwcoTtyquez8SowY1'})

    def test_parse_URI_only_address(self):
        self._do_test_parse_URI('XfTA9qgYmaEHfWhUakwcoTtyquez8SowY1',
                                {'address': 'XfTA9qgYmaEHfWhUakwcoTtyquez8SowY1'})


    def test_parse_URI_address_label(self):
        self._do_test_parse_URI('dash:XfTA9qgYmaEHfWhUakwcoTtyquez8SowY1?label=electrum%20test',
                                {'address': 'XfTA9qgYmaEHfWhUakwcoTtyquez8SowY1', 'label': 'electrum test'})

    def test_parse_URI_address_message(self):
        self._do_test_parse_URI('dash:XfTA9qgYmaEHfWhUakwcoTtyquez8SowY1?message=electrum%20test',
                                {'address': 'XfTA9qgYmaEHfWhUakwcoTtyquez8SowY1', 'message': 'electrum test', 'memo': 'electrum test'})

    def test_parse_URI_address_amount(self):
        self._do_test_parse_URI('dash:XfTA9qgYmaEHfWhUakwcoTtyquez8SowY1?amount=0.0003',
                                {'address': 'XfTA9qgYmaEHfWhUakwcoTtyquez8SowY1', 'amount': 30000})

    def test_parse_URI_address_request_url(self):
        self._do_test_parse_URI('dash:XfTA9qgYmaEHfWhUakwcoTtyquez8SowY1?r=http://domain.tld/page?h%3D2a8628fc2fbe',
                                {'address': 'XfTA9qgYmaEHfWhUakwcoTtyquez8SowY1', 'r': 'http://domain.tld/page?h=2a8628fc2fbe'})

    def test_parse_URI_ignore_args(self):
        self._do_test_parse_URI('dash:XfTA9qgYmaEHfWhUakwcoTtyquez8SowY1?test=test',
                                {'address': 'XfTA9qgYmaEHfWhUakwcoTtyquez8SowY1', 'test': 'test'})

    def test_parse_URI_multiple_args(self):
        self._do_test_parse_URI('dash:XfTA9qgYmaEHfWhUakwcoTtyquez8SowY1?amount=0.00004&label=electrum-test&message=electrum%20test&test=none&r=http://domain.tld/page',
                                {'address': 'XfTA9qgYmaEHfWhUakwcoTtyquez8SowY1', 'amount': 4000, 'label': 'electrum-test', 'message': u'electrum test', 'memo': u'electrum test', 'r': 'http://domain.tld/page', 'test': 'none'})

    def test_parse_URI_no_address_request_url(self):
        self._do_test_parse_URI('dash:?r=http://domain.tld/page?h%3D2a8628fc2fbe',
                                {'r': 'http://domain.tld/page?h=2a8628fc2fbe'})

    def test_parse_URI_invalid_address(self):
        self.assertRaises(BaseException, parse_URI, 'dash:invalidaddress')

    def test_parse_URI_invalid(self):
        self.assertRaises(BaseException, parse_URI, 'notdash:XfTA9qgYmaEHfWhUakwcoTtyquez8SowY1')

    def test_parse_URI_parameter_polution(self):
        self.assertRaises(Exception, parse_URI, 'dash:XfTA9qgYmaEHfWhUakwcoTtyquez8SowY1?amount=0.0003&label=test&amount=30.0')
