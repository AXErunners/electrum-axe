import unittest
from unittest import mock
import shutil
import tempfile
from typing import Sequence

from electrum_dash import storage, bitcoin, keystore
from electrum_dash.transaction import Transaction
from electrum_dash.simple_config import SimpleConfig
from electrum_dash.address_synchronizer import TX_HEIGHT_UNCONFIRMED, TX_HEIGHT_UNCONF_PARENT
from electrum_dash.wallet import sweep, Multisig_Wallet, Standard_Wallet, Imported_Wallet, restore_wallet_from_text
from electrum_dash.util import bfh, bh2u
from electrum_dash.transaction import TxOutput
from electrum_dash.mnemonic import seed_type

from . import TestCaseForTestnet
from . import SequentialTestCase
from .test_bitcoin import needs_test_with_all_ecc_implementations


UNICODE_HORROR_HEX = 'e282bf20f09f988020f09f98882020202020e3818620e38191e3819fe381be20e3828fe3828b2077cda2cda2cd9d68cda16fcda2cda120ccb8cda26bccb5cd9f6eccb4cd98c7ab77ccb8cc9b73cd9820cc80cc8177cd98cda2e1b8a9ccb561d289cca1cda27420cca7cc9568cc816fccb572cd8fccb5726f7273cca120ccb6cda1cda06cc4afccb665cd9fcd9f20ccb6cd9d696ecda220cd8f74cc9568ccb7cca1cd9f6520cd9fcd9f64cc9b61cd9c72cc95cda16bcca2cca820cda168ccb465cd8f61ccb7cca2cca17274cc81cd8f20ccb4ccb7cda0c3b2ccb5ccb666ccb82075cca7cd986ec3adcc9bcd9c63cda2cd8f6fccb7cd8f64ccb8cda265cca1cd9d3fcd9e'
UNICODE_HORROR = bfh(UNICODE_HORROR_HEX).decode('utf-8')
assert UNICODE_HORROR == '₿ 😀 😈     う けたま わる w͢͢͝h͡o͢͡ ̸͢k̵͟n̴͘ǫw̸̛s͘ ̀́w͘͢ḩ̵a҉̡͢t ̧̕h́o̵r͏̵rors̡ ̶͡͠lį̶e͟͟ ̶͝in͢ ͏t̕h̷̡͟e ͟͟d̛a͜r̕͡k̢̨ ͡h̴e͏a̷̢̡rt́͏ ̴̷͠ò̵̶f̸ u̧͘ní̛͜c͢͏o̷͏d̸͢e̡͝?͞'


class WalletIntegrityHelper:

    gap_limit = 1  # make tests run faster

    @classmethod
    def check_seeded_keystore_sanity(cls, test_obj, ks):
        test_obj.assertTrue(ks.is_deterministic())
        test_obj.assertFalse(ks.is_watching_only())
        test_obj.assertFalse(ks.can_import())
        test_obj.assertTrue(ks.has_seed())

    @classmethod
    def check_xpub_keystore_sanity(cls, test_obj, ks):
        test_obj.assertTrue(ks.is_deterministic())
        test_obj.assertTrue(ks.is_watching_only())
        test_obj.assertFalse(ks.can_import())
        test_obj.assertFalse(ks.has_seed())

    @classmethod
    def create_standard_wallet(cls, ks, gap_limit=None):
        store = storage.WalletStorage('if_this_exists_mocking_failed_648151893')
        store.put('keystore', ks.dump())
        store.put('gap_limit', gap_limit or cls.gap_limit)
        w = Standard_Wallet(store)
        w.synchronize()
        return w

    @classmethod
    def create_imported_wallet(cls, privkeys=False):
        store = storage.WalletStorage('if_this_exists_mocking_failed_648151893')
        if privkeys:
            k = keystore.Imported_KeyStore({})
            store.put('keystore', k.dump())
        w = Imported_Wallet(store)
        return w

    @classmethod
    def create_multisig_wallet(cls, keystores: Sequence, multisig_type: str, gap_limit=None):
        """Creates a multisig wallet."""
        store = storage.WalletStorage('if_this_exists_mocking_failed_648151893')
        for i, ks in enumerate(keystores):
            cosigner_index = i + 1
            store.put('x%d/' % cosigner_index, ks.dump())
        store.put('wallet_type', multisig_type)
        store.put('gap_limit', gap_limit or cls.gap_limit)
        w = Multisig_Wallet(store)
        w.synchronize()
        return w


class TestWalletKeystoreAddressIntegrityForMainnet(SequentialTestCase):

    @needs_test_with_all_ecc_implementations
    @mock.patch.object(storage.WalletStorage, '_write')
    def test_electrum_seed_standard(self, mock_write):
        seed_words = 'cycle rocket west magnet parrot shuffle foot correct salt library feed song'
        self.assertEqual(seed_type(seed_words), 'standard')

        ks = keystore.from_seed(seed_words, '', False)

        WalletIntegrityHelper.check_seeded_keystore_sanity(self, ks)
        self.assertTrue(isinstance(ks, keystore.BIP32_KeyStore))

        self.assertEqual(ks.xprv, 'xprv9s21ZrQH143K32jECVM729vWgGq4mUDJCk1ozqAStTphzQtCTuoFmFafNoG1g55iCnBTXUzz3zWnDb5CVLGiFvmaZjuazHDL8a81cPQ8KL6')
        self.assertEqual(ks.xpub, 'xpub661MyMwAqRbcFWohJWt7PHsFEJfZAvw9ZxwQoDa4SoMgsDDM1T7WK3u9E4edkC4ugRnZ8E4xDZRpk8Rnts3Nbt97dPwT52CwBdDWroaZf8U')

        w = WalletIntegrityHelper.create_standard_wallet(ks)
        self.assertEqual(w.txin_type, 'p2pkh')

        self.assertEqual(w.get_receiving_addresses()[0], 'Xx4bj9RuWdhrnmn5vGjKrTHqQHcy99RsGV')
        self.assertEqual(w.get_change_addresses()[0], 'Xu8Vpo1b81a6zCC574LXjEETvV4Wq58z24')

    @needs_test_with_all_ecc_implementations
    @mock.patch.object(storage.WalletStorage, '_write')
    def test_electrum_seed_old(self, mock_write):
        seed_words = 'powerful random nobody notice nothing important anyway look away hidden message over'
        self.assertEqual(seed_type(seed_words), 'old')

        ks = keystore.from_seed(seed_words, '', False)

        WalletIntegrityHelper.check_seeded_keystore_sanity(self, ks)
        self.assertTrue(isinstance(ks, keystore.Old_KeyStore))

        self.assertEqual(ks.mpk, 'e9d4b7866dd1e91c862aebf62a49548c7dbf7bcc6e4b7b8c9da820c7737968df9c09d5a3e271dc814a29981f81b3faaf2737b551ef5dcc6189cf0f8252c442b3')

        w = WalletIntegrityHelper.create_standard_wallet(ks)
        self.assertEqual(w.txin_type, 'p2pkh')

        self.assertEqual(w.get_receiving_addresses()[0], 'Xpz54Rncf6aC9od2cE64teK5okqgWxVpTk')
        self.assertEqual(w.get_change_addresses()[0], 'Xu7Ly4vzExW9r4ijM79KWm1icCTTBoVCFE')

    @needs_test_with_all_ecc_implementations
    @mock.patch.object(storage.WalletStorage, '_write')
    def test_bip39_seed_bip44_standard(self, mock_write):
        seed_words = 'treat dwarf wealth gasp brass outside high rent blood crowd make initial'
        self.assertEqual(keystore.bip39_is_checksum_valid(seed_words), (True, True))

        ks = keystore.from_bip39_seed(seed_words, '', "m/44'/0'/0'")

        self.assertTrue(isinstance(ks, keystore.BIP32_KeyStore))

        self.assertEqual(ks.xprv, 'xprv9zGLcNEb3cHUKizLVBz6RYeE9bEZAVPjH2pD1DEzCnPcsemWc3d3xTao8sfhfUmDLMq6e3RcEMEvJG1Et8dvfL8DV4h7mwm9J6AJsW9WXQD')
        self.assertEqual(ks.xpub, 'xpub6DFh1smUsyqmYD4obDX6ngaxhd53Zx7aeFjoobebm7vbkT6f9awJWFuGzBT9FQJEWFBL7UyhMXtYzRcwDuVbcxtv9Ce2W9eMm4KXLdvdbjv')

        w = WalletIntegrityHelper.create_standard_wallet(ks)
        self.assertEqual(w.txin_type, 'p2pkh')

        self.assertEqual(w.get_receiving_addresses()[0], 'XgQx46PwWrSDcZnU9VWiC74CoUw9ibZm8n')
        self.assertEqual(w.get_change_addresses()[0], 'XqwvRkJQdt2fgShtC68vjAgrEumkqA7qcK')

    @needs_test_with_all_ecc_implementations
    @mock.patch.object(storage.WalletStorage, '_write')
    def test_bip39_seed_bip44_standard_passphrase(self, mock_write):
        seed_words = 'treat dwarf wealth gasp brass outside high rent blood crowd make initial'
        self.assertEqual(keystore.bip39_is_checksum_valid(seed_words), (True, True))

        ks = keystore.from_bip39_seed(seed_words, UNICODE_HORROR, "m/44'/0'/0'")

        self.assertTrue(isinstance(ks, keystore.BIP32_KeyStore))

        self.assertEqual(ks.xprv, 'xprv9z8izheguGnLopSqkY7GcGFrP2Gu6rzBvvHo6uB9B8DWJhsows6WDZAsbBTaP3ncP2AVbTQphyEQkahrB9s1L7ihZtfz5WGQPMbXwsUtSik')
        self.assertEqual(ks.xpub, 'xpub6D85QDBajeLe2JXJrZeGyQCaw47PWKi3J9DPuHakjTkVBWCxVQQkmMVMSSfnw39tj9FntbozpRtb1AJ8ubjeVSBhyK4M5mzdvsXZzKPwodT')

        w = WalletIntegrityHelper.create_standard_wallet(ks)
        self.assertEqual(w.txin_type, 'p2pkh')

        self.assertEqual(w.get_receiving_addresses()[0], 'XpoyWHSU94uoL4R87nCcMo6UhKBG1pnZsS')
        self.assertEqual(w.get_change_addresses()[0], 'XrkF3GWZzhctDRLV2Nd4wBBoVZvpZ1FVPh')

    @needs_test_with_all_ecc_implementations
    @mock.patch.object(storage.WalletStorage, '_write')
    def test_electrum_multisig_seed_standard(self, mock_write):
        seed_words = 'blast uniform dragon fiscal ensure vast young utility dinosaur abandon rookie sure'
        self.assertEqual(seed_type(seed_words), 'standard')

        ks1 = keystore.from_seed(seed_words, '', True)
        WalletIntegrityHelper.check_seeded_keystore_sanity(self, ks1)
        self.assertTrue(isinstance(ks1, keystore.BIP32_KeyStore))
        self.assertEqual(ks1.xprv, 'xprv9s21ZrQH143K3t9vo23J3hajRbzvkRLJ6Y1zFrUFAfU3t8oooMPfb7f87cn5KntgqZs5nipZkCiBFo5ZtaSD2eDo7j7CMuFV8Zu6GYLTpY6')
        self.assertEqual(ks1.xpub, 'xpub661MyMwAqRbcGNEPu3aJQqXTydqR9t49Tkwb4Esrj112kw8xLthv8uybxvaki4Ygt9xiwZUQGeFTG7T2TUzR3eA4Zp3aq5RXsABHFBUrq4c')

        # electrum seed: ghost into match ivory badge robot record tackle radar elbow traffic loud
        ks2 = keystore.from_xpub('xpub661MyMwAqRbcGfCPEkkyo5WmcrhTq8mi3xuBS7VEZ3LYvsgY1cCFDbenT33bdD12axvrmXhuX3xkAbKci3yZY9ZEk8vhLic7KNhLjqdh5ec')
        WalletIntegrityHelper.check_xpub_keystore_sanity(self, ks2)
        self.assertTrue(isinstance(ks2, keystore.BIP32_KeyStore))

        w = WalletIntegrityHelper.create_multisig_wallet([ks1, ks2], '2of2')
        self.assertEqual(w.txin_type, 'p2sh')

        self.assertEqual(w.get_receiving_addresses()[0], '7TTLsc2LVWUd6ZnkhHFGJb3dnZMuSQooiu')
        self.assertEqual(w.get_change_addresses()[0], '7XF9mRa2fUHynUGGLyWzpem8DEYDzN7Bew')

    @needs_test_with_all_ecc_implementations
    @mock.patch.object(storage.WalletStorage, '_write')
    def test_bip39_multisig_seed_bip45_standard(self, mock_write):
        seed_words = 'treat dwarf wealth gasp brass outside high rent blood crowd make initial'
        self.assertEqual(keystore.bip39_is_checksum_valid(seed_words), (True, True))

        ks1 = keystore.from_bip39_seed(seed_words, '', "m/45'/0")
        self.assertTrue(isinstance(ks1, keystore.BIP32_KeyStore))
        self.assertEqual(ks1.xprv, 'xprv9vyEFyXf7pYVv4eDU3hhuCEAHPHNGuxX73nwtYdpbLcqwJCPwFKknAK8pHWuHHBirCzAPDZ7UJHrYdhLfn1NkGp9rk3rVz2aEqrT93qKRD9')
        self.assertEqual(ks1.xpub, 'xpub69xafV4YxC6o8Yiga5EiGLAtqR7rgNgNUGiYgw3S9g9pp6XYUne1KxdcfYtxwmA3eBrzMFuYcNQKfqsXCygCo4GxQFHfywxpUbKNfYvGJka')

        # bip39 seed: tray machine cook badge night page project uncover ritual toward person enact
        # der: m/45'/0
        ks2 = keystore.from_xpub('xpub6Bco9vrgo8rNUSi8Bjomn8xLA41DwPXeuPcgJamNRhTTyGVHsp8fZXaGzp9ypHoei16J6X3pumMAP1u3Dy4jTSWjm4GZowL7Dcn9u4uZC9W')
        WalletIntegrityHelper.check_xpub_keystore_sanity(self, ks2)
        self.assertTrue(isinstance(ks2, keystore.BIP32_KeyStore))

        w = WalletIntegrityHelper.create_multisig_wallet([ks1, ks2], '2of2')
        self.assertEqual(w.txin_type, 'p2sh')

        self.assertEqual(w.get_receiving_addresses()[0], '7hmMoMUPGKPuCnxK1Yz4wawUZ6PinbtLHj')
        self.assertEqual(w.get_change_addresses()[0], '7SRcVV8vWMqMPLLy9jUGJTBvJ6fpavXGvy')

    @needs_test_with_all_ecc_implementations
    @mock.patch.object(storage.WalletStorage, '_write')
    def test_bip32_extended_version_bytes(self, mock_write):
        seed_words = 'crouch dumb relax small truck age shine pink invite spatial object tenant'
        self.assertEqual(keystore.bip39_is_checksum_valid(seed_words), (True, True))
        bip32_seed = keystore.bip39_to_seed(seed_words, '')
        self.assertEqual('0df68c16e522eea9c1d8e090cfb2139c3b3a2abed78cbcb3e20be2c29185d3b8df4e8ce4e52a1206a688aeb88bfee249585b41a7444673d1f16c0d45755fa8b9',
                         bh2u(bip32_seed))

        def create_keystore_from_bip32seed(xtype):
            ks = keystore.BIP32_KeyStore({})
            ks.add_xprv_from_seed(bip32_seed, xtype=xtype, derivation='m/')
            return ks

        ks = create_keystore_from_bip32seed(xtype='standard')
        self.assertEqual('033a05ec7ae9a9833b0696eb285a762f17379fa208b3dc28df1c501cf84fe415d0', ks.derive_pubkey(0, 0))
        self.assertEqual('02bf27f41683d84183e4e930e66d64fc8af5508b4b5bf3c473c505e4dbddaeed80', ks.derive_pubkey(1, 0))

        ks = create_keystore_from_bip32seed(xtype='standard')  # p2pkh
        w = WalletIntegrityHelper.create_standard_wallet(ks)
        self.assertEqual(ks.xprv, 'xprv9s21ZrQH143K3nyWMZVjzGL4KKAE1zahmhTHuV5pdw4eK3o3igC5QywgQG7UTRe6TGBniPDpPFWzXMeMUFbBj8uYsfXGjyMmF54wdNt8QBm')
        self.assertEqual(ks.xpub, 'xpub661MyMwAqRbcGH3yTb2kMQGnsLziRTJZ8vNthsVSCGbdBr8CGDWKxnGAFYgyKTzBtwvPPmfVAWJuFmxRXjSbUTg87wDkWQ5GmzpfUcN9t8Z')
        self.assertEqual(w.get_receiving_addresses()[0], 'XjMM4kERoPWqQihtQGAKfSemZuYk36oeBr')
        self.assertEqual(w.get_change_addresses()[0], 'XovMwtDvyZ1DhvEuVUfJwccopyfNbuheco')

        ks = create_keystore_from_bip32seed(xtype='standard')  # p2sh
        w = WalletIntegrityHelper.create_multisig_wallet([ks], '1of1')
        self.assertEqual(ks.xprv, 'xprv9s21ZrQH143K3nyWMZVjzGL4KKAE1zahmhTHuV5pdw4eK3o3igC5QywgQG7UTRe6TGBniPDpPFWzXMeMUFbBj8uYsfXGjyMmF54wdNt8QBm')
        self.assertEqual(ks.xpub, 'xpub661MyMwAqRbcGH3yTb2kMQGnsLziRTJZ8vNthsVSCGbdBr8CGDWKxnGAFYgyKTzBtwvPPmfVAWJuFmxRXjSbUTg87wDkWQ5GmzpfUcN9t8Z')
        self.assertEqual(w.get_receiving_addresses()[0], '7fnRbKn5baDQxGTny63XNWPCcBs5dQEBtK')
        self.assertEqual(w.get_change_addresses()[0], '7nrNkWYwmyavE9K3SgexxwshHhS9DvyeGK')


class TestWalletKeystoreAddressIntegrityForTestnet(TestCaseForTestnet):

    @needs_test_with_all_ecc_implementations
    @mock.patch.object(storage.WalletStorage, '_write')
    def test_bip32_extended_version_bytes(self, mock_write):
        seed_words = 'crouch dumb relax small truck age shine pink invite spatial object tenant'
        self.assertEqual(keystore.bip39_is_checksum_valid(seed_words), (True, True))
        bip32_seed = keystore.bip39_to_seed(seed_words, '')
        self.assertEqual('0df68c16e522eea9c1d8e090cfb2139c3b3a2abed78cbcb3e20be2c29185d3b8df4e8ce4e52a1206a688aeb88bfee249585b41a7444673d1f16c0d45755fa8b9',
                         bh2u(bip32_seed))

        def create_keystore_from_bip32seed(xtype):
            ks = keystore.BIP32_KeyStore({})
            ks.add_xprv_from_seed(bip32_seed, xtype=xtype, derivation='m/')
            return ks

        ks = create_keystore_from_bip32seed(xtype='standard')
        self.assertEqual('033a05ec7ae9a9833b0696eb285a762f17379fa208b3dc28df1c501cf84fe415d0', ks.derive_pubkey(0, 0))
        self.assertEqual('02bf27f41683d84183e4e930e66d64fc8af5508b4b5bf3c473c505e4dbddaeed80', ks.derive_pubkey(1, 0))

        ks = create_keystore_from_bip32seed(xtype='standard')  # p2pkh
        w = WalletIntegrityHelper.create_standard_wallet(ks)
        self.assertEqual(ks.xprv, 'tprv8ZgxMBicQKsPecD328MF9ux3dSaSFWci7FNQmuWH7uZ86eY8i3XpvjK8KSH8To2QphiZiUqaYc6nzDC6bTw8YCB9QJjaQL5pAApN4z7vh2B')
        self.assertEqual(ks.xpub, 'tpubD6NzVbkrYhZ4Y5Epun1qZKcACU6NQqocgYyC4RYaYBMWw8nuLSMR7DvzVamkqxwRgrTJ1MBMhc8wwxT2vbHqMu8RBXy4BvjWMxR5EdZroxE')
        self.assertEqual(w.get_receiving_addresses()[0], 'yUyx5hJsEwAukTdRy7UihU57rC37Y4y2ZX')
        self.assertEqual(w.get_change_addresses()[0], 'yZYxxqJNR6fJ3fAT4Kyhye3A7G9kC19B9q')

        ks = create_keystore_from_bip32seed(xtype='standard')  # p2sh
        w = WalletIntegrityHelper.create_multisig_wallet([ks], '1of1')
        self.assertEqual(ks.xprv, 'tprv8ZgxMBicQKsPecD328MF9ux3dSaSFWci7FNQmuWH7uZ86eY8i3XpvjK8KSH8To2QphiZiUqaYc6nzDC6bTw8YCB9QJjaQL5pAApN4z7vh2B')
        self.assertEqual(ks.xpub, 'tpubD6NzVbkrYhZ4Y5Epun1qZKcACU6NQqocgYyC4RYaYBMWw8nuLSMR7DvzVamkqxwRgrTJ1MBMhc8wwxT2vbHqMu8RBXy4BvjWMxR5EdZroxE')
        self.assertEqual(w.get_receiving_addresses()[0], '8soEYefwj7c3QZt43M3UptCZVhduigoYNs')
        self.assertEqual(w.get_change_addresses()[0], '8zsBhqSouWyYgSjJWwevRKh4BDCySjizKi')


class TestWalletHistory_DoubleSpend(TestCaseForTestnet):
    transactions = {
        # txn A:
        "0cce62d61ec87ad3e391e8cd752df62e0c952ce45f52885d6d10988e02794060": "0200000001191601a44a81e061502b7bfbc6eaa1cef6d1e6af5308ef96c9342f71dbf4b9b5000000006b483045022100a6d44d0a651790a477e75334adfb8aae94d6612d01187b2c02526e340a7fd6c8022028bdf7a64a54906b13b145cd5dab21a26bd4b85d6044e9b97bceab5be44c2a9201210253e8e0254b0c95776786e40984c1aa32a7d03efa6bdacdea5f421b774917d346feffffff026b20fa04000000001976a914dc3a05eb562fb6f3ef8076946514d4730cff299988aca0860100000000001976a91421919b94ae5cefcdf0271191459157cdb41c4cbf88aca6240700",
        # txn B:
        "e7f4e47f41421e37a8600b6350befd586f30db60a88d0992d54df280498f0968": "0200000001604079028e98106d5d88525fe42c950c2ef62d75cde891e3d37ac81ed662ce0c000000006b483045022100a6d44d0a651790a477e75334adfb8aae94d6612d01187b2c02526e340a7fd6c8022028bdf7a64a54906b13b145cd5dab21a26bd4b85d6044e9b97bceab5be44c2a9201210253e8e0254b0c95776786e40984c1aa32a7d03efa6bdacdea5f421b774917d346feffffff01831cfa04000000001976a914024db2e87dd7cfd0e5f266c5f212e21a31d805a588aca6240700",
        # txn C:
        "a04328fbc9f28268378a8b9cf103db21ca7d673bf1cc7fa4d61b6a7265f07a6b": "0200000001604079028e98106d5d88525fe42c950c2ef62d75cde891e3d37ac81ed662ce0c000000006b483045022100a6d44d0a651790a477e75334adfb8aae94d6612d01187b2c02526e340a7fd6c8022028bdf7a64a54906b13b145cd5dab21a26bd4b85d6044e9b97bceab5be44c2a9201210253e8e0254b0c95776786e40984c1aa32a7d03efa6bdacdea5f421b774917d346feffffff01831cfa04000000001976a914899cdc441b5ec43f1e157d1f93e2ffbea99e051f88aca6240700",
    }

    @mock.patch.object(storage.WalletStorage, '_write')
    def test_restoring_wallet_without_manual_delete(self, mock_write):
        w = restore_wallet_from_text("hint shock chair puzzle shock traffic drastic note dinosaur mention suggest sweet",
                                     path='if_this_exists_mocking_failed_648151893',
                                     gap_limit=5)['wallet']
        for txid in self.transactions:
            tx = Transaction(self.transactions[txid])
            w.add_transaction(tx.txid(), tx)
        # txn A is an external incoming txn funding the wallet
        # txn B is an outgoing payment to an external address
        # txn C is double-spending txn B, to a wallet address
        self.assertEqual(83500163, sum(w.get_balance()))

    @mock.patch.object(storage.WalletStorage, '_write')
    def test_restoring_wallet_with_manual_delete(self, mock_write):
        w = restore_wallet_from_text("hint shock chair puzzle shock traffic drastic note dinosaur mention suggest sweet",
                                     path='if_this_exists_mocking_failed_648151893',
                                     gap_limit=5)['wallet']
        # txn A is an external incoming txn funding the wallet
        txA = Transaction(self.transactions["0cce62d61ec87ad3e391e8cd752df62e0c952ce45f52885d6d10988e02794060"])
        w.add_transaction(txA.txid(), txA)
        # txn B is an outgoing payment to an external address
        txB = Transaction(self.transactions["e7f4e47f41421e37a8600b6350befd586f30db60a88d0992d54df280498f0968"])
        w.add_transaction(txB.txid(), txB)
        # now the user manually deletes txn B to attempt the double spend
        # txn C is double-spending txn B, to a wallet address
        # rationale1: user might do this with opt-in RBF transactions
        # rationale2: this might be a local transaction, in which case the GUI even allows it
        w.remove_transaction(txB)
        txC = Transaction(self.transactions["a04328fbc9f28268378a8b9cf103db21ca7d673bf1cc7fa4d61b6a7265f07a6b"])
        w.add_transaction(txC.txid(), txC)
        self.assertEqual(83500163, sum(w.get_balance()))
