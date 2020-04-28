# Electrum - lightweight Bitcoin client
# Copyright (C) 2018 The Electrum Developers
#
# Permission is hereby granted, free of charge, to any person
# obtaining a copy of this software and associated documentation files
# (the "Software"), to deal in the Software without restriction,
# including without limitation the rights to use, copy, modify, merge,
# publish, distribute, sublicense, and/or sell copies of the Software,
# and to permit persons to whom the Software is furnished to do so,
# subject to the following conditions:
#
# The above copyright notice and this permission notice shall be
# included in all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
# EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
# MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
# NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS
# BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN
# ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN
# CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

import threading
import asyncio
import itertools
from collections import defaultdict
from typing import TYPE_CHECKING, Dict, Optional, Set, Tuple

from . import bitcoin
from .bitcoin import COINBASE_MATURITY, TYPE_ADDRESS, TYPE_PUBKEY
from .axe_ps import PSManager, PS_MIXING_TX_TYPES
from .axe_tx import PSCoinRounds, tx_header_to_tx_type
from .util import profiler, bfh, TxMinedInfo
from .protx import ProTxManager
from .transaction import Transaction, TxOutput
from .synchronizer import Synchronizer
from .verifier import SPV
from .blockchain import hash_header
from .i18n import _
from .logging import Logger

if TYPE_CHECKING:
    from .network import Network
    from .json_db import JsonDB


TX_HEIGHT_LOCAL = -2
TX_HEIGHT_UNCONF_PARENT = -1
TX_HEIGHT_UNCONFIRMED = 0

class AddTransactionException(Exception):
    pass


class UnrelatedTransactionException(AddTransactionException):
    def __str__(self):
        return _("Transaction is unrelated to this wallet.")


class AddressSynchronizer(Logger):
    """
    inherited by wallet
    """

    def __init__(self, db: 'JsonDB'):
        self.db = db
        self.network = None  # type: Network
        Logger.__init__(self)
        # verifier (SPV) and synchronizer are started in start_network
        self.synchronizer = None  # type: Synchronizer
        self.verifier = None  # type: SPV
        # locks: if you need to take multiple ones, acquire them in the order they are defined here!
        self.lock = threading.RLock()
        self.transaction_lock = threading.RLock()
        # Transactions pending verification.  txid -> tx_height. Access with self.lock.
        self.unverified_tx = defaultdict(int)
        # true when synchronized
        self.up_to_date = False
        # thread local storage for caching stuff
        self.threadlocal_cache = threading.local()
        self.psman = PSManager(self)
        self.protx_manager = ProTxManager(self)

        self._get_addr_balance_cache = {}

        self.load_and_cleanup()

    def with_transaction_lock(func):
        def func_wrapper(self, *args, **kwargs):
            with self.transaction_lock:
                return func(self, *args, **kwargs)
        return func_wrapper

    def load_and_cleanup(self):
        self.load_local_history()
        self.check_history()
        self.load_unverified_transactions()
        self.remove_local_transactions_we_dont_have()
        self.psman.load_and_cleanup()
        self.protx_manager.load()

    def is_mine(self, address):
        return self.db.is_addr_in_history(address)

    def get_addresses(self):
        return sorted(self.db.get_history())

    def get_address_history(self, addr):
        h = []
        # we need self.transaction_lock but get_tx_height will take self.lock
        # so we need to take that too here, to enforce order of locks
        with self.lock, self.transaction_lock:
            related_txns = self._history_local.get(addr, set())
            for tx_hash in related_txns:
                tx_height = self.get_tx_height(tx_hash).height
                islock = self.db.get_islock(tx_hash)
                h.append((tx_hash, tx_height, islock))
        return h

    def get_address_history_len(self, addr: str) -> int:
        """Return number of transactions where address is involved."""
        return len(self._history_local.get(addr, ()))

    def get_txin_address(self, txi):
        addr = txi.get('address')
        if addr and addr != "(pubkey)":
            return addr
        prevout_hash = txi.get('prevout_hash')
        prevout_n = txi.get('prevout_n')
        for addr in self.db.get_txo(prevout_hash):
            l = self.db.get_txo_addr(prevout_hash, addr)
            for n, v, is_cb in l:
                if n == prevout_n:
                    return addr
        return None

    def get_txout_address(self, txo: TxOutput):
        if txo.type == TYPE_ADDRESS:
            addr = txo.address
        elif txo.type == TYPE_PUBKEY:
            addr = bitcoin.public_key_to_p2pkh(bfh(txo.address))
        else:
            addr = None
        return addr

    def load_unverified_transactions(self):
        # review transactions that are in the history
        for addr in self.db.get_history():
            hist = self.db.get_addr_history(addr)
            for tx_hash, tx_height in hist:
                # add it in case it was previously unconfirmed
                self.add_unverified_tx(tx_hash, tx_height)

    def start_network(self, network):
        self.network = network
        if self.network is not None:
            self.synchronizer = Synchronizer(self)
            self.verifier = SPV(self.network, self)
            self.network.register_callback(self.on_blockchain_updated, ['blockchain_updated'])
            self.protx_manager.on_network_start(self.network)
            self.psman.on_network_start(self.network)
            axe_net = self.network.axe_net
            axe_net.register_callback(self.on_axe_islock, ['axe-islock'])

    def on_blockchain_updated(self, event, *args):
        self._get_addr_balance_cache = {}  # invalidate cache
        self.db.process_and_clear_islocks(self.get_local_height())

    def on_axe_islock(self, event, txid):
        if txid in self.db.islocks:
            return
        elif txid in self.unverified_tx or txid in self.db.verified_tx:
            self.logger.info(f'found tx for islock: {txid}')
            axe_net = self.network.axe_net
            if axe_net.verify_on_recent_islocks(txid):
                self.db.add_islock(txid)
                self._get_addr_balance_cache = {}  # invalidate cache
                self.storage.write()
                self.network.trigger_callback('verified-islock', self, txid)

    def find_islock_pair(self, txid):
        if txid in self.db.islocks:
            return
        else:
            axe_net = self.network.axe_net
            if axe_net.verify_on_recent_islocks(txid):
                self.db.add_islock(txid)
                self._get_addr_balance_cache = {}  # invalidate cache
                self.storage.write()
                self.network.trigger_callback('verified-islock', self, txid)

    def stop_threads(self):
        if self.network:
            if self.synchronizer:
                asyncio.run_coroutine_threadsafe(self.synchronizer.stop(), self.network.asyncio_loop)
                self.synchronizer = None
            if self.verifier:
                asyncio.run_coroutine_threadsafe(self.verifier.stop(), self.network.asyncio_loop)
                self.verifier = None
            self.network.unregister_callback(self.on_blockchain_updated)
            self.psman.on_stop_threads()
            axe_net = self.network.axe_net
            axe_net.unregister_callback(self.on_axe_islock)
            self.db.put('stored_height', self.get_local_height())

    def add_address(self, address):
        if not self.db.get_addr_history(address):
            self.db.history[address] = []
            self.set_up_to_date(False)
        if self.synchronizer:
            self.synchronizer.add(address)

    def get_conflicting_transactions(self, tx_hash, tx):
        """Returns a set of transaction hashes from the wallet history that are
        directly conflicting with tx, i.e. they have common outpoints being
        spent with tx. If the tx is already in wallet history, that will not be
        reported as a conflict.
        """
        conflicting_txns = set()
        with self.transaction_lock:
            for txin in tx.inputs():
                if txin['type'] == 'coinbase':
                    continue
                prevout_hash = txin['prevout_hash']
                prevout_n = txin['prevout_n']
                spending_tx_hash = self.db.get_spent_outpoint(prevout_hash, prevout_n)
                if spending_tx_hash is None:
                    continue
                # this outpoint has already been spent, by spending_tx
                # annoying assert that has revealed several bugs over time:
                assert self.db.get_transaction(spending_tx_hash), "spending tx not in wallet db"
                conflicting_txns |= {spending_tx_hash}
            if tx_hash in conflicting_txns:
                # this tx is already in history, so it conflicts with itself
                if len(conflicting_txns) > 1:
                    raise Exception('Found conflicting transactions already in wallet history.')
                conflicting_txns -= {tx_hash}
            return conflicting_txns

    def add_transaction(self, tx_hash, tx, allow_unrelated=False):
        assert tx_hash, tx_hash
        assert tx, tx
        assert tx.is_complete()
        # assert tx_hash == tx.txid()  # disabled as expensive; test done by Synchronizer.
        # we need self.transaction_lock but get_tx_height will take self.lock
        # so we need to take that too here, to enforce order of locks
        with self.lock, self.transaction_lock:
            # NOTE: returning if tx in self.transactions might seem like a good idea
            # BUT we track is_mine inputs in a txn, and during subsequent calls
            # of add_transaction tx, we might learn of more-and-more inputs of
            # being is_mine, as we roll the gap_limit forward
            is_coinbase = tx.inputs()[0]['type'] == 'coinbase'
            tx_height = self.get_tx_height(tx_hash).height
            if not allow_unrelated:
                # note that during sync, if the transactions are not properly sorted,
                # it could happen that we think tx is unrelated but actually one of the inputs is is_mine.
                # this is the main motivation for allow_unrelated
                is_mine = any([self.is_mine(self.get_txin_address(txin)) for txin in tx.inputs()])
                is_for_me = any([self.is_mine(self.get_txout_address(txo)) for txo in tx.outputs()])
                if not is_mine and not is_for_me:
                    raise UnrelatedTransactionException()
            # Find all conflicting transactions.
            # In case of a conflict,
            #     1. confirmed > mempool > local
            #     2. this new txn has priority over existing ones
            # When this method exits, there must NOT be any conflict, so
            # either keep this txn and remove all conflicting (along with dependencies)
            #     or drop this txn
            conflicting_txns = self.get_conflicting_transactions(tx_hash, tx)
            if conflicting_txns:
                existing_mempool_txn = any(
                    self.get_tx_height(tx_hash2).height in (TX_HEIGHT_UNCONFIRMED, TX_HEIGHT_UNCONF_PARENT)
                    for tx_hash2 in conflicting_txns)
                existing_confirmed_txn = any(
                    self.get_tx_height(tx_hash2).height > 0
                    for tx_hash2 in conflicting_txns)
                if existing_confirmed_txn and tx_height <= 0:
                    # this is a non-confirmed tx that conflicts with confirmed txns; drop.
                    return False
                if existing_mempool_txn and tx_height == TX_HEIGHT_LOCAL:
                    # this is a local tx that conflicts with non-local txns; drop.
                    return False
                # keep this txn and remove all conflicting
                to_remove = set()
                to_remove |= conflicting_txns
                for conflicting_tx_hash in conflicting_txns:
                    to_remove |= self.get_depending_transactions(conflicting_tx_hash)
                for tx_hash2 in to_remove:
                    self.remove_transaction(tx_hash2)
            # add inputs
            def add_value_from_prev_output():
                # note: this nested loop takes linear time in num is_mine outputs of prev_tx
                for addr in self.db.get_txo(prevout_hash):
                    outputs = self.db.get_txo_addr(prevout_hash, addr)
                    # note: instead of [(n, v, is_cb), ...]; we could store: {n -> (v, is_cb)}
                    for n, v, is_cb in outputs:
                        if n == prevout_n:
                            if addr and self.is_mine(addr):
                                self.db.add_txi_addr(tx_hash, addr, ser, v)
                                self._get_addr_balance_cache.pop(addr, None)  # invalidate cache
                            return
            for txi in tx.inputs():
                if txi['type'] == 'coinbase':
                    continue
                prevout_hash = txi['prevout_hash']
                prevout_n = txi['prevout_n']
                ser = prevout_hash + ':%d' % prevout_n
                self.db.set_spent_outpoint(prevout_hash, prevout_n, tx_hash)
                add_value_from_prev_output()
            # add outputs
            for n, txo in enumerate(tx.outputs()):
                v = txo.value
                ser = tx_hash + ':%d'%n
                addr = self.get_txout_address(txo)
                if addr and self.is_mine(addr):
                    self.db.add_txo_addr(tx_hash, addr, n, v, is_coinbase)
                    self._get_addr_balance_cache.pop(addr, None)  # invalidate cache
                    # give v to txi that spends me
                    next_tx = self.db.get_spent_outpoint(tx_hash, n)
                    if next_tx is not None:
                        self.db.add_txi_addr(next_tx, addr, ser, v)
                        self._add_tx_to_local_history(next_tx)
            # add to local history
            self._add_tx_to_local_history(tx_hash)
            # save
            is_new_tx = (tx_hash not in self.db.transactions)
            self.db.add_transaction(tx_hash, tx)
            if is_new_tx and self.psman.enabled:
                self.psman._add_tx_ps_data(tx_hash, tx)
            if is_new_tx and not self.is_local_tx(tx_hash) and self.network:
                self.network.trigger_callback('new_transaction', self, tx)
            return True

    def remove_transaction(self, tx_hash):
        def remove_from_spent_outpoints():
            # undo spends in spent_outpoints
            if tx is not None:
                # if we have the tx, this branch is faster
                for txin in tx.inputs():
                    if txin['type'] == 'coinbase':
                        continue
                    prevout_hash = txin['prevout_hash']
                    prevout_n = txin['prevout_n']
                    self.db.remove_spent_outpoint(prevout_hash, prevout_n)
            else:
                # expensive but always works
                for prevout_hash, prevout_n in self.db.list_spent_outpoints():
                    spending_txid = self.db.get_spent_outpoint(prevout_hash, prevout_n)
                    if spending_txid == tx_hash:
                        self.db.remove_spent_outpoint(prevout_hash, prevout_n)

        with self.transaction_lock:
            self.logger.info(f"removing tx from history {tx_hash}")
            if self.psman.enabled:
                self.psman._rm_tx_ps_data(tx_hash)
            tx = self.db.remove_transaction(tx_hash)
            remove_from_spent_outpoints()
            self._remove_tx_from_local_history(tx_hash)
            for addr in itertools.chain(self.db.get_txi(tx_hash), self.db.get_txo(tx_hash)):
                self._get_addr_balance_cache.pop(addr, None)  # invalidate cache
            self.db.remove_txi(tx_hash)
            self.db.remove_txo(tx_hash)

    def get_depending_transactions(self, tx_hash):
        """Returns all (grand-)children of tx_hash in this wallet."""
        with self.transaction_lock:
            children = set()
            for n in self.db.get_spent_outpoints(tx_hash):
                other_hash = self.db.get_spent_outpoint(tx_hash, n)
                children.add(other_hash)
                children |= self.get_depending_transactions(other_hash)
            return children

    def receive_tx_callback(self, tx_hash, tx, tx_height):
        self.add_unverified_tx(tx_hash, tx_height)
        self.add_transaction(tx_hash, tx, allow_unrelated=True)
        self.find_islock_pair(tx_hash)

    def receive_history_callback(self, addr, hist, tx_fees):
        old_hist_hashes = set()
        with self.lock:
            old_hist = self.get_address_history(addr)
            for tx_hash, height, islock in old_hist:
                if height > TX_HEIGHT_LOCAL:
                    old_hist_hashes.add(tx_hash)
                if (tx_hash, height) not in hist:
                    # make tx local
                    self.unverified_tx.pop(tx_hash, None)
                    self.db.remove_verified_tx(tx_hash)
                    if self.verifier:
                        self.verifier.remove_spv_proof_for_tx(tx_hash)
            self.db.set_addr_history(addr, hist)

        local_tx_hist_hashes = list()
        for tx_hash, tx_height in hist:
            if tx_hash not in old_hist_hashes and self.is_local_tx(tx_hash):
                local_tx_hist_hashes.append(tx_hash)
            # add it in case it was previously unconfirmed
            self.add_unverified_tx(tx_hash, tx_height)
            # if addr is new, we have to recompute txi and txo
            tx = self.db.get_transaction(tx_hash)
            if tx is None:
                continue
            self.add_transaction(tx_hash, tx, allow_unrelated=True)

        # Store fees
        self.db.update_tx_fees(tx_fees)
        # unsubscribe from spent ps coins addresses
        if self.psman.enabled:
            self.psman.unsubscribe_spent_addr(addr, hist)
        # trigger new_transaction cb when local tx hash appears in history
        if self.network:
            for tx_hash in local_tx_hist_hashes:
                self.find_islock_pair(tx_hash)
                tx = self.db.get_transaction(tx_hash)
                if tx:
                    self.network.trigger_callback('new_transaction', self, tx)

    @profiler
    def load_local_history(self):
        self._history_local = {}  # address -> set(txid)
        self._address_history_changed_events = defaultdict(asyncio.Event)  # address -> Event
        for txid in itertools.chain(self.db.list_txi(), self.db.list_txo()):
            self._add_tx_to_local_history(txid)

    @profiler
    def check_history(self):
        hist_addrs_mine = list(filter(lambda k: self.is_mine(k), self.db.get_history()))
        hist_addrs_not_mine = list(filter(lambda k: not self.is_mine(k), self.db.get_history()))
        for addr in hist_addrs_not_mine:
            self.db.remove_addr_history(addr)
        for addr in hist_addrs_mine:
            hist = self.db.get_addr_history(addr)
            for tx_hash, tx_height in hist:
                if self.db.get_txi(tx_hash) or self.db.get_txo(tx_hash):
                    continue
                tx = self.db.get_transaction(tx_hash)
                if tx is not None:
                    self.add_transaction(tx_hash, tx, allow_unrelated=True)

    def remove_local_transactions_we_dont_have(self):
        for txid in itertools.chain(self.db.list_txi(), self.db.list_txo()):
            tx_height = self.get_tx_height(txid).height
            if tx_height == TX_HEIGHT_LOCAL and not self.db.get_transaction(txid):
                self.remove_transaction(txid)

    def clear_history(self):
        with self.lock:
            with self.transaction_lock:
                self.db.clear_history()

    def get_txpos(self, tx_hash, islock):
        """Returns (height, txpos) tuple, even if the tx is unverified."""
        with self.lock:
            verified_tx_mined_info = self.db.get_verified_tx(tx_hash)
            if verified_tx_mined_info:
                return verified_tx_mined_info.height, verified_tx_mined_info.txpos
            elif tx_hash in self.unverified_tx:
                height = self.unverified_tx[tx_hash]
                if height > 0:
                    return (height, 0)
                elif not islock:
                    return ((1e10 - height), 0)
                else:
                    return (islock, 0)
            else:
                return (1e10+1, 0)

    def with_local_height_cached(func):
        # get local height only once, as it's relatively expensive.
        # take care that nested calls work as expected
        def f(self, *args, **kwargs):
            orig_val = getattr(self.threadlocal_cache, 'local_height', None)
            self.threadlocal_cache.local_height = orig_val or self.get_local_height()
            try:
                return func(self, *args, **kwargs)
            finally:
                self.threadlocal_cache.local_height = orig_val
        return f

    @with_local_height_cached
    def get_history(self, domain=None, config=None, group_ps=False):
        # get domain
        if domain is None:
            domain = self.get_addresses()
        domain = set(domain)
        # 1. Get the history of each address in the domain, maintain the
        #    delta of a tx as the sum of its deltas on domain addresses
        tx_deltas = defaultdict(int)
        tx_islocks = {}
        for addr in domain:
            h = self.get_address_history(addr)
            for tx_hash, height, islock in h:
                delta = self.get_tx_delta(tx_hash, addr)
                if delta is None or tx_deltas[tx_hash] is None:
                    tx_deltas[tx_hash] = None
                else:
                    tx_deltas[tx_hash] += delta
                if tx_hash not in tx_islocks:
                    tx_islocks[tx_hash] = islock
        # 2. create sorted history
        history = []
        for tx_hash in tx_deltas:
            delta = tx_deltas[tx_hash]
            tx_mined_status = self.get_tx_height(tx_hash)
            islock = tx_islocks[tx_hash]
            if islock:
                islock_sort = tx_hash if not tx_mined_status.conf else ''
            else:
                islock_sort = ''
            history.append((tx_hash, tx_mined_status, delta,
                            islock, islock_sort))
        history.sort(key=lambda x: (self.get_txpos(x[0], x[3]), x[4]),
                     reverse=True)
        # 3. add balance
        c, u, x = self.get_balance(domain)
        balance = c + u + x
        h2 = []
        if config:
            def_dip2 = not self.psman.unsupported
            show_dip2 = config.get('show_dip2_tx_type', def_dip2)
        else:
            show_dip2 = True  # for testing
        group_size = 0
        group_h2 = []
        group_txid = None
        group_txids = []
        group_delta = None
        group_balance = None
        hist_len = len(history)
        for i, (tx_hash, tx_mined_status, delta,
                islock, islock_sort) in enumerate(history):
            tx_type = 0
            if show_dip2:
                tx = self.db.get_transaction(tx_hash)
                if tx:
                    tx_type = tx_header_to_tx_type(bfh(tx.raw[:8]))
            if (group_ps or show_dip2) and not tx_type:  # prefer ProTx type
                tx_type, completed = self.db.get_ps_tx(tx_hash)

            if group_ps and tx_type in PS_MIXING_TX_TYPES:
                group_size += 1
                group_txids.append(tx_hash)
                if group_size == 1:
                    group_txid = tx_hash
                    group_balance = balance
                if delta is not None:
                    if group_delta is None:
                        group_delta = delta
                    else:
                        group_delta += delta
                if group_size > 1:
                    group_h2.append((tx_hash, tx_type, tx_mined_status,
                                     delta, balance, islock, group_txid, []))
                else:
                    group_h2.append((tx_hash, tx_type, tx_mined_status,
                                     delta, balance, islock, None, []))
                if i == hist_len - 1:  # last entry in the history
                    if group_size > 1:
                        group_data = group_h2[0][-1]  # last tuple element
                        group_data.append(group_delta)
                        group_data.append(group_balance)
                        group_data.append(group_txids)
                    h2.extend(group_h2)
            else:
                if group_size > 0:
                    if group_size > 1:
                        group_data = group_h2[0][-1]  # last tuple element
                        group_data.append(group_delta)
                        group_data.append(group_balance)
                        group_data.append(group_txids)
                    h2.extend(group_h2)
                    group_size = 0
                    group_h2 = []
                    group_txid = None
                    group_txids = []
                    group_delta = None
                    group_balance = None
                h2.append((tx_hash, tx_type, tx_mined_status,
                           delta, balance, islock, None, []))

            if balance is None or delta is None:
                balance = None
            else:
                balance -= delta
        h2.reverse()
        # fixme: this may happen if history is incomplete
        if balance not in [None, 0]:
            self.logger.info("Error: history not synchronized")
            return []

        return h2

    def _add_tx_to_local_history(self, txid):
        with self.transaction_lock:
            for addr in itertools.chain(self.db.get_txi(txid), self.db.get_txo(txid)):
                cur_hist = self._history_local.get(addr, set())
                cur_hist.add(txid)
                self._history_local[addr] = cur_hist
                self._mark_address_history_changed(addr)

    def _remove_tx_from_local_history(self, txid):
        with self.transaction_lock:
            for addr in itertools.chain(self.db.get_txi(txid), self.db.get_txo(txid)):
                cur_hist = self._history_local.get(addr, set())
                try:
                    cur_hist.remove(txid)
                except KeyError:
                    pass
                else:
                    self._history_local[addr] = cur_hist

    def _mark_address_history_changed(self, addr: str) -> None:
        # history for this address changed, wake up coroutines:
        self._address_history_changed_events[addr].set()
        # clear event immediately so that coroutines can wait() for the next change:
        self._address_history_changed_events[addr].clear()

    async def wait_for_address_history_to_change(self, addr: str) -> None:
        """Wait until the server tells us about a new transaction related to addr.

        Unconfirmed and confirmed transactions are not distinguished, and so e.g. SPV
        is not taken into account.
        """
        assert self.is_mine(addr), "address needs to be is_mine to be watched"
        await self._address_history_changed_events[addr].wait()

    def add_unverified_tx(self, tx_hash, tx_height):
        if self.db.is_in_verified_tx(tx_hash):
            if tx_height in (TX_HEIGHT_UNCONFIRMED, TX_HEIGHT_UNCONF_PARENT):
                with self.lock:
                    self.db.remove_verified_tx(tx_hash)
                if self.verifier:
                    self.verifier.remove_spv_proof_for_tx(tx_hash)
        else:
            with self.lock:
                # tx will be verified only if height > 0
                self.unverified_tx[tx_hash] = tx_height

    def remove_unverified_tx(self, tx_hash, tx_height):
        with self.lock:
            new_height = self.unverified_tx.get(tx_hash)
            if new_height == tx_height:
                self.unverified_tx.pop(tx_hash, None)

    def add_verified_tx(self, tx_hash: str, info: TxMinedInfo):
        # Remove from the unverified map and add to the verified map
        with self.lock:
            self.unverified_tx.pop(tx_hash, None)
            self.db.add_verified_tx(tx_hash, info)
        tx_mined_status = self.get_tx_height(tx_hash)
        self.network.trigger_callback('verified', self, tx_hash, tx_mined_status)

    def get_unverified_txs(self):
        '''Returns a map from tx hash to transaction height'''
        with self.lock:
            return dict(self.unverified_tx)  # copy

    def undo_verifications(self, blockchain, above_height):
        '''Used by the verifier when a reorg has happened'''
        txs = set()
        with self.lock:
            for tx_hash in self.db.list_verified_tx():
                info = self.db.get_verified_tx(tx_hash)
                tx_height = info.height
                if tx_height > above_height:
                    header = blockchain.read_header(tx_height)
                    if not header or hash_header(header) != info.header_hash:
                        self.db.remove_verified_tx(tx_hash)
                        # NOTE: we should add these txns to self.unverified_tx,
                        # but with what height?
                        # If on the new fork after the reorg, the txn is at the
                        # same height, we will not get a status update for the
                        # address. If the txn is not mined or at a diff height,
                        # we should get a status update. Unless we put tx into
                        # unverified_tx, it will turn into local. So we put it
                        # into unverified_tx with the old height, and if we get
                        # a status update, that will overwrite it.
                        self.unverified_tx[tx_hash] = tx_height
                        txs.add(tx_hash)
        return txs

    def get_local_height(self):
        """ return last known height if we are offline """
        cached_local_height = getattr(self.threadlocal_cache, 'local_height', None)
        if cached_local_height is not None:
            return cached_local_height
        return self.network.get_local_height() if self.network else self.db.get('stored_height', 0)

    def get_tx_height(self, tx_hash: str) -> TxMinedInfo:
        with self.lock:
            verified_tx_mined_info = self.db.get_verified_tx(tx_hash)
            if verified_tx_mined_info:
                conf = max(self.get_local_height() - verified_tx_mined_info.height + 1, 0)
                return verified_tx_mined_info._replace(conf=conf)
            elif tx_hash in self.unverified_tx:
                height = self.unverified_tx[tx_hash]
                return TxMinedInfo(height=height, conf=0)
            else:
                # local transaction
                return TxMinedInfo(height=TX_HEIGHT_LOCAL, conf=0)

    def is_local_tx(self, tx_hash: str):
        tx_mined_info = self.get_tx_height(tx_hash)
        if tx_mined_info.height == TX_HEIGHT_LOCAL:
            return True
        else:
            return False

    def set_up_to_date(self, up_to_date):
        with self.lock:
            self.up_to_date = up_to_date
        if self.network:
            self.network.notify('status')

    def is_up_to_date(self):
        with self.lock: return self.up_to_date

    def get_history_sync_state_details(self) -> Tuple[int, int]:
        if self.synchronizer:
            return self.synchronizer.num_requests_sent_and_answered()
        else:
            return 0, 0

    @with_transaction_lock
    def get_tx_delta(self, tx_hash, address):
        """effect of tx on address"""
        delta = 0
        # substract the value of coins sent from address
        d = self.db.get_txi_addr(tx_hash, address)
        for n, v in d:
            delta -= v
        # add the value of the coins received at address
        d = self.db.get_txo_addr(tx_hash, address)
        for n, v, cb in d:
            delta += v
        return delta

    @with_transaction_lock
    def get_tx_value(self, txid):
        """effect of tx on the entire domain"""
        delta = 0
        for addr in self.db.get_txi(txid):
            d = self.db.get_txi_addr(txid, addr)
            for n, v in d:
                delta -= v
        for addr in self.db.get_txo(txid):
            d = self.db.get_txo_addr(txid, addr)
            for n, v, cb in d:
                delta += v
        return delta

    def get_wallet_delta(self, tx: Transaction):
        """ effect of tx on wallet """
        is_relevant = False  # "related to wallet?"
        is_mine = False
        is_pruned = False
        is_partial = False
        v_in = v_out = v_out_mine = 0
        for txin in tx.inputs():
            addr = self.get_txin_address(txin)
            if self.is_mine(addr):
                is_mine = True
                is_relevant = True
                d = self.db.get_txo_addr(txin['prevout_hash'], addr)
                for n, v, cb in d:
                    if n == txin['prevout_n']:
                        value = v
                        break
                else:
                    value = None
                if value is None:
                    is_pruned = True
                else:
                    v_in += value
            else:
                is_partial = True
        if not is_mine:
            is_partial = False
        for o in tx.outputs():
            v_out += o.value
            if self.is_mine(o.address):
                v_out_mine += o.value
                is_relevant = True
        if is_pruned:
            # some inputs are mine:
            fee = None
            if is_mine:
                v = v_out_mine - v_out
            else:
                # no input is mine
                v = v_out_mine
        else:
            v = v_out_mine - v_in
            if is_partial:
                # some inputs are mine, but not all
                fee = None
            else:
                # all inputs are mine
                fee = v_in - v_out
        if not is_mine:
            fee = None
        return is_relevant, is_mine, v, fee

    def get_tx_fee(self, tx: Transaction) -> Optional[int]:
        if not tx:
            return None
        if hasattr(tx, '_cached_fee'):
            return tx._cached_fee
        with self.lock, self.transaction_lock:
            is_relevant, is_mine, v, fee = self.get_wallet_delta(tx)
            if fee is None:
                txid = tx.txid()
                fee = self.db.get_tx_fee(txid)
            # only cache non-None, as None can still change while syncing
            if fee is not None:
                tx._cached_fee = fee
        return fee

    def get_addr_io(self, address):
        with self.lock, self.transaction_lock:
            h = self.get_address_history(address)
            received = {}
            sent = {}
            for tx_hash, height, islock in h:
                l = self.db.get_txo_addr(tx_hash, address)
                for n, v, is_cb in l:
                    received[tx_hash + ':%d'%n] = (height, v, is_cb, islock)
            for tx_hash, height, islock in h:
                l = self.db.get_txi_addr(tx_hash, address)
                for txi, v in l:
                    sent[txi] = (height, islock)
        return received, sent

    def get_addr_utxo(self, address):
        coins, spent = self.get_addr_io(address)
        for txi in spent:
            coins.pop(txi)
        out = {}
        for txo, v in coins.items():
            ps_rounds = None
            ps_denom = self.db.get_ps_denom(txo)
            if ps_denom:
                ps_rounds = ps_denom[2]
            if ps_rounds is None:
                ps_collateral = self.db.get_ps_collateral(txo)
                if ps_collateral:
                    ps_rounds = int(PSCoinRounds.COLLATERAL)
            if ps_rounds is None:
                ps_other = self.db.get_ps_other(txo)
                if ps_other:
                    ps_rounds = int(PSCoinRounds.OTHER)
            tx_height, value, is_cb, islock = v
            prevout_hash, prevout_n = txo.split(':')
            x = {
                'address': address,
                'value': value,
                'prevout_n': int(prevout_n),
                'prevout_hash': prevout_hash,
                'height': tx_height,
                'coinbase': is_cb,
                'islock': islock,
                'ps_rounds': ps_rounds,
            }
            out[txo] = x
        return out

    # return the total amount ever received by an address
    def get_addr_received(self, address):
        received, sent = self.get_addr_io(address)
        return sum([v for height, v, is_cb, islock in received.values()])

    @with_local_height_cached
    def get_addr_balance(self, address, *, excluded_coins: Set[str] = None,
                         min_rounds=None, ps_denoms=None):
        """Return the balance of a bitcoin address:
        confirmed and matured, unconfirmed, unmatured

        min_rounds parameter consider values < 0 same as None
        """
        if min_rounds is not None and min_rounds < 0:
            min_rounds = None
        if ps_denoms is None:
            ps_denoms = {}
        # cache is only used if there are no excluded_coins or min_rounds
        if not excluded_coins and min_rounds is None:
            cached_value = self._get_addr_balance_cache.get(address)
            if cached_value:
                return cached_value
        if excluded_coins is None:
            excluded_coins = set()
        assert isinstance(excluded_coins, set), f"excluded_coins should be set, not {type(excluded_coins)}"
        received, sent = self.get_addr_io(address)
        c = u = x = 0
        local_height = self.get_local_height()
        for txo, (tx_height, v, is_cb, islock) in received.items():
            if min_rounds is not None and txo not in ps_denoms:
                continue
            if txo in excluded_coins:
                continue
            if is_cb and tx_height + COINBASE_MATURITY > local_height:
                x += v
            elif tx_height > 0 or islock:
                c += v
            else:
                u += v
            if txo in sent:
                sent_height, sent_islock = sent[txo]
                if sent_height > 0 or sent_islock:
                    c -= v
                else:
                    u -= v
        result = c, u, x
        # cache result.
        if not excluded_coins and min_rounds is None:
            # Cache needs to be invalidated if a transaction is added to/
            # removed from history; or on new blocks (maturity...);
            # or new islock
            self._get_addr_balance_cache[address] = result
        return result

    @with_local_height_cached
    def get_utxos(self, domain=None, *, excluded_addresses=None,
                  mature_only: bool = False, confirmed_only: bool = False,
                  nonlocal_only: bool = False,
                  consider_islocks=False, include_ps=False, min_rounds=None):
        coins = []
        if domain is None:
            if include_ps:
                domain = self.get_addresses()
            else:
                ps_addrs = self.db.get_ps_addresses(min_rounds=min_rounds)
                if min_rounds is not None:
                    domain = ps_addrs
                else:
                    domain = set(self.get_addresses()) - ps_addrs
        domain = set(domain)
        if excluded_addresses:
            domain = set(domain) - set(excluded_addresses)
        for addr in domain:
            utxos = self.get_addr_utxo(addr)
            for x in utxos.values():
                if confirmed_only:
                    if x['height'] <= 0:
                        if not consider_islocks:
                            continue
                        elif not x['islock']:
                            continue
                if nonlocal_only and x['height'] == TX_HEIGHT_LOCAL:
                    continue
                if mature_only and x['coinbase'] and x['height'] + COINBASE_MATURITY > self.get_local_height():
                    continue
                coins.append(x)
                continue
        return coins

    def get_balance(self, domain=None, *, excluded_addresses: Set[str] = None,
                    excluded_coins: Set[str] = None,
                    include_ps=True, min_rounds=None) -> Tuple[int, int, int]:
        '''min_rounds parameter consider values < 0 same as None'''
        ps_denoms = {}
        if min_rounds is not None:
            if min_rounds < 0:
                min_rounds = None
            else:
                ps_denoms = self.db.get_ps_denoms(min_rounds=min_rounds)
        if domain is None:
            if include_ps:
                domain = self.get_addresses()
            else:
                if min_rounds is not None:
                    domain = [ps_denom[0] for ps_denom in ps_denoms.values()]
                else:
                    ps_addrs = self.db.get_ps_addresses()
                    domain = set(self.get_addresses()) - ps_addrs
        if excluded_addresses is None:
            excluded_addresses = set()
        assert isinstance(excluded_addresses, set), f"excluded_addresses should be set, not {type(excluded_addresses)}"
        domain = set(domain) - excluded_addresses
        cc = uu = xx = 0
        for addr in domain:
            c, u, x = self.get_addr_balance(addr,
                                            excluded_coins=excluded_coins,
                                            min_rounds=min_rounds,
                                            ps_denoms=ps_denoms)
            cc += c
            uu += u
            xx += x
        return cc, uu, xx

    def is_used(self, address):
        return self.get_address_history_len(address) != 0

    def is_empty(self, address):
        c, u, x = self.get_addr_balance(address)
        return c+u+x == 0

    def synchronize(self):
        pass
