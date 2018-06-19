import unittest
from unittest import mock

import lib.bitcoin as bitcoin
import lib.keystore as keystore
import lib.storage as storage
import lib.wallet as wallet
from lib import constants

from . import TestCaseForTestnet


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
    def create_standard_wallet(cls, ks):
        store = storage.WalletStorage('if_this_exists_mocking_failed_648151893')
        store.put('keystore', ks.dump())
        store.put('gap_limit', cls.gap_limit)
        w = wallet.Standard_Wallet(store)
        w.synchronize()
        return w

    @classmethod
    def create_multisig_wallet(cls, ks1, ks2, ks3=None):
        """Creates a 2-of-2 or 2-of-3 multisig wallet."""
        store = storage.WalletStorage('if_this_exists_mocking_failed_648151893')
        store.put('x%d/' % 1, ks1.dump())
        store.put('x%d/' % 2, ks2.dump())
        if ks3 is None:
            multisig_type = "%dof%d" % (2, 2)
        else:
            multisig_type = "%dof%d" % (2, 3)
            store.put('x%d/' % 3, ks3.dump())
        store.put('wallet_type', multisig_type)
        store.put('gap_limit', cls.gap_limit)
        w = wallet.Multisig_Wallet(store)
        w.synchronize()
        return w


# TODO passphrase/seed_extension
class TestWalletKeystoreAddressIntegrityForMainnet(unittest.TestCase):

    @mock.patch.object(storage.WalletStorage, '_write')
    def test_electrum_seed_standard(self, mock_write):
        seed_words = 'cycle rocket west magnet parrot shuffle foot correct salt library feed song'
        self.assertEqual(bitcoin.seed_type(seed_words), 'standard')

        ks = keystore.from_seed(seed_words, '', False)

        WalletIntegrityHelper.check_seeded_keystore_sanity(self, ks)
        self.assertTrue(isinstance(ks, keystore.BIP32_KeyStore))

        self.assertEqual(ks.xprv, 'xprv9s21ZrQH143K32jECVM729vWgGq4mUDJCk1ozqAStTphzQtCTuoFmFafNoG1g55iCnBTXUzz3zWnDb5CVLGiFvmaZjuazHDL8a81cPQ8KL6')
        self.assertEqual(ks.xpub, 'xpub661MyMwAqRbcFWohJWt7PHsFEJfZAvw9ZxwQoDa4SoMgsDDM1T7WK3u9E4edkC4ugRnZ8E4xDZRpk8Rnts3Nbt97dPwT52CwBdDWroaZf8U')

        w = WalletIntegrityHelper.create_standard_wallet(ks)
        self.assertEqual(w.txin_type, 'p2pkh')

        self.assertEqual(w.get_receiving_addresses()[0], 'PVxw3sArbqyTcfrGQTjdfpaKBhDA9k5EK7')
        self.assertEqual(w.get_change_addresses()[0], 'PT2q9WkYDDqhp6GFbFLqYbWwhtehqh1bXh')

    @mock.patch.object(storage.WalletStorage, '_write')
    def test_electrum_seed_old(self, mock_write):
        seed_words = 'powerful random nobody notice nothing important anyway look away hidden message over'
        self.assertEqual(bitcoin.seed_type(seed_words), 'old')

        ks = keystore.from_seed(seed_words, '', False)

        WalletIntegrityHelper.check_seeded_keystore_sanity(self, ks)
        self.assertTrue(isinstance(ks, keystore.Old_KeyStore))

        self.assertEqual(ks.mpk, 'e9d4b7866dd1e91c862aebf62a49548c7dbf7bcc6e4b7b8c9da820c7737968df9c09d5a3e271dc814a29981f81b3faaf2737b551ef5dcc6189cf0f8252c442b3')

        w = WalletIntegrityHelper.create_standard_wallet(ks)
        self.assertEqual(w.txin_type, 'p2pkh')

        self.assertEqual(w.get_receiving_addresses()[0], 'PNtQP9XZkJqnyhhD6R6Ni1bZbARsbmovBo')
        self.assertEqual(w.get_change_addresses()[0], 'PT1gHnfwLAmkfxnuqJ9dL8JCPc3eJkvVqG')

    @mock.patch.object(storage.WalletStorage, '_write')
    def test_bip39_seed_bip44_standard(self, mock_write):
        seed_words = 'treat dwarf wealth gasp brass outside high rent blood crowd make initial'
        self.assertEqual(keystore.bip39_is_checksum_valid(seed_words), (True, True))

        ks = keystore.from_bip39_seed(seed_words, '', "m/44'/4242'/0'")

        self.assertTrue(isinstance(ks, keystore.BIP32_KeyStore))

        self.assertEqual(ks.xprv, 'xprv9z3dKeoZEe6oPP3HGUiwGuDirB6otu4FaitvyztdXFbtNTM8Q2oWm8iAwELb4wVL7mYpzoT3YAMnkyEW8wzobLaFXrU9fdS6egiXgp7Xq8s')
        self.assertEqual(ks.xpub, 'xpub6D2yjALT51f6bs7kNWFwe3ATQCwJJMn6wwpXnPJF5b8sFFgGwa7mJw2enYSrng7a4UrGaSea7ADbbiciBojB8w8qAXfNfctrCGGicTqWfGa')

        w = WalletIntegrityHelper.create_standard_wallet(ks)
        self.assertEqual(w.txin_type, 'p2pkh')

        self.assertEqual(w.get_receiving_addresses()[0], 'PAcFhYAdadySYQ3f6xQX3btQbQDfCVVzn7')
        self.assertEqual(w.get_change_addresses()[0], 'PPrFkU3Mj6JGWLn4gH9EYXyL2KMwtSYapL')

    @mock.patch.object(storage.WalletStorage, '_write')
    def test_electrum_multisig_seed_standard(self, mock_write):
        seed_words = 'blast uniform dragon fiscal ensure vast young utility dinosaur abandon rookie sure'
        self.assertEqual(bitcoin.seed_type(seed_words), 'standard')

        ks1 = keystore.from_seed(seed_words, '', True)
        WalletIntegrityHelper.check_seeded_keystore_sanity(self, ks1)
        self.assertTrue(isinstance(ks1, keystore.BIP32_KeyStore))
        self.assertEqual(ks1.xprv, 'xprv9s21ZrQH143K3t9vo23J3hajRbzvkRLJ6Y1zFrUFAfU3t8oooMPfb7f87cn5KntgqZs5nipZkCiBFo5ZtaSD2eDo7j7CMuFV8Zu6GYLTpY6')
        self.assertEqual(ks1.xpub, 'xpub661MyMwAqRbcGNEPu3aJQqXTydqR9t49Tkwb4Esrj112kw8xLthv8uybxvaki4Ygt9xiwZUQGeFTG7T2TUzR3eA4Zp3aq5RXsABHFBUrq4c')

        # electrum seed: ghost into match ivory badge robot record tackle radar elbow traffic loud
        ks2 = keystore.from_xpub('xpub661MyMwAqRbcGfCPEkkyo5WmcrhTq8mi3xuBS7VEZ3LYvsgY1cCFDbenT33bdD12axvrmXhuX3xkAbKci3yZY9ZEk8vhLic7KNhLjqdh5ec')
        WalletIntegrityHelper.check_xpub_keystore_sanity(self, ks2)
        self.assertTrue(isinstance(ks2, keystore.BIP32_KeyStore))

        w = WalletIntegrityHelper.create_multisig_wallet(ks1, ks2)
        self.assertEqual(w.txin_type, 'p2sh')

        self.assertEqual(w.get_receiving_addresses()[0], '7TTLsc2LVWUd6ZnkhHFGJb3dnZMuSQooiu')
        self.assertEqual(w.get_change_addresses()[0], '7XF9mRa2fUHynUGGLyWzpem8DEYDzN7Bew')

    @mock.patch.object(storage.WalletStorage, '_write')
    def test_bip39_multisig_seed_bip45_standard(self, mock_write):
        seed_words = 'treat dwarf wealth gasp brass outside high rent blood crowd make initial'
        self.assertEqual(keystore.bip39_is_checksum_valid(seed_words), (True, True))

        ks1 = keystore.from_bip39_seed(seed_words, '', "m/45'/4242")
        self.assertTrue(isinstance(ks1, keystore.BIP32_KeyStore))
        self.assertEqual(ks1.xprv, 'xprv9vyEFyXf7pbiKy3pDC6qTX6jah2yrYFKhzHnoXXm1FU7fHDbFxR3Tdho91atnqN8EPTSut4t4xgTRkBoS7PjHN8tDfseZooqCsrVx6Dn3Cb')
        self.assertEqual(ks1.xpub, 'xpub69xafV4YxCA1YT8HKDdqpf3U8isUFzyB5DDPbuwNZb16Y5YjoVjJ1S2GzHTY5oUgpQAjzRxWGw4YA3sqdQ9f9hP2gog7uLbNV3Jm4sjSfFj')

        # bip39 seed: tray machine cook badge night page project uncover ritual toward person enact
        # der: m/45'/0
        ks2 = keystore.from_xpub('xpub6Bco9vrgo8rNUSi8Bjomn8xLA41DwPXeuPcgJamNRhTTyGVHsp8fZXaGzp9ypHoei16J6X3pumMAP1u3Dy4jTSWjm4GZowL7Dcn9u4uZC9W')
        WalletIntegrityHelper.check_xpub_keystore_sanity(self, ks2)
        self.assertTrue(isinstance(ks2, keystore.BIP32_KeyStore))

        w = WalletIntegrityHelper.create_multisig_wallet(ks1, ks2)
        self.assertEqual(w.txin_type, 'p2sh')

        self.assertEqual(w.get_receiving_addresses()[0], '7hmMoMUPGKPuCnxK1Yz4wawUZ6PinbtLHj')
        self.assertEqual(w.get_change_addresses()[0], '7SRcVV8vWMqMPLLy9jUGJTBvJ6fpavXGvy')
