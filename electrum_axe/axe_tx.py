#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Axe-Electrum - lightweight Axe client
# Copyright (C) 2018 Axe Developers
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

import struct
from collections import namedtuple
from enum import IntEnum
from ipaddress import ip_address, IPv6Address
from bls_py import bls

from .util import bh2u, bfh
from .bitcoin import script_to_address, hash160_to_p2pkh, COIN
from .crypto import sha256d


def tx_header_to_tx_type(tx_header_bytes):
    tx_header = struct.unpack('<I', tx_header_bytes)[0]
    tx_type = (tx_header >> 16)
    if tx_type and (tx_header & 0x0000ffff) < 3:
        tx_type = 0
    return tx_type


def serialize_ip(ip):
    if ip.version == 4:
        return b'\x00'*10 + b'\xff'*2 + ip.packed
    else:
        return ip.packed


def service_to_ip_port(service):
    '''Convert str service to ipaddress, port tuple'''
    if ']' in service:                  # IPv6
        ip, port = service.split(']')
        ip = ip[1:]                     # remove opening square bracket
        port = port[1:]                 # remove colon before portnum
    else:                               # IPv4
        ip, port = service.split(':')
    return ip_address(ip), int(port)


def str_ip(ip):
    if type(ip) == IPv6Address and ip.ipv4_mapped:
        return str(ip.ipv4_mapped)
    else:
        return str(ip)


def to_compact_size(size):
    if size < 0:
        raise ValueError('Wroing size arg, must be >= 0')
    elif size < 253:
        return bytes([size])
    elif size < 2**16:
        return b'\xfd' + struct.pack('<H', size)
    elif size < 2**32:
        return b'\xfe' + struct.pack('<I', size)
    else:
        return b'\xff' + struct.pack('<Q', size)


def to_varbytes(_bytes):
    return to_compact_size(len(_bytes)) + _bytes


def read_varbytes(vds):
    return vds.read_bytes(vds.read_compact_size())


def read_outpoint(vds):
    return TxOutPoint.read_vds(vds)


def read_uint16_nbo(vds):
    (i,) = struct.unpack_from('>H', vds.input, vds.read_cursor)
    vds.read_cursor += struct.calcsize('>H')
    return i


class AxeTxError(Exception):
    """Thrown when there's a problem with Axe serialize/deserialize"""


class ProTxService (namedtuple('ProTxService', 'ip port')):
    '''Class representing Masternode service'''
    def __str__(self):
        if not self.ip:
            return '%s:%s' % (self.ip, self.port)
        ip = ip_address(self.ip)
        if ip.version == 4:
            return '%s:%s' % (self.ip, self.port)
        else:
            return '[%s]:%s' % (self.ip, self.port)

    def _asdict(self):
        return {'ip': self.ip, 'port': self.port}


# https://axe-docs.github.io/en/developer-reference#outpoint
class TxOutPoint(namedtuple('TxOutPoint', 'hash index')):
    '''Class representing tx input outpoint'''
    def __str__(self):
        d = self._asdict()
        return '%s:%s' % (d['hash'], d['index'])

    @property
    def is_null(self):
        return self.hash == b'\x00'*32 and self.index == -1

    @property
    def hash_is_null(self):
        return self.hash == b'\x00'*32

    def serialize(self):
        assert len(self.hash) == 32, \
            f'{len(self.hash)} not 32'
        index = 0xffffffff if self.index == -1 else self.index
        return (
            self.hash +                         # hash
            struct.pack('<I', index)            # index
        )

    @classmethod
    def read_vds(cls, vds):
        o_hash = vds.read_bytes(32)             # hash
        o_index = vds.read_uint32()             # index
        if o_index == 0xffffffff:
            o_index = -1
        return TxOutPoint(o_hash, o_index)

    def _asdict(self):
        return {
            'hash': bh2u(self.hash[::-1]) if self.hash else '',
            'index': self.index,
        }


class CTxIn(namedtuple('CTxIn', 'hash index scriptSig sequence')):
    '''Class representing tx input'''
    def __str__(self):
        return ('CTxIn: %s:%s, scriptSig=%s, sequeence=%s' %
                (bh2u(self.hash[::-1]), self.index,
                 self.scriptSig, self.sequence))

    @classmethod
    def read_vds(cls, vds):
        h = vds.read_bytes(32)                  # hash
        idx = vds.read_uint32()                 # index
        slen = vds.read_compact_size()
        scriptSig = vds.read_bytes(slen)        # scriptSig
        sequence = vds.read_uint32()            # sequence
        return CTxIn(h, idx, scriptSig, sequence)

    def serialize(self):
        assert len(self.hash) == 32, \
            f'{len(self.hash)} not 32'
        return (
            self.hash +                         # hash
            struct.pack('<I', self.index) +     # index
            to_varbytes(self.scriptSig) +       # scriptSig
            struct.pack('<I', self.sequence)    # sequence
        )


class CTxOut(namedtuple('CTxOut', 'value scriptPubKey')):
    '''Class representing tx output'''
    def __str__(self):
        return ('CTxOut: %s:%s, scriptPubKey=%s, sequeence=%s' %
                (bh2u(self.hash[::-1]), self.index,
                 self.scriptPubKey, self.sequence))

    @classmethod
    def read_vds(cls, vds):
        value = vds.read_int64()                # value
        slen = vds.read_compact_size()
        scriptPubKey = vds.read_bytes(slen)     # scriptPubKey
        return CTxOut(value, scriptPubKey)

    def serialize(self):
        return (
            struct.pack('<q', self.value) +     # value
            to_varbytes(self.scriptPubKey)      # scriptPubKey
        )


# https://github.com/axerunners/dips/blob/master/dip-0002-special-transactions.md
class ProTxBase:
    '''Base Class representing DIP2 Special Transactions'''
    def __init__(self, *args, **kwargs):
        if args and not kwargs:
            argsl = list(args)
            for f in self.__slots__:
                setattr(self, f, argsl.pop(0))
        elif kwargs and not args:
            for f in self.__slots__:
                setattr(self, f, kwargs[f])
        else:
            raise ValueError('__init__ works with all args or all kwargs')

    def _asdict(self):
        d = {}
        for f in self.__slots__:
            v = getattr(self, f)
            if isinstance(v, (bytes, bytearray)):
                v = bh2u(v)
            elif isinstance(v, TxOutPoint):
                v = v._asdict()
            d[f] = v
        return d

    def update_with_tx_data(self, *args, **kwargs):
        '''Update spec tx data based on main tx data inputs/outputs changes'''

    def check_after_tx_prepared(self, *args, **kwargs):
        '''Check spec tx after inputs/outputs is set (can rise error msg)'''

    def update_before_sign(self, *args, **kwargs):
        '''Update spec tx signature when password is accessible'''

    def after_confirmation(self, *args, **kwargs):
        '''Run after confirmation of spec tx'''


class AxeProRegTx(ProTxBase):
    '''Class representing DIP3 ProRegTx'''

    __slots__ = ('version type mode collateralOutpoint '
                 'ipAddress port KeyIdOwner PubKeyOperator '
                 'KeyIdVoting operatorReward scriptPayout '
                 'inputsHash payloadSig').split()

    def __init__(self, *args, **kwargs):
        super(AxeProRegTx, self).__init__(*args, **kwargs)
        self.payload_sig_msg_part = ''

    def __str__(self):
        return ('ProRegTx Version: %s\n'
                'type: %s, mode: %s\n'
                'collateral: %s\n'
                'ipAddress: %s, port: %s\n'
                'KeyIdOwner: %s\n'
                'PubKeyOperator: %s\n'
                'KeyIdVoting: %s\n'
                'operatorReward: %s\n'
                'scriptPayout: %s\n'
                % (self.version, self.type, self.mode,
                   self.collateralOutpoint,
                   self.ipAddress, self.port,
                   bh2u(self.KeyIdOwner),
                   bh2u(self.PubKeyOperator),
                   bh2u(self.KeyIdVoting),
                   self.operatorReward,
                   bh2u(self.scriptPayout)))

    def serialize(self, full=True):
        assert len(self.KeyIdOwner) == 20, \
            f'{len(self.KeyIdOwner)} not 20'
        assert len(self.PubKeyOperator) == 48, \
            f'{len(self.PubKeyOperator)} not 48'
        assert len(self.KeyIdVoting) == 20, \
            f'{len(self.KeyIdVoting)} not 20'
        assert len(self.inputsHash) == 32, \
            f'{len(self.inputsHash)} not 32'
        ipAddress = ip_address(self.ipAddress)
        ipAddress = serialize_ip(ipAddress)
        payloadSig = to_varbytes(self.payloadSig) if full else b''
        return (
            struct.pack('<H', self.version) +           # version
            struct.pack('<H', self.type) +              # type
            struct.pack('<H', self.mode) +              # mode
            self.collateralOutpoint.serialize() +       # collateralOutpoint
            ipAddress +                                 # ipAddress
            struct.pack('>H', self.port) +              # port
            self.KeyIdOwner +                           # KeyIdOwner
            self.PubKeyOperator +                       # PubKeyOperator
            self.KeyIdVoting +                          # KeyIdVoting
            struct.pack('<H', self.operatorReward) +    # operatorReward
            to_varbytes(self.scriptPayout) +            # scriptPayout
            self.inputsHash +                           # inputsHash
            payloadSig                                  # payloadSig
        )

    @classmethod
    def read_vds(cls, vds):
        version = vds.read_uint16()                     # version
        mn_type = vds.read_uint16()                     # type
        mode = vds.read_uint16()                        # mode
        collateralOutpoint = read_outpoint(vds)         # collateralOutpoint
        ipAddress = vds.read_bytes(16)                  # ipAddress
        port = read_uint16_nbo(vds)                     # port
        KeyIdOwner = vds.read_bytes(20)                 # KeyIdOwner
        PubKeyOperator = vds.read_bytes(48)             # PubKeyOperator
        KeyIdVoting = vds.read_bytes(20)                # KeyIdVoting
        operatorReward = vds.read_uint16()              # operatorReward
        scriptPayout = read_varbytes(vds)               # scriptPayout
        inputsHash = vds.read_bytes(32)                 # inputsHash
        payloadSig = read_varbytes(vds)                 # payloadSig

        ipAddress = ip_address(bytes(ipAddress))
        if ipAddress.ipv4_mapped:
            ipAddress = str(ipAddress.ipv4_mapped)
        else:
            ipAddress = str(ipAddress)
        return AxeProRegTx(version, mn_type, mode, collateralOutpoint,
                            ipAddress, port, KeyIdOwner, PubKeyOperator,
                            KeyIdVoting, operatorReward, scriptPayout,
                            inputsHash, payloadSig)

    def update_with_tx_data(self, tx):
        if self.collateralOutpoint.hash_is_null:
            found_idx = -1
            for i, o in enumerate(tx.outputs()):
                if o.value == 1000 * COIN:
                    found_idx = i
                    break
            self.collateralOutpoint = TxOutPoint(b'\x00'*32, found_idx)

        outpoints = [TxOutPoint(bfh(i['prevout_hash'])[::-1], i['prevout_n'])
                     for i in tx.inputs()]
        outpoints_ser = [o.serialize() for o in outpoints]
        self.inputsHash = sha256d(b''.join(outpoints_ser))

    def check_after_tx_prepared(self, tx):
        outpoints = [TxOutPoint(bfh(i['prevout_hash'])[::-1], i['prevout_n'])
                     for i in tx.inputs()]

        outpoints_str = [str(o) for o in outpoints]
        if str(self.collateralOutpoint) in outpoints_str:
            raise AxeTxError('Collateral outpoint used as ProRegTx input.\n'
                              'Please select coins to spend at Coins tab '
                              'of freeze collateral at Addresses tab.')

    def update_before_sign(self, tx, wallet, password):
        if self.payloadSig == b'':
            return
        coins = wallet.get_utxos(domain=None, excluded_addresses=False,
                                 mature_only=True, confirmed_only=True)

        c_hash = bh2u(self.collateralOutpoint.hash[::-1])
        c_index = self.collateralOutpoint.index
        coins = list(filter(lambda x: (x['prevout_hash'] == c_hash
                                       and x['prevout_n'] == c_index),
                            coins))
        if len(coins) == 1:
            coll_address = coins[0]['address']
            payload_hash = bh2u(sha256d(self.serialize(full=False))[::-1])
            payload_sig_msg = self.payload_sig_msg_part + payload_hash
            self.payloadSig = wallet.sign_message(coll_address,
                                                  payload_sig_msg,
                                                  password)

    def after_confirmation(self, tx, manager):
        found = manager.find_mn_by_proregtx(tx)
        if found:
            mn, protx_hash, collateral = found
            with manager.manager_lock:
                mn.protx_hash = protx_hash
                if collateral:
                    mn.collateral = collateral
                manager.save(with_lock=False)
                manager.alias_updated = mn.alias
            manager.notify('manager-alias-updated')


class AxeProUpServTx(ProTxBase):
    '''Class representing DIP3 ProUpServTx'''

    __slots__ = ('version proTxHash ipAddress port '
                 'scriptOperatorPayout inputsHash '
                 'payloadSig').split()

    def __str__(self):
        res = ('ProUpServTx Version: %s\n'
               'proTxHash: %s\n'
               'ipAddress: %s, port: %s\n'
               % (self.version,
                  bh2u(self.proTxHash[::-1]),
                  self.ipAddress, self.port))
        if self.scriptOperatorPayout:
            res += ('scriptOperatorPayout: %s\n' %
                    bh2u(self.scriptOperatorPayout))
        return res

    def serialize(self, full=True):
        assert len(self.proTxHash) == 32, \
            f'{len(self.proTxHash)} not 32'
        assert len(self.inputsHash) == 32, \
            f'{len(self.inputsHash)} not 32'
        assert len(self.payloadSig) == 96, \
            f'{len(self.payloadSig)} not 96'
        ipAddress = ip_address(self.ipAddress)
        ipAddress = serialize_ip(ipAddress)
        payloadSig = self.payloadSig if full else b''
        return (
            struct.pack('<H', self.version) +           # version
            self.proTxHash +                            # proTxHash
            ipAddress +                                 # ipAddress
            struct.pack('>H', self.port) +              # port
            to_varbytes(self.scriptOperatorPayout) +    # scriptOperatorPayout
            self.inputsHash +                           # inputsHash
            payloadSig                                  # payloadSig
        )

    @classmethod
    def read_vds(cls, vds):
        version = vds.read_uint16()                     # version
        proTxHash = vds.read_bytes(32)                  # proTxHash
        ipAddress = vds.read_bytes(16)                  # ipAddress
        port = read_uint16_nbo(vds)                     # port
        scriptOperatorPayout = read_varbytes(vds)       # scriptOperatorPayout
        inputsHash = vds.read_bytes(32)                 # inputsHash
        payloadSig = vds.read_bytes(96)                 # payloadSig

        ipAddress = ip_address(bytes(ipAddress))
        if ipAddress.ipv4_mapped:
            ipAddress = str(ipAddress.ipv4_mapped)
        else:
            ipAddress = str(ipAddress)
        return AxeProUpServTx(version, proTxHash, ipAddress, port,
                               scriptOperatorPayout, inputsHash, payloadSig)

    def update_with_tx_data(self, tx):
        outpoints = [TxOutPoint(bfh(i['prevout_hash'])[::-1], i['prevout_n'])
                     for i in tx.inputs()]
        outpoints_ser = [o.serialize() for o in outpoints]
        self.inputsHash = sha256d(b''.join(outpoints_ser))

    def update_before_sign(self, tx, wallet, password):
        protx_hash = bh2u(self.proTxHash[::-1])
        manager = wallet.protx_manager
        bls_privk_bytes = None
        for mn in manager.mns.values():
            if protx_hash == mn.protx_hash:
                bls_privk_bytes = bfh(mn.bls_privk)
                break
        if not bls_privk_bytes:
            return
        bls_privk = bls.PrivateKey.from_bytes(bls_privk_bytes)
        bls_sig = bls_privk.sign_prehashed(sha256d(self.serialize(full=False)))
        self.payloadSig = bls_sig.serialize()

    def after_confirmation(self, tx, manager):
        protx_hash = bh2u(self.proTxHash[::-1])
        for alias, mn in manager.mns.items():
            if mn.protx_hash == protx_hash:
                with manager.manager_lock:
                    mn.service = ProTxService(self.ipAddress, self.port)
                    if self.scriptOperatorPayout:
                        op_pay_script = bh2u(self.scriptOperatorPayout)
                        mn.op_payout_address = script_to_address(op_pay_script)
                    else:
                        mn.op_payout_address = ''
                    manager.save(with_lock=False)
                    manager.alias_updated = mn.alias
                manager.notify('manager-alias-updated')


class AxeProUpRegTx(ProTxBase):
    '''Class representing DIP3 ProUpRegTx'''

    __slots__ = ('version proTxHash mode PubKeyOperator '
                 'KeyIdVoting scriptPayout inputsHash '
                 'payloadSig').split()

    def __str__(self):
        return ('ProUpRegTx Version: %s\n'
                'proTxHash: %s\n'
                'mode: %s\n'
                'PubKeyOperator: %s\n'
                'KeyIdVoting: %s\n'
                'scriptPayout: %s\n'
                % (self.version,
                   bh2u(self.proTxHash[::-1]),
                   self.mode,
                   bh2u(self.PubKeyOperator),
                   bh2u(self.KeyIdVoting),
                   bh2u(self.scriptPayout)))

    def serialize(self, full=True):
        assert len(self.proTxHash) == 32, \
            f'{len(self.proTxHash)} not 32'
        assert len(self.PubKeyOperator) == 48, \
            f'{len(self.PubKeyOperator)} not 48'
        assert len(self.KeyIdVoting) == 20, \
            f'{len(self.KeyIdVoting)} not 20'
        assert len(self.inputsHash) == 32, \
            f'{len(self.inputsHash)} not 32'
        payloadSig = to_varbytes(self.payloadSig) if full else b''
        return (
            struct.pack('<H', self.version) +           # version
            self.proTxHash +                            # proTxHash
            struct.pack('<H', self.mode) +              # mode
            self.PubKeyOperator +                       # PubKeyOperator
            self.KeyIdVoting +                          # KeyIdVoting
            to_varbytes(self.scriptPayout) +            # scriptPayout
            self.inputsHash +                           # inputsHash
            payloadSig                                  # payloadSig
        )

    @classmethod
    def read_vds(cls, vds):
        return AxeProUpRegTx(
            vds.read_uint16(),                          # version
            vds.read_bytes(32),                         # proTxHash
            vds.read_uint16(),                          # mode
            vds.read_bytes(48),                         # PubKeyOperator
            vds.read_bytes(20),                         # KeyIdVoting
            read_varbytes(vds),                         # scriptPayout
            vds.read_bytes(32),                         # inputsHash
            read_varbytes(vds)                          # payloadSig
        )

    def update_with_tx_data(self, tx):
        outpoints = [TxOutPoint(bfh(i['prevout_hash'])[::-1], i['prevout_n'])
                     for i in tx.inputs()]
        outpoints_ser = [o.serialize() for o in outpoints]
        self.inputsHash = sha256d(b''.join(outpoints_ser))

    def update_before_sign(self, tx, wallet, password):
        protx_hash = bh2u(self.proTxHash[::-1])
        owner_addr = None
        for alias, mn in wallet.protx_manager.mns.items():
            if mn.protx_hash == protx_hash:
                owner_addr = mn.owner_addr
        if not owner_addr:
            return
        payload_hash = sha256d(self.serialize(full=False))
        self.payloadSig = wallet.sign_digest(owner_addr, payload_hash,
                                             password)

    def after_confirmation(self, tx, manager):
        protx_hash = bh2u(self.proTxHash[::-1])
        for alias, mn in manager.mns.items():
            if mn.protx_hash == protx_hash:
                with manager.manager_lock:
                    pay_script = bh2u(self.scriptPayout)
                    mn.payout_address = script_to_address(pay_script)
                    mn.voting_addr = hash160_to_p2pkh(self.KeyIdVoting)
                    mn.pubkey_operator = bh2u(self.PubKeyOperator)
                    mn.mode = self.mode
                    manager.save(with_lock=False)
                    manager.alias_updated = mn.alias
                manager.notify('manager-alias-updated')


class AxeProUpRevTx(ProTxBase):
    '''Class representing DIP3 ProUpRevTx'''

    __slots__ = ('version proTxHash reason '
                 'inputsHash payloadSig').split()

    def __str__(self):
        return ('ProUpRevTx Version: %s\n'
                'proTxHash: %s\n'
                'reason: %s\n'
                % (self.version,
                   bh2u(self.proTxHash[::-1]),
                   self.reason))

    def serialize(self, full=True):
        assert len(self.proTxHash) == 32, \
            f'{len(self.proTxHash)} not 32'
        assert len(self.inputsHash) == 32, \
            f'{len(self.inputsHash)} not 32'
        assert len(self.payloadSig) == 96, \
            f'{len(self.payloadSig)} not 96'
        payloadSig = self.payloadSig if full else b''
        return (
            struct.pack('<H', self.version) +           # version
            self.proTxHash +                            # proTxHash
            struct.pack('<H', self.reason) +            # reason
            self.inputsHash +                           # inputsHash
            payloadSig                                  # payloadSig
        )

    @classmethod
    def read_vds(cls, vds):
        return AxeProUpRevTx(
            vds.read_uint16(),                          # version
            vds.read_bytes(32),                         # proTxHash
            vds.read_uint16(),                          # reason
            vds.read_bytes(32),                         # inputsHash
            vds.read_bytes(96)                          # payloadSig
        )

    def update_with_tx_data(self, tx):
        outpoints = [TxOutPoint(bfh(i['prevout_hash'])[::-1], i['prevout_n'])
                     for i in tx.inputs()]
        outpoints_ser = [o.serialize() for o in outpoints]
        self.inputsHash = sha256d(b''.join(outpoints_ser))

    def update_before_sign(self, tx, wallet, password):
        protx_hash = bh2u(self.proTxHash[::-1])
        manager = wallet.protx_manager
        bls_privk_bytes = None
        for mn in manager.mns.values():
            if protx_hash == mn.protx_hash:
                bls_privk_bytes = bfh(mn.bls_privk)
                break
        if not bls_privk_bytes:
            return
        bls_privk = bls.PrivateKey.from_bytes(bls_privk_bytes)
        bls_sig = bls_privk.sign_prehashed(sha256d(self.serialize(full=False)))
        self.payloadSig = bls_sig.serialize()


class AxeCbTx(ProTxBase):
    '''Class representing DIP4 coinbase special tx'''

    __slots__ = ('version height merkleRootMNList merkleRootQuorums').split()

    def __str__(self):
        res = ('CbTx Version: %s\n'
               'height: %s\n'
               'merkleRootMNList: %s\n'
               % (self.version, self.height,
                  bh2u(self.merkleRootMNList[::-1])))
        if self.version > 1:
            res += ('merkleRootQuorums: %s\n' %
                    bh2u(self.merkleRootQuorums[::-1]))
        return res

    def serialize(self):
        assert len(self.merkleRootMNList) == 32, \
            f'{len(self.merkleRootMNList)} not 32'
        res = (
            struct.pack('<H', self.version) +           # version
            struct.pack('<I', self.height) +            # height
            self.merkleRootMNList                       # merkleRootMNList
        )
        if self.version > 1:
            assert len(self.merkleRootQuorums) == 32, \
                f'{len(self.merkleRootQuorums)} not 32'
            res += self.merkleRootQuorums               # merkleRootQuorums
        return res

    @classmethod
    def read_vds(cls, vds):
        version = vds.read_uint16()
        height = vds.read_uint32()
        merkleRootMNList = vds.read_bytes(32)
        merkleRootQuorums = b''
        if version > 1:
            merkleRootQuorums = vds.read_bytes(32)
        return AxeCbTx(version, height, merkleRootMNList, merkleRootQuorums)


class AxeSubTxRegister(ProTxBase):
    '''Class representing DIP5 SubTxRegister'''

    __slots__ = ('version userName pubKey payloadSig').split()

    def __str__(self):
        return ('SubTxRegister Version: %s\n'
                'userName: %s\n'
                'pubKey: %s\n'
                % (self.version, self.userName,
                   bh2u(self.pubKey)))

    def serialize(self):
        assert len(self.pubKey) == 48, \
            f'{len(self.pubKey)} not 48'
        assert len(self.payloadSig) == 96, \
            f'{len(self.payloadSig)} not 96'
        return (
            struct.pack('<H', self.version) +           # version
            to_varbytes(self.userName) +                # userName
            self.pubKey +                               # pubKey
            self.payloadSig                             # payloadSig
        )

    @classmethod
    def read_vds(cls, vds):
        return AxeSubTxRegister(
            vds.read_uint16(),                          # version
            read_varbytes(vds),                         # userName
            vds.read_bytes(48),                         # pubKey
            vds.read_bytes(96)                          # payloadSig
        )


class AxeSubTxTopup(ProTxBase):
    '''Class representing DIP5 SubTxTopup'''

    __slots__ = ('version regTxHash').split()

    def __str__(self):
        return ('SubTxTopup Version: %s\n'
                'regTxHash: %s\n'
                % (self.version,
                   bh2u(self.regTxHash[::-1])))

    def serialize(self):
        assert len(self.regTxHash) == 32, \
            f'{len(self.regTxHash)} not 32'
        return (
            struct.pack('<H', self.version) +           # version
            self.regTxHash                              # regTxHash
        )

    @classmethod
    def read_vds(cls, vds):
        return AxeSubTxTopup(
            vds.read_uint16(),                          # version
            vds.read_bytes(32)                          # regTxHash
        )


class AxeSubTxResetKey(ProTxBase):
    '''Class representing DIP5 SubTxResetKey'''

    __slots__ = ('version regTxHash hashPrevSubTx '
                 'creditFee newPubKey payloadSig').split()

    def __str__(self):
        return ('SubTxResetKey Version: %s\n'
                'regTxHash: %s\n'
                'hashPrevSubTx: %s\n'
                'creditFee: %s\n'
                'newPubKey: %s\n'
                % (self.version,
                   bh2u(self.regTxHash[::-1]),
                   bh2u(self.hashPrevSubTx[::-1]),
                   self.creditFee,
                   bh2u(self.newPubKey)))

    def serialize(self):
        assert len(self.regTxHash) == 32, \
            f'{len(self.regTxHash)} not 32'
        assert len(self.hashPrevSubTx) == 32, \
            f'{len(self.hashPrevSubTx)} not 32'
        assert len(self.newPubKey) == 48, \
            f'{len(self.newPubKey)} not 48'
        assert len(self.payloadSig) == 96, \
            f'{len(self.payloadSig)} not 96'
        return (
            struct.pack('<H', self.version) +           # version
            self.regTxHash +                            # regTxHash
            self.hashPrevSubTx +                        # hashPrevSubTx
            struct.pack('<q', self.creditFee) +         # creditFee
            self.newPubKey +                            # newPubKey
            self.payloadSig                             # payloadSig
        )

    @classmethod
    def read_vds(cls, vds):
        return AxeSubTxResetKey(
            vds.read_uint16(),                          # version
            vds.read_bytes(32),                         # regTxHash
            vds.read_bytes(32),                         # hashPrevSubTx
            vds.read_int64(),                           # creditFee
            vds.read_bytes(48),                         # newPubKey
            vds.read_bytes(96)                          # payloadSig
        )


class AxeSubTxCloseAccount(ProTxBase):
    '''Class representing DIP5 SubTxCloseAccount'''

    __slots__ = ('version regTxHash hashPrevSubTx '
                 'creditFee payloadSig').split()

    def __str__(self):
        return ('SubTxCloseAccount Version: %s\n'
                'regTxHash: %s\n'
                'hashPrevSubTx: %s\n'
                'creditFee: %s\n'
                % (self.version,
                   bh2u(self.regTxHash[::-1]),
                   bh2u(self.hashPrevSubTx[::-1]),
                   self.creditFee))

    def serialize(self):
        assert len(self.regTxHash) == 32, \
            f'{len(self.regTxHash)} not 32'
        assert len(self.hashPrevSubTx) == 32, \
            f'{len(self.hashPrevSubTx)} not 32'
        assert len(self.payloadSig) == 96, \
            f'{len(self.payloadSig)} not 96'
        return (
            struct.pack('<H', self.version) +           # version
            self.regTxHash +                            # regTxHash
            self.hashPrevSubTx +                        # hashPrevSubTx
            struct.pack('<q', self.creditFee) +         # creditFee
            self.payloadSig                             # payloadSig
        )

    @classmethod
    def read_vds(cls, vds):
        return AxeSubTxCloseAccount(
            vds.read_uint16(),                          # version
            vds.read_bytes(32),                         # regTxHash
            vds.read_bytes(32),                         # hashPrevSubTx
            vds.read_int64(),                           # creditFee
            vds.read_bytes(96)                          # payloadSig
        )


# Supported Spec Tx types and corresponding handlers mapping
STANDARD_TX = 0
SPEC_PRO_REG_TX = 1
SPEC_PRO_UP_SERV_TX = 2
SPEC_PRO_UP_REG_TX = 3
SPEC_PRO_UP_REV_TX = 4
SPEC_CB_TX = 5
SPEC_SUB_TX_REGISTER = 8
SPEC_SUB_TX_TOPUP = 9
SPEC_SUB_TX_RESET_KEY = 10
SPEC_SUB_TX_CLOSE_ACCOUNT = 11


SPEC_TX_HANDLERS = {
    SPEC_PRO_REG_TX: AxeProRegTx,
    SPEC_PRO_UP_SERV_TX: AxeProUpServTx,
    SPEC_PRO_UP_REG_TX: AxeProUpRegTx,
    SPEC_PRO_UP_REV_TX: AxeProUpRevTx,
    SPEC_CB_TX: AxeCbTx,
    SPEC_SUB_TX_REGISTER: AxeSubTxRegister,
    SPEC_SUB_TX_TOPUP: AxeSubTxTopup,
    SPEC_SUB_TX_RESET_KEY: AxeSubTxResetKey,
    SPEC_SUB_TX_CLOSE_ACCOUNT: AxeSubTxCloseAccount,
}


# Use DIP2 tx_type to output PrivateSend type in wallet history
class PSTxTypes(IntEnum):
    '''PS Tx types'''
    NEW_DENOMS = 65536
    NEW_COLLATERAL = 65537
    DENOMINATE = 65538
    PAY_COLLATERAL = 65539
    PRIVATESEND = 65540
    PS_MIXING_TXS = 65541
    SPEND_PS_COINS = 65542
    OTHER_PS_COINS = 65543


SPEC_TX_NAMES = {
    STANDARD_TX: 'Standard',
    SPEC_PRO_REG_TX: 'ProRegTx',
    SPEC_PRO_UP_SERV_TX: 'ProUpServTx',
    SPEC_PRO_UP_REG_TX: 'ProUpRegTx',
    SPEC_PRO_UP_REV_TX: 'ProUpRevTx',
    SPEC_CB_TX: 'CbTx',
    SPEC_SUB_TX_REGISTER: 'SubTxRegister',
    SPEC_SUB_TX_TOPUP: 'SubTxTopup',
    SPEC_SUB_TX_RESET_KEY: 'SubTxResetKey',
    SPEC_SUB_TX_CLOSE_ACCOUNT: 'SubTxCloseAccount',

    # as tx_type is uint16, can make PrivateSend types >= 65536
    PSTxTypes.NEW_DENOMS: 'PS New Denoms',
    PSTxTypes.NEW_COLLATERAL: 'PS New Collateral',
    PSTxTypes.DENOMINATE: 'PS Denominate',
    PSTxTypes.PAY_COLLATERAL: 'PS Pay Collateral',
    PSTxTypes.PRIVATESEND: 'PrivateSend',
    PSTxTypes.PS_MIXING_TXS: 'PS Mixing Txs ...',
    PSTxTypes.SPEND_PS_COINS: 'Spend PS Coins',
    PSTxTypes.OTHER_PS_COINS: 'Other PS Coins',
}


class PSCoinRounds(IntEnum):
    '''PS Tx types'''
    MINUSINF = -1e9
    OTHER = -2
    COLLATERAL = -1


def read_extra_payload(vds, tx_type):
    if tx_type:
        extra_payload_size = vds.read_compact_size()
        end = vds.read_cursor + extra_payload_size
        spec_tx_class = SPEC_TX_HANDLERS.get(tx_type)
        if spec_tx_class:
            read_method = getattr(spec_tx_class, 'read_vds', None)
            if not read_method:
                raise NotImplementedError('%s has no read_vds method' %
                                          spec_tx_class)
            extra_payload = read_method(vds)
            assert isinstance(extra_payload, spec_tx_class)
        else:
            raise AxeTxError(f'Unkonwn tx type {tx_type}')
        assert vds.read_cursor == end
    else:
        extra_payload = b''
    return extra_payload


def serialize_extra_payload(tx):
    tx_type = tx.tx_type
    if not tx_type:
        raise AxeTxError('No special tx type set to serialize')

    extra = tx.extra_payload
    spec_tx_class = SPEC_TX_HANDLERS.get(tx_type)
    if not spec_tx_class:
        assert isinstance(extra, (bytes, bytearray))
        return extra

    if not isinstance(extra, spec_tx_class):
        raise AxeTxError('Axe tx_type not conform with extra'
                          ' payload class: %s, %s' % (tx_type, extra))
    return extra.serialize()
