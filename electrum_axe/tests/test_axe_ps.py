import asyncio
import os
import gzip
import random
import shutil
import tempfile
import time
from collections import defaultdict

from electrum_axe import axe_ps
from electrum_axe.bitcoin import TYPE_ADDRESS
from electrum_axe.address_synchronizer import (TX_HEIGHT_LOCAL,
                                                TX_HEIGHT_UNCONF_PARENT,
                                                TX_HEIGHT_UNCONFIRMED)
from electrum_axe.axe_ps import (COLLATERAL_VAL, PSPossibleDoubleSpendError,
                                   CREATE_COLLATERAL_VAL, to_haks, PSTxData,
                                   PSTxWorkflow, PSDenominateWorkflow,
                                   PSMinRoundsCheckFailed, PS_DENOMS_VALS,
                                   filter_log_line, KPStates, KP_ALL_TYPES,
                                   KP_SPENDABLE, KP_PS_COINS,
                                   KP_PS_CHANGE, PSStates, calc_tx_size,
                                   calc_tx_fee, FILTERED_TXID, FILTERED_ADDR,
                                   CREATE_COLLATERAL_VALS, MIN_DENOM_VAL)
from electrum_axe.axe_tx import PSTxTypes, PSCoinRounds, SPEC_TX_NAMES
from electrum_axe.keystore import xpubkey_to_address
from electrum_axe.simple_config import SimpleConfig
from electrum_axe.storage import WalletStorage
from electrum_axe.transaction import TxOutput, Transaction
from electrum_axe.util import Satoshis, NotEnoughFunds, TxMinedInfo, bh2u
from electrum_axe.wallet import Wallet

from . import TestCaseForTestnet


class NetworkBroadcastMock:

    def __init__(self, pass_cnt=None):
        self.pass_cnt = pass_cnt
        self.passed_cnt = 0

    async def broadcast_transaction(self, tx, *, timeout=None) -> None:
        if self.pass_cnt is not None and self.passed_cnt >= self.pass_cnt:
            raise Exception('Broadcast Failed')
        self.passed_cnt += 1


class WalletGetTxHeigthMock:

    def __init__(self, nonlocal_txids):
        self.nonlocal_txids = nonlocal_txids

    def is_local_tx(self, txid):
        tx_mined_info = self.get_tx_height(txid)
        if tx_mined_info.height == TX_HEIGHT_LOCAL:
            return True
        else:
            return False

    def get_tx_height(self, txid):
        if txid not in self.nonlocal_txids:
            return TxMinedInfo(height=TX_HEIGHT_LOCAL, conf=0)
        else:
            height = random.choice([TX_HEIGHT_UNCONF_PARENT,
                                    TX_HEIGHT_UNCONFIRMED])
        return TxMinedInfo(height=height, conf=0)


class PSWalletTestCase(TestCaseForTestnet):

    def setUp(self):
        super(PSWalletTestCase, self).setUp()
        self.user_dir = tempfile.mkdtemp()
        self.wallet_path = os.path.join(self.user_dir, 'wallet_ps1')
        tests_path = os.path.dirname(os.path.abspath(__file__))
        test_data_file = os.path.join(tests_path, 'data', 'wallet_ps1.gz')
        shutil.copyfile(test_data_file, '%s.gz' % self.wallet_path)
        with gzip.open('%s.gz' % self.wallet_path, 'rb') as rfh:
            wallet_data = rfh.read()
            wallet_data = wallet_data.decode('utf-8')
        with open(self.wallet_path, 'w') as wfh:
            wfh.write(wallet_data)
        self.config = SimpleConfig({'electrum_path': self.user_dir})
        self.config.set_key('dynamic_fees', False, True)
        self.storage = WalletStorage(self.wallet_path)
        self.wallet = Wallet(self.storage)
        psman = self.wallet.psman
        psman.state = PSStates.Ready
        psman.loop = asyncio.get_event_loop()

    def tearDown(self):
        super(PSWalletTestCase, self).tearDown()
        shutil.rmtree(self.user_dir)

    def test_PSTxData(self):
        psman = self.wallet.psman
        tx_type = PSTxTypes.NEW_DENOMS
        raw_tx = '02000000000000000000'
        txid = '0'*64
        uuid = 'uuid'
        tx_data = PSTxData(uuid=uuid, txid=txid,
                           raw_tx=raw_tx, tx_type=tx_type)
        assert tx_data.txid == txid
        assert tx_data.raw_tx == raw_tx
        assert tx_data.tx_type == int(tx_type)
        assert tx_data.uuid == uuid
        assert tx_data.sent is None
        assert tx_data.next_send is None

        # test _as_dict
        d = tx_data._as_dict()
        assert d == {txid: (uuid, None, None, int(tx_type), raw_tx)}

        # test _from_txid_and_tuple
        new_tx_data = PSTxData._from_txid_and_tuple(txid, d[txid])
        assert id(new_tx_data) != id(tx_data)
        assert new_tx_data == tx_data

        # test send
        t1 = time.time()
        psman.network = NetworkBroadcastMock(pass_cnt=1)
        coro = tx_data.send(psman)
        asyncio.get_event_loop().run_until_complete(coro)
        t2 = time.time()
        assert t2 > tx_data.sent > t1

        # test next_send
        tx_data.sent = None
        t1 = time.time()
        psman.network = NetworkBroadcastMock(pass_cnt=0)
        coro = tx_data.send(psman)
        asyncio.get_event_loop().run_until_complete(coro)
        t2 = time.time()
        assert tx_data.sent is None
        assert t2 > tx_data.next_send - 10 > t1

    def test_PSTxWorkflow(self):
        with self.assertRaises(TypeError):
            workflow = PSTxWorkflow()
        uuid = 'uuid'
        workflow = PSTxWorkflow(uuid=uuid)
        wallet = WalletGetTxHeigthMock([])
        assert workflow.uuid == 'uuid'
        assert not workflow.completed
        assert workflow.next_to_send(wallet) is None
        assert workflow.tx_data == {}
        assert workflow.tx_order == []

        raw_tx = '02000000000000000000'
        tx_type = PSTxTypes.NEW_DENOMS
        txid1 = '1'*64
        txid2 = '2'*64
        txid3 = '3'*64
        workflow.add_tx(txid=txid1, tx_type=tx_type)
        workflow.add_tx(txid=txid2, tx_type=tx_type, raw_tx=raw_tx)
        workflow.add_tx(txid=txid3, tx_type=tx_type, raw_tx=raw_tx)
        workflow.completed = True

        assert workflow.tx_order == [txid1, txid2, txid3]
        tx_data1 = workflow.tx_data[txid1]
        tx_data2 = workflow.tx_data[txid2]
        tx_data3 = workflow.tx_data[txid3]
        assert workflow.next_to_send(wallet) == tx_data1
        assert tx_data1._as_dict() == {txid1:
                                       (uuid, None, None,
                                        int(tx_type), None)}
        assert tx_data2._as_dict() == {txid2:
                                       (uuid, None, None,
                                        int(tx_type), raw_tx)}
        assert tx_data3._as_dict() == {txid3:
                                       (uuid, None, None,
                                        int(tx_type), raw_tx)}
        tx_data1.sent = time.time()
        assert workflow.next_to_send(wallet) == tx_data2

        assert workflow.pop_tx(txid2) == tx_data2
        assert workflow.next_to_send(wallet) == tx_data3

        # test next_to_send if txid has nonlocal height in wallet.get_tx_height
        wallet = WalletGetTxHeigthMock([txid3])
        assert workflow.next_to_send(wallet) is None

        # test _as_dict
        d = workflow._as_dict()
        assert id(d['tx_order']) != id(workflow.tx_order)
        assert id(d['tx_data']) != id(workflow.tx_data)
        assert d['uuid'] == uuid
        assert d['completed']
        assert d['tx_order'] == [txid1, txid3]
        assert set(d['tx_data'].keys()) == {txid1, txid3}
        assert d['tx_data'][txid1] == (uuid, tx_data1.sent, None, tx_type,
                                       tx_data1.raw_tx)
        assert d['tx_data'][txid3] == (uuid, tx_data3.sent, None, tx_type,
                                       tx_data3.raw_tx)

        # test _from_dict
        workflow2 = PSTxWorkflow._from_dict(d)
        assert id(workflow2) != id(workflow)
        assert id(d['tx_order']) != id(workflow2.tx_order)
        assert id(d['tx_data']) != id(workflow2.tx_data)
        assert workflow2 == workflow

    def test_PSDenominateWorkflow(self):
        with self.assertRaises(TypeError):
            workflow = PSDenominateWorkflow()
        uuid = 'uuid'
        workflow = PSDenominateWorkflow(uuid=uuid)
        assert workflow.uuid == 'uuid'
        assert workflow.denom == 0
        assert workflow.rounds == 0
        assert workflow.inputs == []
        assert workflow.outputs == []
        assert workflow.completed == 0

        tc = time.time()
        workflow.denom = 1
        workflow.rounds = 1
        workflow.inputs = ['12345:0', '12345:5', '12345:7']
        workflow.outputs = ['addr1', 'addr2', 'addr3']
        workflow.completed = tc

        # test _as_dict
        d = workflow._as_dict()
        data_tuple = d[uuid]
        assert data_tuple == (workflow.denom, workflow.rounds,
                              workflow.inputs, workflow.outputs,
                              workflow.completed)
        assert id(data_tuple[1]) != id(workflow.inputs)
        assert id(data_tuple[2]) != id(workflow.outputs)

        # test _from_uuid_and_tuple
        workflow2 = PSDenominateWorkflow._from_uuid_and_tuple(uuid, data_tuple)
        assert id(workflow2) != id(workflow)
        assert uuid == workflow2.uuid
        assert data_tuple[0] == workflow2.denom
        assert data_tuple[1] == workflow2.rounds
        assert data_tuple[2] == workflow2.inputs
        assert data_tuple[3] == workflow2.outputs
        assert id(data_tuple[3]) != id(workflow2.inputs)
        assert id(data_tuple[3]) != id(workflow2.outputs)
        assert data_tuple[4] == workflow2.completed
        assert workflow == workflow2

    def test_find_untracked_ps_txs(self):
        w = self.wallet
        psman = w.psman
        ps_txs = w.db.get_ps_txs()
        ps_denoms = w.db.get_ps_denoms()
        ps_spent_denoms = w.db.get_ps_spent_denoms()
        ps_spent_collaterals = w.db.get_ps_spent_collaterals()
        assert len(ps_txs) == 0
        assert len(ps_denoms) == 0
        assert len(ps_spent_denoms) == 0
        assert len(ps_spent_collaterals) == 0
        c_outpoint, ps_collateral = w.db.get_ps_collateral()
        assert c_outpoint is None

        coro = psman.find_untracked_ps_txs(log=False)
        found_txs = asyncio.get_event_loop().run_until_complete(coro)
        assert found_txs == 86
        assert len(ps_txs) == 86
        assert len(ps_denoms) == 131
        assert len(ps_spent_denoms) == 179
        assert len(ps_spent_collaterals) == 6
        c_outpoint, ps_collateral = w.db.get_ps_collateral()
        assert c_outpoint == ('9b6cfb93fe6b002e0c60833fa9bcbeef'
                              '057673ebae64d05864827b5dd808fb23:0')
        assert ps_collateral == ('yiozDzgTrjyXqie28y7z2YEmjaYUZ7gveQ', 20000)

        coro = psman.find_untracked_ps_txs(log=False)
        found_txs = asyncio.get_event_loop().run_until_complete(coro)
        assert found_txs == 0
        assert len(ps_txs) == 86
        assert len(ps_denoms) == 131
        assert len(ps_spent_denoms) == 179
        assert len(ps_spent_collaterals) == 6
        c_outpoint, ps_collateral = w.db.get_ps_collateral()
        assert c_outpoint == ('9b6cfb93fe6b002e0c60833fa9bcbeef'
                              '057673ebae64d05864827b5dd808fb23:0')
        assert ps_collateral == ('yiozDzgTrjyXqie28y7z2YEmjaYUZ7gveQ', 20000)

    def test_ps_history_show_all(self):
        psman = self.wallet.psman
        coro = psman.find_untracked_ps_txs(log=False)
        asyncio.get_event_loop().run_until_complete(coro)
        # check with show_dip2_tx_type on
        self.config.set_key('show_dip2_tx_type', True, True)
        h = self.wallet.get_full_history(config=self.config)
        assert h['summary']['end_balance'] == Satoshis(1484831773)
        txs = h['transactions']
        assert len(txs) == 88
        for i in [1, 6, 7, 10, 11, 83, 84, 85, 86]:
            assert txs[i]['dip2'] == SPEC_TX_NAMES[PSTxTypes.NEW_DENOMS]
        for i in [51]:
            assert txs[i]['dip2'] == SPEC_TX_NAMES[PSTxTypes.NEW_COLLATERAL]
        for i in [2, 3, 4, 5, 8, 9, 12, 13, 14, 15, 16, 81]:
            assert txs[i]['dip2'] == SPEC_TX_NAMES[PSTxTypes.DENOMINATE]
        for i in range(18, 36):
            assert txs[i]['dip2'] == SPEC_TX_NAMES[PSTxTypes.DENOMINATE]
        for i in range(37, 49):
            assert txs[i]['dip2'] == SPEC_TX_NAMES[PSTxTypes.DENOMINATE]
        for i in range(52, 64):
            assert txs[i]['dip2'] == SPEC_TX_NAMES[PSTxTypes.DENOMINATE]
        for i in range(65, 80):
            assert txs[i]['dip2'] == SPEC_TX_NAMES[PSTxTypes.DENOMINATE]
        for i in [17, 36, 49, 50, 64, 80]:
            assert txs[i]['dip2'] == SPEC_TX_NAMES[PSTxTypes.PAY_COLLATERAL]
        for i in [82]:
            assert txs[i]['dip2'] == SPEC_TX_NAMES[PSTxTypes.PRIVATESEND]
        for i, tx in enumerate(txs):
            assert not txs[i]['group_txid']
            assert txs[i]['group_data'] == []
        # check with show_dip2_tx_type off
        self.config.set_key('show_dip2_tx_type', False, True)
        h = self.wallet.get_full_history(config=self.config)
        assert h['summary']['end_balance'] == Satoshis(1484831773)
        txs = h['transactions']
        assert len(txs) == 88
        for i, tx in enumerate(txs):
            assert not txs[i]['group_txid']
            assert txs[i]['group_data'] == []

    def test_ps_history_show_grouped(self):
        psman = self.wallet.psman
        coro = psman.find_untracked_ps_txs(log=False)
        asyncio.get_event_loop().run_until_complete(coro)

        # check with show_dip2_tx_type off
        self.config.set_key('show_dip2_tx_type', False, True)
        h = self.wallet.get_full_history(config=self.config, group_ps=True)
        end_balance = Satoshis(1484831773)
        assert h['summary']['end_balance'] == end_balance
        txs = h['transactions']
        group0 = txs[81]['group_data']
        group0_val = Satoshis(-64144)
        group0_balance = Satoshis(1599935856)
        group0_txs_cnt = 81
        group1 = txs[86]['group_data']
        group1_txs = ['d9565c9cf5d819acb0f94eca4522c442'
                      'f40d8ebee973f6f0896763af5868db4b',
                      '4a256db62ff0c1764d6eeb8708b87d8a'
                      'c61c6c0f8c17db76d8a0c11dcb6477cb',
                      'a58b8396f95489e2f47769ac085e7fb9'
                      '4a2502ed8e32f617927c2f818c41b099',
                      '612bee0394963117251c006c64676c16'
                      '2aa98bd257094f017ae99b4003dfbbab']
        group1_val = Satoshis(-2570)
        group1_balance = Satoshis(1484832135)
        group1_txs_cnt = 4

        # group is tuple: (val, balance, ['txid1', 'txid2, ...])
        assert group0[0] == group0_val
        assert group0[1] == group0_balance
        assert len(group0[2]) == group0_txs_cnt
        assert group1[0] == group1_val
        assert group1[1] == group1_balance
        assert len(group1[2]) == group1_txs_cnt
        assert group1[2] == group1_txs

        for i, tx in enumerate(txs):
            if i not in [81, 86]:
                assert txs[i]['group_data'] == []
            if i in [0, 81, 82, 86, 87]:
                assert not txs[i]['group_txid']
            if i in range(1, 81):
                assert txs[i]['group_txid'] == txs[81]['txid']
            if i in range(83, 86):
                assert txs[i]['group_txid'] == txs[86]['txid']

        # check with show_dip2_tx_type on
        self.config.set_key('show_dip2_tx_type', True, True)
        h = self.wallet.get_full_history(config=self.config, group_ps=True)
        assert h['summary']['end_balance'] == end_balance
        txs = h['transactions']
        for i in [1, 6, 7, 10, 11, 83, 84, 85, 86]:
            assert txs[i]['dip2'] == SPEC_TX_NAMES[PSTxTypes.NEW_DENOMS]
        for i in [51]:
            assert txs[i]['dip2'] == SPEC_TX_NAMES[PSTxTypes.NEW_COLLATERAL]
        for i in [2, 3, 4, 5, 8, 9, 12, 13, 14, 15, 16, 81]:
            assert txs[i]['dip2'] == SPEC_TX_NAMES[PSTxTypes.DENOMINATE]
        for i in range(18, 36):
            assert txs[i]['dip2'] == SPEC_TX_NAMES[PSTxTypes.DENOMINATE]
        for i in range(37, 49):
            assert txs[i]['dip2'] == SPEC_TX_NAMES[PSTxTypes.DENOMINATE]
        for i in range(52, 64):
            assert txs[i]['dip2'] == SPEC_TX_NAMES[PSTxTypes.DENOMINATE]
        for i in range(65, 80):
            assert txs[i]['dip2'] == SPEC_TX_NAMES[PSTxTypes.DENOMINATE]
        for i in [17, 36, 49, 50, 64, 80]:
            assert txs[i]['dip2'] == SPEC_TX_NAMES[PSTxTypes.PAY_COLLATERAL]
        for i in [82]:
            assert txs[i]['dip2'] == SPEC_TX_NAMES[PSTxTypes.PRIVATESEND]

        group0 = txs[81]['group_data']
        group1 = txs[86]['group_data']
        assert group0[0] == group0_val
        assert group0[1] == group0_balance
        assert len(group0[2]) == group0_txs_cnt
        assert group1[0] == group1_val
        assert group1[1] == group1_balance
        assert len(group1[2]) == group1_txs_cnt
        assert group1[2] == group1_txs

        for i, tx in enumerate(txs):
            if i not in [81, 86]:
                assert txs[i]['group_data'] == []
            if i in [0, 81, 82, 86, 87]:
                assert not txs[i]['group_txid']
            if i in range(1, 81):
                assert txs[i]['group_txid'] == txs[81]['txid']
            if i in range(83, 86):
                assert txs[i]['group_txid'] == txs[86]['txid']

    def test_ps_get_utxos_all(self):
        psman = self.wallet.psman
        coro = psman.find_untracked_ps_txs(log=False)
        asyncio.get_event_loop().run_until_complete(coro)
        ps_denoms = self.wallet.db.get_ps_denoms()
        for utxo in self.wallet.get_utxos():
            prev_h = utxo['prevout_hash']
            prev_n = utxo['prevout_n']
            ps_rounds = utxo['ps_rounds']
            ps_denom = ps_denoms.get(f'{prev_h}:{prev_n}')
            if ps_denom:
                assert ps_rounds == ps_denom[2]
            else:
                assert ps_rounds is None

    def test_get_balance(self):
        wallet = self.wallet
        psman = wallet.psman
        assert wallet.get_balance() == (1484831773, 0, 0)
        assert wallet.get_balance(include_ps=False) == (1484831773, 0, 0)
        assert wallet.get_balance(include_ps=False, min_rounds=5) == (0, 0, 0)
        assert wallet.get_balance(include_ps=False, min_rounds=4) == (0, 0, 0)
        assert wallet.get_balance(include_ps=False, min_rounds=3) == (0, 0, 0)
        assert wallet.get_balance(include_ps=False, min_rounds=2) == (0, 0, 0)
        assert wallet.get_balance(include_ps=False, min_rounds=1) == (0, 0, 0)
        assert wallet.get_balance(include_ps=False, min_rounds=0) == (0, 0, 0)

        coro = psman.find_untracked_ps_txs(log=False)
        asyncio.get_event_loop().run_until_complete(coro)
        assert wallet.get_balance() == (1484831773, 0, 0)
        assert wallet.get_balance(include_ps=False) == (984806773, 0, 0)
        assert wallet.get_balance(include_ps=False, min_rounds=5) == (0, 0, 0)
        assert wallet.get_balance(include_ps=False, min_rounds=4) == (0, 0, 0)
        assert wallet.get_balance(include_ps=False, min_rounds=3) == (0, 0, 0)
        assert wallet.get_balance(include_ps=False, min_rounds=2) == \
            (384803848, 0, 0)
        assert wallet.get_balance(include_ps=False, min_rounds=1) == \
            (384903849, 0, 0)
        assert wallet.get_balance(include_ps=False, min_rounds=0) == \
            (500005000, 0, 0)

        # check balance with ps_other
        w = wallet
        coins = w.get_spendable_coins(domain=None, config=self.config)
        denom_addr = list(w.db.get_ps_denoms().values())[0][0]
        outputs = [TxOutput(TYPE_ADDRESS, denom_addr, 300000)]
        tx = w.make_unsigned_transaction(coins, outputs, config=self.config)
        w.sign_transaction(tx, None)
        txid = tx.txid()
        w.add_transaction(txid, tx)
        w.db.add_islock(txid)

        # check when transaction is standard
        assert wallet.get_balance() == (1484831547, 0, 0)
        assert wallet.get_balance(include_ps=False) == (984506547, 0, 0)
        assert wallet.get_balance(include_ps=False, min_rounds=5) == (0, 0, 0)
        assert wallet.get_balance(include_ps=False, min_rounds=4) == (0, 0, 0)
        assert wallet.get_balance(include_ps=False, min_rounds=3) == (0, 0, 0)
        assert wallet.get_balance(include_ps=False, min_rounds=2) == \
            (384803848, 0, 0)
        assert wallet.get_balance(include_ps=False, min_rounds=1) == \
            (384903849, 0, 0)
        assert wallet.get_balance(include_ps=False, min_rounds=0) == \
            (500005000, 0, 0)

        coro = psman.find_untracked_ps_txs(log=True)
        asyncio.get_event_loop().run_until_complete(coro)

        # check when transaction is other ps coins
        assert wallet.get_balance() == (1484831547, 0, 0)
        assert wallet.get_balance(include_ps=False) == (984506547, 0, 0)
        assert wallet.get_balance(include_ps=False, min_rounds=5) == (0, 0, 0)
        assert wallet.get_balance(include_ps=False, min_rounds=4) == (0, 0, 0)
        assert wallet.get_balance(include_ps=False, min_rounds=3) == (0, 0, 0)
        assert wallet.get_balance(include_ps=False, min_rounds=2) == \
            (384803848, 0, 0)
        assert wallet.get_balance(include_ps=False, min_rounds=1) == \
            (384903849, 0, 0)
        assert wallet.get_balance(include_ps=False, min_rounds=0) == \
            (500005000, 0, 0)

    def test_get_ps_addresses(self):
        C_RNDS = PSCoinRounds.COLLATERAL
        assert self.wallet.db.get_ps_addresses() == set()
        psman = self.wallet.psman
        coro = psman.find_untracked_ps_txs(log=False)
        asyncio.get_event_loop().run_until_complete(coro)
        assert len(self.wallet.db.get_ps_addresses()) == 317
        assert len(self.wallet.db.get_ps_addresses(min_rounds=C_RNDS)) == 317
        assert len(self.wallet.db.get_ps_addresses(min_rounds=0)) == 131
        assert len(self.wallet.db.get_ps_addresses(min_rounds=1)) == 78
        assert len(self.wallet.db.get_ps_addresses(min_rounds=2)) == 77
        assert len(self.wallet.db.get_ps_addresses(min_rounds=3)) == 0

    def test_get_spendable_coins(self):
        C_RNDS = PSCoinRounds.COLLATERAL
        psman = self.wallet.psman
        coro = psman.find_untracked_ps_txs(log=False)
        asyncio.get_event_loop().run_until_complete(coro)
        conf = self.config
        coins = self.wallet.get_spendable_coins(None, conf)
        assert len(coins) == 6
        for c in coins:
            assert c['ps_rounds'] is None

        coins = self.wallet.get_spendable_coins(None, conf, include_ps=True)
        assert len(coins) == 138
        rounds = defaultdict(int)
        for c in coins:
            rounds[c['ps_rounds']] += 1
        assert rounds[None] == 6
        assert rounds[C_RNDS] == 1
        assert rounds[0] == 53
        assert rounds[1] == 1
        assert rounds[2] == 77
        assert rounds[3] == 0

        coins = self.wallet.get_spendable_coins(None, conf, min_rounds=C_RNDS)
        assert len(coins) == 132
        rounds = defaultdict(int)
        for c in coins:
            rounds[c['ps_rounds']] += 1
        assert rounds[C_RNDS] == 1
        assert rounds[0] == 53
        assert rounds[1] == 1
        assert rounds[2] == 77
        assert rounds[3] == 0

        coins = self.wallet.get_spendable_coins(None, conf, min_rounds=0)
        assert len(coins) == 131
        rounds = defaultdict(int)
        for c in coins:
            rounds[c['ps_rounds']] += 1
        assert None not in rounds
        assert rounds[0] == 53
        assert rounds[1] == 1
        assert rounds[2] == 77
        assert rounds[3] == 0

        coins = self.wallet.get_spendable_coins(None, conf, min_rounds=1)
        assert len(coins) == 78
        rounds = defaultdict(int)
        for c in coins:
            rounds[c['ps_rounds']] += 1
        assert None not in rounds
        assert 0 not in rounds
        assert rounds[1] == 1
        assert rounds[2] == 77
        assert rounds[3] == 0

        coins = self.wallet.get_spendable_coins(None, conf, min_rounds=2)
        assert len(coins) == 77
        rounds = defaultdict(int)
        for c in coins:
            rounds[c['ps_rounds']] += 1
        assert None not in rounds
        assert 0 not in rounds
        assert 1 not in rounds
        assert rounds[2] == 77
        assert rounds[3] == 0

        coins = self.wallet.get_spendable_coins(None, conf, min_rounds=3)
        assert len(coins) == 0

    def test_get_spendable_coins_allow_others(self):
        w = self.wallet
        psman = w.psman
        psman.config = config = self.config
        coro = psman.find_untracked_ps_txs(log=False)
        asyncio.get_event_loop().run_until_complete(coro)

        # add other coins
        coins = w.get_spendable_coins(domain=None, config=config)
        denom_addr = list(w.db.get_ps_denoms().values())[0][0]
        outputs = [TxOutput(TYPE_ADDRESS, denom_addr, 300000)]
        tx = w.make_unsigned_transaction(coins, outputs, config=config)
        w.sign_transaction(tx, None)
        txid = tx.txid()
        w.add_transaction(txid, tx)
        w.db.add_islock(txid)
        coro = psman.find_untracked_ps_txs(log=True)
        asyncio.get_event_loop().run_until_complete(coro)

        assert not psman.allow_others
        coins = w.get_spendable_coins(domain=None, include_ps=True,
                                      config=config)
        cset = set([c['ps_rounds'] for c in coins])
        assert cset == {None, 0, 1, 2, PSCoinRounds.COLLATERAL}
        assert len(coins) == 138

        psman.allow_others = True
        coins = w.get_spendable_coins(domain=None, include_ps=True,
                                      config=config)
        cset = set([c['ps_rounds'] for c in coins])
        assert cset == {None, 0, 1, 2,
                        PSCoinRounds.COLLATERAL, PSCoinRounds.OTHER}
        assert len(coins) == 139

    def test_get_utxos(self):
        C_RNDS = PSCoinRounds.COLLATERAL
        psman = self.wallet.psman
        coro = psman.find_untracked_ps_txs(log=False)
        asyncio.get_event_loop().run_until_complete(coro)
        coins = self.wallet.get_utxos()
        assert len(coins) == 6
        for c in coins:
            assert c['ps_rounds'] is None

        coins = self.wallet.get_utxos(include_ps=True)
        assert len(coins) == 138
        rounds = defaultdict(int)
        for c in coins:
            rounds[c['ps_rounds']] += 1
        assert rounds[None] == 6
        assert rounds[C_RNDS] == 1
        assert rounds[0] == 53
        assert rounds[1] == 1
        assert rounds[2] == 77
        assert rounds[3] == 0
        assert rounds[4] == 0

        coins = self.wallet.get_utxos(min_rounds=C_RNDS)
        assert len(coins) == 132
        rounds = defaultdict(int)
        for c in coins:
            rounds[c['ps_rounds']] += 1
        assert rounds[C_RNDS] == 1
        assert rounds[0] == 53
        assert rounds[1] == 1
        assert rounds[2] == 77
        assert rounds[3] == 0
        assert rounds[4] == 0

        coins = self.wallet.get_utxos(min_rounds=0)
        assert len(coins) == 131
        rounds = defaultdict(int)
        for c in coins:
            rounds[c['ps_rounds']] += 1
        assert None not in rounds
        assert rounds[0] == 53
        assert rounds[1] == 1
        assert rounds[2] == 77
        assert rounds[3] == 0

        coins = self.wallet.get_utxos(min_rounds=1)
        assert len(coins) == 78
        rounds = defaultdict(int)
        for c in coins:
            rounds[c['ps_rounds']] += 1
        assert None not in rounds
        assert 0 not in rounds
        assert rounds[1] == 1
        assert rounds[2] == 77
        assert rounds[3] == 0

        coins = self.wallet.get_utxos(min_rounds=2)
        assert len(coins) == 77
        rounds = defaultdict(int)
        for c in coins:
            rounds[c['ps_rounds']] += 1
        assert None not in rounds
        assert 0 not in rounds
        assert 1 not in rounds
        assert rounds[2] == 77
        assert rounds[3] == 0

        coins = self.wallet.get_utxos(min_rounds=3)
        assert len(coins) == 0

    def test_keep_amount(self):
        psman = self.wallet.psman
        assert psman.keep_amount == axe_ps.DEFAULT_KEEP_AMOUNT

        psman.keep_amount = psman.min_keep_amount - 0.1
        assert psman.keep_amount == psman.min_keep_amount

        psman.keep_amount = psman.max_keep_amount + 0.1
        assert psman.keep_amount == psman.max_keep_amount

        psman.keep_amount = 5
        assert psman.keep_amount == 5

        psman.state = PSStates.Mixing
        psman.keep_amount = 10
        assert psman.keep_amount == 5

    def test_mix_rounds(self):
        psman = self.wallet.psman
        assert psman.mix_rounds == axe_ps.DEFAULT_MIX_ROUNDS

        psman.mix_rounds = psman.min_mix_rounds - 1
        assert psman.mix_rounds == psman.min_mix_rounds

        psman.mix_rounds = psman.max_mix_rounds + 1
        assert psman.mix_rounds == psman.max_mix_rounds

        psman.mix_rounds = 3
        assert psman.mix_rounds == 3

        psman.state = PSStates.Mixing
        psman.mix_rounds = 4
        assert psman.mix_rounds == 3

    def test_check_min_rounds(self):
        C_RNDS = PSCoinRounds.COLLATERAL
        psman = self.wallet.psman
        coro = psman.find_untracked_ps_txs(log=False)
        asyncio.get_event_loop().run_until_complete(coro)
        coins = self.wallet.get_utxos()
        with self.assertRaises(PSMinRoundsCheckFailed):
            psman.check_min_rounds(coins, 0)

        coins = self.wallet.get_utxos(include_ps=True)
        with self.assertRaises(PSMinRoundsCheckFailed):
            psman.check_min_rounds(coins, 0)

        coins = self.wallet.get_utxos(min_rounds=C_RNDS)
        with self.assertRaises(PSMinRoundsCheckFailed):
            psman.check_min_rounds(coins, 0)

        coins = self.wallet.get_utxos(min_rounds=0)
        psman.check_min_rounds(coins, 0)

        coins = self.wallet.get_utxos(min_rounds=1)
        psman.check_min_rounds(coins, 1)

        coins = self.wallet.get_utxos(min_rounds=2)
        psman.check_min_rounds(coins, 2)

    def test_mixing_progress(self):
        psman = self.wallet.psman
        psman.mix_rounds = 2
        assert psman.mixing_progress() == 0
        coro = psman.find_untracked_ps_txs(log=False)
        asyncio.get_event_loop().run_until_complete(coro)
        assert psman.mixing_progress() == 77
        psman.mix_rounds = 3
        assert psman.mixing_progress() == 51
        psman.mix_rounds = 4
        assert psman.mixing_progress() == 38
        psman.mix_rounds = 5
        assert psman.mixing_progress() == 31

    def test_get_addresses(self):
        C_RNDS = PSCoinRounds.COLLATERAL
        psman = self.wallet.psman
        coro = psman.find_untracked_ps_txs(log=False)
        asyncio.get_event_loop().run_until_complete(coro)
        res0 = psman.get_addresses(include_ps=False, min_rounds=None)
        res1 = psman.get_addresses(include_ps=True, min_rounds=None)
        res2 = psman.get_addresses(include_ps=False, min_rounds=C_RNDS)
        res3 = psman.get_addresses(include_ps=False, min_rounds=0)
        res4 = psman.get_addresses(include_ps=False, min_rounds=1)
        res5 = psman.get_addresses(include_ps=False, min_rounds=2)
        assert len(res0) == 39
        assert res0[0] == 'yPuNCffL88i76SDFZ8crBmUG2PFsysFSvx'
        assert res0[-1] == 'yekcQi63u3KpLp1EGkR4XGwnzr9nAcQ9kQ'
        assert len(res1) == 356
        assert res1[0] == 'yPuNCffL88i76SDFZ8crBmUG2PFsysFSvx'
        assert res1[-1] == 'yekcQi63u3KpLp1EGkR4XGwnzr9nAcQ9kQ'
        assert len(res2) == 317
        assert res2[0] == 'yYP1BSuy4KoVNcCyS9q9tErmh5w3ca9bkM'
        assert res2[-1] == 'yiozDzgTrjyXqie28y7z2YEmjaYUZ7gveQ'
        assert len(res3) == 131
        assert res3[0] == 'yVGq4RmapFnbVJMTT1fpjG9Cd4MKREvEwh'
        assert res3[-1] == 'yV3whZTyTGHZrC9Pwhwm9YMPJEcKw5WUbd'
        assert len(res4) == 78
        assert res4[0] == 'yVGq4RmapFnbVJMTT1fpjG9Cd4MKREvEwh'
        assert res4[-1] == 'yZM9RfqU6JGt6sBNcPz4L6H9kAwocVkd4d'
        assert len(res5) == 77
        assert res5[0] == 'yVGq4RmapFnbVJMTT1fpjG9Cd4MKREvEwh'
        assert res5[-1] == 'yfTYCW57LBXVSb7sgETNTRWPvvvfsDBTyE'

        res0 = psman.get_addresses(include_ps=False, min_rounds=None,
                                   for_change=True)
        res1 = psman.get_addresses(include_ps=True, min_rounds=None,
                                   for_change=True)
        res2 = psman.get_addresses(include_ps=False, min_rounds=C_RNDS,
                                   for_change=True)
        res3 = psman.get_addresses(include_ps=False, min_rounds=0,
                                   for_change=True)
        res4 = psman.get_addresses(include_ps=False, min_rounds=1,
                                   for_change=True)
        res5 = psman.get_addresses(include_ps=False, min_rounds=2,
                                   for_change=True)
        assert len(res0) == 18
        assert res0[0] == 'yRUktd39y5aU3JCgvZSx2NVfwPnv5nB2PF'
        assert res0[-1] == 'yekcQi63u3KpLp1EGkR4XGwnzr9nAcQ9kQ'
        assert len(res1) == 23
        assert res1[0] == 'yRUktd39y5aU3JCgvZSx2NVfwPnv5nB2PF'
        assert res1[-1] == 'yekcQi63u3KpLp1EGkR4XGwnzr9nAcQ9kQ'
        assert len(res2) == 5
        assert res2[0] == 'yaLt5itjqxehBSQW9ksasvEFRaqZtXkbUU'
        assert res2[-1] == 'yiozDzgTrjyXqie28y7z2YEmjaYUZ7gveQ'
        assert len(res3) == 0
        assert len(res4) == 0
        assert len(res5) == 0

        res0 = psman.get_addresses(include_ps=False, min_rounds=None,
                                   for_change=False)
        res1 = psman.get_addresses(include_ps=True, min_rounds=None,
                                   for_change=False)
        res2 = psman.get_addresses(include_ps=False, min_rounds=C_RNDS,
                                   for_change=False)
        res3 = psman.get_addresses(include_ps=False, min_rounds=0,
                                   for_change=False)
        res4 = psman.get_addresses(include_ps=False, min_rounds=1,
                                   for_change=False)
        res5 = psman.get_addresses(include_ps=False, min_rounds=2,
                                   for_change=False)
        assert len(res0) == 21
        assert res0[0] == 'yPuNCffL88i76SDFZ8crBmUG2PFsysFSvx'
        assert res0[-1] == 'yjCtWrfyCSeE5fDqmrmoMzXerMxsWpySkS'
        assert len(res1) == 333
        assert res1[0] == 'yPuNCffL88i76SDFZ8crBmUG2PFsysFSvx'
        assert res1[-1] == 'yjCtWrfyCSeE5fDqmrmoMzXerMxsWpySkS'
        assert len(res2) == 312
        assert res2[0] == 'yYP1BSuy4KoVNcCyS9q9tErmh5w3ca9bkM'
        assert res2[-1] == 'yV3whZTyTGHZrC9Pwhwm9YMPJEcKw5WUbd'
        assert len(res3) == 131
        assert res3[0] == 'yVGq4RmapFnbVJMTT1fpjG9Cd4MKREvEwh'
        assert res3[-1] == 'yV3whZTyTGHZrC9Pwhwm9YMPJEcKw5WUbd'
        assert len(res4) == 78
        assert res4[0] == 'yVGq4RmapFnbVJMTT1fpjG9Cd4MKREvEwh'
        assert res4[-1] == 'yZM9RfqU6JGt6sBNcPz4L6H9kAwocVkd4d'
        assert len(res5) == 77
        assert res5[0] == 'yVGq4RmapFnbVJMTT1fpjG9Cd4MKREvEwh'
        assert res5[-1] == 'yfTYCW57LBXVSb7sgETNTRWPvvvfsDBTyE'

    def test_get_change_addresses_for_new_transaction(self):
        w = self.wallet
        psman = w.psman
        coro = psman.find_untracked_ps_txs(log=False)
        asyncio.get_event_loop().run_until_complete(coro)
        unused1 = w.calc_unused_change_addresses()
        assert len(unused1) == 13
        for addr in unused1:
            psman.add_ps_reserved(addr, 'test')
        unused2 = w.calc_unused_change_addresses()
        assert len(unused2) == 0
        for i in range(100):
            addrs = w.get_change_addresses_for_new_transaction()
            for addr in addrs:
                assert addr not in unused1

    def test_synchronize_sequence(self):
        w = self.wallet
        psman = w.psman
        coro = psman.find_untracked_ps_txs(log=False)
        asyncio.get_event_loop().run_until_complete(coro)
        unused1 = w.get_unused_addresses()
        assert len(unused1) == 20

        w.synchronize_sequence(for_change=False)

        unused1 = w.get_unused_addresses()
        assert len(unused1) == 20
        for addr in unused1:
            psman.add_ps_reserved(addr, 'test')
        unused2 = w.get_unused_addresses()
        assert len(unused2) == 0

        w.synchronize_sequence(for_change=False)
        unused2 = w.get_unused_addresses()
        assert len(unused2) == 0

    def test_synchronize_sequence_for_change(self):
        w = self.wallet
        psman = w.psman
        coro = psman.find_untracked_ps_txs(log=False)
        asyncio.get_event_loop().run_until_complete(coro)
        unused1 = w.calc_unused_change_addresses()
        assert len(unused1) == 13

        w.synchronize_sequence(for_change=True)

        unused1 = w.calc_unused_change_addresses()
        assert len(unused1) == 13
        for addr in unused1:
            psman.add_ps_reserved(addr, 'test')
        unused2 = w.calc_unused_change_addresses()
        assert len(unused2) == 0

        w.synchronize_sequence(for_change=True)
        unused2 = w.calc_unused_change_addresses()
        assert len(unused2) == 0

    def test_reserve_addresses(self):
        w = self.wallet
        psman = w.psman
        get_addrs = psman.get_addresses
        coro = psman.find_untracked_ps_txs(log=False)
        asyncio.get_event_loop().run_until_complete(coro)

        assert len(get_addrs(for_change=False)) == 21
        assert len(get_addrs(include_ps=True, for_change=False)) == 333
        assert len(get_addrs(for_change=True)) == 18
        assert len(get_addrs(include_ps=True, for_change=True)) == 23
        unused_change = w.calc_unused_change_addresses()
        assert len(unused_change) == 13
        unused = w.get_unused_addresses()
        assert len(unused) == 20

        res1 = psman.reserve_addresses(10)
        assert len(res1) == 10
        res2 = psman.reserve_addresses(1, for_change=True, data='coll')
        assert len(res2) == 1
        sel1 = w.db.select_ps_reserved()
        sel2 = w.db.select_ps_reserved(for_change=True, data='coll')
        assert res1 == sel1
        assert res2 == sel2
        unused = w.get_unused_addresses()
        for a in sel1:
            assert a not in unused
        assert len(unused) == 10
        unused_change = w.calc_unused_change_addresses()
        for a in sel2:
            assert a not in unused_change
        assert len(unused_change) == 12

        assert len(get_addrs(for_change=False)) == 11
        assert len(get_addrs(include_ps=True, for_change=False)) == 333
        assert len(get_addrs(for_change=True)) == 17
        assert len(get_addrs(include_ps=True, for_change=True)) == 23

    def test_first_unused_index(self):
        w = self.wallet
        psman = w.psman

        assert psman.first_unused_index() == 313
        assert psman.first_unused_index(for_change=True) == 7

        assert w.db.num_receiving_addresses() == 333
        assert w.db.num_change_addresses() == 23
        assert len(w.get_unused_addresses()) == 20
        assert len(w.calc_unused_change_addresses()) == 13

        psman.reserve_addresses(20)
        psman.reserve_addresses(13, for_change=True)

        assert psman.first_unused_index() == 333
        assert psman.first_unused_index(for_change=True) == 23

        assert w.db.num_receiving_addresses() == 333
        assert w.db.num_change_addresses() == 23
        assert len(w.get_unused_addresses()) == 0
        assert len(w.calc_unused_change_addresses()) == 0

    def test_add_ps_collateral(self):
        w = self.wallet
        outpoint0 = '0'*64 + ':0'
        collateral0 = (w.dummy_address(), 10000)
        outpoint1 = '1'*64 + ':1'
        collateral1 = (w.dummy_address(), 40000)
        w.db.add_ps_collateral(outpoint0, collateral0)
        assert set(w.db.ps_collaterals.keys()) == {outpoint0}
        assert w.db.ps_collaterals[outpoint0] == collateral0
        w.db.add_ps_collateral(outpoint1, collateral1)
        assert set(w.db.ps_collaterals.keys()) == {outpoint0, outpoint1}
        assert w.db.ps_collaterals[outpoint1] == collateral1

    def test_pop_ps_collateral(self):
        w = self.wallet
        outpoint0 = '0'*64 + ':0'
        collateral0 = (w.dummy_address(), 10000)
        outpoint1 = '1'*64 + ':1'
        collateral1 = (w.dummy_address(), 40000)
        w.db.add_ps_collateral(outpoint0, collateral0)
        w.db.add_ps_collateral(outpoint1, collateral1)
        w.db.pop_ps_collateral(outpoint1)
        assert set(w.db.ps_collaterals.keys()) == {outpoint0}
        assert w.db.ps_collaterals[outpoint0] == collateral0
        w.db.pop_ps_collateral(outpoint0)
        assert set(w.db.ps_collaterals.keys()) == set()

    def test_get_ps_collateral(self):
        w = self.wallet
        psman = w.psman
        outpoint0 = '0'*64 + ':0'
        collateral0 = (w.dummy_address(), 10000)
        outpoint1 = '1'*64 + ':1'
        collateral1 = (w.dummy_address(), 40000)

        w.db.add_ps_collateral(outpoint0, collateral0)
        c_outpoint, ps_collateral = w.db.get_ps_collateral()
        assert psman.ps_collateral_cnt
        assert c_outpoint == outpoint0
        assert ps_collateral == collateral0

        w.db.add_ps_collateral(outpoint1, collateral1)
        assert psman.ps_collateral_cnt == 2
        with self.assertRaises(Exception):  # multiple values
            assert w.db.get_ps_collateral()

        assert w.db.get_ps_collateral(outpoint0) == collateral0
        assert w.db.get_ps_collateral(outpoint1) == collateral1

        w.db.pop_ps_collateral(outpoint0)
        w.db.pop_ps_collateral(outpoint1)
        c_outpoint, ps_collateral = w.db.get_ps_collateral()
        assert not psman.ps_collateral_cnt
        assert c_outpoint is None
        assert ps_collateral is None

    def test_add_ps_denom(self):
        w = self.wallet
        psman = w.psman
        outpoint = '0'*64 + ':0'
        denom = (w.dummy_address(), 100001, 0)
        assert w.db.ps_denoms == {}
        assert psman._ps_denoms_amount_cache == 0
        psman.add_ps_denom(outpoint, denom)
        assert w.db.ps_denoms == {outpoint: denom}
        assert psman._ps_denoms_amount_cache == 100001

    def test_pop_ps_denom(self):
        w = self.wallet
        psman = w.psman
        outpoint1 = '0'*64 + ':0'
        outpoint2 = '1'*64 + ':0'
        denom1 = (w.dummy_address(), 100001, 0)
        denom2 = (w.dummy_address(), 1000010, 0)
        assert w.db.ps_denoms == {}
        assert psman._ps_denoms_amount_cache == 0
        psman.add_ps_denom(outpoint1, denom1)
        psman.add_ps_denom(outpoint2, denom2)
        assert w.db.ps_denoms == {outpoint1: denom1, outpoint2: denom2}
        assert psman._ps_denoms_amount_cache == 1100011
        assert denom2 == psman.pop_ps_denom(outpoint2)
        assert w.db.ps_denoms == {outpoint1: denom1}
        assert psman._ps_denoms_amount_cache == 100001
        assert denom1 == psman.pop_ps_denom(outpoint1)
        assert w.db.ps_denoms == {}
        assert psman._ps_denoms_amount_cache == 0

    def test_denoms_to_mix_cache(self):
        w = self.wallet
        psman = w.psman
        psman.mix_rounds = 2
        outpoint1 = 'outpoint1'
        outpoint2 = 'outpoint2'
        outpoint3 = 'outpoint3'
        outpoint4 = 'outpoint4'
        denom1 = ('addr1', 100001, 0)
        denom2 = ('addr2', 100001, 1)
        denom3 = ('addr3', 100001, 1)
        denom4 = ('addr4', 100001, 2)

        assert psman._denoms_to_mix_cache == {}
        psman.add_ps_denom(outpoint1, denom1)
        psman.add_ps_denom(outpoint2, denom2)
        psman.add_ps_denom(outpoint3, denom3)
        psman.add_ps_denom(outpoint4, denom4)

        assert len(psman._denoms_to_mix_cache) == 3
        psman.add_ps_spending_denom(outpoint1, 'uuid')
        assert len(psman._denoms_to_mix_cache) == 2
        psman.add_ps_spending_denom(outpoint2, 'uuid')
        assert len(psman._denoms_to_mix_cache) == 1
        psman.mix_rounds = 3
        assert len(psman._denoms_to_mix_cache) == 2

        psman.pop_ps_denom(outpoint1)
        assert len(psman._denoms_to_mix_cache) == 2
        psman.pop_ps_spending_denom(outpoint1)
        assert len(psman._denoms_to_mix_cache) == 2
        psman.pop_ps_spending_denom(outpoint2)
        assert len(psman._denoms_to_mix_cache) == 3

        psman.pop_ps_denom(outpoint1)
        psman.pop_ps_denom(outpoint2)
        psman.pop_ps_denom(outpoint3)
        psman.pop_ps_denom(outpoint4)

        psman.mix_rounds = 2
        coro = psman.find_untracked_ps_txs(log=False)
        asyncio.get_event_loop().run_until_complete(coro)
        denoms = psman._denoms_to_mix_cache
        assert len(denoms) == 54
        for outpoint, denom in denoms.items():
            assert denom[2] < psman.mix_rounds

        psman.mix_rounds = 3
        denoms = psman._denoms_to_mix_cache
        assert len(denoms) == 131
        for outpoint, denom in denoms.items():
            assert denom[2] < psman.mix_rounds

    def test_denoms_to_mix(self):
        w = self.wallet
        psman = w.psman
        psman.mix_rounds = 2
        outpoint1 = 'outpoint1'
        outpoint2 = 'outpoint2'
        outpoint3 = 'outpoint3'
        outpoint4 = 'outpoint4'
        denom1 = ('addr1', 100001, 0)
        denom2 = ('addr2', 100001, 1)
        denom3 = ('addr3', 100001, 1)
        denom4 = ('addr4', 100001, 2)

        assert psman.denoms_to_mix() == {}
        psman.add_ps_denom(outpoint1, denom1)
        psman.add_ps_denom(outpoint2, denom2)
        psman.add_ps_denom(outpoint3, denom3)
        psman.add_ps_denom(outpoint4, denom4)

        assert len(psman.denoms_to_mix(mix_rounds=0)) == 1
        assert len(psman.denoms_to_mix(mix_rounds=1)) == 2
        assert len(psman.denoms_to_mix(mix_rounds=2)) == 1
        assert len(psman.denoms_to_mix(mix_rounds=3)) == 0

        assert len(psman.denoms_to_mix(mix_rounds=1, denom_value=100001)) == 2
        assert len(psman.denoms_to_mix(mix_rounds=1, denom_value=1000010)) == 0

        assert len(psman.denoms_to_mix()) == 3
        psman.add_ps_spending_denom(outpoint1, 'uuid')
        assert len(psman.denoms_to_mix()) == 2
        psman.add_ps_spending_denom(outpoint2, 'uuid')
        assert len(psman.denoms_to_mix()) == 1
        psman.mix_rounds = 3
        assert len(psman.denoms_to_mix()) == 2

        psman.pop_ps_denom(outpoint1)
        assert len(psman.denoms_to_mix()) == 2
        psman.pop_ps_spending_denom(outpoint1)
        assert len(psman.denoms_to_mix()) == 2
        psman.pop_ps_spending_denom(outpoint2)
        assert len(psman.denoms_to_mix()) == 3

        psman.pop_ps_denom(outpoint1)
        psman.pop_ps_denom(outpoint2)
        psman.pop_ps_denom(outpoint3)
        psman.pop_ps_denom(outpoint4)

        psman.mix_rounds = 2
        coro = psman.find_untracked_ps_txs(log=False)
        asyncio.get_event_loop().run_until_complete(coro)
        denoms = psman.denoms_to_mix()
        assert len(denoms) == 54
        for outpoint, denom in denoms.items():
            assert denom[2] < psman.mix_rounds

        psman.mix_rounds = 3
        denoms = psman.denoms_to_mix()
        assert len(denoms) == 131
        for outpoint, denom in denoms.items():
            assert denom[2] < psman.mix_rounds

    def _prepare_workflow(self):
        uuid = 'uuid'
        raw_tx = '02000000000000000000'
        tx_type = PSTxTypes.NEW_DENOMS
        txid1 = '1'*64
        txid2 = '2'*64
        txid3 = '3'*64
        workflow = PSTxWorkflow(uuid=uuid)
        workflow.add_tx(txid=txid1, tx_type=tx_type, raw_tx=raw_tx)
        workflow.add_tx(txid=txid2, tx_type=tx_type, raw_tx=raw_tx)
        workflow.add_tx(txid=txid3, tx_type=tx_type, raw_tx=raw_tx)
        workflow.completed = True
        return workflow

    def test_pay_collateral_wfl(self):
        psman = self.wallet.psman
        assert psman.pay_collateral_wfl is None
        workflow = self._prepare_workflow()
        psman.set_pay_collateral_wfl(workflow)
        workflow2 = psman.pay_collateral_wfl
        assert id(workflow2) != id(workflow)
        assert workflow2 == workflow
        workflow2 = psman.clear_pay_collateral_wfl()
        assert psman.pay_collateral_wfl is None

    def test_new_collateral_wfl(self):
        psman = self.wallet.psman
        assert psman.new_collateral_wfl is None
        workflow = self._prepare_workflow()
        psman.set_new_collateral_wfl(workflow)
        workflow2 = psman.new_collateral_wfl
        assert id(workflow2) != id(workflow)
        assert workflow2 == workflow
        workflow2 = psman.clear_new_collateral_wfl()
        assert psman.new_collateral_wfl is None

    def test_new_denoms_wfl(self):
        psman = self.wallet.psman
        assert psman.new_denoms_wfl is None
        workflow = self._prepare_workflow()
        psman.set_new_denoms_wfl(workflow)
        workflow2 = psman.new_denoms_wfl
        assert id(workflow2) != id(workflow)
        assert workflow2 == workflow
        workflow2 = psman.clear_new_denoms_wfl()
        assert psman.new_denoms_wfl is None

    def test_denominate_wfl(self):
        uuid1 = 'uuid1'
        uuid2 = 'uuid2'
        outpoint1 = 'outpoint1'
        addr1 = 'addr1'
        psman = self.wallet.psman
        assert psman.denominate_wfl_list == []
        wfl1 = PSDenominateWorkflow(uuid=uuid1)
        wfl2 = PSDenominateWorkflow(uuid=uuid2)
        psman.set_denominate_wfl(wfl1)
        assert set(psman.denominate_wfl_list) == set([uuid1])
        wfl1.denom = 4
        wfl1.rounds = 1
        wfl1.inputs.append(outpoint1)
        wfl1.outputs.append(addr1)
        psman.set_denominate_wfl(wfl1)
        assert set(psman.denominate_wfl_list) == set([uuid1])
        psman.set_denominate_wfl(wfl2)
        assert set(psman.denominate_wfl_list) == set([uuid1, uuid2])

        dwfl_ps_data = self.wallet.db.get_ps_data('denominate_workflows')
        assert dwfl_ps_data[uuid1] == (4, 1, [outpoint1], [addr1], 0)
        assert dwfl_ps_data[uuid2] == (0, 0, [], [], 0)

        wfl1_get = psman.get_denominate_wfl(uuid1)
        assert wfl1_get == wfl1
        wfl2_get = psman.get_denominate_wfl(uuid2)
        assert wfl2_get == wfl2
        assert set(psman.denominate_wfl_list) == set([uuid1, uuid2])

        psman.clear_denominate_wfl(uuid1)
        assert set(psman.denominate_wfl_list) == set([uuid2])
        assert psman.get_denominate_wfl(uuid1) is None
        wfl2_get = psman.get_denominate_wfl(uuid2)
        assert wfl2_get == wfl2
        dwfl_ps_data = self.wallet.db.get_ps_data('denominate_workflows')
        assert dwfl_ps_data[uuid2] == (0, 0, [], [], 0)
        assert uuid1 not in dwfl_ps_data

        psman.clear_denominate_wfl(uuid2)
        assert psman.denominate_wfl_list == []
        assert psman.get_denominate_wfl(uuid1) is None
        assert psman.get_denominate_wfl(uuid2) is None

        dwfl_ps_data = self.wallet.db.get_ps_data('denominate_workflows')
        assert dwfl_ps_data == {}

    def test_spending_collaterals(self):
        uuid1 = 'uuid1'
        uuid2 = 'uuid2'
        outpoint1 = 'outpoint1'
        outpoint2 = 'outpoint2'
        w = self.wallet
        psman = w.psman
        assert w.db.get_ps_spending_collaterals() == {}
        psman.add_ps_spending_collateral(outpoint1, uuid1)
        assert len(w.db.get_ps_spending_collaterals()) == 1
        assert w.db.get_ps_spending_collateral(outpoint1) == uuid1
        psman.add_ps_spending_collateral(outpoint2, uuid2)
        assert len(w.db.get_ps_spending_collaterals()) == 2
        assert w.db.get_ps_spending_collateral(outpoint2) == uuid2
        assert w.db.get_ps_spending_collateral(outpoint1) == uuid1

        assert psman.pop_ps_spending_collateral(outpoint1) == uuid1
        assert len(w.db.get_ps_spending_collaterals()) == 1
        assert w.db.get_ps_spending_collateral(outpoint2) == uuid2
        assert psman.pop_ps_spending_collateral(outpoint2) == uuid2
        assert w.db.get_ps_spending_collaterals() == {}

    def test_spending_denoms(self):
        uuid1 = 'uuid1'
        uuid2 = 'uuid2'
        outpoint1 = 'outpoint1'
        outpoint2 = 'outpoint2'
        w = self.wallet
        psman = w.psman
        assert w.db.get_ps_spending_denoms() == {}
        psman.add_ps_spending_denom(outpoint1, uuid1)
        assert len(w.db.get_ps_spending_denoms()) == 1
        assert w.db.get_ps_spending_denom(outpoint1) == uuid1
        psman.add_ps_spending_denom(outpoint2, uuid2)
        assert len(w.db.get_ps_spending_denoms()) == 2
        assert w.db.get_ps_spending_denom(outpoint2) == uuid2
        assert w.db.get_ps_spending_denom(outpoint1) == uuid1

        assert psman.pop_ps_spending_denom(outpoint1) == uuid1
        assert len(w.db.get_ps_spending_denoms()) == 1
        assert w.db.get_ps_spending_denom(outpoint2) == uuid2
        assert psman.pop_ps_spending_denom(outpoint2) == uuid2
        assert w.db.get_ps_spending_denoms() == {}

    def test_prepare_pay_collateral_wfl(self):
        w = self.wallet
        psman = w.psman

        # check not created if no ps_collateral exists
        coro = psman.prepare_pay_collateral_wfl()
        asyncio.get_event_loop().run_until_complete(coro)
        assert not psman.pay_collateral_wfl

        coro = psman.find_untracked_ps_txs(log=False)
        asyncio.get_event_loop().run_until_complete(coro)
        # check not created if pay_collateral_wfl is not empty
        wfl = PSTxWorkflow(uuid='uuid')
        psman.set_pay_collateral_wfl(wfl)
        coro = psman.prepare_pay_collateral_wfl()
        asyncio.get_event_loop().run_until_complete(coro)
        assert psman.pay_collateral_wfl == wfl
        psman.clear_pay_collateral_wfl()

        # check not created if utxo not found
        c_outpoint, ps_collateral = w.db.get_ps_collateral()
        w.db.pop_ps_collateral(c_outpoint)
        outpoint0 = '0'*64 + ':0'
        collateral0 = (w.dummy_address(), 40000)
        w.db.add_ps_collateral(outpoint0, collateral0)
        coro = psman.prepare_pay_collateral_wfl()
        asyncio.get_event_loop().run_until_complete(coro)
        assert not psman.pay_collateral_wfl
        w.db.pop_ps_collateral(outpoint0)
        w.db.add_ps_collateral(c_outpoint, ps_collateral)

        # check created pay collateral tx
        coro = psman.prepare_pay_collateral_wfl()
        asyncio.get_event_loop().run_until_complete(coro)
        wfl = psman.pay_collateral_wfl
        assert wfl.completed
        assert len(wfl.tx_order) == 1
        txid = wfl.tx_order[0]
        tx_data = wfl.tx_data[txid]
        tx = Transaction(tx_data.raw_tx)
        assert txid == tx.txid()
        txins = tx.inputs()
        txouts = tx.outputs()
        assert len(txins) == 1
        assert len(txouts) == 1
        in0 = txins[0]
        c_outpoint, ps_collateral = w.db.get_ps_collateral()
        assert w.db.get_ps_spending_collateral(c_outpoint) == wfl.uuid
        in0_prev_h = in0['prevout_hash']
        in0_prev_n = in0['prevout_n']
        assert f'{in0_prev_h}:{in0_prev_n}' == c_outpoint
        assert txouts[0].value == COLLATERAL_VAL
        reserved = w.db.select_ps_reserved(for_change=True, data=c_outpoint)
        assert len(reserved) == 1
        assert txouts[0].address in reserved
        assert tx.locktime == 0
        assert txins[0]['sequence'] == 0xffffffff

    def test_cleanup_pay_collateral_wfl(self):
        w = self.wallet
        psman = w.psman

        # check if pay_collateral_wfl is empty
        assert not psman.pay_collateral_wfl
        coro = psman.cleanup_pay_collateral_wfl()
        asyncio.get_event_loop().run_until_complete(coro)
        assert not psman.pay_collateral_wfl

        # check no cleanup if completed and tx_order is not empty
        coro = psman.find_untracked_ps_txs(log=False)
        asyncio.get_event_loop().run_until_complete(coro)
        coro = psman.prepare_pay_collateral_wfl()
        asyncio.get_event_loop().run_until_complete(coro)
        coro = psman.cleanup_pay_collateral_wfl()
        asyncio.get_event_loop().run_until_complete(coro)
        assert psman.pay_collateral_wfl

        # check cleanup if not completed and tx_order is not empty
        wfl = psman.pay_collateral_wfl
        for outpoint, ps_collateral in w.db.get_ps_collaterals().items():
            pass
        reserved = w.db.select_ps_reserved(for_change=True, data=outpoint)
        assert len(reserved) == 1

        wfl.completed = False
        psman.set_pay_collateral_wfl(wfl)
        coro = psman.cleanup_pay_collateral_wfl()
        asyncio.get_event_loop().run_until_complete(coro)
        assert w.db.get_ps_spending_collaterals() == {}

        assert not psman.pay_collateral_wfl
        reserved = w.db.select_ps_reserved(for_change=True, data=outpoint)
        assert len(reserved) == 1
        reserved = w.db.select_ps_reserved(for_change=True)
        assert len(reserved) == 0
        assert not psman.pay_collateral_wfl

        # check cleaned up with force
        assert not psman.pay_collateral_wfl
        coro = psman.prepare_pay_collateral_wfl()
        asyncio.get_event_loop().run_until_complete(coro)
        assert psman.pay_collateral_wfl
        coro = psman.cleanup_pay_collateral_wfl(force=True)
        asyncio.get_event_loop().run_until_complete(coro)
        assert not psman.pay_collateral_wfl
        assert w.db.get_ps_spending_collaterals() == {}

    def test_process_by_pay_collateral_wfl(self):
        w = self.wallet
        psman = w.psman
        coro = psman.find_untracked_ps_txs(log=False)
        asyncio.get_event_loop().run_until_complete(coro)
        old_c_outpoint, old_collateral = w.db.get_ps_collateral()
        coro = psman.prepare_pay_collateral_wfl()
        asyncio.get_event_loop().run_until_complete(coro)

        wfl = psman.pay_collateral_wfl
        txid = wfl.tx_order[0]
        tx = Transaction(wfl.tx_data[txid].raw_tx)
        w.add_unverified_tx(txid, TX_HEIGHT_UNCONFIRMED)
        assert not w.is_local_tx(txid)
        psman._add_ps_data(txid, tx, PSTxTypes.PAY_COLLATERAL)
        psman._process_by_pay_collateral_wfl(txid, tx)
        assert not psman.pay_collateral_wfl
        reserved = w.db.select_ps_reserved(for_change=True, data=wfl.uuid)
        assert reserved == []
        reserved = w.db.select_ps_reserved(for_change=True)
        assert reserved == []
        new_c_outpoint, new_collateral = w.db.get_ps_collateral()
        out0 = tx.outputs()[0]
        assert new_collateral[0] == out0.address
        assert new_collateral[1] == out0.value
        assert new_c_outpoint == f'{txid}:0'
        spent_c = w.db.get_ps_spent_collaterals()
        assert spent_c[old_c_outpoint] == old_collateral
        assert w.db.get_ps_spending_collaterals() == {}

    def test_create_new_collateral_wfl(self):
        w = self.wallet
        psman = w.psman
        psman.config = self.config

        coro = psman.find_untracked_ps_txs(log=False)
        asyncio.get_event_loop().run_until_complete(coro)
        psman.state = PSStates.Mixing

        # check not created if new_collateral_wfl is not empty
        wfl = PSTxWorkflow(uuid='uuid')
        psman.set_new_collateral_wfl(wfl)
        coro = psman.create_new_collateral_wfl()
        asyncio.get_event_loop().run_until_complete(coro)
        assert psman.new_collateral_wfl == wfl
        psman.clear_new_collateral_wfl()

        # check not created if psman.config is not set
        psman.config = None
        coro = psman.create_new_collateral_wfl()
        asyncio.get_event_loop().run_until_complete(coro)
        assert not psman.new_collateral_wfl
        psman.config = self.config

        # check prepared tx
        coro = psman.create_new_collateral_wfl()
        asyncio.get_event_loop().run_until_complete(coro)
        wfl = psman.new_collateral_wfl
        assert wfl.completed
        assert len(wfl.tx_order) == 1
        txid = wfl.tx_order[0]
        tx_data = wfl.tx_data[txid]
        tx = w.db.get_transaction(txid)
        assert tx.serialize_to_network() == tx_data.raw_tx
        txins = tx.inputs()
        txouts = tx.outputs()
        assert len(txins) == 1
        assert len(txouts) == 2
        assert txouts[0].value == CREATE_COLLATERAL_VAL
        assert txouts[0].address in w.db.select_ps_reserved(data=wfl.uuid)

    def test_create_new_collateral_wfl_from_coins(self):
        w = self.wallet
        psman = w.psman
        psman.config = self.config

        coro = psman.find_untracked_ps_txs(log=False)
        asyncio.get_event_loop().run_until_complete(coro)
        psman.state = PSStates.Mixing

        coins = w.get_spendable_coins(domain=None, config=self.config)
        coins = sorted([c for c in coins], key=lambda x: x['value'])
        # check selected to many utxos
        coro = psman.create_new_collateral_wfl(coins=coins)
        asyncio.get_event_loop().run_until_complete(coro)
        assert not psman.new_collateral_wfl
        # check selected to large utxo
        coro = psman.create_new_collateral_wfl(coins=coins[-1])
        asyncio.get_event_loop().run_until_complete(coro)
        assert not psman.new_collateral_wfl

        w.set_frozen_state_of_coins(coins, True)
        coins = w.get_spendable_coins(domain=None, include_ps=False,
                                      config=self.config)
        assert coins == []

        # check created from minimal denom value
        coro = psman.create_new_collateral_wfl()
        asyncio.get_event_loop().run_until_complete(coro)
        assert psman.new_collateral_wfl
        wfl = psman.new_collateral_wfl
        txid = wfl.tx_order[0]
        raw_tx = wfl.tx_data[txid].raw_tx
        tx = Transaction(raw_tx)
        inputs = tx.inputs()
        outputs = tx.outputs()
        assert len(inputs) == 1
        assert len(outputs) == 1  # no change
        txin = inputs[0]
        prev_h = txin['prevout_hash']
        prev_n = txin['prevout_n']
        prev_tx = w.db.get_transaction(prev_h)
        prev_txout = prev_tx.outputs()[prev_n]
        assert prev_txout.value == MIN_DENOM_VAL
        assert outputs[0].value == CREATE_COLLATERAL_VALS[-2]  # 90000

        # check denom is spent
        denom_oupoint = f'{prev_h}:{prev_n}'
        assert not w.db.get_ps_denom(denom_oupoint)
        assert w.db.get_ps_spent_denom(denom_oupoint)[1] == MIN_DENOM_VAL

        assert psman.new_collateral_wfl
        for txid in wfl.tx_order:
            tx = Transaction(wfl.tx_data[txid].raw_tx)
            psman._process_by_new_collateral_wfl(txid, tx)
        assert not psman.new_collateral_wfl

    def test_create_new_collateral_wfl_from_gui(self):
        w = self.wallet
        psman = w.psman
        psman.config = self.config

        coro = psman.find_untracked_ps_txs(log=False)
        asyncio.get_event_loop().run_until_complete(coro)

        coins = w.get_spendable_coins(domain=None, config=self.config)
        coins = sorted([c for c in coins], key=lambda x: x['value'])
        # check selected to many utxos
        assert not psman.new_collateral_from_coins_info(coins)
        wfl, err = psman.create_new_collateral_wfl_from_gui(coins, None)
        assert err
        assert not wfl

        # check selected to large utxo
        assert not psman.new_collateral_from_coins_info(coins[-1])
        wfl, err = psman.create_new_collateral_wfl_from_gui(coins, None)
        assert err
        assert not wfl

        # check on single minimal denom
        coins = w.get_utxos(None, mature_only=True, confirmed_only=True,
                            consider_islocks=True, min_rounds=0)
        coins = [c for c in coins if c['value'] == MIN_DENOM_VAL]
        coins = sorted(coins, key=lambda x: x['ps_rounds'])
        coins = coins[0:1]
        assert psman.new_collateral_from_coins_info(coins) == \
            ('Transactions type: PS New Collateral\n'
             'Count of transactions: 1\n'
             'Total sent amount: 100001\n'
             'Total output amount: 90000\n'
             'Total fee: 10001')

        # check not created if mixing
        psman.state = PSStates.Mixing
        wfl, err = psman.create_new_collateral_wfl_from_gui(coins, None)
        assert err
        assert not wfl
        psman.state = PSStates.Ready

        # check created on minimal denom
        wfl, err = psman.create_new_collateral_wfl_from_gui(coins, None)
        assert not err
        txid = wfl.tx_order[0]
        raw_tx = wfl.tx_data[txid].raw_tx
        tx = Transaction(raw_tx)
        inputs = tx.inputs()
        outputs = tx.outputs()
        assert len(inputs) == 1
        assert len(outputs) == 1  # no change
        txin = inputs[0]
        prev_h = txin['prevout_hash']
        prev_n = txin['prevout_n']
        prev_tx = w.db.get_transaction(prev_h)
        prev_txout = prev_tx.outputs()[prev_n]
        assert prev_txout.value == MIN_DENOM_VAL
        assert outputs[0].value == CREATE_COLLATERAL_VALS[-2]  # 90000

        # check denom is spent
        denom_oupoint = f'{prev_h}:{prev_n}'
        assert not w.db.get_ps_denom(denom_oupoint)
        assert w.db.get_ps_spent_denom(denom_oupoint)[1] == MIN_DENOM_VAL

        assert psman.new_collateral_wfl
        for txid in wfl.tx_order:
            tx = Transaction(wfl.tx_data[txid].raw_tx)
            psman._process_by_new_collateral_wfl(txid, tx)
        assert not psman.new_collateral_wfl

    def test_cleanup_new_collateral_wfl(self):
        w = self.wallet
        psman = w.psman
        psman.config = self.config
        coro = psman.find_untracked_ps_txs(log=False)
        asyncio.get_event_loop().run_until_complete(coro)
        psman.state = PSStates.Mixing
        c_outpoint, ps_collateral = w.db.get_ps_collateral()
        w.db.pop_ps_collateral(c_outpoint)

        # check if new_collateral_wfl is empty
        assert not psman.new_collateral_wfl
        coro = psman.cleanup_new_collateral_wfl()
        asyncio.get_event_loop().run_until_complete(coro)
        assert not psman.new_collateral_wfl

        # check no cleanup if completed and tx_order is not empty
        coro = psman.create_new_collateral_wfl()
        asyncio.get_event_loop().run_until_complete(coro)
        assert psman.new_collateral_wfl
        coro = psman.cleanup_new_collateral_wfl()
        asyncio.get_event_loop().run_until_complete(coro)
        assert psman.new_collateral_wfl

        # check cleanup if not completed and tx_order is not empty
        wfl = psman.new_collateral_wfl
        txid = wfl.tx_order[0]
        assert w.db.get_transaction(txid) is not None
        reserved = w.db.select_ps_reserved(data=wfl.uuid)
        assert len(reserved) == 1

        wfl.completed = False
        psman.set_new_collateral_wfl(wfl)
        coro = psman.cleanup_new_collateral_wfl()
        asyncio.get_event_loop().run_until_complete(coro)

        assert not psman.new_collateral_wfl
        reserved = w.db.select_ps_reserved(data=wfl.uuid)
        assert len(reserved) == 0
        reserved = w.db.select_ps_reserved()
        assert len(reserved) == 0
        assert w.db.get_transaction(txid) is None
        assert not psman.new_collateral_wfl

        # check cleaned up with force
        assert not psman.new_collateral_wfl
        coro = psman.create_new_collateral_wfl()
        asyncio.get_event_loop().run_until_complete(coro)
        assert psman.new_collateral_wfl
        coro = psman.cleanup_new_collateral_wfl(force=True)
        asyncio.get_event_loop().run_until_complete(coro)
        assert not psman.new_collateral_wfl

        # check cleaned up when all txs removed
        assert not psman.new_collateral_wfl
        coro = psman.create_new_collateral_wfl()
        asyncio.get_event_loop().run_until_complete(coro)
        assert psman.new_collateral_wfl
        txid = psman.new_collateral_wfl.tx_order[0]
        w.remove_transaction(txid)
        assert not psman.new_collateral_wfl

    def test_broadcast_new_collateral_wfl(self):
        w = self.wallet
        psman = w.psman
        psman.config = self.config
        coro = psman.find_untracked_ps_txs(log=False)
        asyncio.get_event_loop().run_until_complete(coro)
        psman.state = PSStates.Mixing
        c_outpoint, ps_collateral = w.db.get_ps_collateral()
        w.db.pop_ps_collateral(c_outpoint)
        coro = psman.create_new_collateral_wfl()
        asyncio.get_event_loop().run_until_complete(coro)
        wfl = psman.new_collateral_wfl
        assert wfl.completed

        # check not broadcasted (no network)
        assert wfl.next_to_send(w) is not None
        coro = psman.broadcast_new_collateral_wfl()
        asyncio.get_event_loop().run_until_complete(coro)
        wfl = psman.new_collateral_wfl
        assert wfl.next_to_send(w) is not None

        # check not broadcasted (mock network method raises)
        assert wfl.next_to_send(w) is not None
        psman.network = NetworkBroadcastMock(pass_cnt=0)
        coro = psman.broadcast_new_collateral_wfl()
        asyncio.get_event_loop().run_until_complete(coro)
        wfl = psman.new_collateral_wfl
        assert wfl.next_to_send(w) is not None

        # check not broadcasted (skipped) if tx is in wallet.unverified_tx
        assert wfl.next_to_send(w) is not None
        txid = wfl.tx_order[0]
        w.add_unverified_tx(txid, TX_HEIGHT_UNCONF_PARENT)
        assert wfl.next_to_send(w) is None
        psman.network = NetworkBroadcastMock()
        coro = psman.broadcast_new_collateral_wfl()
        asyncio.get_event_loop().run_until_complete(coro)
        wfl = psman.new_collateral_wfl
        assert wfl.next_to_send(w) is None
        w.unverified_tx.pop(txid)

        # check not broadcasted (mock network) but recently send failed
        assert wfl.next_to_send(w) is not None
        psman.network = NetworkBroadcastMock()
        coro = psman.broadcast_new_collateral_wfl()
        asyncio.get_event_loop().run_until_complete(coro)
        wfl = psman.new_collateral_wfl
        assert wfl.next_to_send(w) is not None

        # check broadcasted (mock network)
        assert wfl.next_to_send(w) is not None
        tx_data = wfl.next_to_send(w)
        tx_data.next_send = None
        psman.set_new_collateral_wfl(wfl)
        coro = psman.broadcast_new_collateral_wfl()
        asyncio.get_event_loop().run_until_complete(coro)
        assert psman.new_collateral_wfl is None

    def test_process_by_new_collateral_wfl(self):
        w = self.wallet
        psman = w.psman
        psman.config = self.config
        coro = psman.find_untracked_ps_txs(log=False)
        asyncio.get_event_loop().run_until_complete(coro)
        psman.state = PSStates.Mixing
        c_outpoint, ps_collateral = w.db.get_ps_collateral()
        w.db.pop_ps_collateral(c_outpoint)
        coro = psman.create_new_collateral_wfl()
        asyncio.get_event_loop().run_until_complete(coro)

        wfl = psman.new_collateral_wfl
        txid = wfl.tx_order[0]
        tx = Transaction(wfl.tx_data[txid].raw_tx)
        w.add_unverified_tx(txid, TX_HEIGHT_UNCONFIRMED)
        psman._process_by_new_collateral_wfl(txid, tx)
        assert not psman.new_collateral_wfl
        reserved = w.db.select_ps_reserved(data=wfl.uuid)
        assert reserved == []
        reserved = w.db.select_ps_reserved()
        assert reserved == []
        new_c_outpoint, new_collateral = w.db.get_ps_collateral()
        tx = w.db.get_transaction(txid)
        out0 = tx.outputs()[0]
        assert new_collateral[0] == out0.address
        assert new_collateral[1] == out0.value
        assert new_c_outpoint == f'{txid}:0'
        assert w.db.get_ps_tx(txid) == (PSTxTypes.NEW_COLLATERAL, True)

    def test_calc_need_denoms_amounts(self):
        all_test_amounts = [
            [40000] + [100001]*11 + [1000010]*11 + [10000100]*11,
            [100001]*11 + [1000010]*11 + [10000100]*6,
            [100001]*11 + [1000010]*4,
            [100001]*8,
        ]
        w = self.wallet
        psman = w.psman
        psman.config = self.config
        res = psman.calc_need_denoms_amounts()
        assert res == all_test_amounts
        res = psman.calc_need_denoms_amounts(use_cache=True)
        assert res == all_test_amounts
        coro = psman.find_untracked_ps_txs(log=False)
        asyncio.get_event_loop().run_until_complete(coro)
        res = psman.calc_need_denoms_amounts()
        assert res == []
        res = psman.calc_need_denoms_amounts(use_cache=True)
        assert res == []

    def test_calc_need_denoms_amounts_from_coins(self):
        w = self.wallet
        psman = w.psman
        psman.config = self.config

        dv0001 = PS_DENOMS_VALS[0]
        dv001 = PS_DENOMS_VALS[1]
        dv01 = PS_DENOMS_VALS[2]
        dv1 = PS_DENOMS_VALS[3]
        coins = w.get_spendable_coins(domain=None, config=self.config)
        c0001 = list(filter(lambda x: x['value'] == dv0001, coins))
        c001 = list(filter(lambda x: x['value'] == dv001, coins))
        c01 = list(filter(lambda x: x['value'] == dv01, coins))
        c1 = list(filter(lambda x: x['value'] == dv1, coins))
        other = list(filter(lambda x: x['value'] not in PS_DENOMS_VALS, coins))
        ccv = COLLATERAL_VAL*9
        assert len(c1) == 2
        assert len(c01) == 26
        assert len(c001) == 33
        assert len(c0001) == 70

        assert psman.calc_need_denoms_amounts(coins=c0001[0:1]) == []

        expected = [[ccv] + [dv0001]]
        assert psman.calc_need_denoms_amounts(coins=c0001[0:2]) == expected

        expected = [[ccv] + [dv0001]*2]
        assert psman.calc_need_denoms_amounts(coins=c0001[0:3]) == expected

        expected = [[ccv] + [dv0001]*3]
        assert psman.calc_need_denoms_amounts(coins=c0001[0:4]) == expected

        expected = [[ccv] + [dv0001]*4]
        assert psman.calc_need_denoms_amounts(coins=c0001[0:5]) == expected

        expected = [[ccv] + [dv0001]*5]
        assert psman.calc_need_denoms_amounts(coins=c0001[0:6]) == expected

        expected = [[ccv] + [dv0001]*6]
        assert psman.calc_need_denoms_amounts(coins=c0001[0:7]) == expected

        expected = [[ccv] + [dv0001]*7]
        assert psman.calc_need_denoms_amounts(coins=c0001[0:8]) == expected


        expected = [[ccv] + [dv0001]*9]
        assert psman.calc_need_denoms_amounts(coins=c001[0:1]) == expected

        expected = [[ccv] + [dv0001]*11, [dv0001]*8]
        assert psman.calc_need_denoms_amounts(coins=c001[0:2]) == expected

        expected = [[ccv] + [dv0001]*11 + [dv001], [dv0001]*8]
        assert psman.calc_need_denoms_amounts(coins=c001[0:3]) == expected

        expected = [[ccv] + [dv0001]*11 + [dv001]*2, [dv0001]*8]
        assert psman.calc_need_denoms_amounts(coins=c001[0:4]) == expected

        expected = [[ccv] + [dv0001]*11 + [dv001]*3, [dv0001]*8]
        assert psman.calc_need_denoms_amounts(coins=c001[0:5]) == expected

        expected = [[ccv] + [dv0001]*11 + [dv001]*4, [dv0001]*8]
        assert psman.calc_need_denoms_amounts(coins=c001[0:6]) == expected

        expected = [[ccv] + [dv0001]*11 + [dv001]*5, [dv0001]*8]
        assert psman.calc_need_denoms_amounts(coins=c001[0:7]) == expected

        expected = [[ccv] + [dv0001]*11 + [dv001]*6, [dv0001]*8]
        assert psman.calc_need_denoms_amounts(coins=c001[0:8]) == expected


        expected = [[ccv] + [dv0001]*11 + [dv001]*8, [dv0001]*8]
        assert psman.calc_need_denoms_amounts(coins=c01[0:1]) == expected

        expected = [[ccv] + [dv0001]*11 + [dv001]*11,
                    [dv0001]*11 + [dv001]*6, [dv0001]*7]
        assert psman.calc_need_denoms_amounts(coins=c01[0:2]) == expected

        expected = [[ccv] + [dv0001]*11 + [dv001]*11 + [dv01],
                    [dv0001]*11 + [dv001]*6, [dv0001]*7]
        assert psman.calc_need_denoms_amounts(coins=c01[0:3]) == expected

        expected = [[ccv] + [dv0001]*11 + [dv001]*11 + [dv01]*2,
                    [dv0001]*11 + [dv001]*6, [dv0001]*7]
        assert psman.calc_need_denoms_amounts(coins=c01[0:4]) == expected

        expected = [[ccv] + [dv0001]*11 + [dv001]*11 + [dv01]*3,
                    [dv0001]*11 + [dv001]*6, [dv0001]*7]
        assert psman.calc_need_denoms_amounts(coins=c01[0:5]) == expected

        expected = [[ccv] + [dv0001]*11 + [dv001]*11 + [dv01]*4,
                    [dv0001]*11 + [dv001]*6, [dv0001]*7]
        assert psman.calc_need_denoms_amounts(coins=c01[0:6]) == expected

        expected = [[ccv] + [dv0001]*11 + [dv001]*11 + [dv01]*5,
                    [dv0001]*11 + [dv001]*6, [dv0001]*7]
        assert psman.calc_need_denoms_amounts(coins=c01[0:7]) == expected

        expected = [[ccv] + [dv0001]*11 + [dv001]*11 + [dv01]*6,
                    [dv0001]*11 + [dv001]*6, [dv0001]*7]
        assert psman.calc_need_denoms_amounts(coins=c01[0:8]) == expected

        expected = [[ccv] + [dv0001]*11 + [dv001]*11 + [dv01]*7,
                    [dv0001]*11 + [dv001]*6, [dv0001]*7]
        assert psman.calc_need_denoms_amounts(coins=c01[0:9]) == expected


        expected = [[ccv] + [dv0001]*11 + [dv001]*11 + [dv01]*8,
                    [dv0001]*11 + [dv001]*6, [dv0001]*7]
        assert psman.calc_need_denoms_amounts(coins=c1[0:1]) == expected

        expected = [[ccv] + [dv0001]*11 + [dv001]*11 + [dv01]*11,
                    [dv0001]*11 + [dv001]*11 + [dv01]*6,
                    [dv0001]*11 + [dv001]*4, [dv0001]*6]
        assert psman.calc_need_denoms_amounts(coins=c1[0:2]) == expected

        expected = [[10000] + [dv0001]*11 + [dv001]*11 + [dv01]*11 + [dv1]*8,
                    [dv0001]*11 + [dv001]*11 + [dv01]*5, [dv0001]*6]
        assert psman.calc_need_denoms_amounts(coins=other) == expected

    def test_calc_tx_size(self):
        # average sizes
        assert 192 == calc_tx_size(1, 1)
        assert 226 == calc_tx_size(1, 2)
        assert 37786 == calc_tx_size(255, 1)
        assert 8830 == calc_tx_size(1, 255)
        assert 46424 == calc_tx_size(255, 255)
        assert 148046 == calc_tx_size(1000, 1)
        assert 34160 == calc_tx_size(1, 1000)
        assert 182014 == calc_tx_size(1000, 1000)

        # max sizes
        assert 193 == calc_tx_size(1, 1, max_size=True)
        assert 227 == calc_tx_size(1, 2, max_size=True)
        assert 38041 == calc_tx_size(255, 1, max_size=True)
        assert 8831 == calc_tx_size(1, 255, max_size=True)
        assert 46679 == calc_tx_size(255, 255, max_size=True)
        assert 149046 == calc_tx_size(1000, 1, max_size=True)
        assert 34161 == calc_tx_size(1, 1000, max_size=True)
        assert 183014 == calc_tx_size(1000, 1000, max_size=True)

    def test_calc_tx_fee(self):
        # average sizes
        assert 192 == calc_tx_fee(1, 1, 1000)
        assert 226 == calc_tx_fee(1, 2, 1000)
        assert 37786 == calc_tx_fee(255, 1, 1000)
        assert 8830 == calc_tx_fee(1, 255, 1000)
        assert 46424 == calc_tx_fee(255, 255, 1000)
        assert 148046 == calc_tx_fee(1000, 1, 1000)
        assert 34160 == calc_tx_fee(1, 1000, 1000)
        assert 182014 == calc_tx_fee(1000, 1000, 1000)

        # max sizes
        assert 193 == calc_tx_fee(1, 1, 1000, max_size=True)
        assert 227 == calc_tx_fee(1, 2, 1000, max_size=True)
        assert 38041 == calc_tx_fee(255, 1, 1000, max_size=True)
        assert 8831 == calc_tx_fee(1, 255, 1000, max_size=True)
        assert 46679 == calc_tx_fee(255, 255, 1000, max_size=True)
        assert 149046 == calc_tx_fee(1000, 1, 1000, max_size=True)
        assert 34161 == calc_tx_fee(1, 1000, 1000, max_size=True)
        assert 183014 == calc_tx_fee(1000, 1000, 1000, max_size=True)

    def test_create_new_denoms_wfl(self):
        w = self.wallet
        psman = w.psman
        psman.config = self.config
        psman.state = PSStates.Mixing

        # check not created if new_denoms_wfl is not empty
        wfl = PSTxWorkflow(uuid='uuid')
        psman.set_new_denoms_wfl(wfl)
        coro = psman.create_new_denoms_wfl()
        asyncio.get_event_loop().run_until_complete(coro)
        assert psman.new_denoms_wfl == wfl
        psman.clear_new_denoms_wfl()

        # check not created if psman.config is not set
        with self.assertRaises(AttributeError):
            psman.config = None
            coro = psman.create_new_denoms_wfl()
            asyncio.get_event_loop().run_until_complete(coro)
        psman.config = self.config

        # check created successfully
        coro = psman.create_new_denoms_wfl()
        asyncio.get_event_loop().run_until_complete(coro)
        wfl = psman.new_denoms_wfl
        assert wfl.completed
        all_test_amounts = [
            [100001]*11 + [1000010]*11 + [10000100]*11,
            [100001]*11 + [1000010]*11 + [10000100]*6,
            [100001]*11 + [1000010]*4,
            [100001]*8,
        ]
        for i, txid in enumerate(wfl.tx_order):
            tx = w.db.get_transaction(txid)
            collaterals_count = 0
            denoms_count = 0
            change_count = 0
            for o in tx.outputs():
                val = o.value
                if val == CREATE_COLLATERAL_VAL:
                    collaterals_count += 1
                elif val in PS_DENOMS_VALS:
                    assert all_test_amounts[i][denoms_count] == val
                    denoms_count += 1
                else:
                    change_count += 1
            if i == 0:
                assert collaterals_count == 1
            else:
                assert collaterals_count == 0
            assert denoms_count == len(all_test_amounts[i])
            assert change_count == 1
        assert len(w.db.select_ps_reserved(data=wfl.uuid)) == 85

        wfl.completed = False
        psman.set_new_denoms_wfl(wfl)
        coro = psman.cleanup_new_denoms_wfl()
        asyncio.get_event_loop().run_until_complete(coro)
        outpoint0 = '0'*64 + ':0'
        w.db.add_ps_collateral(outpoint0, (w.dummy_address(), 1))
        assert not psman.new_denoms_wfl

        # check created successfully without ps_collateral output
        coro = psman.create_new_denoms_wfl()
        asyncio.get_event_loop().run_until_complete(coro)
        wfl = psman.new_denoms_wfl
        assert wfl.completed
        all_test_amounts = [
            [100001]*11 + [1000010]*11 + [10000100]*11,
            [100001]*11 + [1000010]*11 + [10000100]*6,
            [100001]*11 + [1000010]*4,
            [100001]*8,
        ]
        for i, txid in enumerate(wfl.tx_order):
            tx = w.db.get_transaction(txid)
            collaterals_count = 0
            denoms_count = 0
            change_count = 0
            for o in tx.outputs():
                val = o.value
                if val == CREATE_COLLATERAL_VAL:
                    collaterals_count += 1
                elif val in PS_DENOMS_VALS:
                    assert all_test_amounts[i][denoms_count] == val
                    denoms_count += 1
                else:
                    change_count += 1
            assert collaterals_count == 0
            assert denoms_count == len(all_test_amounts[i])
            assert change_count == 1
        assert len(w.db.select_ps_reserved(data=wfl.uuid)) == 84

        # check not created if enoug denoms exists
        psman.keep_amount = 5
        wfl.completed = False
        psman.set_new_denoms_wfl(wfl)
        coro = psman.cleanup_new_denoms_wfl()
        asyncio.get_event_loop().run_until_complete(coro)
        w.db.pop_ps_collateral(outpoint0)
        psman.state = PSStates.Ready
        coro = psman.find_untracked_ps_txs(log=False)
        asyncio.get_event_loop().run_until_complete(coro)
        psman.state = PSStates.Mixing
        coro = psman.create_new_denoms_wfl()
        asyncio.get_event_loop().run_until_complete(coro)
        assert not psman.new_denoms_wfl

    def test_create_new_denoms_wfl_low_balance(self):
        w = self.wallet
        psman = w.psman
        psman.config = self.config
        psman.keep_amount = 1000
        fee_per_kb = self.config.fee_per_kb()

        coro = psman.find_untracked_ps_txs(log=False)
        asyncio.get_event_loop().run_until_complete(coro)
        psman.state = PSStates.Mixing

        coro = psman.create_new_denoms_wfl()
        asyncio.get_event_loop().run_until_complete(coro)
        wfl = psman.new_denoms_wfl
        assert wfl.completed

        # assert coins left less of half_minimal_denom
        c, u, x = w.get_balance(include_ps=False)
        new_collateral_cnt = 19
        new_collateral_fee = calc_tx_fee(1, 2, fee_per_kb, max_size=True)
        half_minimal_denom = MIN_DENOM_VAL // 2
        assert (c + u -
                CREATE_COLLATERAL_VAL * new_collateral_cnt -
                new_collateral_fee * new_collateral_cnt) < half_minimal_denom

    def test_create_new_denoms_wfl_from_gui(self):
        w = self.wallet
        psman = w.psman
        psman.config = self.config

        coro = psman.find_untracked_ps_txs(log=False)
        asyncio.get_event_loop().run_until_complete(coro)

        coins = w.get_spendable_coins(domain=None, config=self.config)
        coins = sorted([c for c in coins], key=lambda x: x['value'])
        # check selected to many utxos
        assert not psman.new_denoms_from_coins_info(coins)
        wfl, err = psman.create_new_denoms_wfl_from_gui(coins, None)
        assert err
        assert not wfl

        coins = w.get_utxos(None, mature_only=True, confirmed_only=True,
                            consider_islocks=True, min_rounds=0)
        coins = [c for c in coins if c['value'] == PS_DENOMS_VALS[-2]]
        coins = sorted(coins, key=lambda x: x['ps_rounds'])

        # check on single max value available denom
        coins = coins[0:1]

        # check not created if mixing
        psman.state = PSStates.Mixing
        wfl, err = psman.create_new_denoms_wfl_from_gui(coins, None)
        assert err
        assert not wfl
        psman.state = PSStates.Ready

        # check on 100001000 denom
        assert psman.new_denoms_from_coins_info(coins) == \
            ('Transactions type: PS New Denoms\n'
             'Count of transactions: 3\n'
             'Total sent amount: 100001000\n'
             'Total output amount: 99990999\n'
             'Total fee: 10001')

        wfl, err = psman.create_new_denoms_wfl_from_gui(coins, None)
        assert not err
        txid = wfl.tx_order[0]
        raw_tx = wfl.tx_data[txid].raw_tx
        tx = Transaction(raw_tx)
        inputs = tx.inputs()
        outputs = tx.outputs()
        assert len(inputs) == 1
        assert len(outputs) == 32
        txin = inputs[0]
        prev_h = txin['prevout_hash']
        prev_n = txin['prevout_n']
        prev_tx = w.db.get_transaction(prev_h)
        prev_txout = prev_tx.outputs()[prev_n]
        assert prev_txout.value == PS_DENOMS_VALS[-2]
        assert outputs[0].value == CREATE_COLLATERAL_VALS[-2]  # 90000
        total_out_vals = 0
        out_vals = [o.value for o in outputs]
        total_out_vals += sum(out_vals) - 7808833
        assert out_vals == [90000, 100001, 100001, 100001, 100001, 100001,
                            100001, 100001, 100001, 100001, 100001, 100001,
                            1000010, 1000010, 1000010, 1000010, 1000010,
                            1000010, 1000010, 1000010, 1000010, 1000010,
                            1000010, 7808833, 10000100, 10000100, 10000100,
                            10000100, 10000100, 10000100, 10000100, 10000100]

        txid = wfl.tx_order[1]
        raw_tx = wfl.tx_data[txid].raw_tx
        tx = Transaction(raw_tx)
        inputs = tx.inputs()
        outputs = tx.outputs()
        out_vals = [o.value for o in outputs]
        total_out_vals += sum(out_vals) - 707992
        assert out_vals == [100001, 100001, 100001, 100001, 100001, 100001,
                            100001, 100001, 100001, 100001, 100001, 707992,
                            1000010, 1000010, 1000010, 1000010, 1000010,
                            1000010]

        txid = wfl.tx_order[2]
        raw_tx = wfl.tx_data[txid].raw_tx
        tx = Transaction(raw_tx)
        inputs = tx.inputs()
        outputs = tx.outputs()
        out_vals = [o.value for o in outputs]
        total_out_vals += sum(out_vals)
        assert out_vals == [100001, 100001, 100001, 100001, 100001, 100001,
                            100001]
        assert total_out_vals == 99990999

        # check denom is spent
        denom_oupoint = f'{prev_h}:{prev_n}'
        assert not w.db.get_ps_denom(denom_oupoint)
        assert w.db.get_ps_spent_denom(denom_oupoint)[1] == PS_DENOMS_VALS[-2]

        # process
        for txid in wfl.tx_order:
            tx = Transaction(wfl.tx_data[txid].raw_tx)
            psman._process_by_new_denoms_wfl(txid, tx)
        assert not psman.new_denoms_wfl

        # check on 10000100 denom
        total_out_vals = 0
        coins = w.get_utxos(None, mature_only=True, confirmed_only=True,
                            consider_islocks=True, min_rounds=0)
        coins = [c for c in coins if c['value'] == PS_DENOMS_VALS[-3]]
        coins = sorted(coins, key=lambda x: x['ps_rounds'])
        coins = coins[0:1]
        assert psman.new_denoms_from_coins_info(coins) == \
            ('Transactions type: PS New Denoms\n'
             'Count of transactions: 2\n'
             'Total sent amount: 10000100\n'
             'Total output amount: 9990099\n'
             'Total fee: 10001')
        wfl, err = psman.create_new_denoms_wfl_from_gui(coins, None)
        txid = wfl.tx_order[0]
        raw_tx = wfl.tx_data[txid].raw_tx
        tx = Transaction(raw_tx)
        out_vals = [o.value for o in tx.outputs()]
        total_out_vals += sum(out_vals) - 809137
        assert out_vals == [90000, 100001, 100001, 100001, 100001, 100001,
                            100001, 100001, 100001, 100001, 100001, 100001,
                            809137, 1000010, 1000010, 1000010, 1000010,
                            1000010, 1000010, 1000010, 1000010]
        txid = wfl.tx_order[1]
        raw_tx = wfl.tx_data[txid].raw_tx
        tx = Transaction(raw_tx)
        out_vals = [o.value for o in tx.outputs()]
        total_out_vals += sum(out_vals)
        assert out_vals == [100001, 100001, 100001, 100001, 100001, 100001,
                            100001, 100001]
        assert total_out_vals == 9990099
        # process
        for txid in wfl.tx_order:
            tx = Transaction(wfl.tx_data[txid].raw_tx)
            psman._process_by_new_denoms_wfl(txid, tx)
        assert not psman.new_denoms_wfl

        # check on 1000010 denom
        total_out_vals = 0
        coins = w.get_utxos(None, mature_only=True, confirmed_only=True,
                            consider_islocks=True, min_rounds=0)
        coins = [c for c in coins if c['value'] == PS_DENOMS_VALS[-4]]
        coins = sorted(coins, key=lambda x: x['ps_rounds'])
        coins = coins[0:1]
        assert psman.new_denoms_from_coins_info(coins) == \
            ('Transactions type: PS New Denoms\n'
             'Count of transactions: 1\n'
             'Total sent amount: 1000010\n'
             'Total output amount: 990009\n'
             'Total fee: 10001')
        wfl, err = psman.create_new_denoms_wfl_from_gui(coins, None)
        txid = wfl.tx_order[0]
        raw_tx = wfl.tx_data[txid].raw_tx
        tx = Transaction(raw_tx)
        out_vals = [o.value for o in tx.outputs()]
        total_out_vals += sum(out_vals)
        assert out_vals == [90000, 100001, 100001, 100001, 100001, 100001,
                            100001, 100001, 100001, 100001]
        assert total_out_vals == 990009
        # process
        for txid in wfl.tx_order:
            tx = Transaction(wfl.tx_data[txid].raw_tx)
            psman._process_by_new_denoms_wfl(txid, tx)
        assert not psman.new_denoms_wfl

    def test_cleanup_new_denoms_wfl(self):
        w = self.wallet
        psman = w.psman
        psman.config = self.config
        psman.state = PSStates.Mixing

        # check if new_denoms_wfl is empty
        assert not psman.new_denoms_wfl
        coro = psman.cleanup_new_denoms_wfl()
        asyncio.get_event_loop().run_until_complete(coro)
        assert not psman.new_denoms_wfl

        # check no cleanup if completed and tx_order is not empty
        coro = psman.create_new_denoms_wfl()
        asyncio.get_event_loop().run_until_complete(coro)
        assert psman.new_denoms_wfl
        coro = psman.cleanup_new_denoms_wfl()
        asyncio.get_event_loop().run_until_complete(coro)
        assert psman.new_denoms_wfl

        # check cleanup if not completed and tx_order is not empty
        coro = psman.create_new_denoms_wfl()
        asyncio.get_event_loop().run_until_complete(coro)
        wfl = psman.new_denoms_wfl
        for txid in wfl.tx_order:
            assert w.db.get_transaction(txid) is not None
        reserved = w.db.select_ps_reserved(data=wfl.uuid)
        assert len(reserved) == 85

        wfl.completed = False
        psman.set_new_denoms_wfl(wfl)
        coro = psman.cleanup_new_denoms_wfl()
        asyncio.get_event_loop().run_until_complete(coro)
        assert not psman.new_denoms_wfl

        for txid in wfl.tx_order:
            assert w.db.get_transaction(txid) is None
        reserved = w.db.select_ps_reserved(data=wfl.uuid)
        assert len(reserved) == 0
        reserved = w.db.select_ps_reserved()
        assert len(reserved) == 0

        # check cleaned up with force
        assert not psman.new_denoms_wfl
        coro = psman.create_new_denoms_wfl()
        asyncio.get_event_loop().run_until_complete(coro)
        assert psman.new_denoms_wfl
        coro = psman.cleanup_new_denoms_wfl(force=True)
        asyncio.get_event_loop().run_until_complete(coro)
        assert not psman.new_denoms_wfl

        # check cleaned up when all txs removed
        assert not psman.new_denoms_wfl
        coro = psman.create_new_denoms_wfl()
        asyncio.get_event_loop().run_until_complete(coro)
        assert psman.new_denoms_wfl
        assert len(psman.new_denoms_wfl.tx_order) == 4
        txid = psman.new_denoms_wfl.tx_order[0]
        w.remove_transaction(txid)
        assert len(psman.new_denoms_wfl.tx_order) == 3
        txid = psman.new_denoms_wfl.tx_order[0]
        w.remove_transaction(txid)
        assert len(psman.new_denoms_wfl.tx_order) == 2
        txid = psman.new_denoms_wfl.tx_order[0]
        w.remove_transaction(txid)
        assert len(psman.new_denoms_wfl.tx_order) == 1
        txid = psman.new_denoms_wfl.tx_order[0]
        w.remove_transaction(txid)
        assert not psman.new_denoms_wfl

    def test_broadcast_new_denoms_wfl(self):
        w = self.wallet
        psman = w.psman
        psman.state = PSStates.Mixing
        psman.config = self.config
        coro = psman.create_new_denoms_wfl()
        asyncio.get_event_loop().run_until_complete(coro)
        wfl = psman.new_denoms_wfl
        assert wfl.completed
        tx_order = wfl.tx_order
        tx_data = wfl.tx_data

        # check not broadcasted (no network)
        assert wfl.next_to_send(w) == tx_data[tx_order[0]]
        coro = psman.broadcast_new_denoms_wfl()
        asyncio.get_event_loop().run_until_complete(coro)
        wfl = psman.new_denoms_wfl
        tx_data = wfl.tx_data
        for txid in wfl.tx_order:
            assert tx_data[txid].sent is None
        assert wfl.next_to_send(w) == tx_data[tx_order[0]]

        # check not broadcasted (mock network method raises)
        psman.network = NetworkBroadcastMock(pass_cnt=0)
        coro = psman.broadcast_new_denoms_wfl()
        asyncio.get_event_loop().run_until_complete(coro)
        wfl = psman.new_denoms_wfl
        tx_data = wfl.tx_data
        for txid in wfl.tx_order:
            assert tx_data[txid].sent is None

        # check not broadcasted (skipped) if tx is in wallet.unverified_tx
        assert wfl.next_to_send(w) == tx_data[tx_order[0]]
        for i, txid in enumerate(tx_order):
            w.add_unverified_tx(txid, TX_HEIGHT_UNCONF_PARENT)
            if i < len(tx_order) - 1:
                assert wfl.next_to_send(w) == tx_data[tx_order[i+1]]
        assert wfl.next_to_send(w) is None
        psman.network = NetworkBroadcastMock()
        coro = psman.broadcast_new_denoms_wfl()
        asyncio.get_event_loop().run_until_complete(coro)
        wfl = psman.new_denoms_wfl
        tx_data = wfl.tx_data
        for i, txid in enumerate(tx_order):
            assert tx_data[txid].sent is None
            w.unverified_tx.pop(txid)
        assert wfl.next_to_send(w) == tx_data[tx_order[0]]

        # check not broadcasted (mock network) but recently send failed
        psman.network = NetworkBroadcastMock()
        coro = psman.broadcast_new_denoms_wfl()
        asyncio.get_event_loop().run_until_complete(coro)
        coro = psman.broadcast_new_denoms_wfl()
        asyncio.get_event_loop().run_until_complete(coro)
        coro = psman.broadcast_new_denoms_wfl()
        asyncio.get_event_loop().run_until_complete(coro)
        coro = psman.broadcast_new_denoms_wfl()
        asyncio.get_event_loop().run_until_complete(coro)
        wfl = psman.new_denoms_wfl
        tx_data = wfl.tx_data
        assert wfl.next_to_send(w) is not None
        for txid in wfl.tx_order:
            assert not tx_data[txid].sent

        # check broadcasted (mock network)
        for txid in wfl.tx_order:
            tx_data[txid].next_send = None
        psman.set_new_denoms_wfl(wfl)

        psman.network = NetworkBroadcastMock()
        coro = psman.broadcast_new_denoms_wfl()
        asyncio.get_event_loop().run_until_complete(coro)
        coro = psman.broadcast_new_denoms_wfl()
        asyncio.get_event_loop().run_until_complete(coro)
        coro = psman.broadcast_new_denoms_wfl()
        asyncio.get_event_loop().run_until_complete(coro)
        coro = psman.broadcast_new_denoms_wfl()
        asyncio.get_event_loop().run_until_complete(coro)
        assert psman.new_denoms_wfl is None

    def test_process_by_new_denoms_wfl(self):
        w = self.wallet
        psman = w.psman
        psman.state = PSStates.Mixing
        psman.config = self.config
        coro = psman.create_new_denoms_wfl()
        asyncio.get_event_loop().run_until_complete(coro)
        wfl = psman.new_denoms_wfl
        uuid = wfl.uuid

        denoms_cnt = [84, 84, 84, 84]
        reserved_cnt = [85, 85, 85, 0]
        reserved_none_cnt = [0, 0, 0, 0]
        for i, txid in enumerate(wfl.tx_order):
            w.add_unverified_tx(txid, TX_HEIGHT_UNCONFIRMED)
            assert not w.is_local_tx(txid)
            tx = Transaction(wfl.tx_data[txid].raw_tx)
            psman._process_by_new_denoms_wfl(txid, tx)
            wfl = psman.new_denoms_wfl
            if i == 0:
                c_outpoint, collateral = w.db.get_ps_collateral()
                assert c_outpoint and collateral
            if i < len(denoms_cnt) - 1:
                assert len(wfl.tx_order) == len(denoms_cnt) - i - 1
            assert len(w.db.ps_denoms) == denoms_cnt[i]
            assert len(w.db.select_ps_reserved(data=uuid)) == reserved_cnt[i]
            assert len(w.db.select_ps_reserved()) == reserved_none_cnt[i]
            assert w.db.get_ps_tx(txid) == (PSTxTypes.NEW_DENOMS, True)
        assert not wfl

    def test_sign_denominate_tx(self):
        raw_tx_final = (
            '020000000b35c83d33f4eb22cf07b87d6deb1f73ff9e72df33d5b9699255bbab'
            'b41b7823290e00000000ffffffffabaae659d6a4f2072d722dd7e7c478d5c366'
            '3b454f7f143dd20374e54a3478442000000000ffffffff3c3328c309414c2573'
            '43ab98f818f2cfe29bbb4b4e1a472d89e892c2eb22c3702000000000ffffffff'
            'c8c88b7e49a966a03eca39f5248cd66095f54278af3d1ba525955d150e0fbb7a'
            '0100000000ffffffff6679b6c0a77142c0a3c9812788d279ecee873c13cc85d5'
            '1d4b5081fbb464d87d0800000000ffffffffc2a56cd9393c4f3f207a721232a9'
            '6fa570c03062cd19fad1f2dfc9e5e84f4c7f0c00000000ffffffff4de733c7d2'
            'b2d5d82af0deb8edded3ac51916c2d47c726f362e7ddcb66354ca10000000000'
            'ffffffff47b4d30c252862f099027353c15ad264853c4569936f04bd8b24bdeb'
            '9ca8f1c10900000000fffffffff03bb7d5d3e6f46ccc36ea2b32cd00ad21aaa2'
            '644cf7e98b0e0ba8b1b80f27c91200000000ffffffff73fa0a029ecf2f95559b'
            '87bdf94207a1c6e35ea551c409862c0a298affe023de0800000000ffffffff92'
            '61f033620895cfd212b083d65b2fa607b799d20d834e9df8eeeb819dddb7f604'
            '00000000ffffffff0be4969800000000001976a9140dab039f105c1f0cf685f1'
            '7802241cf74c5a3c0a88ace4969800000000001976a91427d38aa89216e0f38d'
            '8b3b2dfca6c5a0813c319988ace4969800000000001976a9146d9aad56a22f5c'
            '22adc138838b967480032579ab88ace4969800000000001976a9148e8953727d'
            '6f70fa2c6fa073f660f6698dd7902788ace4969800000000001976a9149669e8'
            '2a91a1275204098d9960d3c6e73a37711588ace4969800000000001976a914ca'
            'bb5582885d713a5a5055cda3ba22d546eeb22288ace4969800000000001976a9'
            '14cf839533846857f38e6399a598588b49c3cb763d88ace49698000000000019'
            '76a914e3987f30f44ea35bc938cdfaf10203b8c1f6d84288ace4969800000000'
            '001976a914f2cadaf584f9ec642c9bdac7edc4690a3e8f833d88ace496980000'
            '0000001976a914f787ffced16771f5f88445450af7b8cf9262fffd88ace49698'
            '00000000001976a914f7ad936793f2206a0fb67fa27f4c4dc5723175c188ac00'
            '000000')
        tx = Transaction(raw_tx_final)
        tx = self.wallet.psman._sign_denominate_tx(tx)
        assert tx.inputs()[-1]['scriptSig'] == (
            '48304502210085e21ab1c080886d4bd84e523962cd52d5aeabaea50f571f99e7'
            '19cabbd23d3a02201de6a77f885aa3d718c5de9c3771af5d51f3155d2ce4f457'
            'cd1628dbbf3fd80b012102a17ec54ed6f8ba9a110d4f4f61f5b9d20024c16bf9'
            '6239ec8a3ebfc4b1f658b0')

    def _check_tx_io(self, tx, spend_to, spend_haks, fee_haks,
                     change=None, change_haks=None,
                     include_ps=False, min_rounds=None):
        o = tx.outputs()
        in_haks = 0
        out_haks = 0
        if not include_ps and min_rounds is None:
            for _in_ in tx.inputs():
                in_haks += _in_['value']
                assert _in_['ps_rounds'] is None
        elif include_ps:
            for _in_ in tx.inputs():
                in_haks += _in_['value']
        elif min_rounds is not None:
            assert len(o) == 1
            for _in_ in tx.inputs():
                in_haks += _in_['value']
                assert _in_['ps_rounds'] == min_rounds

        if change is not None:
            assert len(o) == 2

        for oi in o:
            out_haks += oi.value
            if oi.value == spend_haks:
                assert oi.type == 0
                assert oi.address == spend_to
            elif oi.value == change_haks:
                assert oi.type == 0
                assert oi.address == change
            else:
                raise Exception(f'Unknown amount: {oi.value}')
        assert fee_haks == (in_haks - out_haks)

    def test_make_unsigned_transaction(self):
        w = self.wallet
        psman = w.psman
        coro = psman.find_untracked_ps_txs(log=False)
        asyncio.get_event_loop().run_until_complete(coro)
        config = self.config
        addr_type = TYPE_ADDRESS
        spend_to = 'yiXJV2PodX4uuadFtt6e7wMTNkydHpp8ns'
        change = 'yanRmD5ZR66L1G51ixvXvUiJEmso5trn97'
        test_amounts = [0.0123, 0.123, 1.23, 5.123]
        test_fees = [226, 226, 374, 374]
        test_changes = [0.00769774, 0.17699774, 0.26999626, 2.90506399]

        coins = w.get_spendable_coins(domain=None, config=config)
        for i in range(len(test_amounts)):
            amount_haks = to_haks(test_amounts[i])
            change_haks = to_haks(test_changes[i])
            outputs = [TxOutput(addr_type, spend_to, amount_haks)]
            tx = w.make_unsigned_transaction(coins, outputs, config=config)
            self._check_tx_io(tx, spend_to, amount_haks, test_fees[i],
                              change, change_haks)

        # check max amount
        amount_haks = to_haks(9.84805841)
        outputs = [TxOutput(addr_type, spend_to, amount_haks)]
        coins = w.get_spendable_coins(domain=None, config=config)
        tx = w.make_unsigned_transaction(coins, outputs, config=config)
        self._check_tx_io(tx, spend_to, amount_haks, 932)  # no change

        amount_haks = to_haks(9.84805842)  # NotEnoughFunds
        outputs = [TxOutput(addr_type, spend_to, amount_haks)]
        coins = w.get_spendable_coins(domain=None, config=config)
        with self.assertRaises(NotEnoughFunds):
            tx = w.make_unsigned_transaction(coins, outputs, config=config)

    def test_make_unsigned_transaction_include_ps(self):
        w = self.wallet
        psman = w.psman
        coro = psman.find_untracked_ps_txs(log=False)
        asyncio.get_event_loop().run_until_complete(coro)
        config = self.config
        addr_type = TYPE_ADDRESS
        spend_to = 'yiXJV2PodX4uuadFtt6e7wMTNkydHpp8ns'
        change = 'yanRmD5ZR66L1G51ixvXvUiJEmso5trn97'
        test_amounts = [0.0123, 0.123, 1.23, 5.123]
        test_fees = [226, 226, 374, 374]
        test_changes = [0.00769774, 0.17699774, 0.26999626, 2.90506399]

        coins = w.get_spendable_coins(domain=None, config=config,
                                      include_ps=True)
        for i in range(len(test_amounts)):
            amount_haks = to_haks(test_amounts[i])
            change_haks = to_haks(test_changes[i])
            outputs = [TxOutput(addr_type, spend_to, amount_haks)]
            tx = w.make_unsigned_transaction(coins, outputs, config=config)
            self._check_tx_io(tx, spend_to, amount_haks, test_fees[i],
                              change, change_haks)

        # check max amount
        amount_haks = to_haks(9.84805841)
        outputs = [TxOutput(addr_type, spend_to, amount_haks)]
        coins = w.get_spendable_coins(domain=None, config=config)
        tx = w.make_unsigned_transaction(coins, outputs, config=config)
        self._check_tx_io(tx, spend_to, amount_haks, 932)  # no change

        # check with include_ps
        amount_haks = to_haks(14.84811305)
        outputs = [TxOutput(addr_type, spend_to, amount_haks)]
        coins = w.get_spendable_coins(domain=None, config=config,
                                      include_ps=True)
        tx = w.make_unsigned_transaction(coins, outputs, config=config)
        self._check_tx_io(tx, spend_to, amount_haks, 20468,  # no change
                          include_ps=True)

        # check max amount with include_ps
        amount_haks = to_haks(14.84811306)  # NotEnoughFunds
        outputs = [TxOutput(addr_type, spend_to, amount_haks)]
        coins = w.get_spendable_coins(domain=None, config=config,
                                      include_ps=True)
        with self.assertRaises(NotEnoughFunds):
            tx = w.make_unsigned_transaction(coins, outputs, config=config)

    def test_make_unsigned_transaction_min_rounds(self):
        C_RNDS = PSCoinRounds.COLLATERAL
        w = self.wallet
        psman = w.psman
        coro = psman.find_untracked_ps_txs(log=False)
        asyncio.get_event_loop().run_until_complete(coro)
        config = self.config
        addr_type = TYPE_ADDRESS
        spend_to = 'yiXJV2PodX4uuadFtt6e7wMTNkydHpp8ns'

        amount_haks = to_haks(1)
        outputs = [TxOutput(addr_type, spend_to, amount_haks)]

        # check PSMinRoundsCheckFailed raises on inappropriate coins selection
        coins = w.get_spendable_coins(domain=None, config=config)
        with self.assertRaises(PSMinRoundsCheckFailed):
            tx = w.make_unsigned_transaction(coins, outputs, config=config,
                                             min_rounds=2)

        coins = w.get_spendable_coins(domain=None, config=config,
                                      min_rounds=C_RNDS)
        with self.assertRaises(PSMinRoundsCheckFailed):
            tx = w.make_unsigned_transaction(coins, outputs, config=config,
                                             min_rounds=0)

        coins = w.get_spendable_coins(domain=None, config=config, min_rounds=0)
        with self.assertRaises(PSMinRoundsCheckFailed):
            tx = w.make_unsigned_transaction(coins, outputs, config=config,
                                             min_rounds=1)

        coins = w.get_spendable_coins(domain=None, config=config, min_rounds=1)
        with self.assertRaises(PSMinRoundsCheckFailed):
            tx = w.make_unsigned_transaction(coins, outputs, config=config,
                                             min_rounds=2)

        # check different amounts and resulting fees
        test_amounts = [0.00001000]
        test_amounts += [0.00009640, 0.00005314, 0.00002269, 0.00005597,
                         0.00008291, 0.00009520, 0.00004102, 0.00009167,
                         0.00005735, 0.00001904, 0.00009245, 0.00002641,
                         0.00009115, 0.00003185, 0.00004162, 0.00003386,
                         0.00007656, 0.00006820, 0.00005044, 0.00006789]
        test_amounts += [0.00010000]
        test_amounts += [0.00839115, 0.00372971, 0.00654267, 0.00014316,
                         0.00491488, 0.00522527, 0.00627107, 0.00189861,
                         0.00092579, 0.00324560, 0.00032433, 0.00707310,
                         0.00737818, 0.00022760, 0.00235986, 0.00365554,
                         0.00975527, 0.00558680, 0.00506627, 0.00390911]
        test_amounts += [0.01000000]
        test_amounts += [0.74088413, 0.51044833, 0.81502578, 0.63804620,
                         0.38508255, 0.38838208, 0.20597175, 0.61405212,
                         0.23782970, 0.67059459, 0.29112021, 0.01425332,
                         0.44445507, 0.47530820, 0.04363325, 0.86807901,
                         0.82236638, 0.38637845, 0.04937359, 0.77029427]
        test_amounts += [1.00000000]
        test_amounts += [3.15592994, 1.51850574, 3.35457853, 1.20958635,
                         3.14494582, 3.43228624, 2.14182061, 1.30301733,
                         3.40340773, 1.21422826, 2.99683531, 1.3497565,
                         1.56368795, 2.60851955, 3.62983949, 3.13599564,
                         3.30433324, 2.67731925, 2.75157724, 1.48492533]

        test_fees = [99001, 90361, 94687, 97732, 94404, 91710, 90481, 95899,
                     90834, 94266, 98097, 90756, 97360, 90886, 96816, 95839,
                     96615, 92345, 93181, 94957, 93212, 90001, 60894, 27033,
                     45740, 85685, 8517, 77479, 72900, 10141, 7422, 75444,
                     67568, 92698, 62190, 77241, 64017, 34450, 24483, 41326,
                     93379, 9093, 100011, 12328, 55678, 98238, 96019, 92131,
                     62181, 3031, 95403, 17268, 41212, 88271, 74683, 54938,
                     69656, 36719, 92968, 64185, 62542, 62691, 71344, 1000,
                     10162, 50945, 45502, 42575, 8563, 74809, 20081, 99571,
                     62631, 78389, 19466, 25700, 32769, 50654, 19681, 3572,
                     69981, 70753, 45028, 8952]
        coins = w.get_spendable_coins(domain=None, config=config, min_rounds=2)
        for i in range(len(test_amounts)):
            amount_haks = to_haks(test_amounts[i])
            outputs = [TxOutput(addr_type, spend_to, amount_haks)]
            tx = w.make_unsigned_transaction(coins, outputs, config=config,
                                             min_rounds=2)
            self._check_tx_io(tx, spend_to, amount_haks,  # no change
                              test_fees[i],
                              min_rounds=2)
        assert min(test_fees) == 1000
        assert max(test_fees) == 100011

    def test_double_spend_warn(self):
        psman = self.wallet.psman
        assert psman.double_spend_warn == ''

        psman.state = PSStates.Mixing
        assert psman.double_spend_warn != ''
        psman.state = PSStates.Ready

        psman.last_mix_stop_time = time.time()
        assert psman.double_spend_warn != ''

        psman.last_mix_stop_time = time.time() - psman.wait_for_mn_txs_time
        assert psman.double_spend_warn == ''

    def test_broadcast_transaction(self):
        w = self.wallet
        psman = w.psman
        coro = psman.find_untracked_ps_txs(log=False)
        asyncio.get_event_loop().run_until_complete(coro)
        psman.network = NetworkBroadcastMock()

        # check spending ps_collateral currently in mixing
        c_outpoint, collateral = w.db.get_ps_collateral()
        psman.add_ps_spending_collateral(c_outpoint, 'uuid')
        inputs = w.get_spendable_coins([collateral[0]], self.config)
        dummy = w.dummy_address()
        outputs = [TxOutput(TYPE_ADDRESS, dummy, COLLATERAL_VAL)]
        tx = w.make_unsigned_transaction(inputs, outputs, self.config)

        psman.state = PSStates.Mixing
        with self.assertRaises(PSPossibleDoubleSpendError):
            coro = psman.broadcast_transaction(tx)
            asyncio.get_event_loop().run_until_complete(coro)

        psman.state = PSStates.Ready
        psman.last_mix_stop_time = time.time()
        with self.assertRaises(PSPossibleDoubleSpendError):
            coro = psman.broadcast_transaction(tx)
            asyncio.get_event_loop().run_until_complete(coro)

        psman.last_mix_stop_time = time.time() - psman.wait_for_mn_txs_time
        coro = psman.broadcast_transaction(tx)
        asyncio.get_event_loop().run_until_complete(coro)

        # check spending ps_denoms currently in mixing
        ps_denoms = w.db.get_ps_denoms()
        outpoint = list(ps_denoms.keys())[0]
        denom = ps_denoms[outpoint]
        psman.add_ps_spending_denom(outpoint, 'uuid')
        inputs = w.get_spendable_coins([denom[0]], self.config)
        dummy = w.dummy_address()
        outputs = [TxOutput(TYPE_ADDRESS, dummy, COLLATERAL_VAL)]
        tx = w.make_unsigned_transaction(inputs, outputs, self.config)

        psman.last_mix_stop_time = time.time()
        with self.assertRaises(PSPossibleDoubleSpendError):
            coro = psman.broadcast_transaction(tx)
            asyncio.get_event_loop().run_until_complete(coro)

    def test_sign_transaction(self):
        w = self.wallet
        psman = w.psman
        psman.config = self.config

        # test sign with no _keypairs_cache
        coro = psman.create_new_collateral_wfl()
        psman.state = PSStates.Mixing
        asyncio.get_event_loop().run_until_complete(coro)
        wfl = psman.new_collateral_wfl
        assert wfl.completed
        psman._cleanup_new_collateral_wfl(force=True)
        assert not psman.new_collateral_wfl

        # test sign with _keypairs_cache
        psman._cache_keypairs(password=None)
        coro = psman.create_new_collateral_wfl()
        asyncio.get_event_loop().run_until_complete(coro)
        wfl = psman.new_collateral_wfl
        assert wfl.completed
        psman._cleanup_new_collateral_wfl(force=True)
        assert not psman.new_collateral_wfl

    def test_calc_need_new_keypairs_cnt(self):
        w = self.wallet
        psman = w.psman
        psman.config = self.config
        psman.keep_amount = 15

        psman.mix_rounds = 2
        assert psman.calc_need_new_keypairs_cnt() == (372, 18)

        psman.mix_rounds = 3
        assert psman.calc_need_new_keypairs_cnt() == (529, 27)

        psman.mix_rounds = 4
        assert psman.calc_need_new_keypairs_cnt() == (657, 36)

        psman.mix_rounds = 5
        assert psman.calc_need_new_keypairs_cnt() == (783, 45)

        psman.mix_rounds = 16
        assert psman.calc_need_new_keypairs_cnt() == (2154, 136)

        coro = psman.find_untracked_ps_txs(log=False)  # find already mixed
        asyncio.get_event_loop().run_until_complete(coro)

        psman.mix_rounds = 2
        assert psman.calc_need_new_keypairs_cnt() == (327, 18)

        psman.mix_rounds = 3
        assert psman.calc_need_new_keypairs_cnt() == (604, 36)

        psman.mix_rounds = 4
        assert psman.calc_need_new_keypairs_cnt() == (931, 57)

        psman.mix_rounds = 5
        assert psman.calc_need_new_keypairs_cnt() == (1148, 71)

        psman.mix_rounds = 16
        assert psman.calc_need_new_keypairs_cnt() == (3576, 234)

    def test_check_need_new_keypairs(self):
        w = self.wallet
        psman = w.psman
        psman.config = self.config
        psman.mix_rounds = 2
        psman.keep_amount = 2
        coro = psman.find_untracked_ps_txs(log=False)
        asyncio.get_event_loop().run_until_complete(coro)
        psman.state = PSStates.Mixing

        # check when wallet has no password
        assert psman.check_need_new_keypairs() == (False, None)

        # mock wallet.has_password
        prev_has_password = w.has_password
        w.has_password = lambda: True
        assert psman.check_need_new_keypairs() == (True, KPStates.Empty)
        assert psman.keypairs_state == KPStates.NeedCache

        assert psman.check_need_new_keypairs() == (False, None)
        assert psman.keypairs_state == KPStates.NeedCache

        psman._keypairs_state = KPStates.Caching
        assert psman.check_need_new_keypairs() == (False, None)
        assert psman.keypairs_state == KPStates.Caching

        psman.keypairs_state = KPStates.Empty
        psman._cache_keypairs(password=None)
        assert psman.keypairs_state == KPStates.Ready

        assert psman.check_need_new_keypairs() == (False, None)
        assert psman.keypairs_state == KPStates.Ready

        psman.keypairs_state = KPStates.Unused
        assert psman.check_need_new_keypairs() == (False, None)
        assert psman.keypairs_state == KPStates.Ready

        # clean some keypairs and check again
        psman.keypairs_state = KPStates.Unused
        psman._keypairs_cache[KP_SPENDABLE] = {}
        assert psman.check_need_new_keypairs() == (True, KPStates.Unused)
        assert psman.keypairs_state == KPStates.NeedCache
        psman._cache_keypairs(password=None)

        psman.keypairs_state = KPStates.Unused
        psman._keypairs_cache[KP_PS_COINS] = {}
        assert psman.check_need_new_keypairs() == (True, KPStates.Unused)
        assert psman.keypairs_state == KPStates.NeedCache
        psman._cache_keypairs(password=None)

        psman.keypairs_state = KPStates.Unused
        psman._keypairs_cache[KP_PS_CHANGE] = {}
        assert psman.check_need_new_keypairs() == (True, KPStates.Unused)
        assert psman.keypairs_state == KPStates.NeedCache
        psman._cache_keypairs(password=None)

        w.has_password = prev_has_password

    def test_find_addrs_not_in_keypairs(self):
        w = self.wallet
        psman = w.psman
        psman.config = self.config
        psman.mix_rounds = 2
        psman.keep_amount = 2
        coro = psman.find_untracked_ps_txs(log=False)
        asyncio.get_event_loop().run_until_complete(coro)
        psman.state = PSStates.Mixing

        spendable = ['yRUktd39y5aU3JCgvZSx2NVfwPnv5nB2PF',
                     'yUV122HRSuL1scPnvnqSqoQ3TV8SWpRcYd',
                     'yXYkfpHkyR8PRE9GtLB6huKpGvS27wqmTw',
                     'yZwFosFcLXGWomh11ddUNgGBKCBp7yueyo',
                     'yeeU1n6Bm4Y3rz7Y1JZb9gQAbsc4uv4Y5j']

        ps_spendable = ['yextsfRiRvGD5Gv36yhZ96ErYmtKxf4Ffp',
                        'ydeK8hNyBKs1o7eoCr7hC3QAHBTXyJudGU',
                        'ydxBaF2BKMTn7VSUeR7A3zk1jxYt6zCPQ2',
                        'yTAotTVzQipPEHFaR1CcsKEMGtyrdf1mo7',
                        'yVgfDzEodzZh6vfgkGTkmPXv1eJCUytdQS']

        ps_coins = ['yiXJV2PodX4uuadFtt6e7wMTNkydHpp8ns',
                    'yXwT5tUAp84wTfFuAJdkedtqGXkh3RP5zv',
                    'yh8nPSALi6mhsFbK5WPoCzBWWjHwonp5iz',
                    'yazd3VRfghZ2VhtFmzpmnYifJXdhLTm9np',
                    'ygEFS3cdoDosJCTdR2moQ9kdrik4UUcNge']

        ps_change = ['yanRmD5ZR66L1G51ixvXvUiJEmso5trn97',
                     'yaWPA5UrUe1kbnLfAbpdYtm3ePZje4YQ1G',
                     'yePrR43WFHSAXirUFsXKxXXRk6wJKiYXzU',
                     'yiYQjsdvXpPGt72eSy7wACwea85Enpa1p4',
                     'ydsi9BZnNUBWNbxN3ymYp4wkuw8q37rTfK']

        psman._cache_keypairs(password=None)
        unk_addrs = [w.dummy_address()] * 2
        res = psman._find_addrs_not_in_keypairs(unk_addrs + spendable)
        assert res == {unk_addrs[0]}

        res = psman._find_addrs_not_in_keypairs(ps_coins + unk_addrs)
        assert res == {unk_addrs[0]}

        res = psman._find_addrs_not_in_keypairs(ps_change + unk_addrs)
        assert res == {unk_addrs[0]}

        res = psman._find_addrs_not_in_keypairs(ps_change + spendable)
        assert res == set()

    def test_cache_keypairs(self):
        w = self.wallet
        psman = w.psman
        psman.config = self.config

        psman.mix_rounds = 2
        psman.keep_amount = 2
        psman.state = PSStates.Mixing
        psman._cache_keypairs(password=None)
        # cache_results by types: spendable, ps spendable, ps coins, ps change
        cache_results = [137, 0, 259, 12]
        for i, cache_type in enumerate(KP_ALL_TYPES):
            assert len(psman._keypairs_cache[cache_type]) == cache_results[i]
        psman._cleanup_all_keypairs_cache()
        assert psman._keypairs_cache == {}
        psman.state = PSStates.Ready

        psman.mix_rounds = 4
        psman.keep_amount = 2
        psman.state = PSStates.Mixing
        psman._cache_keypairs(password=None)
        cache_results = [137, 0, 433, 24]
        for i, cache_type in enumerate(KP_ALL_TYPES):
            assert len(psman._keypairs_cache[cache_type]) == cache_results[i]
        psman._cleanup_all_keypairs_cache()
        assert psman._keypairs_cache == {}
        psman.state = PSStates.Ready

        psman.mix_rounds = 4
        psman.keep_amount = 10
        psman.state = PSStates.Mixing
        psman._cache_keypairs(password=None)
        cache_results = [137, 0, 474, 26]
        for i, cache_type in enumerate(KP_ALL_TYPES):
            assert len(psman._keypairs_cache[cache_type]) == cache_results[i]
        psman._cleanup_all_keypairs_cache()
        assert psman._keypairs_cache == {}
        psman.state = PSStates.Ready

        coro = psman.find_untracked_ps_txs(log=False)  # find already mixed
        asyncio.get_event_loop().run_until_complete(coro)

        psman.mix_rounds = 2
        psman.keep_amount = 2
        psman.state = PSStates.Mixing
        psman._cache_keypairs(password=None)
        cache_results = [5, 55, 111, 8]
        for i, cache_type in enumerate(KP_ALL_TYPES):
            assert len(psman._keypairs_cache[cache_type]) == cache_results[i]
        psman._cleanup_all_keypairs_cache()
        assert psman._keypairs_cache == {}
        psman.state = PSStates.Ready

        psman.mix_rounds = 4
        psman.keep_amount = 2
        psman.state = PSStates.Mixing
        psman._cache_keypairs(password=None)
        cache_results = [5, 132, 458, 31]
        for i, cache_type in enumerate(KP_ALL_TYPES):
            assert len(psman._keypairs_cache[cache_type]) == cache_results[i]
        psman._cleanup_all_keypairs_cache()
        assert psman._keypairs_cache == {}
        psman.state = PSStates.Ready

        psman.mix_rounds = 4
        psman.keep_amount = 10
        psman.state = PSStates.Mixing
        psman._cache_keypairs(password=None)
        cache_results = [5, 132, 901, 55]
        for i, cache_type in enumerate(KP_ALL_TYPES):
            assert len(psman._keypairs_cache[cache_type]) == cache_results[i]
        psman._cleanup_all_keypairs_cache()
        assert psman._keypairs_cache == {}
        psman.state = PSStates.Ready

    def test_cleanup_spendable_keypairs(self):
        # check spendable keypair for change is not cleaned up if change amount
        # is small (change output placed in middle of outputs sorted by bip69)
        w = self.wallet
        psman = w.psman
        psman.keep_amount = 16  # raise keep amount to make small change val
        psman.config = self.config
        coro = psman.find_untracked_ps_txs(log=False)
        asyncio.get_event_loop().run_until_complete(coro)
        psman.state = PSStates.Mixing

        # freeze some coins to make small change amount
        selected_coins_vals = [801806773, 50000000, 1000000]
        coins = w.get_utxos(None, excluded_addresses=w.frozen_addresses,
                            mature_only=True)
        coins = [c for c in coins if not w.is_frozen_coin(c) ]
        coins = [c for c in coins if not c['value'] in selected_coins_vals]
        w.set_frozen_state_of_coins(coins, True)

        # check spendable coins
        coins = w.get_utxos(None, excluded_addresses=w.frozen_addresses,
                            mature_only=True)
        coins = [c for c in coins if not w.is_frozen_coin(c) ]
        coins = sorted([c for c in coins if not w.is_frozen_coin(c)],
                       key=lambda x: -x['value'])
        assert coins[0]['address'] == 'yRUktd39y5aU3JCgvZSx2NVfwPnv5nB2PF'
        assert coins[0]['value'] == 801806773
        assert coins[1]['address'] == 'yeeU1n6Bm4Y3rz7Y1JZb9gQAbsc4uv4Y5j'
        assert coins[1]['value'] == 50000000
        assert coins[2]['address'] == 'yRUktd39y5aU3JCgvZSx2NVfwPnv5nB2PF'
        assert coins[2]['value'] == 1000000

        psman._cache_keypairs(password=None)
        spendable = ['yRUktd39y5aU3JCgvZSx2NVfwPnv5nB2PF',
                     'yeeU1n6Bm4Y3rz7Y1JZb9gQAbsc4uv4Y5j']
        assert sorted(psman._keypairs_cache[KP_SPENDABLE].keys()) == spendable

        coro = psman.create_new_denoms_wfl()
        asyncio.get_event_loop().run_until_complete(coro)
        wfl = psman.new_denoms_wfl
        assert wfl.completed

        txid = wfl.tx_order[0]
        tx0 = Transaction(wfl.tx_data[txid].raw_tx)
        txid = wfl.tx_order[1]
        tx1 = Transaction(wfl.tx_data[txid].raw_tx)
        txid = wfl.tx_order[2]
        tx2 = Transaction(wfl.tx_data[txid].raw_tx)
        txid = wfl.tx_order[3]
        tx3 = Transaction(wfl.tx_data[txid].raw_tx)

        outputs = tx0.outputs()
        assert len(outputs) == 41
        change = outputs[33]
        assert change.address == 'yRUktd39y5aU3JCgvZSx2NVfwPnv5nB2PF'

        outputs = tx1.outputs()
        assert len(outputs) == 24
        change = outputs[22]
        assert change.address == 'yRUktd39y5aU3JCgvZSx2NVfwPnv5nB2PF'

        outputs = tx2.outputs()
        assert len(outputs) == 18
        change = outputs[17]
        assert change.address == 'yRUktd39y5aU3JCgvZSx2NVfwPnv5nB2PF'

        outputs = tx3.outputs()
        assert len(outputs) == 8
        change = outputs[7]
        assert change.address == 'yRUktd39y5aU3JCgvZSx2NVfwPnv5nB2PF'

        spendable = ['yRUktd39y5aU3JCgvZSx2NVfwPnv5nB2PF']
        assert sorted(psman._keypairs_cache[KP_SPENDABLE].keys()) == spendable

    def test_filter_log_line(self):
        w = self.wallet
        test_line = ''
        assert filter_log_line(test_line) == test_line

        txid = bh2u(bytes(random.getrandbits(8) for _ in range(32)))
        test_line = 'load_and_cleanup rm %s ps data'
        assert filter_log_line(test_line % txid) == test_line % FILTERED_TXID

        txid = bh2u(bytes(random.getrandbits(8) for _ in range(32)))
        test_line = ('Error: err on checking tx %s from'
                     ' pay collateral workflow: wfl.uuid')
        assert filter_log_line(test_line % txid) == test_line % FILTERED_TXID

        test_line = 'Error: %s not found'
        filtered_line = filter_log_line(test_line % w.dummy_address())
        assert filtered_line == test_line % FILTERED_ADDR

    def test_is_mine_slow(self):
        w = self.wallet
        psman = w.psman
        psman.config = self.config

        last_recv_addr = w.db.get_receiving_addresses(slice_start=-1)[0]
        last_recv_index = w.get_address_index(last_recv_addr)[1]
        last_change_addr = w.db.get_change_addresses(slice_start=-1)[0]
        last_change_index = w.get_address_index(last_change_addr)[1]

        not_in_wallet_recv_addrs = []
        for ri in range(last_recv_index + 1, last_recv_index + 101):
            sequence = [0, ri]
            x_pubkey = w.keystore.get_xpubkey(*sequence)
            _, generated_addr = xpubkey_to_address(x_pubkey)
            assert not w.is_mine(generated_addr)
            not_in_wallet_recv_addrs.append(generated_addr)

        not_in_wallet_change_addrs = []
        for ci in range(last_change_index + 1, last_change_index + 101):
            sequence = [1, ci]
            x_pubkey = w.keystore.get_xpubkey(*sequence)
            _, generated_addr = xpubkey_to_address(x_pubkey)
            assert not w.is_mine(generated_addr)
            not_in_wallet_change_addrs.append(generated_addr)

        assert psman._is_mine_slow(not_in_wallet_recv_addrs[9])

        assert psman._is_mine_slow(not_in_wallet_change_addrs[9],
                                   for_change=True)

        for addr in not_in_wallet_recv_addrs:
            assert psman._is_mine_slow(addr)

        for addr in not_in_wallet_change_addrs:
            assert psman._is_mine_slow(addr, for_change=True)

    def test_calc_denoms_by_values(self):
        w = self.wallet
        psman = w.psman
        psman.config = self.config

        null_vals = {100001: 0, 1000010: 0, 10000100: 0,
                     100001000: 0, 1000010000: 0}
        assert psman.calc_denoms_by_values() == {}

        coro = psman.find_untracked_ps_txs(log=False)
        asyncio.get_event_loop().run_until_complete(coro)

        found_vals = {100001: 70, 1000010: 33, 10000100: 26,
                      100001000: 2, 1000010000: 0}
        assert psman.calc_denoms_by_values() == found_vals

    def test_min_new_denoms_from_coins_val(self):
        w = self.wallet
        psman = w.psman

        with self.assertRaises(Exception):
            psman.min_new_denoms_from_coins_val

        psman.config = self.config
        assert psman.min_new_denoms_from_coins_val == 110228

    def test_min_new_collateral_from_coins_val(self):
        w = self.wallet
        psman = w.psman

        with self.assertRaises(Exception):
            psman.min_new_collateral_from_coins_val

        psman.config = self.config
        assert psman.min_new_collateral_from_coins_val == 10193

    def test_check_enough_sm_denoms(self):
        w = self.wallet
        psman = w.psman
        psman.config = self.config

        denoms_by_vals = {}
        assert not psman.check_enough_sm_denoms(denoms_by_vals)

        denoms_by_vals = {100001: 5, 1000010: 0,
                          10000100: 5, 100001000: 0, 1000010000: 0}
        assert not psman.check_enough_sm_denoms(denoms_by_vals)

        denoms_by_vals = {100001: 4, 1000010: 5,
                          10000100: 0, 100001000: 0, 1000010000: 0}
        assert not psman.check_enough_sm_denoms(denoms_by_vals)

        denoms_by_vals = {100001: 5, 1000010: 5,
                          10000100: 0, 100001000: 0, 1000010000: 0}
        assert psman.check_enough_sm_denoms(denoms_by_vals)

        denoms_by_vals = {100001: 25, 1000010: 25,
                          10000100: 2, 100001000: 0, 1000010000: 0}
        assert psman.check_enough_sm_denoms(denoms_by_vals)

    def test_check_big_denoms_presented(self):
        w = self.wallet
        psman = w.psman
        psman.config = self.config

        denoms_by_vals = {}
        assert not psman.check_big_denoms_presented(denoms_by_vals)

        denoms_by_vals = {100001: 1, 1000010: 0,
                          10000100: 0, 100001000: 0, 1000010000: 0}
        assert not psman.check_big_denoms_presented(denoms_by_vals)

        denoms_by_vals = {100001: 0, 1000010: 1,
                          10000100: 0, 100001000: 0, 1000010000: 0}
        assert psman.check_big_denoms_presented(denoms_by_vals)

        denoms_by_vals = {100001: 0, 1000010: 0,
                          10000100: 1, 100001000: 0, 1000010000: 0}
        assert psman.check_big_denoms_presented(denoms_by_vals)

        denoms_by_vals = {100001: 0, 1000010: 0,
                          10000100: 1, 100001000: 0, 1000010000: 1}
        assert psman.check_big_denoms_presented(denoms_by_vals)

    def test_get_biggest_denoms_by_min_round(self):
        w = self.wallet
        psman = w.psman
        psman.config = self.config

        assert psman.get_biggest_denoms_by_min_round() == []

        coro = psman.find_untracked_ps_txs(log=False)
        asyncio.get_event_loop().run_until_complete(coro)

        coins = psman.get_biggest_denoms_by_min_round()
        res_r = [c['ps_rounds'] for c in coins]
        res_v = [c['value'] for c in coins]
        assert res_r == [0] * 22 + [2] * 39
        assert res_v == ([10000100] * 10 + [1000010] * 12 + [100001000] * 2 +
                         [10000100] * 16 + [1000010] * 21)
