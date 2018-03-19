import unittest
import sys
from ecdsa.util import number_to_string

from lib.bitcoin import (
    generator_secp256k1, point_to_ser, public_key_to_p2pkh, EC_KEY,
    bip32_root, bip32_public_derivation, bip32_private_derivation, pw_encode,
    pw_decode, Hash, PoWHash, rev_hex, public_key_from_private_key,
    address_from_private_key,
    is_valid, is_private_key, xpub_from_xprv, is_new_seed, is_old_seed,
    var_int, op_push, deserialize_xpub, deserialize_xprv,
    deserialize_drkp, deserialize_drkv)

from lib.keystore import from_keys

try:
    import ecdsa
except ImportError:
    sys.exit("Error: python-ecdsa does not seem to be installed. Try 'sudo pip install ecdsa'")


class Test_hash(unittest.TestCase):
    """ The block used here was arbitrarily chosen.
        Block height: 339142."""

    def test_hash_block(self):
        raw_header = '030000001a12ed8fe3b2abe61161c3171f20a4dff83e721298934943ff86170000000000972b51909e1911b9d4462a448cfb14b6d3d2e25151eb75b3e0f252f39a84d22ac4d2fd55e85b1d1b116e56de'
        header_hash = rev_hex(PoWHash(raw_header.decode('hex')).encode('hex'))
        self.assertEqual('000000000008aba1c6b076ba5f147b39007cb1f9c34398960edc7c9d1edf8ad7', header_hash)


class Test_bitcoin(unittest.TestCase):

    def test_crypto(self):
        for message in ["Chancellor on brink of second bailout for banks", chr(255)*512]:
            self._do_test_crypto(message)

    def _do_test_crypto(self, message):
        G = generator_secp256k1
        _r  = G.order()
        pvk = ecdsa.util.randrange( pow(2,256) ) %_r

        Pub = pvk*G
        pubkey_c = point_to_ser(Pub,True)
        #pubkey_u = point_to_ser(Pub,False)
        addr_c = public_key_to_p2pkh(pubkey_c)
        #addr_u = public_key_to_bc_address(pubkey_u)

        #print "Private key            ", '%064x'%pvk
        eck = EC_KEY(number_to_string(pvk,_r))

        #print "Compressed public key  ", pubkey_c.encode('hex')
        enc = EC_KEY.encrypt_message(message, pubkey_c)
        dec = eck.decrypt_message(enc)
        assert dec == message

        #print "Uncompressed public key", pubkey_u.encode('hex')
        #enc2 = EC_KEY.encrypt_message(message, pubkey_u)
        dec2 = eck.decrypt_message(enc)
        assert dec2 == message

        signature = eck.sign_message(message, True)
        #print signature
        EC_KEY.verify_message(eck, signature, message)

    def test_bip32(self):
        # see https://en.bitcoin.it/wiki/BIP_0032_TestVectors
        xpub, xprv = self._do_test_bip32("000102030405060708090a0b0c0d0e0f", "m/0'/1/2'/2/1000000000")
        assert xpub == "xpub6H1LXWLaKsWFhvm6RVpEL9P4KfRZSW7abD2ttkWP3SSQvnyA8FSVqNTEcYFgJS2UaFcxupHiYkro49S8yGasTvXEYBVPamhGW6cFJodrTHy"
        assert xprv == "xprvA41z7zogVVwxVSgdKUHDy1SKmdb533PjDz7J6N6mV6uS3ze1ai8FHa8kmHScGpWmj4WggLyQjgPie1rFSruoUihUZREPSL39UNdE3BBDu76"

        xpub, xprv = self._do_test_bip32("fffcf9f6f3f0edeae7e4e1dedbd8d5d2cfccc9c6c3c0bdbab7b4b1aeaba8a5a29f9c999693908d8a8784817e7b7875726f6c696663605d5a5754514e4b484542","m/0/2147483647'/1/2147483646'/2")
        assert xpub == "xpub6FnCn6nSzZAw5Tw7cgR9bi15UV96gLZhjDstkXXxvCLsUXBGXPdSnLFbdpq8p9HmGsApME5hQTZ3emM2rnY5agb9rXpVGyy3bdW6EEgAtqt"
        assert xprv == "xprvA2nrNbFZABcdryreWet9Ea4LvTJcGsqrMzxHx98MMrotbir7yrKCEXw7nadnHM8Dq38EGfSh6dqA9QWTyefMLEcBYJUuekgW4BYPJcr9E7j"

    def _do_test_bip32(self, seed, sequence):
        xprv, xpub = bip32_root(seed.decode('hex'), 0)
        assert sequence[0:2] == "m/"
        path = 'm'
        sequence = sequence[2:]
        for n in sequence.split('/'):
            child_path = path + '/' + n
            if n[-1] != "'":
                xpub2 = bip32_public_derivation(xpub, path, child_path)
            xprv, xpub = bip32_private_derivation(xprv, path, child_path)
            if n[-1] != "'":
                assert xpub == xpub2
            path = child_path

        return xpub, xprv

    def test_aes_homomorphic(self):
        """Make sure AES is homomorphic."""
        payload = u'\u66f4\u7a33\u5b9a\u7684\u4ea4\u6613\u5e73\u53f0'
        password = u'secret'
        enc = pw_encode(payload, password)
        dec = pw_decode(enc, password)
        self.assertEqual(dec, payload)

    def test_aes_encode_without_password(self):
        """When not passed a password, pw_encode is noop on the payload."""
        payload = u'\u66f4\u7a33\u5b9a\u7684\u4ea4\u6613\u5e73\u53f0'
        enc = pw_encode(payload, None)
        self.assertEqual(payload, enc)

    def test_aes_deencode_without_password(self):
        """When not passed a password, pw_decode is noop on the payload."""
        payload = u'\u66f4\u7a33\u5b9a\u7684\u4ea4\u6613\u5e73\u53f0'
        enc = pw_decode(payload, None)
        self.assertEqual(payload, enc)

    def test_aes_decode_with_invalid_password(self):
        """pw_decode raises an Exception when supplied an invalid password."""
        payload = u"blah"
        password = u"uber secret"
        wrong_password = u"not the password"
        enc = pw_encode(payload, password)
        self.assertRaises(Exception, pw_decode, enc, wrong_password)

    def test_hash(self):
        """Make sure the Hash function does sha256 twice"""
        payload = u"test"
        expected = '\x95MZI\xfdp\xd9\xb8\xbc\xdb5\xd2R&x)\x95\x7f~\xf7\xfalt\xf8\x84\x19\xbd\xc5\xe8"\t\xf4'

        result = Hash(payload)
        self.assertEqual(expected, result)

    def test_xpub_from_xprv(self):
        """We can derive the xpub key from a xprv."""
        # Taken from test vectors in https://en.bitcoin.it/wiki/BIP_0032_TestVectors
        xpub = "xpub6H1LXWLaKsWFhvm6RVpEL9P4KfRZSW7abD2ttkWP3SSQvnyA8FSVqNTEcYFgJS2UaFcxupHiYkro49S8yGasTvXEYBVPamhGW6cFJodrTHy"
        xprv = "xprvA41z7zogVVwxVSgdKUHDy1SKmdb533PjDz7J6N6mV6uS3ze1ai8FHa8kmHScGpWmj4WggLyQjgPie1rFSruoUihUZREPSL39UNdE3BBDu76"

        result = xpub_from_xprv(xprv)
        self.assertEqual(result, xpub)

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
        self.assertEqual(op_push(0x00), '00')
        self.assertEqual(op_push(0x12), '12')
        self.assertEqual(op_push(0x4b), '4b')
        self.assertEqual(op_push(0x4c), '4c4c')
        self.assertEqual(op_push(0xfe), '4cfe')
        self.assertEqual(op_push(0xff), '4dff00')
        self.assertEqual(op_push(0x100), '4d0001')
        self.assertEqual(op_push(0x1234), '4d3412')
        self.assertEqual(op_push(0xfffe), '4dfeff')
        self.assertEqual(op_push(0xffff), '4effff0000')
        self.assertEqual(op_push(0x10000), '4e00000100')
        self.assertEqual(op_push(0x12345678), '4e78563412')


class Test_keyImport(unittest.TestCase):
    """ The keys used in this class are TEST keys from
        https://en.bitcoin.it/wiki/BIP_0032_TestVectors"""

    private_key = "XK6TSbQyfRvQuHBuTjEhHcbaBW8dM8KaQzLv47Vpc5xXPNqesKTt"
    public_key_hex = "0339a36013301597daef41fbe593a02cc513d0b55527ec2df1050e2e8ff49c85c2"
    main_address = "XfTA9qgYmaEHfWhUakwcoTtyquez8SowY1"

    def test_public_key_from_private_key(self):
        result = public_key_from_private_key(self.private_key)
        self.assertEqual(self.public_key_hex, result)

    def test_address_from_private_key(self):
        result = address_from_private_key(self.private_key)
        self.assertEqual(self.main_address, result)

    def test_is_valid_address(self):
        self.assertTrue(is_valid(self.main_address))
        self.assertFalse(is_valid("not an address"))

    def test_is_private_key(self):
        self.assertTrue(is_private_key(self.private_key))
        self.assertFalse(is_private_key(self.public_key_hex))


class Test_xkey_import(unittest.TestCase):
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

    def test_deserialize_xpub(self):
        xtype, depth, fpr, child_number, c, K = deserialize_xpub(self.xpub)

        self.assertEqual(0, xtype)
        self.assertEqual(1, depth)
        self.assertEqual(self.master_fpr, fpr.encode('hex'))
        self.assertEqual(self.child_num, child_number.encode('hex'))
        self.assertEqual(self.chain_code, c.encode('hex'))
        self.assertEqual(self.pub_key, K.encode('hex'))

    def test_deserialize_xprv(self):
        xtype, depth, fpr, child_number, c, k = deserialize_xprv(self.xprv)

        self.assertEqual(0, xtype)
        self.assertEqual(1, depth)
        self.assertEqual(self.master_fpr, fpr.encode('hex'))
        self.assertEqual(self.child_num, child_number.encode('hex'))
        self.assertEqual(self.chain_code, c.encode('hex'))
        self.assertEqual(self.sec_key, k.encode('hex'))

    def test_deserialize_drkp(self):
        xtype, depth, fpr, child_number, c, K = deserialize_drkp(self.drkp)

        self.assertEqual(0, xtype)
        self.assertEqual(1, depth)
        self.assertEqual(self.master_fpr, fpr.encode('hex'))
        self.assertEqual(self.child_num, child_number.encode('hex'))
        self.assertEqual(self.chain_code, c.encode('hex'))
        self.assertEqual(self.pub_key, K.encode('hex'))

    def test_deserialize_drkv(self):
        xtype, depth, fpr, child_number, c, k = deserialize_drkv(self.drkv)

        self.assertEqual(0, xtype)
        self.assertEqual(1, depth)
        self.assertEqual(self.master_fpr, fpr.encode('hex'))
        self.assertEqual(self.child_num, child_number.encode('hex'))
        self.assertEqual(self.chain_code, c.encode('hex'))
        self.assertEqual(self.sec_key, k.encode('hex'))

    def test_keystore_from_xpub(self):
        keystore = from_keys(self.xpub)
        self.assertEqual(keystore.xpub, self.xpub)
        self.assertEqual(keystore.xprv, None)

    def test_keystore_from_xprv(self):
        keystore = from_keys(self.xprv)
        self.assertEqual(keystore.xpub, self.xpub)
        self.assertEqual(keystore.xprv, self.xprv)

    def test_keystore_from_drkp(self):
        keystore = from_keys(self.drkp)
        self.assertEqual(keystore.xpub, self.xpub)
        self.assertEqual(keystore.xprv, None)

    def test_keystore_from_drkv(self):
        keystore = from_keys(self.drkv)
        self.assertEqual(keystore.xpub, self.xpub)
        self.assertEqual(keystore.xprv, self.xprv)


class Test_seeds(unittest.TestCase):
    """ Test old and new seeds. """
    
    def test_new_seed(self):
        seed = "cram swing cover prefer miss modify ritual silly deliver chunk behind inform able"
        self.assertTrue(is_new_seed(seed))

        seed = "cram swing cover prefer miss modify ritual silly deliver chunk behind inform"
        self.assertFalse(is_new_seed(seed))

    def test_old_seed(self):
        self.assertTrue(is_old_seed(" ".join(["like"] * 12)))
        self.assertFalse(is_old_seed(" ".join(["like"] * 18)))
        self.assertTrue(is_old_seed(" ".join(["like"] * 24)))
        self.assertFalse(is_old_seed("not a seed"))

        self.assertTrue(is_old_seed("0123456789ABCDEF" * 2))
        self.assertTrue(is_old_seed("0123456789ABCDEF" * 4))
