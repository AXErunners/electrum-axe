#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Dash-Electrum - lightweight Dash client
# Copyright (C) 2019 Dash Developers
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

import asyncio
import gzip
import json
import os
import queue
import random
import re
import threading
import time
from aiorpcx import TaskGroup
from bls_py import bls
from collections import defaultdict, deque
from typing import Optional, Dict

from . import constants
from .blockchain import MissingHeader
from .dash_peer import DashPeer
from .dash_msg import SporkID
from .i18n import _
from .logging import Logger
from .simple_config import SimpleConfig
from .util import (log_exceptions, ignore_exceptions, SilentTaskGroup,
                   make_aiohttp_session, make_dir, bfh)


Y2099 = 4070908800  # Thursday, January 1, 2099 12:00:00 AM
MIN_PEERS_LIMIT = 2
MAX_PEERS_LIMIT = 8
MAX_PEERS_DEFAULT = 2
NUM_RECENT_PEERS = 20
NET_THREAD_MSG = 'must not be called from network thread'
DNS_OVER_HTTPS_ENDPOINTS = [
    'https://dns.google.com/resolve',
    'https://cloudflare-dns.com/dns-query',
]
ALLOWED_HOSTNAME_RE = re.compile(r'(?!-)[A-Z\d-]{1,63}(?<!-)$', re.IGNORECASE)
INSTANCE = None


def is_valid_hostname(hostname):
    if len(hostname) > 255:
        return False
    if hostname[-1] == ".":
        hostname = hostname[:-1]
    return all(ALLOWED_HOSTNAME_RE.match(x) for x in hostname.split("."))


def is_valid_portnum(portnum):
    if not portnum.isdigit():
        return False
    return 0 < int(portnum) < 65536


class DashSporks:
    '''Dash Sporks manager'''

    LOGGING_SHORTCUT = 'D'

    SPORKS_DEFAULTS = {
        SporkID.SPORK_2_INSTANTSEND_ENABLED.value: 0,               # ON
        SporkID.SPORK_3_INSTANTSEND_BLOCK_FILTERING.value: 0,       # ON
        SporkID.SPORK_5_INSTANTSEND_MAX_VALUE.value: 1000,          # 1000 Dash
        SporkID.SPORK_6_NEW_SIGS.value: Y2099,                      # OFF
        SporkID.SPORK_9_SUPERBLOCKS_ENABLED.value: Y2099,           # OFF
        SporkID.SPORK_12_RECONSIDER_BLOCKS.value: 0,                # 0 Blocks
        SporkID.SPORK_15_DETERMINISTIC_MNS_ENABLED.value: Y2099,    # OFF
        SporkID.SPORK_16_INSTANTSEND_AUTOLOCKS.value: Y2099,        # OFF
        SporkID.SPORK_17_QUORUM_DKG_ENABLED.value: Y2099,           # OFF
        SporkID.SPORK_19_CHAINLOCKS_ENABLED.value: Y2099,           # OFF
        SporkID.SPORK_20_INSTANTSEND_LLMQ_BASED.value: Y2099,       # OFF
    }

    def __init__(self):
        self.from_peers = set()
        self.gathered_sporks = {}

    def set_spork(self, spork_id, value, peer):
        spork_id = int(spork_id)
        if not SporkID.has_value(spork_id):
            self.logger.info(f'unknown spork id: {spork_id}')
        else:
            self.gathered_sporks[spork_id] = value
        self.from_peers.add(peer)

    def is_spork_active(self, spork_id):
        spork_id = int(spork_id)
        if not SporkID.has_value(spork_id):
            self.logger.info(f'unknown spork id: {spork_id}')
        value = self.gathered_sporks.get(spork_id)
        if value is None:
            value = self.SPORKS_DEFAULTS.get(spork_id)
        if value is None:
            return False
        return value < time.time()

    def is_spork_default(self, spork_id):
        spork_id = int(spork_id)
        if not SporkID.has_value(spork_id):
            self.logger.info(f'unknown spork id: {spork_id}')
        value = self.gathered_sporks.get(spork_id)
        if value is not None:
            return False
        value = self.SPORKS_DEFAULTS.get(spork_id)
        if value is None:
            return False
        return True

    def get_spork_value(self, spork_id):
        spork_id = int(spork_id)
        if not SporkID.has_value(spork_id):
            self.logger.info(f'unknown spork id: {spork_id}')
        value = self.gathered_sporks.get(spork_id)
        if value is None:
            value = self.SPORKS_DEFAULTS.get(spork_id)
        return value

    def is_new_sigs(self):
        return self.is_spork_active(SporkID.SPORK_6_NEW_SIGS)

    def as_dict(self):
        res = {}
        for k, v in self.SPORKS_DEFAULTS.items():
            name = f'{SporkID(k).name}' if SporkID.has_value(k) else str(k)
            res[k] = {'name': name, 'value': v,
                      'default': True, 'active': v < time.time()}
        for k, v in self.gathered_sporks.items():
            name = f'{SporkID(k).name}' if SporkID.has_value(k) else str(k)
            res[k] = {'name': name, 'value': v,
                      'default': False, 'active': v < time.time()}
        return res


class DashNet(Logger):
    '''The DashNet class manages a set of connections to remote peers
    each connected peer is handled by an DashPeer() object.
    '''

    LOGGING_SHORTCUT = 'D'

    def __init__(self, network, config: SimpleConfig=None):
        global INSTANCE
        INSTANCE = self

        Logger.__init__(self)

        if constants.net.TESTNET:
            self.default_port = 19999
            self.start_str = b'\xCE\xE2\xCA\xFF'
            self.spork_address = 'yjPtiKh2uwk3bDutTEA2q9mCtXyiZRWn55'
            self.dns_seeds = ['testnet-seed.dashdot.io',
                              'test.dnsseed.masternode.io']
        else:
            self.default_port = 9999
            self.start_str = b'\xBF\x0C\x6B\xBD'
            self.spork_address = 'Xgtyuk76vhuFW2iT7UAiHgNdWXCf3J34wh'
            self.dns_seeds = ['dnsseed.dash.org',
                              'dnsseed.dashdot.io',
                              'dnsseed.masternode.io']
        self.network = network
        self.proxy = None
        self.loop = network.asyncio_loop
        self._loop_thread = network._loop_thread
        self.config = network.config

        if config.path:
            self.data_dir = os.path.join(config.path, 'dash_net')
            make_dir(self.data_dir)
        else:
            self.data_dir = None

        self.main_taskgroup = None  # type: TaskGroup

        # locks
        self.restart_lock = asyncio.Lock()
        self.callback_lock = threading.Lock()
        self.recent_peers_lock = threading.RLock()       # <- re-entrant
        self.banlist_lock = threading.RLock()            # <- re-entrant
        self.peers_lock = threading.Lock()  # for mutating/iterating self.peers

        # callbacks set by the GUI
        self.callbacks = defaultdict(list)  # note: needs self.callback_lock

        # set of peers we have an ongoing connection with
        self.peers = {}  # type: Dict[str, DashPeer]
        self.connecting = set()
        self.peers_queue = None
        self.recent_peers = self._read_recent_peers()
        self.banlist = self._read_banlist()
        self.found_peers = set(self.recent_peers)

        self.is_cmd_dash_peers = not config.is_modifiable('dash_peers')
        self.read_conf()

        self._max_peers = self.config.get('dash_max_peers', MAX_PEERS_DEFAULT)
        # sporks manager
        self.sporks = DashSporks()

        # Recent islocks and chainlocks data
        self.recent_islock_invs = deque([], 200)
        self.recent_islocks = deque([], 200)

        # Activity data
        self.read_bytes = 0
        self.read_time = 0
        self.write_bytes = 0
        self.write_time = 0
        self.set_spork_time = 0

        # Dump network messages. Set at runtime from the console.
        self.debug = False

    def read_conf(self):
        config = self.config
        self.run_dash_net = config.get('run_dash_net', True)
        self.dash_peers = self.config.get('dash_peers', [])
        if self.is_cmd_dash_peers:
            self.use_static_peers = True
        else:
            self.use_static_peers = config.get('dash_use_static_peers', False)
        self.static_peers = []
        if self.use_static_peers:
            for p in self.dash_peers:
                if ':' not in p:
                    p = f'{p}:{self.default_port}'
                self.static_peers.append(p)

    def dash_peers_as_str(self):
        return ', '.join(self.dash_peers)

    def dash_peers_from_str(self, peers_str):
        peers = list(filter(lambda x: x, re.split(r';|,| |\n', peers_str)))
        for p in peers:
            if ':' in p:
                hostname, portnum = p.split(':', 1)
                if (not is_valid_hostname(hostname)
                        or not is_valid_portnum(portnum)):
                    return _('Invalid hostname: "{}"'.format(p))
            elif not is_valid_hostname(p):
                return _('Invalid hostname: "{}"'.format(p))
        return peers

    @staticmethod
    def get_instance() -> Optional['DashNet']:
        return INSTANCE

    def with_recent_peers_lock(func):
        def func_wrapper(self, *args, **kwargs):
            with self.recent_peers_lock:
                return func(self, *args, **kwargs)
        return func_wrapper

    def with_banlist_lock(func):
        def func_wrapper(self, *args, **kwargs):
            with self.banlist_lock:
                return func(self, *args, **kwargs)
        return func_wrapper

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
        for callback in callbacks:
            # FIXME: if callback throws, we will lose the traceback
            if asyncio.iscoroutinefunction(callback):
                asyncio.run_coroutine_threadsafe(callback(event, *args),
                                                 self.loop)
            else:
                self.loop.call_soon_threadsafe(callback, event, *args)

    @with_recent_peers_lock
    def _read_recent_peers(self):
        if not self.data_dir:
            return []
        path = os.path.join(self.data_dir, 'recent_peers')
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = f.read()
                return json.loads(data)
        except Exception as e:
            self.logger.info(f'failed to load recent_peers: {repr(e)}')
            return []

    @with_recent_peers_lock
    def _save_recent_peers(self):
        if not self.data_dir:
            return
        path = os.path.join(self.data_dir, 'recent_peers')
        s = json.dumps(self.recent_peers, indent=4, sort_keys=True)
        try:
            with open(path, 'w', encoding='utf-8') as f:
                f.write(s)
        except Exception as e:
            self.logger.info(f'failed to save recent_peers: {repr(e)}')

    @with_recent_peers_lock
    def _add_recent_peer(self, peer):
        # list is ordered
        if peer in self.recent_peers:
            self.recent_peers.remove(peer)
        self.recent_peers.insert(0, peer)
        self.recent_peers = self.recent_peers[:NUM_RECENT_PEERS]
        self._save_recent_peers()

    @with_banlist_lock
    def _read_banlist(self):
        if not self.data_dir:
            return {}
        path = os.path.join(self.data_dir, 'banlist.gz')
        try:
            with gzip.open(path, 'rb') as f:
                data = f.read()
                return json.loads(data.decode('utf-8'))
        except Exception as e:
            self.logger.info(f'failed to load banlist.gz: {repr(e)}')
            return {}

    @with_banlist_lock
    def _save_banlist(self):
        if not self.data_dir:
            return
        path = os.path.join(self.data_dir, 'banlist.gz')
        try:
            s = json.dumps(self.banlist, indent=4)
            with gzip.open(path, 'wb') as f:
                f.write(s.encode('utf-8'))
        except Exception as e:
            self.logger.info(f'failed to save banlist.gz: {repr(e)}')

    @with_banlist_lock
    def _add_banned_peer(self, dash_peer):
        peer = dash_peer.peer
        self.banlist[peer] = {
            'at': time.time(),
            'msg': dash_peer.ban_msg,
            'till': dash_peer.ban_till,
            'ua': dash_peer.version.user_agent.decode('utf-8'),
        }
        self._save_banlist()
        self.trigger_callback('dash-banlist-updated', 'added', peer)

    @with_banlist_lock
    def _remove_banned_peer(self, peer):
        if peer in self.banlist:
            del self.banlist[peer]
            self._save_banlist()
            self.trigger_callback('dash-banlist-updated', 'removed', peer)

    def status_icon(self):
        if self.run_dash_net:
            peers_cnt = len(self.peers)
            peers_percent = peers_cnt * 100 // MAX_PEERS_LIMIT
            if peers_percent == 0:
                return 'dash_net_0.png'
            elif peers_percent <= 25:
                return 'dash_net_1.png'
            elif peers_percent <= 50:
                return 'dash_net_2.png'
            elif peers_percent <= 75:
                return 'dash_net_3.png'
            else:
                return 'dash_net_4.png'
        else:
            return 'dash_net_off.png'

    @log_exceptions
    async def set_parameters(self):
        proxy = self.network.proxy
        run_dash_net = self.config.get('run_dash_net', True)
        if not self.is_cmd_dash_peers:
            dash_peers = self.config.get('dash_peers', [])
            use_static_peers = self.config.get('dash_use_static_peers', False)
        else:
            dash_peers = self.dash_peers
            use_static_peers = self.use_static_peers
        async with self.restart_lock:
            if (self.proxy != proxy
                    or self.run_dash_net != run_dash_net
                    or self.use_static_peers != use_static_peers
                    or self.dash_peers != dash_peers):
                await self._stop()
                await self._start()

    async def _start(self):
        self.read_conf()
        if not self.run_dash_net:
            return

        assert not self.main_taskgroup
        self.main_taskgroup = main_taskgroup = SilentTaskGroup()
        assert not self.peers
        assert not self.connecting and not self.peers_queue
        self.peers_queue = queue.Queue()
        self.proxy = self.network.proxy
        self.logger.info('starting Dash network')
        self.disconnected_static = {}
        async def main():
            try:
                async with main_taskgroup as group:
                    await group.spawn(self._maintain_peers())
                    await group.spawn(self._gather_sporks())
                    await group.spawn(self._monitor_activity())
            except Exception as e:
                self.logger.exception('')
                raise e

        asyncio.run_coroutine_threadsafe(main(), self.loop)
        self.trigger_callback('dash-net-updated', 'enabled')

    def start(self):
        asyncio.run_coroutine_threadsafe(self._start(), self.loop)

    @log_exceptions
    async def _stop(self, full_shutdown=False):
        if not self.main_taskgroup:
            return

        self.logger.info('stopping Dash network')
        try:
            await asyncio.wait_for(self.main_taskgroup.cancel_remaining(),
                                   timeout=2)
        except (asyncio.TimeoutError, asyncio.CancelledError) as e:
            self.logger.info(f'exc during main_taskgroup cancellation: '
                             f'{repr(e)}')
        self.main_taskgroup = None  # type: TaskGroup
        self.peeers = {}  # type: Dict[str, DashPeer]
        self.connecting.clear()
        self.peers_queue = None
        if not full_shutdown:
            self.trigger_callback('dash-net-updated', 'disabled')

    def stop(self):
        assert self._loop_thread != threading.current_thread(), NET_THREAD_MSG
        fut = asyncio.run_coroutine_threadsafe(self._stop(full_shutdown=True),
                                               self.loop)
        try:
            fut.result(timeout=2)
        except (asyncio.TimeoutError, asyncio.CancelledError): pass

    def run_from_another_thread(self, coro):
        assert self._loop_thread != threading.current_thread(), NET_THREAD_MSG
        fut = asyncio.run_coroutine_threadsafe(coro, self.loop)
        return fut.result()

    @property
    def peers_total(self):
        return len(self.connecting.union(self.peers))

    @property
    def max_peers(self):
        return self._max_peers

    @max_peers.setter
    def max_peers(self, cnt):
        cnt = MIN_PEERS_LIMIT if cnt < MIN_PEERS_LIMIT else cnt
        cnt = MAX_PEERS_LIMIT if cnt > MAX_PEERS_LIMIT else cnt
        self._max_peers = cnt
        self.config.set_key('dash_max_peers', cnt, True)

    async def find_peers(self):
        peers_set = set(self.peers.keys())
        peers_union = peers_set.union(self.connecting).union(self.found_peers)
        peers_union = peers_union.difference(self.banlist)
        peers_union_len = len(peers_union)
        if peers_union_len < 2:
            for seed in self.dns_seeds:
                new_ips = await self.resolve_dns_over_https(seed)
                if new_ips:
                    new_peers = [f'{ip}:{self.default_port}' for ip in new_ips]
                    self.found_peers = self.found_peers.union(new_peers)
                    break
        elif peers_union_len < self.max_peers:
            p = await self.get_random_peer()
            if not p.getaddr_done and not p.is_active():
                await p.send_msg('getaddr')
                p.getaddr_done = True

    async def queue_peers(self):
        if self.peers_total >= self.max_peers:
            return
        if self.use_static_peers:
            for peer in self.static_peers:
                if self.peers_total >= self.max_peers:
                    break
                if peer not in self.peers and peer not in self.connecting:
                    now = time.time()
                    disconnected_time = self.disconnected_static.get(peer)
                    if disconnected_time:
                        if now - disconnected_time < 10:
                            # make 10 sec interval on reconnect
                            continue
                        self.disconnected_static.pop(peer)
                    self._start_peer(peer)
        else:
            while self.peers_total < self.max_peers:
                inavailable = self.connecting.union(self.peers)
                available = self.found_peers.difference(inavailable)
                available = available.difference(self.banlist)
                if available:
                    self._start_peer(random.choice(list(available)))
                await asyncio.sleep(0.1)

    async def get_random_peer(self):
        '''Get one random peer'''
        peers_cnt = len(self.peers)
        while peers_cnt == 0:
            await asyncio.sleep(1)
            peers_cnt = len(self.peers)
        peers = list(self.peers.values())
        if peers_cnt == 1:
            return peers[0]
        randi = random.randint(0, peers_cnt-1)
        return peers[randi]

    async def _gather_sporks(self):
        while True:
            peers_cnt = len(self.peers)
            if peers_cnt == 0:
                await asyncio.sleep(1)
                continue
            if peers_cnt <= 2:
                gather_cnt = peers_cnt
            else:
                gather_cnt = round(peers_cnt * 0.51)
            if len(self.sporks.from_peers) < gather_cnt:
                p = await self.get_random_peer()
                if not p.sporks_done:
                    await p.send_msg('getsporks')
                    p.sporks_done = True
            await asyncio.sleep(1)

    async def _monitor_activity(self):
        read_time = self.read_time
        write_time = self.write_time
        set_spork_time = self.set_spork_time
        while True:
            await asyncio.sleep(2)
            new_read_time = self.read_time
            new_write_time = self.write_time
            new_set_spork_time = self.set_spork_time
            if read_time < new_read_time or write_time < new_write_time:
                read_time = new_read_time
                write_time = new_write_time
                self.trigger_callback('dash-net-activity')
            if set_spork_time < new_set_spork_time:
                set_spork_time = new_set_spork_time
                self.trigger_callback('sporks-activity')

    async def _maintain_peers(self):
        async def launch_already_queued_up_new_peers():
            while self.peers_queue.qsize() > 0:
                peer = self.peers_queue.get()
                await self.main_taskgroup.spawn(self._run_new_peer(peer))
        async def disconnect_excess_peers():
            while self.peers_total - self.max_peers > 0:
                p = await self.get_random_peer()
                await self.connection_down(p)
        while True:
            try:
                if not self.use_static_peers:
                    await self.find_peers()
                await self.queue_peers()
                await launch_already_queued_up_new_peers()
                await disconnect_excess_peers()
            except asyncio.CancelledError:
                # suppress spurious cancellations
                group = self.main_taskgroup
                if not group or group._closed:
                    raise
            await asyncio.sleep(0.1)

    def _start_peer(self, peer: str):
        if peer not in self.peers and peer not in self.connecting:
            self.connecting.add(peer)
            self.peers_queue.put(peer)

    async def _close_peer(self, dash_peer):
        if dash_peer:
            with self.peers_lock:
                if self.peers.get(dash_peer.peer) == dash_peer:
                    self.peers.pop(dash_peer.peer)
            await dash_peer.close()

    async def connection_down(self, dash_peer, msg=None):
        if msg is not None:
            await dash_peer.ban(msg)
        peer = dash_peer.peer
        await self._close_peer(dash_peer)
        if self.use_static_peers and peer in self.static_peers:
            self.disconnected_static[peer] = time.time()
        elif dash_peer.ban_msg:
            self._add_banned_peer(dash_peer)
        self.trigger_callback('dash-peers-updated', 'removed', peer)

    @ignore_exceptions  # do not kill main_taskgroup
    @log_exceptions
    async def _run_new_peer(self, peer):
        dash_peer = DashPeer(self, peer, self.proxy)
        # note: using longer timeouts here as DNS can sometimes be slow!
        timeout = self.network.get_network_timeout_seconds()
        try:
            await asyncio.wait_for(dash_peer.ready, timeout)
        except BaseException as e:
            self.logger.info(f'could not connect peer {peer} -- {repr(e)}')
            await dash_peer.close()
            return
        else:
            with self.peers_lock:
                assert peer not in self.peers
                self.peers[peer] = dash_peer
        finally:
            try:
                self.connecting.remove(peer)
            except KeyError:
                pass

        self._add_recent_peer(peer)
        self.trigger_callback('dash-peers-updated', 'added', peer)

    async def getmnlistd(self, get_mns=False):
        mn_list = self.network.mn_list
        llmq_offset = mn_list.LLMQ_OFFSET
        base_height = mn_list.protx_height if get_mns else mn_list.llmq_height

        height = self.network.get_local_height()
        if get_mns:
            if not height or height <= base_height:
                return
        else:
            if not height or height <= base_height + llmq_offset:
                return

        max_blocks = 2016  # block headers chunk size
        activation_height = constants.net.DIP3_ACTIVATION_HEIGHT
        if base_height <= 1:
            if height > activation_height:
                height = activation_height // max_blocks * max_blocks
        elif height - (base_height + llmq_offset) > max_blocks:
            height = (base_height + max_blocks) // max_blocks * max_blocks
        elif height - base_height > llmq_offset:
            height = height - llmq_offset

        try:
            params = (base_height, height)
            mn_list.sent_getmnlistd.put_nowait(params)
        except asyncio.QueueFull:
            self.logger.info('ignore excess getmnlistd request')
            return
        try:
            err = None
            p = await self.get_random_peer()
            res = await p.getmnlistd(*params)
        except Exception as e:
            err = f'getmnlistd(get_mns={get_mns} params={params}): {repr(e)}'
            res = None
        self.trigger_callback('mnlistdiff', {'error': err,
                                             'result': res,
                                             'params': params})

    async def resolve_dns_over_https(self, hostname, record_type='A'):
        params = {'ct': 'application/dns-json',
                  'name': hostname,
                  'type': record_type}
        for endpoint in DNS_OVER_HTTPS_ENDPOINTS:
            addresses = []
            async with make_aiohttp_session(proxy=self.proxy) as session:
                try:
                    async with session.get(endpoint, params=params) as result:
                        resp_json = await result.json(content_type=None)
                        answer = resp_json.get('Answer')
                        if answer:
                            addresses = [a.get('data') for a in answer]
                except Exception as e:
                    self.logger.info(f'make dns over https fail: {repr(e)}')
            if addresses:
                break
        return addresses

    async def get_hash(self, height, as_hex=False):
        chain = self.network.blockchain()
        block_hash = b''
        while not block_hash:
            try:
                block_hash = chain.get_hash(height)
            except MissingHeader as e:
                self.logger.info(f'get_hash: {repr(e)}')
                await self.network.request_chunk(height)
            await asyncio.sleep(0.1)
        if as_hex:
            return block_hash
        else:
            return bfh(block_hash)[::-1]

    @staticmethod
    def verify_islock(islock, quorum, request_id):
        msg_hash = islock.msg_hash(quorum, request_id)
        pubk = bls.PublicKey.from_bytes(quorum.quorumPublicKey)
        sig = bls.Signature.from_bytes(islock.sig)
        aggr_info = bls.AggregationInfo.from_msg_hash(pubk, msg_hash)
        sig.set_aggregation_info(aggr_info)
        return bls.BLS.verify(sig)
