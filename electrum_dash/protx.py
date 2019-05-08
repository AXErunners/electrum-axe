# -*- coding: utf-8 -*-

import asyncio
import ipaddress
import struct
import threading
from collections import namedtuple, defaultdict

from . import bitcoin
from .bitcoin import TYPE_ADDRESS, is_b58_address, b58_address_to_hash160
from .crypto import sha256d
from .dash_tx import (TxOutPoint, ProTxService, DashProRegTx, DashProUpServTx,
                      DashProUpRegTx, DashProUpRevTx, DashCbTx, SPEC_PRO_REG_TX,
                      SPEC_PRO_UP_SERV_TX, SPEC_PRO_UP_REG_TX, SPEC_PRO_UP_REV_TX)
from .transaction import Transaction, BCDataStream, SerializationError
from .util import bfh, bh2u, hfu
from .verifier import SPV
from .logging import Logger


PROTX_TX_TYPES = [
    SPEC_PRO_REG_TX,
    SPEC_PRO_UP_SERV_TX,
    SPEC_PRO_UP_REG_TX,
    SPEC_PRO_UP_REV_TX
]


class ProTxMNExc(Exception): pass


class PartialMerkleTree(namedtuple('PartialMerkleTree', 'total hashes flags')):
    '''Class representing CPartialMerkleTree of dashd'''
    @classmethod
    def read_bytes(cls, raw_bytes):
        vds = BCDataStream()
        vds.write(raw_bytes)

        total = vds.read_uint32()
        n_hashes = vds.read_compact_size()
        hashes = []
        for n in range(n_hashes):
            hashes.append(bh2u(vds.read_bytes(32)[::-1]))
        n_flags = vds.read_compact_size()
        flags = []
        for n in range(n_flags):
            flags_n = vds.read_uchar()
            for i in range(8):
                flags.append((flags_n >> i) & 1)
        if vds.can_read_more():
            raise SerializationError('extra junk at the '
                                     'end of PartialMerkleTree')
        return PartialMerkleTree(total, hashes, flags)


class ProTxMN:
    """
    Masternode data with next properties:

    alias               MN alias
    is_owned            This wallet is has owner_addr privk
    is_operated         This wallet must generate BLS privk
    bls_privk           Random BLS key

    type                MN type
    mode                MN mode
    collateral          TxOutPoint collateral data
    service             ProTxService masternode service data
    owner_addr          Address of MN owner pubkey
    pubkey_operator     BLS pubkey of MN operator
    voting_addr         Address of pubkey used for voting
    op_reward           Operator reward, a value from 0 to 10000
    payout_address      Payee address
    op_payout_address   Operator payee address

    protx_hash          Hash of ProRegTx transaction
    """

    fields = ('alias is_owned is_operated bls_privk type mode '
              'collateral service owner_addr pubkey_operator voting_addr '
              'op_reward payout_address op_payout_address protx_hash').split()

    def __init__(self):
        self.alias = ''
        self.is_owned = True
        self.is_operated = True
        self.bls_privk = None

        self.type = 0
        self.mode = 0
        self.collateral = TxOutPoint('', -1)
        self.service = ProTxService('', 9999)
        self.owner_addr = ''
        self.pubkey_operator = ''
        self.voting_addr = ''
        self.op_reward = 0
        self.payout_address = ''
        self.op_payout_address = ''

        self.protx_hash = ''

    def __repr__(self):
        f = ', '.join(['%s=%s' % (f, getattr(self, f)) for f in self.fields])
        return 'ProTxMN(%s)' % f

    def as_dict(self):
        res = {}
        for f in self.fields:
            v = getattr(self, f)
            if isinstance(v, tuple):
                res[f] = dict(v._asdict())
            else:
                res[f] = v
        return res

    @classmethod
    def from_dict(cls, d):
        mn = ProTxMN()
        for f in cls.fields:
            if f not in d:
                raise ProTxMNExc('Key %s is missing in supplied dict')
            v = d[f]
            if f == 'collateral':
                v['hash'] = bfh(v['hash'])[::-1]
                setattr(mn, f, TxOutPoint(**v))
            elif f == 'service':
                setattr(mn, f, ProTxService(**v))
            else:
                setattr(mn, f, v)
        return mn


class ProTxManagerExc(Exception): pass


class ProRegTxExc(Exception): pass


class ProTxManager(Logger):
    DIP3_DISABLED = 0
    DIP3_ENABLED = 1
    DIP3_UNKNOWN = 2

    def __init__(self, wallet):
        Logger.__init__(self)
        self.wallet = wallet
        self.network = None
        self.mns = {}  # Wallet MNs
        self.callback_lock = threading.Lock()
        self.manager_lock = threading.Lock()
        self.callbacks = defaultdict(list)
        self.network_subscribed = False
        self.protx_subscribed = False

        self.protx_base_height = 1
        self.protx_state = ProTxManager.DIP3_UNKNOWN
        self.protx_mns = {}  # Network registered MNs
        self.protx_info = {} # Detailed info on registered ProTxHash

        self.diffs_ready = False
        self.diff_deleted_mns = []
        self.diff_hashes = []
        self.info_hash = ''
        self.alias_updated = ''
        self.sml_hashes_cache = {}

    def with_manager_lock(func):
        def func_wrapper(self, *args, **kwargs):
            with self.manager_lock:
                return func(self, *args, **kwargs)
        return func_wrapper

    def clean_up(self):
        self.unsubscribe_from_network_updates()

    def subscribe_to_network_updates(self):
        if self.network and not self.protx_subscribed:
            if not self.network.is_connected():
                return
            self.protx_subscribed = True
            self.network.register_callback(self.on_protx_diff,
                                           ['protx-diff'])
            self.network.register_callback(self.on_protx_info,
                                           ['protx-info'])
            self.network.register_callback(self.on_network_updated,
                                           ['network_updated'])
            coro = self.network.request_protx_diff(self.protx_base_height)
            loop = self.network.asyncio_loop
            asyncio.run_coroutine_threadsafe(coro, loop)

    def unsubscribe_from_network_updates(self):
        if self.network:
            if self.protx_subscribed:
                self.protx_subscribed = False
                self.network.unregister_callback(self.on_protx_diff)
                self.network.unregister_callback(self.on_protx_info)
                self.network.unregister_callback(self.on_network_updated)
            if self.network_subscribed:
                self.network_subscribed = False
                self.network.unregister_callback(self.on_verified_tx)
                self.network.unregister_callback(self.on_network_status)

    def on_network_start(self, network):
        self.network = network
        if not self.network_subscribed:
            self.network_subscribed = True
            self.network.register_callback(self.on_verified_tx, ['verified'])
            self.network.register_callback(self.on_network_status, ['status'])

    def on_network_status(self, event):
        self.notify('manager-net-state-changed')

    async def on_network_updated(self, key):
        if not self.network or not self.diffs_ready:
            return
        await self.network.request_protx_diff(self.protx_base_height)

    def register_callback(self, callback, events):
        with self.callback_lock:
            for event in events:
                self.callbacks[event].append(callback)

    def unregister_callback(self, callback):
        with self.callback_lock:
            for callbacks in self.callbacks.values():
                if callback in callbacks:
                    callbacks.remove(callback)

    def trigger_callback(self, event, *args):
        with self.callback_lock:
            callbacks = self.callbacks[event][:]
        [callback(event, *args) for callback in callbacks]

    def notify(self, key):
        if key == 'manager-diff-updated':
            value = {
                'state': self.protx_state,
                'deleted_mns': self.diff_deleted_mns,
                'diff_hashes': self.diff_hashes,
            }
            self.diff_deleted_mns = []
            self.diff_hashes = []
        elif key == 'manager-info-updated':
            value = self.info_hash
            self.info_hash = ''
        elif key == 'manager-alias-updated':
            value = self.alias_updated
            self.alias_updated = ''
        elif key == 'manager-net-state-changed':
            value = True if self.network.is_connected() else False
        else:
            value = None
        self.trigger_callback(key, value)

    @with_manager_lock
    def load(self):
        """Load masternodes from wallet storage."""
        stored_mns = self.wallet.storage.get('protx_mns', {})
        self.mns = {k: ProTxMN.from_dict(d) for k, d in stored_mns.items()}

    def save(self, with_lock=False):
        """Save masternodes to wallet storage with lock."""
        if with_lock:
            with self.manager_lock:
                self._do_save()
        else:
            self._do_save()

    def _do_save(self):
        """Save masternodes to wallet storage."""
        stored_mns = {}
        for mn in self.mns.values():
            if not mn.alias:
                raise ProTxManagerExc('Attempt to write Masternode '
                                      'with empty alias')
            stored_mns[mn.alias] = mn.as_dict()
        self.wallet.storage.put('protx_mns', stored_mns)
        self.wallet.storage.write()

    @with_manager_lock
    def update_mn(self, alias, new_mn):
        new_alias = new_mn.alias
        if not new_alias:
            raise ProTxManagerExc('Masternode alias can not be empty')
        if len(new_alias) > 32:
            raise ProTxManagerExc('Masternode alias can not be longer '
                                  'than 32 characters')
        if not alias in self.mns.keys():
            raise ProTxManagerExc('Masternode with alias %s does not exists' %
                                  alias)
        self.mns[alias] = new_mn
        self.save()

    @with_manager_lock
    def add_mn(self, mn):
        alias = mn.alias
        if not alias:
            raise ProTxManagerExc('Masternode alias can not be empty')
        if len(alias) > 32:
            raise ProTxManagerExc('Masternode alias can not be longer '
                                  'than 32 characters')
        if alias in self.mns.keys():
            raise ProTxManagerExc('Masternode with alias %s already exists' %
                                  alias)
        self.mns[alias] = mn
        self.save()

    @with_manager_lock
    def remove_mn(self, alias):
        if not alias in self.mns.keys():
            raise ProTxManagerExc('Masternode with alias %s does not exists' %
                                  alias)
        del self.mns[alias]
        self.save()

    @with_manager_lock
    def rename_mn(self, alias, new_alias):
        if not new_alias:
            raise ProTxManagerExc('Masternode alias can not be empty')
        if len(new_alias) > 32:
            raise ProTxManagerExc('Masternode alias can not be longer '
                                  'than 32 characters')
        if not alias in self.mns.keys():
            raise ProTxManagerExc('Masternode with alias %s does not exists' %
                                  alias)
        if new_alias in self.mns.keys():
            raise ProTxManagerExc('Masternode with alias %s already exists' %
                                  new_alias)
        mn = self.mns[alias]
        mn.alias = new_alias
        self.mns[new_alias] = mn
        del self.mns[alias]
        self.save()

    def prepare_pro_reg_tx(self, alias):
        """Prepare and return ProRegTx from ProTxMN alias"""
        mn = self.mns.get('%s' % alias)
        if not mn:
            raise ProRegTxExc('Masternode alias %s not found' % alias)

        if mn.protx_hash:
            raise ProRegTxExc('Masternode already registered')

        if not mn.is_owned:
            raise ProRegTxExc('You not owner of this masternode')

        if not len(mn.collateral.hash) == 32:
            raise ProRegTxExc('Collateral hash is not set')

        if not mn.collateral.index >= 0:
            raise ProRegTxExc('Collateral index is not set')

        if mn.is_operated and not mn.service.ip:
            raise ProRegTxExc('Service IP address is not set')

        if not mn.owner_addr:
            raise ProRegTxExc('Owner address is not set')

        if not mn.pubkey_operator:
            raise ProRegTxExc('PubKeyOperator is not set')

        if not mn.voting_addr:
            raise ProRegTxExc('Voting address is not set')

        if not 0 <= mn.op_reward <= 10000:
            raise ProRegTxExc('operatorReward not in range 0-10000')

        if not mn.payout_address:
            raise ProRegTxExc('Payout address is not set')

        if not is_b58_address(mn.payout_address):
            raise ProRegTxExc('Payout address is not address')

        scriptPayout = bfh(Transaction.pay_script(TYPE_ADDRESS,
                                                  mn.payout_address))
        KeyIdOwner = b58_address_to_hash160(mn.owner_addr)[1]
        PubKeyOperator = bfh(mn.pubkey_operator)
        KeyIdVoting = b58_address_to_hash160(mn.voting_addr)[1]

        tx = DashProRegTx(1, mn.type, mn.mode, mn.collateral, mn.service.ip,
                          mn.service.port, KeyIdOwner, PubKeyOperator,
                          KeyIdVoting, mn.op_reward, scriptPayout,
                          b'\x00'*32, b'\x00'*65)

        tx.payload_sig_msg_part = ('%s|%s|%s|%s|' %
                                   (mn.payout_address,
                                    mn.op_reward,
                                    mn.owner_addr,
                                    mn.voting_addr))
        return tx

    def prepare_pro_up_srv_tx(self, mn):
        """Prepare and return ProUpServTx from ProTxMN alias"""
        if not mn.protx_hash:
            raise ProRegTxExc('Masternode has no proTxHash')

        if not mn.is_operated:
            raise ProRegTxExc('You are not operator of this masternode')

        if not mn.service.ip:
            raise ProRegTxExc('Service IP address is not set')

        if mn.op_payout_address:
            if not is_b58_address(mn.op_payout_address):
                raise ProRegTxExc('Operator payout address is not address')
            scriptOpPayout = bfh(Transaction.pay_script(TYPE_ADDRESS,
                                                        mn.op_payout_address))
        else:
            scriptOpPayout = b''

        tx = DashProUpServTx(1, bfh(mn.protx_hash)[::-1],
                             mn.service.ip, mn.service.port,
                             scriptOpPayout, b'\x00'*32, b'\x00'*96)
        return tx

    def prepare_pro_up_reg_tx(self, mn):
        """Prepare and return ProUpRegTx from ProTxMN alias"""
        if not mn.protx_hash:
            raise ProRegTxExc('Masternode has no proTxHash')

        if not mn.is_owned:
            raise ProRegTxExc('You not owner of this masternode')

        if not mn.pubkey_operator:
            raise ProRegTxExc('PubKeyOperator is not set')

        if not mn.voting_addr:
            raise ProRegTxExc('Voting address is not set')

        if not mn.payout_address:
            raise ProRegTxExc('Payout address is not set')

        if not is_b58_address(mn.payout_address):
            raise ProRegTxExc('Payout address is not address')

        scriptPayout = bfh(Transaction.pay_script(TYPE_ADDRESS,
                                                  mn.payout_address))
        PubKeyOperator = bfh(mn.pubkey_operator)
        KeyIdVoting = b58_address_to_hash160(mn.voting_addr)[1]

        tx = DashProUpRegTx(1, bfh(mn.protx_hash)[::-1], mn.mode,
                            PubKeyOperator, KeyIdVoting, scriptPayout,
                            b'\x00'*32, b'\x00'*65)
        return tx

    def prepare_pro_up_rev_tx(self, alias, reason):
        """Prepare and return ProUpRevTx from ProTxMN alias"""
        mn = self.mns.get('%s' % alias)
        if not mn:
            raise ProRegTxExc('Masternode alias %s not found' % alias)

        if not mn.protx_hash:
            raise ProRegTxExc('Masternode has no proTxHash')

        if not mn.is_operated:
            raise ProRegTxExc('You are not operator of this masternode')

        if not isinstance(reason, int) or not 0 <= reason <= 3:
            raise ProRegTxExc('Reason must be integer in range 0-3')

        tx = DashProUpRevTx(1, bfh(mn.protx_hash)[::-1], reason,
                            b'\x00'*32, b'\x00'*96)
        return tx

    async def on_protx_diff(self, key, value):
        '''Process and check protx.diff data, update protx_mns data/status'''
        base_height, height = value.get('params')
        if base_height != self.protx_base_height:
            return  # not this instance base height

        self.diff_deleted_mns = []
        self.diff_hashes = []

        error = value.get('error')
        if error:
            self.logger.error(f'on_protx_diff: error: {error}')
            self.protx_state = ProTxManager.DIP3_DISABLED
            self.notify('manager-diff-updated')
            return

        protx_diff = value.get('result')

        cbtx = Transaction(protx_diff.get('cbTx', ''))
        cbtx.deserialize()
        if cbtx.tx_type != 5:
            self.protx_base_height = height
            self.protx_state = ProTxManager.DIP3_DISABLED
            self.notify('manager-diff-updated')
            return

        cbtx_extra = cbtx.extra_payload
        if not isinstance(cbtx_extra, DashCbTx):
            self.logger.error('on_protx_diff: wrong CbTx extra_payload')
            self.protx_state = ProTxManager.DIP3_DISABLED
            self.notify('manager-diff-updated')
            return

        if cbtx_extra.version > 2:
            self.logger.error(f'on_protx_diff: unkonw CbTx '
                              f'version {cbtx_extra.version}')
            self.protx_state = ProTxManager.DIP3_DISABLED
            self.notify('manager-diff-updated')
            return

        protx_new = {k: v.copy() for k, v in self.protx_mns.items()}
        deleted_mns = protx_diff.get('deletedMNs', [])
        for del_hash in deleted_mns:
            if del_hash in protx_new:
                del protx_new[del_hash]

        for mn in protx_diff.get('mnList', []):
            protx_hash = mn.get('proRegTxHash', '')
            protx_new[protx_hash] = mn

        hash_sorted = [v for k,v in sorted(protx_new.items(),
                                           key=lambda x: bfh(x[0])[::-1])]

        # Calculate SML entries hashes
        sml_hashes = []
        for protx_entry in hash_sorted:
            proRegTxHash = protx_entry.get('proRegTxHash')
            confirmedHash = protx_entry.get('confirmedHash')
            service = protx_entry.get('service')
            pubKeyOperator = protx_entry.get('pubKeyOperator')
            votingAddress = protx_entry.get('votingAddress')
            isValid = protx_entry.get('isValid')
            cache_key = (proRegTxHash + confirmedHash + service +
                         pubKeyOperator + votingAddress + str(isValid))
            sml_hash = self.sml_hashes_cache.get(cache_key)
            if not sml_hash:
                sml_entry = bfh(proRegTxHash)[::-1]
                sml_entry += bfh(confirmedHash)[::-1]
                if ']' in service:          # IPv6
                    ip, port = service.split(']')
                    ip = ip[1:]             # remove opening square bracket
                    port = port[1:]         # remove colon before portnum
                    sml_entry += ipaddress.ip_address(ip).packed
                else:                       # IPv4
                    ip, port = service.split(':')
                    sml_entry += b'\x00'*10 + b'\xff'*2
                    sml_entry += ipaddress.ip_address(ip).packed
                sml_entry += struct.pack('>H', int(port))
                sml_entry += bfh(pubKeyOperator)
                sml_entry += bitcoin.b58_address_to_hash160(votingAddress)[1]
                sml_entry += b'\x01' if isValid else b'\x00'
                sml_hash = sha256d(sml_entry)
                self.sml_hashes_cache[cache_key] = sml_hash
            sml_hashes.append(sml_hash)

        # Calculate Merkle root for SML hashes
        hashes_len = len(sml_hashes)
        if hashes_len == 0:
            self.protx_base_height = height
            self.protx_state = ProTxManager.DIP3_ENABLED
            self.notify('manager-diff-updated')
            return

        while True:
            if hashes_len == 1:
                break
            if hashes_len % 2 == 1:
                sml_hashes.append(sml_hashes[-1])
                hashes_len += 1
            res = []
            for i in range(hashes_len//2):
                res.append(sha256d(sml_hashes[i*2] + sml_hashes[i*2+1]))
            sml_hashes = res
            hashes_len = len(sml_hashes)

        # Check merkle root to match protx.diff merkleRootMNList
        mr_calculated = hfu(sml_hashes[0][::-1])
        mr_diff = protx_diff.get('merkleRootMNList', '').encode('utf-8')
        if mr_calculated != mr_diff:
            self.logger.error('on_protx_diff: SML merkle root '
                              'differs from protx.diff merkle root')
            return

        # Check merkle root to match CbTx merkleRootMNList
        mr_cbtx = hfu(cbtx_extra.merkleRootMNList[::-1])
        if mr_calculated != mr_cbtx:
            self.logger.error('on_protx_diff: SML merkle root '
                              'differs from CbTx merkle root')
            return

        # Check CbTx in blockchain
        cbtx_txid = cbtx.txid()
        cbtx_height = cbtx_extra.height
        cbtx_merkle_tree = protx_diff.get('cbTxMerkleTree', '')
        pmt = PartialMerkleTree.read_bytes(bfh(cbtx_merkle_tree)).hashes

        if cbtx_txid != pmt[0]:
            self.logger.error('on_protx_diff: CbTx txid differs '
                              'from merkle tree hash 0')
            return

        pmt.pop(0)  # remove cbtx_txid
        if len(pmt) > 0:
            merkle_root_calculated = SPV.hash_merkle_root(pmt, cbtx_txid, 0)
        else:
            merkle_root_calculated = cbtx_txid

        cbtx_header = self.network.blockchain().read_header(cbtx_height)
        if not cbtx_header or not 'merkle_root' in cbtx_header:
            self.logger.error('on_protx_diff: can not read blockchain'
                              'header to check merkle root')
            return

        if cbtx_header['merkle_root'] != merkle_root_calculated:
            self.logger.error('on_protx_diff: CbTx calculated merkle root '
                              'differs from blockchain merkle root')
            return

        self.protx_mns = protx_new
        self.protx_base_height = cbtx_height
        self.protx_state = ProTxManager.DIP3_ENABLED
        self.diff_deleted_mns = deleted_mns
        self.diff_hashes = list(map(lambda x: x['proRegTxHash'],
                                    protx_diff.get('mnList', [])))

        for h in self.diff_deleted_mns:
            self.protx_info.pop(h, None)

        for h in self.protx_info.keys():
            await self.network.request_protx_info(h)

        if self.protx_base_height >= self.network.get_server_height():
            self.diffs_ready = True

        self.notify('manager-diff-updated')

    async def on_protx_info(self, key, value):
        self.info_hash = ''

        error = value.get('error')
        if error:
            self.logger.error('on_protx_info: error: {error}')
            return

        protx_info = value.get('result')
        protx_hash = protx_info.get('proTxHash', '')

        if not protx_hash:
            self.logger.error('on_protx_info: empty result')
            return

        self.protx_info[protx_hash] = protx_info
        self.info_hash = protx_hash
        self.notify('manager-info-updated')

    def on_verified_tx(self, event, wallet, tx_hash, tx_mined_status):
        tx = wallet.db.get_transaction(tx_hash)
        if not tx:
            return
        conf = tx_mined_status.conf
        if tx.tx_type in PROTX_TX_TYPES and tx.extra_payload and conf >= 1:
            tx.extra_payload.after_confirmation(tx, self)
