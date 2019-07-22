import unittest
from unittest import mock
from decimal import Decimal

from electrum_dash.commands import Commands, eval_bool
from electrum_dash import storage
from electrum_dash.wallet import restore_wallet_from_text

from . import TestCaseForTestnet


class TestCommands(unittest.TestCase):

    def test_setconfig_non_auth_number(self):
        self.assertEqual(7777, Commands._setconfig_normalize_value('rpcport', "7777"))
        self.assertEqual(7777, Commands._setconfig_normalize_value('rpcport', '7777'))
        self.assertAlmostEqual(Decimal(2.3), Commands._setconfig_normalize_value('somekey', '2.3'))

    def test_setconfig_non_auth_number_as_string(self):
        self.assertEqual("7777", Commands._setconfig_normalize_value('somekey', "'7777'"))

    def test_setconfig_non_auth_boolean(self):
        self.assertEqual(True, Commands._setconfig_normalize_value('show_console_tab', "true"))
        self.assertEqual(True, Commands._setconfig_normalize_value('show_console_tab', "True"))

    def test_setconfig_non_auth_list(self):
        self.assertEqual(['file:///var/www/', 'https://electrum.org'],
            Commands._setconfig_normalize_value('url_rewrite', "['file:///var/www/','https://electrum.org']"))
        self.assertEqual(['file:///var/www/', 'https://electrum.org'],
            Commands._setconfig_normalize_value('url_rewrite', '["file:///var/www/","https://electrum.org"]'))

    def test_setconfig_auth(self):
        self.assertEqual("7777", Commands._setconfig_normalize_value('rpcuser', "7777"))
        self.assertEqual("7777", Commands._setconfig_normalize_value('rpcuser', '7777'))
        self.assertEqual("7777", Commands._setconfig_normalize_value('rpcpassword', '7777'))
        self.assertEqual("2asd", Commands._setconfig_normalize_value('rpcpassword', '2asd'))
        self.assertEqual("['file:///var/www/','https://electrum.org']",
            Commands._setconfig_normalize_value('rpcpassword', "['file:///var/www/','https://electrum.org']"))

    def test_eval_bool(self):
        self.assertFalse(eval_bool("False"))
        self.assertFalse(eval_bool("false"))
        self.assertFalse(eval_bool("0"))
        self.assertTrue(eval_bool("True"))
        self.assertTrue(eval_bool("true"))
        self.assertTrue(eval_bool("1"))

    def test_convert_xkey(self):
        cmds = Commands(config=None, wallet=None, network=None)
        xpubs = {
            ("xpub6CCWFbvCbqF92kGwm9nV7t7RvVoQUKaq5USMdyVP6jvv1NgN52KAX6NNYCeE8Ca7JQC4K5tZcnQrubQcjJ6iixfPs4pwAQJAQgTt6hBjg11", "standard"),
        }
        for xkey1, xtype1 in xpubs:
            for xkey2, xtype2 in xpubs:
                self.assertEqual(xkey2, cmds.convert_xkey(xkey1, xtype2))

        xprvs = {
            ("xprv9yD9r6PJmTgqpGCUf8FUkkAhNTxv4rryiFWkqb5mYQPw8aMDXUzuyJ3tgv5vUqYkdK1E6Q5jKxPss4HkMBYV4q8AfG8t7rxgyS4xQX4ndAm", "standard"),
        }
        for xkey1, xtype1 in xprvs:
            for xkey2, xtype2 in xprvs:
                self.assertEqual(xkey2, cmds.convert_xkey(xkey1, xtype2))

    @mock.patch.object(storage.WalletStorage, '_write')
    def test_encrypt_decrypt(self, mock_write):
        wallet = restore_wallet_from_text('p2pkh:XJvTzLoBy3jPMZFSTzK6KqTiNR3n5xbreSScEy7u9C8fEf1GZG3X',
                                          path='if_this_exists_mocking_failed_648151893')['wallet']
        cmds = Commands(config=None, wallet=wallet, network=None)
        cleartext = "asdasd this is the message"
        pubkey = "021f110909ded653828a254515b58498a6bafc96799fb0851554463ed44ca7d9da"
        ciphertext = cmds.encrypt(pubkey, cleartext)
        self.assertEqual(cleartext, cmds.decrypt(pubkey, ciphertext))

    @mock.patch.object(storage.WalletStorage, '_write')
    def test_export_private_key_imported(self, mock_write):
        wallet = restore_wallet_from_text('p2pkh:XGx8LpkmLRv9RiMvpYx965BCaQKQbeMVVqgAh7B5SQVdosQiKJ4i p2pkh:XEn9o6oayjsRmoEQwDbvkrWVvjRNqPj3xNskJJPAKraJTrWuutwd',
                                          path='if_this_exists_mocking_failed_648151893')['wallet']
        cmds = Commands(config=None, wallet=wallet, network=None)
        # single address tests
        with self.assertRaises(Exception):
            cmds.getprivatekeys("asdasd")  # invalid addr, though might raise "not in wallet"
        with self.assertRaises(Exception):
            cmds.getprivatekeys("XdDHzW6aTeuQsraNXeEsPy5gAv1nUz7Y7Q")  # not in wallet
        self.assertEqual("p2pkh:XEn9o6oayjsRmoEQwDbvkrWVvjRNqPj3xNskJJPAKraJTrWuutwd",
                         cmds.getprivatekeys("Xci5KnMVkHrqBQk9cU4jwmzJfgaTPopHbz"))
        # list of addresses tests
        with self.assertRaises(Exception):
            cmds.getprivatekeys(['XmQ3Tn67Fgs7bwNXthtiEnBFh7ZeDG3aw2', 'asd'])
        self.assertEqual(['p2pkh:XGx8LpkmLRv9RiMvpYx965BCaQKQbeMVVqgAh7B5SQVdosQiKJ4i', 'p2pkh:XEn9o6oayjsRmoEQwDbvkrWVvjRNqPj3xNskJJPAKraJTrWuutwd'],
                         cmds.getprivatekeys(['XmQ3Tn67Fgs7bwNXthtiEnBFh7ZeDG3aw2', 'Xci5KnMVkHrqBQk9cU4jwmzJfgaTPopHbz']))

    @mock.patch.object(storage.WalletStorage, '_write')
    def test_export_private_key_deterministic(self, mock_write):
        wallet = restore_wallet_from_text('hint shock chair puzzle shock traffic drastic note dinosaur mention suggest sweet',
                                          gap_limit=2,
                                          path='if_this_exists_mocking_failed_648151893')['wallet']
        cmds = Commands(config=None, wallet=wallet, network=None)
        # single address tests
        with self.assertRaises(Exception):
            cmds.getprivatekeys("asdasd")  # invalid addr, though might raise "not in wallet"
        with self.assertRaises(Exception):
            cmds.getprivatekeys("XdDHzW6aTeuQsraNXeEsPy5gAv1nUz7Y7Q")  # not in wallet
        self.assertEqual("p2pkh:XE5VEmWKQRK5N7kQMfw6KqoRp3ExKWgaeCKsxsmDFBxJJBgdQdTH",
                         cmds.getprivatekeys("XvmHzyQe8QWbvv17wc1PPMyJgaomknSp7W"))
        # list of addresses tests
        with self.assertRaises(Exception):
            cmds.getprivatekeys(['XvmHzyQe8QWbvv17wc1PPMyJgaomknSp7W', 'asd'])
        self.assertEqual(['p2pkh:XE5VEmWKQRK5N7kQMfw6KqoRp3ExKWgaeCKsxsmDFBxJJBgdQdTH', 'p2pkh:XGtpLmVGmaRnfvRvd4qxSeE7PqJoi9FUfkgPKD24PeoJsZCh1EXg'],
                         cmds.getprivatekeys(['XvmHzyQe8QWbvv17wc1PPMyJgaomknSp7W', 'XoEUKPPiPETff1S4oQmo4HGR1rYrRAX6uT']))


class TestCommandsTestnet(TestCaseForTestnet):

    def test_convert_xkey(self):
        cmds = Commands(config=None, wallet=None, network=None)
        xpubs = {
            ("tpubD8p5qNfjczgTGbh9qgNxsbFgyhv8GgfVkmp3L88qtRm5ibUYiDVCrn6WYfnGey5XVVw6Bc5QNQUZW5B4jFQsHjmaenvkFUgWtKtgj5AdPm9", "standard"),
        }
        for xkey1, xtype1 in xpubs:
            for xkey2, xtype2 in xpubs:
                self.assertEqual(xkey2, cmds.convert_xkey(xkey1, xtype2))

        xprvs = {
            ("tprv8c83gxdVUcznP8fMx2iNUBbaQgQC7MUbBUDG3c6YU9xgt7Dn5pfcgHUeNZTAvuYmNgVHjyTzYzGWwJr7GvKCm2FkPaaJipyipbfJeB3tdPW", "standard"),
        }
        for xkey1, xtype1 in xprvs:
            for xkey2, xtype2 in xprvs:
                self.assertEqual(xkey2, cmds.convert_xkey(xkey1, xtype2))
