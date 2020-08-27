import unittest

from electrum_axe.axe_tx import TxOutPoint
from electrum_axe.protx import ProTxMN


class ProTxTestCase(unittest.TestCase):

    def test_protxmn(self):
        mn_dict = {
            'alias': 'default',
            'bls_privk': '702ac35f02311c6b3209538c2784c21a'
                         '066d767b53d5a7c69fd677f1949a76a5',
            'collateral': {
                'hash': '0'*64,
                'index': -1
            },
            'is_operated': True,
            'is_owned': True,
            'mode': 0,
            'op_payout_address': '',
            'op_reward': 0,
            'owner_addr': 'yevc1CQmqyPWJjz1kg9KbnAvov8K3RmaYz',
            'payout_address': 'ygeCXmn4ysXxL1DmUAcmuG5WA6QwNJbr3b',
            'protx_hash': '',
            'pubkey_operator': '012152114d9b7edaa5473c93858f8c11'
                               'fa12b6f8afa37a40ed335407b207f7c8'
                               'caa46092586c369daba06cfda00893ae',
            'service': {
                'ip': '127.0.0.1',
                'port': 9937
            },
            'type': 0,
            'voting_addr': 'yevc1CQmqyPWJjz1kg9KbnAvov8K3RmaYz'}

        mn = ProTxMN.from_dict(mn_dict)
        assert mn.alias == 'default'
        assert mn.is_owned == True
        assert mn.is_operated == True
        assert mn.bls_privk == ('702ac35f02311c6b3209538c2784c21a'
                                '066d767b53d5a7c69fd677f1949a76a5')
        assert mn.type == 0
        assert mn.mode == 0
        assert mn.collateral == TxOutPoint(b'\x00'*32, -1)
        assert str(mn.service) == '127.0.0.1:9937'
        assert mn.owner_addr == 'yevc1CQmqyPWJjz1kg9KbnAvov8K3RmaYz'
        assert mn.pubkey_operator == ('012152114d9b7edaa5473c93858f8c11'
                                      'fa12b6f8afa37a40ed335407b207f7c8'
                                      'caa46092586c369daba06cfda00893ae')
        assert mn.voting_addr == 'yevc1CQmqyPWJjz1kg9KbnAvov8K3RmaYz'
        assert mn.op_reward == 0
        assert mn.payout_address == 'ygeCXmn4ysXxL1DmUAcmuG5WA6QwNJbr3b'
        assert mn.op_payout_address == ''
        assert mn.protx_hash == ''
        mn_dict2 = mn.as_dict()
        assert mn_dict2 == mn_dict
