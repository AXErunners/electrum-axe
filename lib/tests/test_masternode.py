import unittest
import base64

from lib.masternode import MasternodeAnnounce, MasternodePing, NetworkAddress
from lib.masternode_manager import parse_masternode_conf, MasternodeConfLine
from lib import bitcoin


raw_announce = '108d6bcba250fef7fc6dfaa5747092f6a1d00651fdb997233d94e0fd3cc4c7270000000000ffffffff00000000000000000000ffffc0a801654e1f2102d3879cdf9afcc59c42d8d858e44ba0e3d51df7792c6c0bbb6dd5e9de41f5580e4104431873cf0a6ae3f6903e72ed915f0e21029e59c1c279358f98e3d4136250c774a4b14bbd8a1ffb800c85310a8379869f05a24a6b99ce3d79f6194881ed7091d6411fabe342d726678ae2139c5e56870803111f9ce00c0df8b48d4d3aa7ef0c95f9567923bb53dce7b3a1ea694111abbf956f84ff1719922e08dbd0530fca23ce144400e70b5700000000d7110100108d6bcba250fef7fc6dfaa5747092f6a1d00651fdb997233d94e0fd3cc4c7270000000000ffffffff9fe612de60e895d900acee8387ede352f438b6a7318615c4a43ef4849700000000e70b5700000000411b5c4e56329362b83dfcbbaa70397c8c49cb7e69edf85b0e8232d2798b7196ec705036069ddc91126df98db4f6755b2ec01577ca417dfaa2e90a0382bd667e410d0000000000000000'
class TestMasternode(unittest.TestCase):
    def test_serialization(self):
        announce = MasternodeAnnounce.deserialize(raw_announce)

        self.assertEqual('27c7c43cfde0943d2397b9fd5106d0a1f6927074a5fa6dfcf7fe50a2cb6b8d10', announce.vin['prevout_hash'])
        self.assertEqual(0, announce.vin['prevout_n'])
        self.assertEqual('', announce.vin['scriptSig'])
        self.assertEqual(0xffffffff, announce.vin['sequence'])

        self.assertEqual('192.168.1.101:19999', str(announce.addr))

        self.assertEqual('02d3879cdf9afcc59c42d8d858e44ba0e3d51df7792c6c0bbb6dd5e9de41f5580e', announce.collateral_key)
        self.assertEqual('04431873cf0a6ae3f6903e72ed915f0e21029e59c1c279358f98e3d4136250c774a4b14bbd8a1ffb800c85310a8379869f05a24a6b99ce3d79f6194881ed7091d6', announce.delegate_key)
        self.assertEqual('H6vjQtcmZ4riE5xeVocIAxEfnOAMDfi0jU06p+8MlflWeSO7U9zns6HqaUERq7+Vb4T/FxmSLgjb0FMPyiPOFEQ=', base64.b64encode(announce.sig))
        self.assertEqual(1460397824, announce.sig_time)
        self.assertEqual(70103, announce.protocol_version)

        self.assertEqual('27c7c43cfde0943d2397b9fd5106d0a1f6927074a5fa6dfcf7fe50a2cb6b8d10', announce.last_ping.vin['prevout_hash'])
        self.assertEqual(0, announce.last_ping.vin['prevout_n'])
        self.assertEqual('', announce.last_ping.vin['scriptSig'])
        self.assertEqual(0xffffffff, announce.last_ping.vin['sequence'])
        self.assertEqual('0000009784f43ea4c4158631a7b638f452e3ed8783eeac00d995e860de12e69f', announce.last_ping.block_hash)
        self.assertEqual(1460397824, announce.last_ping.sig_time)
        self.assertEqual('G1xOVjKTYrg9/LuqcDl8jEnLfmnt+FsOgjLSeYtxluxwUDYGndyREm35jbT2dVsuwBV3ykF9+qLpCgOCvWZ+QQ0=', base64.b64encode(announce.last_ping.sig))

        self.assertEqual(0, announce.last_dsq)

        self.assertEqual(raw_announce, announce.serialize())

    def test_hash(self):
        announce = MasternodeAnnounce.deserialize(raw_announce)

        expected_hash = 'a8a3dc1782191f28f613c8971709a57ee58a4d0d7a11138804f89a0b088d67d1'
        msg = announce.serialize_for_sig()

        h = bitcoin.Hash(bitcoin.msg_magic(msg))
        h = bitcoin.hash_encode(h)
        self.assertEqual(expected_hash, h)

    def test_get_hash(self):
        announce = MasternodeAnnounce.deserialize(raw_announce)
        expected = 'ef3fe643adc638044b32879bc644a0fb1ebe6ca75281368184c891da9c07986b'
        self.assertEqual(expected, announce.get_hash())

    def test_verify(self):
        announce = MasternodeAnnounce.deserialize(raw_announce)
        message = announce.serialize_for_sig()

        pk = bitcoin.public_key_to_p2pkh(announce.collateral_key.decode('hex'))
        self.assertTrue(announce.verify())


        raw = '7ca6564432d0e0920b811887e1f9077a92924c83564e6ea8ea874fc8843ccd2b0000000000ffffffff00000000000000000000ffffc0a801014e1f410411e2638aeb4584ff2e027b6ee20e05655ff05583185b1d87188185d6955534fe02ad35caabb5e6e9ce8747ba73fdccccd2369feb9a6f2b0bdee93378e7c8f1c0410411e2638aeb4584ff2e027b6ee20e05655ff05583185b1d87188185d6955534fe02ad35caabb5e6e9ce8747ba73fdccccd2369feb9a6f2b0bdee93378e7c8f1c0411bab132617d8e6a0e3b5434c91a5a64ff13a9cfadc6c178a47b87691f13a26e7440c08660e488ddf927bba1bf04c1ec196370452a30fd3381ea8ba27d627f9d4468be80e5700000000d71101007ca6564432d0e0920b811887e1f9077a92924c83564e6ea8ea874fc8843ccd2b0000000000ffffffffd75eb4fa0cb71dd2e99d7b242784a5601c5c86d7c1cf0362a3391575070000008be80e5700000000411b6d5985008e0821c936fafc192f31963141ae2fab837e84bb9f12422711c1952d5750f9a781c89117a6f4576edc1149a1bf211e7151c5c88cf3252e2d83cb154a0000000000000000'
        announce = MasternodeAnnounce.deserialize(raw)
        msg = announce.serialize_for_sig()

        pk = bitcoin.public_key_to_p2pkh(announce.collateral_key.decode('hex'))
        self.assertTrue(announce.verify(pk))

    def test_serialize_protocol_version_70201(self):
        raw = '08108933d948aed6a107cd01e7862ed61ef9bf14e87da0a14e8d17791e9f9c570100000000ffffffff00000000000000000000ffff7f0000014e1f210269e1abb1ffe231ea045068272a06f0fae231d11b11a54225867d89267faa4e23210269e1abb1ffe231ea045068272a06f0fae231d11b11a54225867d89267faa4e234120b8bc547ce2471125eddfdfd5af30ea1e892e750acfe2896b241097b7f21442a61da073d47c885535769bf215eb3e97eca692d868db1bfb9dee469a1ece5acb92a1945457000000003912010008108933d948aed6a107cd01e7862ed61ef9bf14e87da0a14e8d17791e9f9c570100000000ffffffffefc894d8431c1774a19aeb732ea7fc56925b740ed80486f30424109a05000000a1945457000000004120818f17742e6644359c8b9a91e56b595615bd2c593de713304435dcfd07ceb6a815559fd3b2f05f531d9b9918b22b8748491c3f36cb25e8397ff950f74030444f0000000000000000'
        announce = MasternodeAnnounce.deserialize(raw)
        announce.sig_time = 1465161129
        msg = announce.serialize_for_sig()
        expected = ''.join([
            '127.0.0.1:19999',
            '1465161129',
            bitcoin.hash_encode(bitcoin.hash_160('0269e1abb1ffe231ea045068272a06f0fae231d11b11a54225867d89267faa4e23'.decode('hex'))),
            bitcoin.hash_encode(bitcoin.hash_160('0269e1abb1ffe231ea045068272a06f0fae231d11b11a54225867d89267faa4e23'.decode('hex'))),
            '70201',
        ])

        self.assertEqual(expected, msg)

    def test_create_and_sign(self):
        collateral_pub = '038ae57bd0fa5b45640e771614ec571c7326a2266c78bb444f1971c85188411ba1' # XahPxwmCuKjPq69hzVxP18V1eASwDWbUrn
        delegate_pub = '02526201c87c1b4630aabbd04572eec3e2545e442503e57e60880fafcc1f684dbc' # Xx2nSdhaT7c9SREKBPAgzpkhu518XFgkgh
        protocol_version = 70103

        ip = '0.0.0.0'
        port = 20000
        addr = NetworkAddress(ip=ip, port=port)

        vin = {'prevout_hash': '00'*32, 'prevout_n': 0, 'scriptSig': '', 'sequence':0xffffffff}

        last_ping = MasternodePing(vin=vin, block_hash='ff'*32)

        announce = MasternodeAnnounce(vin=vin, addr=addr, collateral_key=collateral_pub, delegate_key=delegate_pub,
                protocol_version=protocol_version, last_ping=last_ping)

        collateral_wif = 'XJqCcyfnLYK4Y7ZDVjLrgPnsrq2cWMF6MX9cyhKgfMajwqrCwZaS'
        delegate_wif = 'XCbhXBc2N9q8kxqBF41rSuLWVpVVbDm7P1oPv9GxcrS9QXYBWZkB'
        announce.last_ping.sign(delegate_wif, delegate_pub.decode('hex'), 1461858375)
        sig = announce.sign(collateral_wif, 1461858375)

        address = 'XahPxwmCuKjPq69hzVxP18V1eASwDWbUrn'
        self.assertTrue(announce.verify(address))
        self.assertTrue(bitcoin.verify_message(address, sig, announce.serialize_for_sig()))
        # DEBUG information. Uncomment to see serialization.
        # from pprint import pprint
        # pprint(announce.dump())
        # print(' - sig follows - ')
        # print(base64.b64encode(sig))
        # self.assertFalse(announce.serialize())

class TestMasternodePing(unittest.TestCase):
    def test_serialize_for_sig(self):
        vin = {'prevout_hash': '27c7c43cfde0943d2397b9fd5106d0a1f6927074a5fa6dfcf7fe50a2cb6b8d10',
               'prevout_n': 0, 'scriptSig': '', 'sequence': 0xffffffff}
        block_hash = '0000009784f43ea4c4158631a7b638f452e3ed8783eeac00d995e860de12e69f'
        sig_time = 1460397824
        ping = MasternodePing(vin=vin, block_hash=block_hash, sig_time=sig_time)

        expected = 'CTxIn(COutPoint(27c7c43cfde0943d2397b9fd5106d0a1f6927074a5fa6dfcf7fe50a2cb6b8d10, 0), scriptSig=)0000009784f43ea4c4158631a7b638f452e3ed8783eeac00d995e860de12e69f1460397824'
        self.assertEqual(expected, ping.serialize_for_sig())

    def test_sign(self):
        vin = {'prevout_hash': '00'*32, 'prevout_n': 0, 'scriptSig': '', 'sequence':0xffffffff}
        block_hash = 'ff'*32
        current_time = 1461858375
        ping = MasternodePing(vin=vin, block_hash=block_hash, sig_time=current_time)

        expected_sig = 'H6k0M7G15GLnJ7i7Zcs8uCHcVRsn1P0hKK4lVMkgY4byaOvUECCsfxA9ktUiFT8scfFYYb/sxkcD8ifU/SEnBUg='
        wif = 'XCbhXBc2N9q8kxqBF41rSuLWVpVVbDm7P1oPv9GxcrS9QXYBWZkB'
        sig = ping.sign(wif, current_time = current_time)
        address = bitcoin.address_from_private_key(wif)
        self.assertTrue(bitcoin.verify_message(address, sig, ping.serialize_for_sig()))
        self.assertEqual(expected_sig, base64.b64encode(sig))

class TestNetworkAddr(unittest.TestCase):
    def test_serialize(self):
        expected = '00000000000000000000ffffc0a801654e1f'
        addr = NetworkAddress(ip='192.168.1.101', port=19999)
        self.assertEqual(expected, addr.serialize())
        self.assertEqual('192.168.1.101:19999', str(addr))

class TestParseMasternodeConf(unittest.TestCase):
    def test_parse(self):
        lines = [
            'mn1 127.0.0.2:19999 XJo71yhAvayar2geJiJocDMXVSwQCm14gNZvMmk7Pc1M8Bv8Ev7L 2bcd3c84c84f87eaa86e4e56834c92927a07f9e18718810b92e0d0324456a67c 0',
        ]
        conf_lines = parse_masternode_conf(lines)
        expected = [
            MasternodeConfLine('mn1', '127.0.0.2:19999', 'XJo71yhAvayar2geJiJocDMXVSwQCm14gNZvMmk7Pc1M8Bv8Ev7L', '2bcd3c84c84f87eaa86e4e56834c92927a07f9e18718810b92e0d0324456a67c', 0),
        ]

        for i, conf in enumerate(conf_lines):
            self.assertEqual(expected[i], conf)
