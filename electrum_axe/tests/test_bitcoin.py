import base64
import sys

from electrum_axe.bitcoin import (public_key_to_p2pkh, address_from_private_key,
                                   is_address, is_private_key,
                                   var_int, _op_push, address_to_script,
                                   deserialize_privkey, serialize_privkey,
                                   is_b58_address, address_to_scripthash, is_minikey,
                                   is_compressed_privkey, EncodeBase58Check, DecodeBase58Check,
                                   script_num_to_hex, push_script, add_number_to_script, int_to_hex,
                                   opcodes, base_encode, base_decode, BitcoinException)
from electrum_axe.bip32 import (BIP32Node, convert_bip32_intpath_to_strpath,
                                 xpub_from_xprv, xpub_type, is_xprv, is_bip32_derivation,
                                 is_xpub, convert_bip32_path_to_list_of_uint32,
                                 normalize_bip32_derivation)
from electrum_axe.crypto import sha256d, SUPPORTED_PW_HASH_VERSIONS
from electrum_axe import ecc, crypto, constants
from electrum_axe.ecc import number_to_string, string_to_number
from electrum_axe.util import bfh, bh2u, InvalidPassword
from electrum_axe.storage import WalletStorage
from electrum_axe.keystore import xtype_from_derivation, from_master_key

from electrum_axe import ecc_fast

from . import SequentialTestCase
from . import TestCaseForTestnet
from . import FAST_TESTS


try:
    import ecdsa
except ImportError:
    sys.exit("Error: python-ecdsa does not seem to be installed. Try 'sudo python3 -m pip install ecdsa'")


def needs_test_with_all_ecc_implementations(func):
    """Function decorator to run a unit test twice:
    once when libsecp256k1 is not available, once when it is.

    NOTE: this is inherently sequential;
    tests running in parallel would break things
    """
    def run_test(*args, **kwargs):
        if FAST_TESTS:  # if set, only run tests once, using fastest implementation
            func(*args, **kwargs)
            return
        ecc_fast.undo_monkey_patching_of_python_ecdsa_internals_with_libsecp256k1()
        try:
            # first test without libsecp
            func(*args, **kwargs)
        finally:
            ecc_fast.do_monkey_patching_of_python_ecdsa_internals_with_libsecp256k1()
        # if libsecp is not available, we are done
        if not ecc_fast._libsecp256k1:
            return
        # if libsecp is available, test again now
        func(*args, **kwargs)
    return run_test


def needs_test_with_all_aes_implementations(func):
    """Function decorator to run a unit test twice:
    once when pycryptodomex is not available, once when it is.

    NOTE: this is inherently sequential;
    tests running in parallel would break things
    """
    def run_test(*args, **kwargs):
        if FAST_TESTS:  # if set, only run tests once, using fastest implementation
            func(*args, **kwargs)
            return
        _aes = crypto.AES
        crypto.AES = None
        try:
            # first test without pycryptodomex
            func(*args, **kwargs)
        finally:
            crypto.AES = _aes
        # if pycryptodomex is not available, we are done
        if not _aes:
            return
        # if pycryptodomex is available, test again now
        func(*args, **kwargs)
    return run_test


class Test_bitcoin(SequentialTestCase):

    def test_libsecp256k1_is_available(self):
        # we want the unit testing framework to test with libsecp256k1 available.
        self.assertTrue(bool(ecc_fast._libsecp256k1))

    def test_pycryptodomex_is_available(self):
        # we want the unit testing framework to test with pycryptodomex available.
        self.assertTrue(bool(crypto.AES))

    @needs_test_with_all_aes_implementations
    @needs_test_with_all_ecc_implementations
    def test_crypto(self):
        for message in [b"Chancellor on brink of second bailout for banks", b'\xff'*512]:
            self._do_test_crypto(message)

    def _do_test_crypto(self, message):
        G = ecc.generator()
        _r  = G.order()
        pvk = ecdsa.util.randrange(_r)

        Pub = pvk*G
        pubkey_c = Pub.get_public_key_bytes(True)
        #pubkey_u = point_to_ser(Pub,False)
        addr_c = public_key_to_p2pkh(pubkey_c)

        #print "Private key            ", '%064x'%pvk
        eck = ecc.ECPrivkey(number_to_string(pvk,_r))

        #print "Compressed public key  ", pubkey_c.encode('hex')
        enc = ecc.ECPubkey(pubkey_c).encrypt_message(message)
        dec = eck.decrypt_message(enc)
        self.assertEqual(message, dec)

        #print "Uncompressed public key", pubkey_u.encode('hex')
        #enc2 = EC_KEY.encrypt_message(message, pubkey_u)
        dec2 = eck.decrypt_message(enc)
        self.assertEqual(message, dec2)

        signature = eck.sign_message(message, True)
        #print signature
        eck.verify_message_for_address(signature, message)

    @needs_test_with_all_ecc_implementations
    def test_ecc_sanity(self):
        G = ecc.generator()
        n = G.order()
        self.assertEqual(ecc.CURVE_ORDER, n)
        inf = n * G
        self.assertEqual(ecc.point_at_infinity(), inf)
        self.assertTrue(inf.is_at_infinity())
        self.assertFalse(G.is_at_infinity())
        self.assertEqual(11 * G, 7 * G + 4 * G)
        self.assertEqual((n + 2) * G, 2 * G)
        self.assertEqual((n - 2) * G, -2 * G)
        A = (n - 2) * G
        B = (n - 1) * G
        C = n * G
        D = (n + 1) * G
        self.assertFalse(A.is_at_infinity())
        self.assertFalse(B.is_at_infinity())
        self.assertTrue(C.is_at_infinity())
        self.assertTrue((C * 5).is_at_infinity())
        self.assertFalse(D.is_at_infinity())
        self.assertEqual(inf, C)
        self.assertEqual(inf, A + 2 * G)
        self.assertEqual(inf, D + (-1) * G)
        self.assertNotEqual(A, B)

    @needs_test_with_all_ecc_implementations
    def test_msg_signing(self):
        msg1 = b'Chancellor on brink of second bailout for banks'
        msg2 = b'Electrum'

        def sign_message_with_wif_privkey(wif_privkey, msg):
            txin_type, privkey, compressed = deserialize_privkey(wif_privkey)
            key = ecc.ECPrivkey(privkey)
            return key.sign_message(msg, compressed)

        sig1 = sign_message_with_wif_privkey(
            'XDL8kYsDheEviC7EYMNbo3Myy1txzKyfhZFZBaYUSPDPm9BZZae8', msg1)
        addr1 = 'PUFpXCipFhCM1n3CvY1pdJnsuBYGXopNoZ'
        sig2 = sign_message_with_wif_privkey(
            'XDsEyEN6HvL8TMJzi285YhCvQbEAAwr1X3WcrYHjnTk4q3GM4JvW', msg2)
        addr2 = 'PAXaycHBoaQSGrjgurCnuihGRozuWbzors'

        sig1_b64 = base64.b64encode(sig1)
        sig2_b64 = base64.b64encode(sig2)

        self.assertEqual(sig1_b64, b'HxotOszC5f11BXHmUCedMJiMMIm1LJjq99MXXydPB5xjOAYgS0Nu6Aa2dPsxzxBAXJIVrpXGwlXHuzlI17Q+IxQ=')
        self.assertEqual(sig2_b64, b'IPTzdPgV0VAO/XS5H4K/qFC8I18KYPtysrzLnYIBwh8YHBtUUXS2kv9yhwKRi9Ii0xHUfLW1BNp8P6hENgH13SY=')

        self.assertTrue(ecc.verify_message_with_address(addr1, sig1, msg1))
        self.assertTrue(ecc.verify_message_with_address(addr2, sig2, msg2))

        self.assertFalse(ecc.verify_message_with_address(addr1, b'wrong', msg1))
        self.assertFalse(ecc.verify_message_with_address(addr1, sig2, msg1))

    @needs_test_with_all_aes_implementations
    @needs_test_with_all_ecc_implementations
    def test_decrypt_message(self):
        key = WalletStorage.get_eckey_from_password('pw123')
        self.assertEqual(b'me<(s_s)>age', key.decrypt_message(b'QklFMQMDFtgT3zWSQsa+Uie8H/WvfUjlu9UN9OJtTt3KlgKeSTi6SQfuhcg1uIz9hp3WIUOFGTLr4RNQBdjPNqzXwhkcPi2Xsbiw6UCNJncVPJ6QBg=='))
        self.assertEqual(b'me<(s_s)>age', key.decrypt_message(b'QklFMQKXOXbylOQTSMGfo4MFRwivAxeEEkewWQrpdYTzjPhqjHcGBJwdIhB7DyRfRQihuXx1y0ZLLv7XxLzrILzkl/H4YUtZB4uWjuOAcmxQH4i/Og=='))
        self.assertEqual(b'hey_there' * 100, key.decrypt_message(b'QklFMQLOOsabsXtGQH8edAa6VOUa5wX8/DXmxX9NyHoAx1a5bWgllayGRVPeI2bf0ZdWK0tfal0ap0ZIVKbd2eOJybqQkILqT6E1/Syzq0Zicyb/AA1eZNkcX5y4gzloxinw00ubCA8M7gcUjJpOqbnksATcJ5y2YYXcHMGGfGurWu6uJ/UyrNobRidWppRMW5yR9/6utyNvT6OHIolCMEf7qLcmtneoXEiz51hkRdZS7weNf9mGqSbz9a2NL3sdh1A0feHIjAZgcCKcAvksNUSauf0/FnIjzTyPRpjRDMeDC8Ci3sGiuO3cvpWJwhZfbjcS26KmBv2CHWXfRRNFYOInHZNIXWNAoBB47Il5bGSMd+uXiGr+SQ9tNvcu+BiJNmFbxYqg+oQ8dGAl1DtvY2wJVY8k7vO9BIWSpyIxfGw7EDifhc5vnOmGe016p6a01C3eVGxgl23UYMrP7+fpjOcPmTSF4rk5U5ljEN3MSYqlf1QEv0OqlI9q1TwTK02VBCjMTYxDHsnt04OjNBkNO8v5uJ4NR+UUDBEp433z53I59uawZ+dbk4v4ZExcl8EGmKm3Gzbal/iJ/F7KQuX2b/ySEhLOFVYFWxK73X1nBvCSK2mC2/8fCw8oI5pmvzJwQhcCKTdEIrz3MMvAHqtPScDUOjzhXxInQOCb3+UBj1PPIdqkYLvZss1TEaBwYZjLkVnK2MBj7BaqT6Rp6+5A/fippUKHsnB6eYMEPR2YgDmCHL+4twxHJG6UWdP3ybaKiiAPy2OHNP6PTZ0HrqHOSJzBSDD+Z8YpaRg29QX3UEWlqnSKaan0VYAsV1VeaN0XFX46/TWO0L5tjhYVXJJYGqo6tIQJymxATLFRF6AZaD1Mwd27IAL04WkmoQoXfO6OFfwdp/shudY/1gBkDBvGPICBPtnqkvhGF+ZF3IRkuPwiFWeXmwBxKHsRx/3+aJu32Ml9+za41zVk2viaxcGqwTc5KMexQFLAUwqhv+aIik7U+5qk/gEVSuRoVkihoweFzKolNF+BknH2oB4rZdPixag5Zje3DvgjsSFlOl69W/67t/Gs8htfSAaHlsB8vWRQr9+v/lxTbrAw+O0E+sYGoObQ4qQMyQshNZEHbpPg63eWiHtJJnrVBvOeIbIHzoLDnMDsWVWZSMzAQ1vhX1H5QLgSEbRlKSliVY03kDkh/Nk/KOn+B2q37Ialq4JcRoIYFGJ8AoYEAD0tRuTqFddIclE75HzwaNG7NyKW1plsa72ciOPwsPJsdd5F0qdSQ3OSKtooTn7uf6dXOc4lDkfrVYRlZ0PX'))

    @needs_test_with_all_aes_implementations
    @needs_test_with_all_ecc_implementations
    def test_encrypt_message(self):
        key = WalletStorage.get_eckey_from_password('secret_password77')
        msgs = [
            bytes([0] * 555),
            b'cannot think of anything funny'
        ]
        for plaintext in msgs:
            ciphertext1 = key.encrypt_message(plaintext)
            ciphertext2 = key.encrypt_message(plaintext)
            self.assertEqual(plaintext, key.decrypt_message(ciphertext1))
            self.assertEqual(plaintext, key.decrypt_message(ciphertext2))
            self.assertNotEqual(ciphertext1, ciphertext2)

    @needs_test_with_all_ecc_implementations
    def test_sign_transaction(self):
        eckey1 = ecc.ECPrivkey(bfh('7e1255fddb52db1729fc3ceb21a46f95b8d9fe94cc83425e936a6c5223bb679d'))
        sig1 = eckey1.sign_transaction(bfh('5a548b12369a53faaa7e51b5081829474ebdd9c924b3a8230b69aa0be254cd94'))
        self.assertEqual(bfh('3045022100902a288b98392254cd23c0e9a49ac6d7920f171b8249a48e484b998f1874a2010220723d844826828f092cf400cb210c4fa0b8cd1b9d1a7f21590e78e022ff6476b9'), sig1)

        eckey2 = ecc.ECPrivkey(bfh('c7ce8c1462c311eec24dff9e2532ac6241e50ae57e7d1833af21942136972f23'))
        sig2 = eckey2.sign_transaction(bfh('642a2e66332f507c92bda910158dfe46fc10afbf72218764899d3af99a043fac'))
        self.assertEqual(bfh('30440220618513f4cfc87dde798ce5febae7634c23e7b9254a1eabf486be820f6a7c2c4702204fef459393a2b931f949e63ced06888f35e286e446dc46feb24b5b5f81c6ed52'), sig2)

    @needs_test_with_all_aes_implementations
    def test_aes_homomorphic(self):
        """Make sure AES is homomorphic."""
        payload = u'\u66f4\u7a33\u5b9a\u7684\u4ea4\u6613\u5e73\u53f0'
        password = u'secret'
        for version in SUPPORTED_PW_HASH_VERSIONS:
            enc = crypto.pw_encode(payload, password, version=version)
            dec = crypto.pw_decode(enc, password, version=version)
            self.assertEqual(dec, payload)

    @needs_test_with_all_aes_implementations
    def test_aes_encode_without_password(self):
        """When not passed a password, pw_encode is noop on the payload."""
        payload = u'\u66f4\u7a33\u5b9a\u7684\u4ea4\u6613\u5e73\u53f0'
        for version in SUPPORTED_PW_HASH_VERSIONS:
            enc = crypto.pw_encode(payload, None, version=version)
            self.assertEqual(payload, enc)

    @needs_test_with_all_aes_implementations
    def test_aes_deencode_without_password(self):
        """When not passed a password, pw_decode is noop on the payload."""
        payload = u'\u66f4\u7a33\u5b9a\u7684\u4ea4\u6613\u5e73\u53f0'
        for version in SUPPORTED_PW_HASH_VERSIONS:
            enc = crypto.pw_decode(payload, None, version=version)
            self.assertEqual(payload, enc)

    @needs_test_with_all_aes_implementations
    def test_aes_decode_with_invalid_password(self):
        """pw_decode raises an Exception when supplied an invalid password."""
        payload = u"blah"
        password = u"uber secret"
        wrong_password = u"not the password"
        for version in SUPPORTED_PW_HASH_VERSIONS:
            enc = crypto.pw_encode(payload, password, version=version)
            with self.assertRaises(InvalidPassword):
                crypto.pw_decode(enc, wrong_password, version=version)

    def test_sha256d(self):
        self.assertEqual(b'\x95MZI\xfdp\xd9\xb8\xbc\xdb5\xd2R&x)\x95\x7f~\xf7\xfalt\xf8\x84\x19\xbd\xc5\xe8"\t\xf4',
                         sha256d(u"test"))

    def test_int_to_hex(self):
        self.assertEqual('00', int_to_hex(0, 1))
        self.assertEqual('ff', int_to_hex(-1, 1))
        self.assertEqual('00000000', int_to_hex(0, 4))
        self.assertEqual('01000000', int_to_hex(1, 4))
        self.assertEqual('7f', int_to_hex(127, 1))
        self.assertEqual('7f00', int_to_hex(127, 2))
        self.assertEqual('80', int_to_hex(128, 1))
        self.assertEqual('80', int_to_hex(-128, 1))
        self.assertEqual('8000', int_to_hex(128, 2))
        self.assertEqual('ff', int_to_hex(255, 1))
        self.assertEqual('ff7f', int_to_hex(32767, 2))
        self.assertEqual('0080', int_to_hex(-32768, 2))
        self.assertEqual('ffff', int_to_hex(65535, 2))
        with self.assertRaises(OverflowError): int_to_hex(256, 1)
        with self.assertRaises(OverflowError): int_to_hex(-129, 1)
        with self.assertRaises(OverflowError): int_to_hex(-257, 1)
        with self.assertRaises(OverflowError): int_to_hex(65536, 2)
        with self.assertRaises(OverflowError): int_to_hex(-32769, 2)

    def test_var_int(self):
        for i in range(0xfd):
            self.assertEqual(var_int(i), "{:02x}".format(i) )

        self.assertEqual(var_int(0xfd), "fdfd00")
        self.assertEqual(var_int(0xfe), "fdfe00")
        self.assertEqual(var_int(0xff), "fdff00")
        self.assertEqual(var_int(0x1234), "fd3412")
        self.assertEqual(var_int(0xffff), "fdffff")
        self.assertEqual(var_int(0x10000), "fe00000100")
        self.assertEqual(var_int(0x12345678), "fe78563412")
        self.assertEqual(var_int(0xffffffff), "feffffffff")
        self.assertEqual(var_int(0x100000000), "ff0000000001000000")
        self.assertEqual(var_int(0x0123456789abcdef), "ffefcdab8967452301")

    def test_op_push(self):
        self.assertEqual(_op_push(0x00), '00')
        self.assertEqual(_op_push(0x12), '12')
        self.assertEqual(_op_push(0x4b), '4b')
        self.assertEqual(_op_push(0x4c), '4c4c')
        self.assertEqual(_op_push(0xfe), '4cfe')
        self.assertEqual(_op_push(0xff), '4cff')
        self.assertEqual(_op_push(0x100), '4d0001')
        self.assertEqual(_op_push(0x1234), '4d3412')
        self.assertEqual(_op_push(0xfffe), '4dfeff')
        self.assertEqual(_op_push(0xffff), '4dffff')
        self.assertEqual(_op_push(0x10000), '4e00000100')
        self.assertEqual(_op_push(0x12345678), '4e78563412')

    def test_script_num_to_hex(self):
        # test vectors from https://github.com/btcsuite/btcd/blob/fdc2bc867bda6b351191b5872d2da8270df00d13/txscript/scriptnum.go#L77
        self.assertEqual(script_num_to_hex(127), '7f')
        self.assertEqual(script_num_to_hex(-127), 'ff')
        self.assertEqual(script_num_to_hex(128), '8000')
        self.assertEqual(script_num_to_hex(-128), '8080')
        self.assertEqual(script_num_to_hex(129), '8100')
        self.assertEqual(script_num_to_hex(-129), '8180')
        self.assertEqual(script_num_to_hex(256), '0001')
        self.assertEqual(script_num_to_hex(-256), '0081')
        self.assertEqual(script_num_to_hex(32767), 'ff7f')
        self.assertEqual(script_num_to_hex(-32767), 'ffff')
        self.assertEqual(script_num_to_hex(32768), '008000')
        self.assertEqual(script_num_to_hex(-32768), '008080')

    def test_push_script(self):
        # https://github.com/bitcoin/bips/blob/master/bip-0062.mediawiki#push-operators
        self.assertEqual(push_script(''), bh2u(bytes([opcodes.OP_0])))
        self.assertEqual(push_script('07'), bh2u(bytes([opcodes.OP_7])))
        self.assertEqual(push_script('10'), bh2u(bytes([opcodes.OP_16])))
        self.assertEqual(push_script('81'), bh2u(bytes([opcodes.OP_1NEGATE])))
        self.assertEqual(push_script('11'), '0111')
        self.assertEqual(push_script(75 * '42'), '4b' + 75 * '42')
        self.assertEqual(push_script(76 * '42'), bh2u(bytes([opcodes.OP_PUSHDATA1]) + bfh('4c' + 76 * '42')))
        self.assertEqual(push_script(100 * '42'), bh2u(bytes([opcodes.OP_PUSHDATA1]) + bfh('64' + 100 * '42')))
        self.assertEqual(push_script(255 * '42'), bh2u(bytes([opcodes.OP_PUSHDATA1]) + bfh('ff' + 255 * '42')))
        self.assertEqual(push_script(256 * '42'), bh2u(bytes([opcodes.OP_PUSHDATA2]) + bfh('0001' + 256 * '42')))
        self.assertEqual(push_script(520 * '42'), bh2u(bytes([opcodes.OP_PUSHDATA2]) + bfh('0802' + 520 * '42')))

    def test_add_number_to_script(self):
        # https://github.com/bitcoin/bips/blob/master/bip-0062.mediawiki#numbers
        self.assertEqual(add_number_to_script(0), bytes([opcodes.OP_0]))
        self.assertEqual(add_number_to_script(7), bytes([opcodes.OP_7]))
        self.assertEqual(add_number_to_script(16), bytes([opcodes.OP_16]))
        self.assertEqual(add_number_to_script(-1), bytes([opcodes.OP_1NEGATE]))
        self.assertEqual(add_number_to_script(-127), bfh('01ff'))
        self.assertEqual(add_number_to_script(-2), bfh('0182'))
        self.assertEqual(add_number_to_script(17), bfh('0111'))
        self.assertEqual(add_number_to_script(127), bfh('017f'))
        self.assertEqual(add_number_to_script(-32767), bfh('02ffff'))
        self.assertEqual(add_number_to_script(-128), bfh('028080'))
        self.assertEqual(add_number_to_script(128), bfh('028000'))
        self.assertEqual(add_number_to_script(32767), bfh('02ff7f'))
        self.assertEqual(add_number_to_script(-8388607), bfh('03ffffff'))
        self.assertEqual(add_number_to_script(-32768), bfh('03008080'))
        self.assertEqual(add_number_to_script(32768), bfh('03008000'))
        self.assertEqual(add_number_to_script(8388607), bfh('03ffff7f'))
        self.assertEqual(add_number_to_script(-2147483647), bfh('04ffffffff'))
        self.assertEqual(add_number_to_script(-8388608 ), bfh('0400008080'))
        self.assertEqual(add_number_to_script(8388608), bfh('0400008000'))
        self.assertEqual(add_number_to_script(2147483647), bfh('04ffffff7f'))

    def test_address_to_script(self):
        # base58 P2PKH
        self.assertEqual(address_to_script('PBenpocD6pDoAoFZP4qA2pLpNwrm6FAcVw'), '76a9142197669050d01c6136181127ac8a0c631733da9688ac')
        self.assertEqual(address_to_script('P9h6zCz253jmc4TvqgKPRNpkx5qELdNWWT'), '76a9140c1724583577182cceef0e31bc176b2dcfdaadfd88ac')

        # base58 P2SH
        self.assertEqual(address_to_script('7WHUEVtMDLeereT5r4ZoNKjr3MXr4gqfon'), 'a9142a84cf00d47f699ee7bbc1dea5ec1bdecb4ac15487')
        self.assertEqual(address_to_script('7phNpVKta6kkbP24HfvvQVeHEmgBQYiJCB'), 'a914f47c8954e421031ad04ecd8e7752c9479206b9d387')


class Test_bitcoin_testnet(TestCaseForTestnet):

    def test_address_to_script(self):
        # base58 P2PKH
        self.assertEqual(address_to_script('yah2ARXMnY5A9VaR5Cd43fjiQnsu2vZ5a8'), '76a9149da64e300c5e4eb4aaffc9c2fd465348d5618ad488ac')
        self.assertEqual(address_to_script('yPeP8a774GuYaZyqJPxC7K24hcbcsqz1Au'), '76a914247d2d5b6334bdfa2038e85b20fc15264f8e5d2788ac')

        # base58 P2SH
        self.assertEqual(address_to_script('8pWgedHiF9DQswwXdR59ATSQe9pxyBZqbv'), 'a9146eae23d8c4a941316017946fc761a7a6c85561fb87')
        self.assertEqual(address_to_script('91EoMZCG6Yfs9NGZLYQcrJcUa55TLnvVxz'), 'a914e4567743d378957cd2ee7072da74b1203c1a7a0b87')


class Test_xprv_xpub(SequentialTestCase):

    xprv_xpub = (
        # Taken from test vectors in https://en.bitcoin.it/wiki/BIP_0032_TestVectors
        {'xprv': 'xprvA41z7zogVVwxVSgdKUHDy1SKmdb533PjDz7J6N6mV6uS3ze1ai8FHa8kmHScGpWmj4WggLyQjgPie1rFSruoUihUZREPSL39UNdE3BBDu76',
         'xpub': 'xpub6H1LXWLaKsWFhvm6RVpEL9P4KfRZSW7abD2ttkWP3SSQvnyA8FSVqNTEcYFgJS2UaFcxupHiYkro49S8yGasTvXEYBVPamhGW6cFJodrTHy',
         'xtype': 'standard'},
    )

    def _do_test_bip32(self, seed: str, sequence):
        node = BIP32Node.from_rootseed(bfh(seed), xtype='standard')
        xprv, xpub = node.to_xprv(), node.to_xpub()
        self.assertEqual("m/", sequence[0:2])
        sequence = sequence[2:]
        for n in sequence.split('/'):
            if n[-1] != "'":
                xpub2 = BIP32Node.from_xkey(xpub).subkey_at_public_derivation(n).to_xpub()
            node = BIP32Node.from_xkey(xprv).subkey_at_private_derivation(n)
            xprv, xpub = node.to_xprv(), node.to_xpub()
            if n[-1] != "'":
                self.assertEqual(xpub, xpub2)

        return xpub, xprv

    @needs_test_with_all_ecc_implementations
    def test_bip32(self):
        # see https://en.bitcoin.it/wiki/BIP_0032_TestVectors
        xpub, xprv = self._do_test_bip32("000102030405060708090a0b0c0d0e0f", "m/0'/1/2'/2/1000000000")
        self.assertEqual("xpub6H1LXWLaKsWFhvm6RVpEL9P4KfRZSW7abD2ttkWP3SSQvnyA8FSVqNTEcYFgJS2UaFcxupHiYkro49S8yGasTvXEYBVPamhGW6cFJodrTHy", xpub)
        self.assertEqual("xprvA41z7zogVVwxVSgdKUHDy1SKmdb533PjDz7J6N6mV6uS3ze1ai8FHa8kmHScGpWmj4WggLyQjgPie1rFSruoUihUZREPSL39UNdE3BBDu76", xprv)

        xpub, xprv = self._do_test_bip32("fffcf9f6f3f0edeae7e4e1dedbd8d5d2cfccc9c6c3c0bdbab7b4b1aeaba8a5a29f9c999693908d8a8784817e7b7875726f6c696663605d5a5754514e4b484542","m/0/2147483647'/1/2147483646'/2")
        self.assertEqual("xpub6FnCn6nSzZAw5Tw7cgR9bi15UV96gLZhjDstkXXxvCLsUXBGXPdSnLFbdpq8p9HmGsApME5hQTZ3emM2rnY5agb9rXpVGyy3bdW6EEgAtqt", xpub)
        self.assertEqual("xprvA2nrNbFZABcdryreWet9Ea4LvTJcGsqrMzxHx98MMrotbir7yrKCEXw7nadnHM8Dq38EGfSh6dqA9QWTyefMLEcBYJUuekgW4BYPJcr9E7j", xprv)

    @needs_test_with_all_ecc_implementations
    def test_xpub_from_xprv(self):
        """We can derive the xpub key from a xprv."""
        for xprv_details in self.xprv_xpub:
            result = xpub_from_xprv(xprv_details['xprv'])
            self.assertEqual(result, xprv_details['xpub'])

    @needs_test_with_all_ecc_implementations
    def test_is_xpub(self):
        for xprv_details in self.xprv_xpub:
            xpub = xprv_details['xpub']
            self.assertTrue(is_xpub(xpub))
        self.assertFalse(is_xpub('xpub1nval1d'))
        self.assertFalse(is_xpub('xpub661MyMwAqRbcFWohJWt7PHsFEJfZAvw9ZxwQoDa4SoMgsDDM1T7WK3u9E4edkC4ugRnZ8E4xDZRpk8Rnts3Nbt97dPwT52WRONGBADWRONG'))

    @needs_test_with_all_ecc_implementations
    def test_xpub_type(self):
        for xprv_details in self.xprv_xpub:
            xpub = xprv_details['xpub']
            self.assertEqual(xprv_details['xtype'], xpub_type(xpub))

    @needs_test_with_all_ecc_implementations
    def test_is_xprv(self):
        for xprv_details in self.xprv_xpub:
            xprv = xprv_details['xprv']
            self.assertTrue(is_xprv(xprv))
        self.assertFalse(is_xprv('xprv1nval1d'))
        self.assertFalse(is_xprv('xprv661MyMwAqRbcFWohJWt7PHsFEJfZAvw9ZxwQoDa4SoMgsDDM1T7WK3u9E4edkC4ugRnZ8E4xDZRpk8Rnts3Nbt97dPwT52WRONGBADWRONG'))

    def test_is_bip32_derivation(self):
        self.assertTrue(is_bip32_derivation("m/0'/1"))
        self.assertTrue(is_bip32_derivation("m/0'/0'"))
        self.assertTrue(is_bip32_derivation("m/3'/-5/8h/"))
        self.assertTrue(is_bip32_derivation("m/44'/0'/0'/0/0"))
        self.assertTrue(is_bip32_derivation("m/49'/0'/0'/0/0"))
        self.assertTrue(is_bip32_derivation("m"))
        self.assertTrue(is_bip32_derivation("m/"))
        self.assertFalse(is_bip32_derivation("m5"))
        self.assertFalse(is_bip32_derivation("mmmmmm"))
        self.assertFalse(is_bip32_derivation("n/"))
        self.assertFalse(is_bip32_derivation(""))
        self.assertFalse(is_bip32_derivation("m/q8462"))
        self.assertFalse(is_bip32_derivation("m/-8h"))

    def test_convert_bip32_path_to_list_of_uint32(self):
        self.assertEqual([0, 0x80000001, 0x80000001], convert_bip32_path_to_list_of_uint32("m/0/-1/1'"))
        self.assertEqual([], convert_bip32_path_to_list_of_uint32("m/"))
        self.assertEqual([2147483692, 2147488889, 221], convert_bip32_path_to_list_of_uint32("m/44'/5241h/221"))

    def test_convert_bip32_intpath_to_strpath(self):
        self.assertEqual("m/0/1'/1'", convert_bip32_intpath_to_strpath([0, 0x80000001, 0x80000001]))
        self.assertEqual("m", convert_bip32_intpath_to_strpath([]))
        self.assertEqual("m/44'/5241'/221", convert_bip32_intpath_to_strpath([2147483692, 2147488889, 221]))

    def test_normalize_bip32_derivation(self):
        self.assertEqual("m/0/1'/1'", normalize_bip32_derivation("m/0/1h/1'"))
        self.assertEqual("m", normalize_bip32_derivation("m////"))
        self.assertEqual("m/0/2/1'", normalize_bip32_derivation("m/0/2/-1/"))
        self.assertEqual("m/0/1'/1'/5'", normalize_bip32_derivation("m/0//-1/1'///5h"))

    def test_xtype_from_derivation(self):
        self.assertEqual('standard', xtype_from_derivation("m/44'"))
        self.assertEqual('standard', xtype_from_derivation("m/44'/"))
        self.assertEqual('standard', xtype_from_derivation("m/44'/0'/0'"))
        self.assertEqual('standard', xtype_from_derivation("m/44'/5241'/221"))
        self.assertEqual('standard', xtype_from_derivation("m/45'"))
        self.assertEqual('standard', xtype_from_derivation("m/45'/56165/271'"))

    def test_version_bytes(self):
        xprv_headers_b58 = {
            'standard':    'xprv',
        }
        xpub_headers_b58 = {
            'standard':    'xpub',
        }
        for xtype, xkey_header_bytes in constants.net.XPRV_HEADERS.items():
            xkey_header_bytes = bfh("%08x" % xkey_header_bytes)
            xkey_bytes = xkey_header_bytes + bytes([0] * 74)
            xkey_b58 = EncodeBase58Check(xkey_bytes)
            self.assertTrue(xkey_b58.startswith(xprv_headers_b58[xtype]))

            xkey_bytes = xkey_header_bytes + bytes([255] * 74)
            xkey_b58 = EncodeBase58Check(xkey_bytes)
            self.assertTrue(xkey_b58.startswith(xprv_headers_b58[xtype]))

        for xtype, xkey_header_bytes in constants.net.XPUB_HEADERS.items():
            xkey_header_bytes = bfh("%08x" % xkey_header_bytes)
            xkey_bytes = xkey_header_bytes + bytes([0] * 74)
            xkey_b58 = EncodeBase58Check(xkey_bytes)
            self.assertTrue(xkey_b58.startswith(xpub_headers_b58[xtype]))

            xkey_bytes = xkey_header_bytes + bytes([255] * 74)
            xkey_b58 = EncodeBase58Check(xkey_bytes)
            self.assertTrue(xkey_b58.startswith(xpub_headers_b58[xtype]))


class Test_xprv_xpub_testnet(TestCaseForTestnet):

    def test_version_bytes(self):
        xprv_headers_b58 = {
            'standard':    'tprv',
        }
        xpub_headers_b58 = {
            'standard':    'tpub',
        }
        for xtype, xkey_header_bytes in constants.net.XPRV_HEADERS.items():
            xkey_header_bytes = bfh("%08x" % xkey_header_bytes)
            xkey_bytes = xkey_header_bytes + bytes([0] * 74)
            xkey_b58 = EncodeBase58Check(xkey_bytes)
            self.assertTrue(xkey_b58.startswith(xprv_headers_b58[xtype]))

            xkey_bytes = xkey_header_bytes + bytes([255] * 74)
            xkey_b58 = EncodeBase58Check(xkey_bytes)
            self.assertTrue(xkey_b58.startswith(xprv_headers_b58[xtype]))

        for xtype, xkey_header_bytes in constants.net.XPUB_HEADERS.items():
            xkey_header_bytes = bfh("%08x" % xkey_header_bytes)
            xkey_bytes = xkey_header_bytes + bytes([0] * 74)
            xkey_b58 = EncodeBase58Check(xkey_bytes)
            self.assertTrue(xkey_b58.startswith(xpub_headers_b58[xtype]))

            xkey_bytes = xkey_header_bytes + bytes([255] * 74)
            xkey_b58 = EncodeBase58Check(xkey_bytes)
            self.assertTrue(xkey_b58.startswith(xpub_headers_b58[xtype]))


class Test_drk_import(SequentialTestCase):
    """ The keys used in this class are TEST keys from
        https://en.bitcoin.it/wiki/BIP_0032_TestVectors"""

    xpub = 'xpub68Gmy5EdvgibQVfPdqkBBCHxA5htiqg55crXYuXoQRKfDBFA1WEjWgP6LHhwBZeNK1VTsfTFUHCdrfp1bgwQ9xv5ski8PX9rL2dZXvgGDnw'
    xprv = 'xprv9uHRZZhk6KAJC1avXpDAp4MDc3sQKNxDiPvvkX8Br5ngLNv1TxvUxt4cV1rGL5hj6KCesnDYUhd7oWgT11eZG7XnxHrnYeSvkzY7d2bhkJ7'
    drkp = 'drkpRv3MKBiuEwFtNSzj62Kwpj7Cd77NVUYAPoxBN8EL5rSn6EMWr3bD4RnwwbGrnQZStpYJ1iGZCiGKt9mR7aYNtaurGyTCQZuwVzqzAbX9znj'
    drkv = 'drkvjLuVs1zJu2rKwexyhS5mYeVuNs2umm4bZMg8hv4Zy28xLX2tXbr6tzytFNsAsqjveLoFqSgcNhF4YoonH1y35REUMeSFJZ8ALdoFutwvbtw'
    master_fpr = '3442193e'
    sec_key = 'edb2e14f9ee77d26dd93b4ecede8d16ed408ce149b6cd80b0715a2d911a0afea'
    pub_key = '035a784662a4a20a65bf6aab9ae98a6c068a81c52e4b032c0fb5400c706cfccc56'
    child_num = '80000000'
    chain_code = '47fdacbd0f1097043b78c63c20c34ef4ed9a111d980047ad16282c7ae6236141'
    xtype = 'standard'

    @needs_test_with_all_ecc_implementations
    def check_from_x(self, x, prv):
        node = BIP32Node.from_xkey(x)

        self.assertEqual(self.xtype, node.xtype)
        self.assertEqual(1, node.depth)
        self.assertEqual(self.master_fpr, bh2u(node.fingerprint))
        self.assertEqual(self.child_num, bh2u(node.child_number))
        self.assertEqual(self.chain_code, bh2u(node.chaincode))
        self.assertEqual(self.pub_key, node.eckey.get_public_key_hex())
        if prv:
            self.assertEqual(self.sec_key, bh2u(node.eckey.get_secret_bytes()))

    @needs_test_with_all_ecc_implementations
    def test_from_xpub(self):
        self.check_from_x(self.xpub, False)

    @needs_test_with_all_ecc_implementations
    def test_from_xprv(self):
        self.check_from_x(self.xprv, True)

    @needs_test_with_all_ecc_implementations
    def test_from_drkp(self):
        self.check_from_x(self.drkp, False)

    @needs_test_with_all_ecc_implementations
    def test_from_drkv(self):
        self.check_from_x(self.drkv, True)

    @needs_test_with_all_ecc_implementations
    def test_keystore_from_xpub(self):
        keystore = from_master_key(self.xpub)
        self.assertEqual(keystore.xpub, self.xpub)
        self.assertEqual(keystore.xprv, None)

    @needs_test_with_all_ecc_implementations
    def test_keystore_from_xprv(self):
        keystore = from_master_key(self.xprv)
        self.assertEqual(keystore.xpub, self.xpub)
        self.assertEqual(keystore.xprv, self.xprv)

    @needs_test_with_all_ecc_implementations
    def test_keystore_from_drkp(self):
        keystore = from_master_key(self.drkp)
        self.assertEqual(keystore.xpub, self.xpub)
        self.assertEqual(keystore.xprv, None)

    @needs_test_with_all_ecc_implementations
    def test_keystore_from_drkv(self):
        keystore = from_master_key(self.drkv)
        self.assertEqual(keystore.xpub, self.xpub)
        self.assertEqual(keystore.xprv, self.xprv)


class Test_keyImport(SequentialTestCase):

    priv_pub_addr = (
           {'priv': 'XDL8kYsDheEviC7EYMNbo3Myy1txzKyfhZFZBaYUSPDPm9BZZae8',
            'exported_privkey': 'p2pkh:XDL8kYsDheEviC7EYMNbo3Myy1txzKyfhZFZBaYUSPDPm9BZZae8',
            'pub': '0218864d879997fefbb2846e54ac4db0df99029b91cd12be32312d7e0da45029a8',
            'address': 'PUFpXCipFhCM1n3CvY1pdJnsuBYGXopNoZ',
            'minikey' : False,
            'txin_type': 'p2pkh',
            'compressed': True,
            'addr_encoding': 'base58',
            'scripthash': '33a07d5e4c49c5075ffdd6e018aa76adc6356cea32246af6cdd65d29acd6d36f'},
           {'priv': 'p2pkh:XEo3x1LBrpn3UAW2WURQMZ6Y4ncRTbi7tXbFihdyLH3HSHFVub9W',
            'exported_privkey': 'p2pkh:XEo3x1LBrpn3UAW2WURQMZ6Y4ncRTbi7tXbFihdyLH3HSHFVub9W',
            'pub': '0352d78b4b37e0f6d4e164423436f2925fa57817467178eca550a88f2821973c41',
            'address': 'PQ7ri3oZ9cFiS8ADAYi61s2UKmxUoZtBZ9',
            'minikey': False,
            'txin_type': 'p2pkh',
            'compressed': True,
            'addr_encoding': 'base58',
            'scripthash': 'a9b2a76fc196c553b352186dfcca81fcf323a721cd8431328f8e9d54216818c1'},
           {'priv': 'XFsDL1FgC4VWQWZQu1NZAs5ri1rUP8mu1CviQYBbXedBTK37uppF',
            'exported_privkey': 'p2pkh:XFsDL1FgC4VWQWZQu1NZAs5ri1rUP8mu1CviQYBbXedBTK37uppF',
            'pub': '0329e04e958045a2866e59d13423772e16551cc1bedc50adb0e10b33ae28146cfc',
            'address': 'P9h6zCz253jmc4TvqgKPRNpkx5qELdNWWT',
            'minikey': False,
            'txin_type': 'p2pkh',
            'compressed': True,
            'addr_encoding': 'base58',
            'scripthash': '4b72a36e24dac8375220db482e44b04d350e3a6c05e6901bd15b251c6553eaca'},
           {'priv': 'p2pkh:7sS7opkSixUtHF1RfpSkxsnfpaGAZeyLdB6NucDUvyTVesfwXv9',
            'exported_privkey': 'p2pkh:7sS7opkSixUtHF1RfpSkxsnfpaGAZeyLdB6NucDUvyTVesfwXv9',
            'pub': '048f0431b0776e8210376c81280011c2b68be43194cb00bd47b7e9aa66284b713ce09556cde3fee606051a07613f3c159ef3953b8927c96ae3dae94a6ba4182e0e',
            'address': 'PBhvsPg8p5A2dC5D2uybQw3ocegDVXhShn',
            'minikey': False,
            'txin_type': 'p2pkh',
            'compressed': False,
            'addr_encoding': 'base58',
            'scripthash': '6dd2e07ad2de9ba8eec4bbe8467eb53f8845acff0d9e6f5627391acc22ff62df'},
           # from http://bitscan.com/articles/security/spotlight-on-mini-private-keys
           {'priv': 'SzavMBLoXU6kDrqtUVmffv',   #E9873D79C6D87DC0FB6A5778633389F4453213303DA61F20BD67FC233AA33262
            'exported_privkey': 'p2pkh:7sKi9xmam1ud39rKXGL3ajZEvmGSy5aauGthuG9aYBV73kq1i2J',
            'pub': '04588d202afcc1ee4ab5254c7847ec25b9a135bbda0f2bc69ee1a714749fd77dc9f88ff2a00d7e752d44cbe16e1ebcf0890b76ec7c78886109dee76ccfc8445424',
            'address': 'PKnDg15k847HvN9GhjzMatLQuuqLYyMQbJ', # somehow needs uncompressed .. compressed value is PGs65CKCQQ3KufnqHXRgLpmCK6nxTwLixp
            'minikey': True,
            'txin_type': 'p2pkh',
            'compressed': False,  # this is actually ambiguous... issue #2748
            'addr_encoding': 'base58',
            'scripthash': '5b07ddfde826f5125ee823900749103cea37808038ecead5505a766a07c34445'}, #script has is diff for uncomressed add 60ad5a8b922f758cd7884403e90ee7e6f093f8d21a0ff24c9a865e695ccefdf1
    )

    @needs_test_with_all_ecc_implementations
    def test_public_key_from_private_key(self):
        for priv_details in self.priv_pub_addr:
            txin_type, privkey, compressed = deserialize_privkey(priv_details['priv'])
            result = ecc.ECPrivkey(privkey).get_public_key_hex(compressed=compressed)
            self.assertEqual(priv_details['pub'], result)
            self.assertEqual(priv_details['txin_type'], txin_type)
            self.assertEqual(priv_details['compressed'], compressed)

    @needs_test_with_all_ecc_implementations
    def test_address_from_private_key(self):
        for priv_details in self.priv_pub_addr:
            addr2 = address_from_private_key(priv_details['priv'])
            self.assertEqual(priv_details['address'], addr2)

    @needs_test_with_all_ecc_implementations
    def test_is_valid_address(self):
        for priv_details in self.priv_pub_addr:
            addr = priv_details['address']
            self.assertFalse(is_address(priv_details['priv']))
            self.assertFalse(is_address(priv_details['pub']))
            self.assertTrue(is_address(addr))

            is_enc_b58 = priv_details['addr_encoding'] == 'base58'
            self.assertEqual(is_enc_b58, is_b58_address(addr))

        self.assertFalse(is_address("not an address"))

    @needs_test_with_all_ecc_implementations
    def test_is_private_key(self):
        for priv_details in self.priv_pub_addr:
            self.assertTrue(is_private_key(priv_details['priv']))
            self.assertTrue(is_private_key(priv_details['exported_privkey']))
            self.assertFalse(is_private_key(priv_details['pub']))
            self.assertFalse(is_private_key(priv_details['address']))
        self.assertFalse(is_private_key("not a privkey"))

    @needs_test_with_all_ecc_implementations
    def test_serialize_privkey(self):
        for priv_details in self.priv_pub_addr:
            txin_type, privkey, compressed = deserialize_privkey(priv_details['priv'])
            priv2 = serialize_privkey(privkey, compressed, txin_type)
            self.assertEqual(priv_details['exported_privkey'], priv2)

    @needs_test_with_all_ecc_implementations
    def test_address_to_scripthash(self):
        for priv_details in self.priv_pub_addr:
            sh = address_to_scripthash(priv_details['address'])
            self.assertEqual(priv_details['scripthash'], sh)

    @needs_test_with_all_ecc_implementations
    def test_is_minikey(self):
        for priv_details in self.priv_pub_addr:
            minikey = priv_details['minikey']
            priv = priv_details['priv']
            self.assertEqual(minikey, is_minikey(priv))

    @needs_test_with_all_ecc_implementations
    def test_is_compressed_privkey(self):
        for priv_details in self.priv_pub_addr:
            self.assertEqual(priv_details['compressed'],
                             is_compressed_privkey(priv_details['priv']))

    @needs_test_with_all_ecc_implementations
    def test_wif_with_invalid_magic_byte_for_compressed_pubkey(self):
        with self.assertRaises(BitcoinException):
            is_private_key("KwFAa6AumokBD2dVqQLPou42jHiVsvThY1n25HJ8Ji8REf1wxAQb",
                           raise_on_error=True)


class TestBaseEncode(SequentialTestCase):

    def test_base43(self):
        tx_hex = "020000000001021cd0e96f9ca202e017ca3465e3c13373c0df3a4cdd91c1fd02ea42a1a65d2a410000000000fdffffff757da7cf8322e5063785e2d8ada74702d2648fa2add2d533ba83c52eb110df690200000000fdffffff02d07e010000000000160014b544c86eaf95e3bb3b6d2cabb12ab40fc59cad9ca086010000000000232102ce0d066fbfcf150a5a1bbc4f312cd2eb080e8d8a47e5f2ce1a63b23215e54fb5ac02483045022100a9856bf10a950810abceeabc9a86e6ba533e130686e3d7863971b9377e7c658a0220288a69ef2b958a7c2ecfa376841d4a13817ed24fa9a0e0a6b9cb48e6439794c701210324e291735f83ff8de47301b12034950b80fa4724926a34d67e413d8ff8817c53024830450221008f885978f7af746679200ed55fe2e86c1303620824721f95cc41eb7965a3dfcf02207872082ac4a3c433d41a203e6d685a459e70e551904904711626ac899238c20a0121023d4c9deae1aacf3f822dd97a28deaec7d4e4ff97be746d124a63d20e582f5b290a971600"
        tx_bytes = bfh(tx_hex)
        tx_base43 = base_encode(tx_bytes, 43)
        self.assertEqual("3E2DH7.J3PKVZJ3RCOXQVS3Y./6-WE.75DDU0K58-0N1FRL565N8ZH-DG1Z.1IGWTE5HK8F7PWH5P8+V3XGZZ6GQBPHNDE+RD8CAQVV1/6PQEMJIZTGPMIJ93B8P$QX+Y2R:TGT9QW8S89U4N2.+FUT8VG+34USI/N/JJ3CE*KLSW:REE8T5Y*9:U6515JIUR$6TODLYHSDE3B5DAF:5TF7V*VAL3G40WBOM0DO2+CFKTTM$G-SO:8U0EW:M8V:4*R9ZDX$B1IRBP9PLMDK8H801PNTFB4$HL1+/U3F61P$4N:UAO88:N5D+J:HI4YR8IM:3A7K1YZ9VMRC/47$6GGW5JEL1N690TDQ4XW+TWHD:V.1.630QK*JN/.EITVU80YS3.8LWKO:2STLWZAVHUXFHQ..NZ0:.J/FTZM.KYDXIE1VBY7/:PHZMQ$.JZQ2.XT32440X/HM+UY/7QP4I+HTD9.DUSY-8R6HDR-B8/PF2NP7I2-MRW9VPW3U9.S0LQ.*221F8KVMD5ANJXZJ8WV4UFZ4R.$-NXVE+-FAL:WFERGU+WHJTHAP",
                         tx_base43)
        self.assertEqual(tx_bytes,
                         base_decode(tx_base43, None, 43))

    def test_base58(self):
        data_hex = '0cd394bef396200774544c58a5be0189f3ceb6a41c8da023b099ce547dd4d8071ed6ed647259fba8c26382edbf5165dfd2404e7a8885d88437db16947a116e451a5d1325e3fd075f9d370120d2ab537af69f32e74fc0ba53aaaa637752964b3ac95cfea7'
        data_bytes = bfh(data_hex)
        data_base58 = base_encode(data_bytes, 58)
        self.assertEqual("VuvZ2K5UEcXCVcogny7NH4Evd9UfeYipsTdWuU4jLDhyaESijKtrGWZTFzVZJPjaoC9jFBs3SFtarhDhQhAxkXosUD8PmUb5UXW1tafcoPiCp8jHy7Fe2CUPXAbYuMvAyrkocbe6",
                         data_base58)
        self.assertEqual(data_bytes,
                         base_decode(data_base58, None, 58))

    def test_base58check(self):
        data_hex = '0cd394bef396200774544c58a5be0189f3ceb6a41c8da023b099ce547dd4d8071ed6ed647259fba8c26382edbf5165dfd2404e7a8885d88437db16947a116e451a5d1325e3fd075f9d370120d2ab537af69f32e74fc0ba53aaaa637752964b3ac95cfea7'
        data_bytes = bfh(data_hex)
        data_base58check = EncodeBase58Check(data_bytes)
        self.assertEqual("4GCCJsjHqFbHxWbFBvRg35cSeNLHKeNqkXqFHW87zRmz6iP1dJU9Tk2KHZkoKj45jzVsSV4ZbQ8GpPwko6V3Z7cRfux3zJhUw7TZB6Kpa8Vdya8cMuUtL5Ry3CLtMetaY42u52X7Ey6MAH",
                         data_base58check)
        self.assertEqual(data_bytes,
                         DecodeBase58Check(data_base58check))
