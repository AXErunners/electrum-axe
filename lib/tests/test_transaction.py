import unittest
from lib import transaction
from lib.bitcoin import TYPE_ADDRESS

from lib.keystore import xpubkey_to_address

from lib.util import bh2u

unsigned_blob = '010000000180b54f1bd8265147a40d95316e8ce9da1a1f01e1b36d563a8275e0be3807ff94000000005701ff4c53ff0488b21e000000000000000000d6f1f7cd3d082daddffc75e8e558e4d33efc1c2f0b1cf6d52cd8719621e7c49e03123e1dc268988db79c47f91dfc00b328f666c375dd9e7b5d1d2bb7658a3b027e00000000feffffff0140ddf505000000001976a914ab4b96c435fd4ac967b27745fee19982a510430888ac41fc0000'
signed_blob = '010000000180b54f1bd8265147a40d95316e8ce9da1a1f01e1b36d563a8275e0be3807ff94000000006a473044022057e5b082ef4aaeae33562766012a2fbc85869b8e625255e2111df4f9d39c971302200c07a8f1d96d079710e6451a87ba3007dcacc1c1f322bf879bf19e584c1f5216012103aa69e4e3f9fddc3e087491996e9d59eae908e650c12a75054d2249e6573ff52afeffffff0140ddf505000000001976a914ab4b96c435fd4ac967b27745fee19982a510430888ac41fc0000'
v2_blob = "0200000001191601a44a81e061502b7bfbc6eaa1cef6d1e6af5308ef96c9342f71dbf4b9b5000000006b483045022100a6d44d0a651790a477e75334adfb8aae94d6612d01187b2c02526e340a7fd6c8022028bdf7a64a54906b13b145cd5dab21a26bd4b85d6044e9b97bceab5be44c2a9201210253e8e0254b0c95776786e40984c1aa32a7d03efa6bdacdea5f421b774917d346feffffff026b20fa04000000001976a914024db2e87dd7cfd0e5f266c5f212e21a31d805a588aca0860100000000001976a91421919b94ae5cefcdf0271191459157cdb41c4cbf88aca6240700"

class TestBCDataStream(unittest.TestCase):

    def test_compact_size(self):
        s = transaction.BCDataStream()
        values = [0, 1, 252, 253, 2**16-1, 2**16, 2**32-1, 2**32, 2**64-1]
        for v in values:
            s.write_compact_size(v)

        with self.assertRaises(transaction.SerializationError):
            s.write_compact_size(-1)

        self.assertEqual(bh2u(s.input),
                          '0001fcfdfd00fdfffffe00000100feffffffffff0000000001000000ffffffffffffffffff')
        for v in values:
            self.assertEqual(s.read_compact_size(), v)

        with self.assertRaises(transaction.SerializationError):
            s.read_compact_size()

    def test_string(self):
        s = transaction.BCDataStream()
        with self.assertRaises(transaction.SerializationError):
            s.read_string()

        msgs = ['Hello', ' ', 'World', '', '!']
        for msg in msgs:
            s.write_string(msg)
        for msg in msgs:
            self.assertEqual(s.read_string(), msg)

        with self.assertRaises(transaction.SerializationError):
            s.read_string()

    def test_bytes(self):
        s = transaction.BCDataStream()
        s.write(b'foobar')
        self.assertEqual(s.read_bytes(3), b'foo')
        self.assertEqual(s.read_bytes(2), b'ba')
        self.assertEqual(s.read_bytes(4), b'r')
        self.assertEqual(s.read_bytes(1), b'')

class TestTransaction(unittest.TestCase):

    def test_tx_unsigned(self):
        expected = {
            'inputs': [{
                'type': 'p2pkh',
                'address': 'PUFpXCipFhCM1n3CvY1pdJnsuBYGXopNoZ',
                'num_sig': 1,
                'prevout_hash': 'aa03d442b257122d1f9a0d153139d1f6aecf74314f2b884c6d463fc6f34a773a',
                'prevout_n': 1,
                'pubkeys': ['fd76a914d7b9635605a6006e53623cf4bbe5fbd39051e73988ac'],
                'scriptSig': '01ff1afd76a914d7b9635605a6006e53623cf4bbe5fbd39051e73988ac',
                'sequence': 4294967294,
                'signatures': [None],
                'x_pubkeys': ['fd76a914d7b9635605a6006e53623cf4bbe5fbd39051e73988ac']}],
            'lockTime': 64261,
            'outputs': [{
                'address': 'P9h6zCz253jmc4TvqgKPRNpkx5qELdNWWT',
                'prevout_n': 0,
                'scriptPubKey': '76a9140c1724583577182cceef0e31bc176b2dcfdaadfd88ac',
                'type': TYPE_ADDRESS,
                'value': 10000000},
                {
                'address': 'PUFpXCipFhCM1n3CvY1pdJnsuBYGXopNoZ',
                'prevout_n': 1,
                'scriptPubKey': '76a914d7b9635605a6006e53623cf4bbe5fbd39051e73988ac',
                'type': TYPE_ADDRESS,
                'value': 29980000}],
            'version': 1
        }
        tx = transaction.Transaction(unsigned_blob)
        #trx=tx.deserialize()
        #print(trx)
        #print(trx.get("inputs"))
        self.assertEqual(tx.deserialize(), expected)
        self.assertEqual(tx.deserialize(), None)

        self.assertEqual(tx.as_dict(), {'hex': unsigned_blob, 'complete': False, 'final': True})
        self.assertEqual(tx.get_outputs(), [('P9h6zCz253jmc4TvqgKPRNpkx5qELdNWWT', 10000000),('PUFpXCipFhCM1n3CvY1pdJnsuBYGXopNoZ', 29980000)])
        self.assertEqual(tx.get_output_addresses(), ['P9h6zCz253jmc4TvqgKPRNpkx5qELdNWWT','PUFpXCipFhCM1n3CvY1pdJnsuBYGXopNoZ'])

        self.assertTrue(tx.has_address('P9h6zCz253jmc4TvqgKPRNpkx5qELdNWWT'))
        self.assertTrue(tx.has_address('P9h6zCz253jmc4TvqgKPRNpkx5qELdNWWT'))
        self.assertFalse(tx.has_address('PUFpXCipFhCM1n3incCvY1pdJnsuBYGXopNoZ'))

        self.assertEqual(tx.serialize(), unsigned_blob)

        tx.update_signatures(signed_blob)
        self.assertEqual(tx.raw, signed_blob)

        tx.update(unsigned_blob)
        tx.raw = None
        blob = str(tx)
        self.assertEqual(transaction.deserialize(blob), expected)

    def test_tx_signed(self):
        expected = {
            'inputs': [{
                'type': 'p2pkh',
                'address': 'PUFpXCipFhCM1n3CvY1pdJnsuBYGXopNoZ',
                'num_sig': 1,
                'prevout_hash': '3140eb24b43386f35ba69e3875eb6c93130ac66201d01c58f598defc949a5c2a',
                'prevout_n': 0,
                'pubkeys': ['0218864d879997fefbb2846e54ac4db0df99029b91cd12be32312d7e0da45029a8'],
                'scriptSig': '493046022100a82bbc57a0136751e5433f41cf000b3f1a99c6744775e76ec764fb78c54ee100022100f9e80b7de89de861dc6fb0c1429d5da72c2b6b2ee2406bc9bfb1beedd729d985012102e61d176da16edd1d258a200ad9759ef63adf8e14cd97f53227bae35cdb84d2f6',
                'sequence': 4294967295,
                'signatures': ['3046022100a82bbc57a0136751e5433f41cf000b3f1a99c6744775e76ec764fb78c54ee100022100f9e80b7de89de861dc6fb0c1429d5da72c2b6b2ee2406bc9bfb1beedd729d98501'],
                'x_pubkeys': ['0218864d879997fefbb2846e54ac4db0df99029b91cd12be32312d7e0da45029a8']}],
            'lockTime': 0,
            'outputs': [{
                'address': 'P9h6zCz253jmc4TvqgKPRNpkx5qELdNWWT',
                'prevout_n': 0,
                'scriptPubKey': '4b72a36e24dac8375220db482e44b04d350e3a6c05e6901bd15b251c6553eaca',
                'type': TYPE_ADDRESS,
                'value': 99900000}],
            'version': 1
        }
        tx = transaction.Transaction(signed_blob)
        self.assertEqual(tx.deserialize(), expected)
        self.assertEqual(tx.deserialize(), None)
        self.assertEqual(tx.as_dict(), {'hex': signed_blob, 'complete': True, 'final': True})

        self.assertEqual(tx.serialize(), signed_blob)

        tx.update_signatures(signed_blob)

        self.assertEqual(tx.estimated_total_size(), 193)
        self.assertEqual(tx.estimated_base_size(), 193)
        self.assertEqual(tx.estimated_weight(), 772)
        self.assertEqual(tx.estimated_size(), 193)

    def test_errors(self):
        with self.assertRaises(TypeError):
            transaction.Transaction.pay_script(output_type=None, addr='')

        with self.assertRaises(BaseException):
            xpubkey_to_address('')

    def test_parse_xpub(self):
        res = xpubkey_to_address('fe4e13b0f311a55b8a5db9a32e959da9f011b131019d4cebe6141b9e2c93edcbfc0954c358b062a9f94111548e50bde5847a3096b8b7872dcffadb0e9579b9017b01000200')
        self.assertEqual(res, ('04ee98d63800824486a1cf5b4376f2f574d86e0a3009a6448105703453f3368e8e1d8d090aaecdd626a45cc49876709a3bbb6dc96a4311b3cac03e225df5f63dfc', 'PHHKD22ugdpo4xwHrBadkJLue4gnRTxAsK'))

    def test_version_field(self):
        tx = transaction.Transaction(v2_blob)
        self.assertEqual(tx.txid(), "b97f9180173ab141b61b9f944d841e60feec691d6daab4d4d932b24dd36606fe")

    def test_txid_coinbase_to_p2pk(self):
        tx = transaction.Transaction('01000000010000000000000000000000000000000000000000000000000000000000000000ffffffff4103400d0302ef02062f503253482f522cfabe6d6dd90d39663d10f8fd25ec88338295d4c6ce1c90d4aeb368d8bdbadcc1da3b635801000000000000000474073e03ffffffff013c25cf2d01000000434104b0bd634234abbb1ba1e986e884185c61cf43e001f9137f23c2c409273eb16e6537a576782eba668a7ef8bd3b3cfb1edb7117ab65129b8a2e681f3c1e0908ef7bac00000000')
        self.assertEqual('dbaf14e1c476e76ea05a8b71921a46d6b06f0a950f17c5f9f1a03b8fae467f10', tx.txid())

    def test_txid_coinbase_to_p2pkh(self):
        tx = transaction.Transaction('01000000010000000000000000000000000000000000000000000000000000000000000000ffffffff25033ca0030400001256124d696e656420627920425443204775696c640800000d41000007daffffffff01c00d1298000000001976a91427a1f12771de5cc3b73941664b2537c15316be4388ac00000000')
        self.assertEqual('4328f9311c6defd9ae1bd7f4516b62acf64b361eb39dfcf09d9925c5fd5c61e8', tx.txid())

    def test_txid_p2pk_to_p2pkh(self):
        tx = transaction.Transaction('010000000118231a31d2df84f884ced6af11dc24306319577d4d7c340124a7e2dd9c314077000000004847304402200b6c45891aed48937241907bc3e3868ee4c792819821fcde33311e5a3da4789a02205021b59692b652a01f5f009bd481acac2f647a7d9c076d71d85869763337882e01fdffffff016c95052a010000001976a9149c4891e7791da9e622532c97f43863768264faaf88ac00000000')
        self.assertEqual('90ba90a5b115106d26663fce6c6215b8699c5d4b2672dd30756115f3337dddf9', tx.txid())

    def test_txid_p2pk_to_p2sh(self):
        tx = transaction.Transaction('0100000001e4643183d6497823576d17ac2439fb97eba24be8137f312e10fcc16483bb2d070000000048473044022032bbf0394dfe3b004075e3cbb3ea7071b9184547e27f8f73f967c4b3f6a21fa4022073edd5ae8b7b638f25872a7a308bb53a848baa9b9cc70af45fcf3c683d36a55301fdffffff011821814a0000000017a9143c640bc28a346749c09615b50211cb051faff00f8700000000')
        self.assertEqual('172bdf5a690b874385b98d7ab6f6af807356f03a26033c6a65ab79b4ac2085b5', tx.txid())

    def test_txid_p2pkh_to_p2pkh(self):
        tx = transaction.Transaction('0100000001f9dd7d33f315617530dd72264b5d9c69b815626cce3f66266d1015b1a590ba90000000006a4730440220699bfee3d280a499daf4af5593e8750b54fef0557f3c9f717bfa909493a84f60022057718eec7985b7796bb8630bf6ea2e9bf2892ac21bd6ab8f741a008537139ffe012103b4289890b40590447b57f773b5843bf0400e9cead08be225fac587b3c2a8e973fdffffff01ec24052a010000001976a914ce9ff3d15ed5f3a3d94b583b12796d063879b11588ac00000000')
        self.assertEqual('24737c68f53d4b519939119ed83b2a8d44d716d7f3ca98bcecc0fbb92c2085ce', tx.txid())

    def test_txid_p2pkh_to_p2sh(self):
        tx = transaction.Transaction('010000000195232c30f6611b9f2f82ec63f5b443b132219c425e1824584411f3d16a7a54bc000000006b4830450221009f39ac457dc8ff316e5cc03161c9eff6212d8694ccb88d801dbb32e85d8ed100022074230bb05e99b85a6a50d2b71e7bf04d80be3f1d014ea038f93943abd79421d101210317be0f7e5478e087453b9b5111bdad586038720f16ac9658fd16217ffd7e5785fdffffff0200e40b540200000017a914d81df3751b9e7dca920678cc19cac8d7ec9010b08718dfd63c2c0000001976a914303c42b63569ff5b390a2016ff44651cd84c7c8988acc7010000')
        self.assertEqual('155e4740fa59f374abb4e133b87247dccc3afc233cb97c2bf2b46bba3094aedc', tx.txid())


class NetworkMock(object):

    def __init__(self, unspent):
        self.unspent = unspent

    def synchronous_get(self, arg):
        return self.unspent
