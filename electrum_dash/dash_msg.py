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

from collections import namedtuple
from enum import IntEnum
from ipaddress import ip_address
from struct import pack

from .crypto import sha256d
from .bitcoin import hash160_to_p2pkh, b58_address_to_hash160
from .ecc import msg_magic
from .dash_tx import (to_compact_size, to_varbytes, serialize_ip, str_ip,
                      service_to_ip_port, TxOutPoint, read_uint16_nbo)
from .transaction import Transaction, BCDataStream, SerializationError
from .util import bh2u, bfh


# https://dash-docs.github.io/en/developer-reference#version
MAX_USER_AGENT_SIZE = 256
# https://dash-docs.github.io/en/developer-reference#addr
MAX_ADDRESSES = 1000
# https://dash-docs.github.io/en/developer-reference#inv
MAX_INV_ENTRIES = 50000
# https://dash-docs.github.io/en/developer-reference#filterload
FILTERLOAD_MAX_HASH_FUNCS = 50
FILTERLOAD_MAX_FILTER_BYTES = 36000
# https://dash-docs.github.io/en/developer-reference#filteradd
FILTERADD_MAX_ELEMENT_BYTES = 520


class DashMsgError(Exception):
    """Thrown when there's a problem with Dash message serialize/deserialize"""


class IntEnumWithCheck(IntEnum):
    '''IntEnum with hash_value class method'''
    @classmethod
    def has_value(cls, value):
        return any(value == item.value for item in cls)


class DashType(IntEnumWithCheck):
    '''Enum representing Inventory object types'''
    MSG_TX = 1
    MSG_BLOCK = 2
    MSG_FILTERED_BLOCK = 3
    MSG_TXLOCK_REQUEST = 4
    MSG_TXLOCK_VOTE = 5
    MSG_SPORK = 6
    MSG_DSTX = 16
    MSG_GOVERNANCE_OBJECT = 17
    MSG_GOVERNANCE_OBJECT_VOTE = 18
    MSG_CMPCT_BLOCK = 20
    MSG_QUORUM_FINAL_COMMITMENT = 21
    MSG_QUORUM_CONTRIB = 23
    MSG_QUORUM_COMPLAINT = 24
    MSG_QUORUM_JUSTIFICATION = 25
    MSG_QUORUM_PREMATURE_COMMITMENT = 26
    MSG_QUORUM_RECOVERED_SIG = 28
    MSG_CLSIG = 29                          # The hash is a ChainLock signature
    MSG_ISLOCK = 30                         # The hash is an LLMQ-based IS lock

    # Deprecated
    MSG_MASTERNODE_PAYMENT_VOTE = 7
    MSG_MASTERNODE_PAYMENT_BLOCK = 8
    MSG_BUDGET_VOTE = 9
    MSG_BUDGET_PROPOSAL = 10
    MSG_BUDGET_FINALIZED = 11
    MSG_BUDGET_FINALIZED_VOTE = 12
    MSG_MASTERNODE_QUORUM = 13
    MSG_MASTERNODE_ANNOUNCE = 14
    MSG_MASTERNODE_PING = 15
    MSG_MASTERNODE_VERIFY = 19
    MSG_QUORUM_DUMMY_COMMITMENT = 22
    MSG_QUORUM_DEBUG_STATUS = 27


class SporkID(IntEnumWithCheck):
    '''Enum representing known Dash spork IDs'''
    SPORK_2_INSTANTSEND_ENABLED = 10001
    SPORK_3_INSTANTSEND_BLOCK_FILTERING = 10002
    SPORK_5_INSTANTSEND_MAX_VALUE = 10004
    SPORK_6_NEW_SIGS = 10005
    SPORK_9_SUPERBLOCKS_ENABLED = 10008
    SPORK_12_RECONSIDER_BLOCKS = 10011
    SPORK_15_DETERMINISTIC_MNS_ENABLED = 10014
    SPORK_16_INSTANTSEND_AUTOLOCKS = 10015
    SPORK_17_QUORUM_DKG_ENABLED = 10016
    SPORK_19_CHAINLOCKS_ENABLED = 10018
    SPORK_20_INSTANTSEND_LLMQ_BASED = 10019


class LLMQType(IntEnumWithCheck):
    '''Enum representing known LLMQ types'''
    LLMQ_50_60 = 1
    LLMQ_400_60 = 2
    LLMQ_400_85 = 3
    LLMQ_5_60 = 100  # For testing only


class DashNetIPAddr(namedtuple('DashNetIPAddr', 'time services ip port')):
    '''Class representing addr mesage payload'''

    def __str__(self):
        return ('DashNetIPAddr: time: %s,'
                ' services: 0x%.16X, ip: %s, port: %s' %
                (self.time, self.services, str_ip(self.ip), self.port))


class DeletedQuorum(namedtuple('DeletedQuorum', 'llmqType quorumHash')):
    '''Class representing deleted LLMQ quorum'''

    def __str__(self):
        llmqType = (LLMQType(self.llmqType)
                        if LLMQType.has_value(self.llmqType)
                        else self.llmqType)
        return ('DeletedQuorum: llmqType: %s(%s), quorumHash: %s' %
                (llmqType, self.llmqType, bh2u(self.quorumHash[::-1])))

    @classmethod
    def read_vds(cls, vds, alone_data=False):
        llmqType = vds.read_uchar()                     # llmqType
        quorumHash = vds.read_bytes(32)                 # quorumHash
        if alone_data and vds.can_read_more():
            raise SerializationError(f'{cls}: extra junk at the end')
        return DeletedQuorum(llmqType, quorumHash)


class DashSMLEntry(namedtuple('DashSMLEntry',
                              'proRegTxHash confirmedHash ipAddress port'
                              ' pubKeyOperator keyIDVoting isValid')):
    '''Class representing Simplified Masternode List entry'''

    def __str__(self):
        return ('DashSMLEntry: proRegTxHash: %s, confirmedHash: %s,'
                ' ipAddress: %s, port: %s, pubKeyOperator: %s,'
                ' keyIDVoting: %s, isValid: %s' %
                (bh2u(self.proRegTxHash[::-1]), bh2u(self.confirmedHash[::-1]),
                 str_ip(self.ipAddress), self.port, bh2u(self.pubKeyOperator),
                 bh2u(self.keyIDVoting), self.isValid))

    def as_dict(self):
        return {
            'proRegTxHash': bh2u(self.proRegTxHash[::-1]),
            'confirmedHash': bh2u(self.confirmedHash[::-1]),
            'service': f'{str_ip(self.ipAddress)}:{self.port}',
            'pubKeyOperator': bh2u(self.pubKeyOperator),
            'votingAddress': hash160_to_p2pkh(self.keyIDVoting),
            'isValid': self.isValid,
        }

    @classmethod
    def from_dict(cls, d):
        proRegTxHash = bfh(d['proRegTxHash'])[::-1]
        confirmedHash = bfh(d['confirmedHash'])[::-1]
        ipAddress, port = service_to_ip_port(d['service'])
        pubKeyOperator = bfh(d['pubKeyOperator'])
        keyIDVoting = b58_address_to_hash160(d['votingAddress'])[1]
        isValid = d['isValid']
        return DashSMLEntry(proRegTxHash, confirmedHash, ipAddress,
                            port, pubKeyOperator, keyIDVoting, isValid)

    def serialize(self, as_hex=False):
        assert len(self.proRegTxHash) == 32
        assert len(self.confirmedHash) == 32
        assert len(self.pubKeyOperator) == 48
        assert len(self.keyIDVoting) == 20
        ipAddress = serialize_ip(self.ipAddress)
        res = (
            self.proRegTxHash +                         # proRegTxHash
            self.confirmedHash +                        # confirmedHash
            ipAddress +                                 # ipAddress
            pack('>H', self.port) +                     # port
            self.pubKeyOperator +                       # pubKeyOperator
            self.keyIDVoting +                          # keyIDVoting
            pack('B', self.isValid)                     # isValid
        )
        if as_hex:
            return bh2u(res)
        else:
            return res

    @classmethod
    def from_hex(cls, hex_str):
        vds = BCDataStream()
        vds.clear_and_set_bytes(bfh(hex_str))
        return cls.read_vds(vds)

    @classmethod
    def read_vds(cls, vds, alone_data=False):
        proRegTxHash = vds.read_bytes(32)               # proRegTxHash
        confirmedHash = vds.read_bytes(32)              # confirmedHash
        ipAddress = ip_address(vds.read_bytes(16))      # ipAddress
        port = read_uint16_nbo(vds)                     # port
        pubKeyOperator = vds.read_bytes(48)             # pubKeyOperator
        keyIDVoting = vds.read_bytes(20)                # keyIDVoting
        isValid = vds.read_uchar()                      # isValid
        if alone_data and vds.can_read_more():
            raise SerializationError(f'{cls}: extra junk at the end')
        return DashSMLEntry(proRegTxHash, confirmedHash, ipAddress,
                            port, pubKeyOperator, keyIDVoting, isValid)


class DashInventory(namedtuple('DashInventory', 'type hash')):
    '''Class representing addr mesage payload'''

    def __str__(self):
        tv = self.type
        tn = DashType(tv).name if DashType.has_value(tv) else tv
        return ('DashInventory: %s %s' % (tn, bh2u(self.hash[::-1])))


class DashCmd:
    '''Class representing Dash network message packed with msg header cmd'''

    def __init__(self, cmd, payload=None):
        vds = BCDataStream()
        vds.clear_and_set_bytes(payload)
        if cmd == 'version':
            self.payload = DashVersionMsg.read_vds(vds, alone_data=True)
        elif cmd == 'ping':
            self.payload = DashPingMsg.read_vds(vds, alone_data=True)
        elif cmd == 'pong':
            self.payload = DashPongMsg.read_vds(vds, alone_data=True)
        elif cmd == 'addr':
            self.payload = DashAddrMsg.read_vds(vds, alone_data=True)
        elif cmd == 'inv':
            self.payload = DashInvMsg.read_vds(vds, alone_data=True)
        elif cmd == 'spork':
            self.payload = DashSporkMsg.read_vds(vds, alone_data=True)
        elif cmd == 'islock':
            self.payload = DashISLockMsg.read_vds(vds, alone_data=True)
        elif cmd == 'mnlistdiff':
            self.payload = DashMNListDiffMsg.read_vds(vds, alone_data=True)
        elif cmd == 'qfcommit':
            self.payload = DashQFCommitMsg.read_vds(vds, alone_data=True)
        else:
            self.payload = payload
        self.cmd = cmd

    def __str__(self):
        if not self.payload:
            return f'{self.cmd}'
        elif isinstance(self.payload, bytes):
            return f'{self.cmd}: {bh2u(self.payload)}'
        else:
            return f'{self.cmd}: {self.payload}'


class DashMsgBase:
    '''Base Class representing Dash Network messages'''
    def __init__(self, *args, **kwargs):
        if args and not kwargs:
            argsl = list(args)
            for f in self.fields:
                setattr(self, f, argsl.pop(0))
        elif kwargs and not args:
            for f in self.fields:
                setattr(self, f, kwargs[f])
        else:
            raise ValueError('__init__ works with all args or all kwargs')


class DashVersionMsg(DashMsgBase):
    '''Class representing version message'''

    fields = ('version services timestamp '
              'recv_services recv_ip recv_port '
              'trans_services trans_ip trans_port '
              'nonce user_agent start_height '
              'relay mnauth_challenge').split()

    def __init__(self, *args, **kwargs):
        super(DashVersionMsg, self).__init__(*args, **kwargs)

    def __str__(self):
        res = ('DashVersionMsg: version: %s,'
               ' services: 0x%.16X, timestamp: %s,'
               ' recv_services: 0x%.16X, recv_ip: %s, recv_port: %s,'
               ' trans_services: 0x%.16X, trans_ip: %s, trans_port: %s,'
               ' nonce: %s, user_agent: %s, start_height: %s'
                % (self.version, self.services, self.timestamp,
                   self.recv_services, str_ip(self.recv_ip), self.recv_port,
                   self.trans_services, str_ip(self.trans_ip), self.trans_port,
                   self.nonce, self.user_agent, self.start_height))
        if self.relay is not None:
            res += (', relay: 0x%.2X' % self.relay)
        if self.mnauth_challenge is not None:
            res += (', mnauth_challenge: %s' % bh2u(self.mnauth_challenge))
        return res

    def serialize(self):
        if self.mnauth_challenge is not None:
            assert len(self.mnauth_challenge) == 32
        recv_ip = serialize_ip(self.recv_ip)
        trans_ip = serialize_ip(self.trans_ip)
        if self.user_agent:
            user_agent_bytes = to_varbytes(self.user_agent.encode())
        else:
            user_agent_bytes = bytes([0])
        res = (
            pack('<i', self.version) +                  # version
            pack('<Q', self.services) +                 # services
            pack('<I', self.timestamp) + b'\x00' * 4 +  # timestamp
            pack('<Q', self.recv_services) +            # recv_services
            recv_ip +                                   # recv_ip
            pack('>H', self.recv_port) +                # recv_port
            pack('<Q', self.trans_services) +           # trans_services
            trans_ip +                                  # trans_ip
            pack('>H', self.trans_port) +               # trans_port
            pack('<Q', self.nonce) +                    # nonce
            user_agent_bytes +                          # user_agent
            pack('<i', self.start_height)               # start_height
        )
        if self.relay is not None:
            res += pack('B', self.relay)                # relay
        if self.mnauth_challenge is not None:
            res += self.mnauth_challenge                # mnauth_challenge
        return res

    @classmethod
    def read_vds(cls, vds, alone_data=False):
        version = vds.read_int32()                      # version
        services = vds.read_uint64()                    # services
        timestamp = vds.read_int64()                    # timestamp
        recv_services = vds.read_uint64()               # recv_services
        recv_ip = ip_address(vds.read_bytes(16))        # recv_ip
        recv_port = read_uint16_nbo(vds)                # recv_port
        trans_services = vds.read_uint64()              # trans_services
        trans_ip = ip_address(vds.read_bytes(16))       # trans_ip
        trans_port = read_uint16_nbo(vds)               # trans_port
        nonce = vds.read_uint64()                       # nonce
        user_agent_csize = vds.read_compact_size()
        if user_agent_csize > MAX_USER_AGENT_SIZE:
            raise DashMsgError('version msg: user_agent too long')
        user_agent = vds.read_bytes(user_agent_csize)   # user_agent
        start_height = vds.read_int32()                 # start_height

        relay = None
        mnauth_challenge = None
        bleft = vds.bytes_left()
        if bleft == 1:
            relay = vds.read_uchar()
        elif bleft == 32:
            mnauth_challenge = vds.read_bytes(32)
        elif bleft == 33:
            relay = vds.read_uchar()
            mnauth_challenge = vds.read_bytes(32)
        if alone_data and vds.can_read_more():
            raise SerializationError(f'{cls}: extra junk at the end')
        return DashVersionMsg(version, services, timestamp,
                              recv_services, recv_ip, recv_port,
                              trans_services, trans_ip, trans_port,
                              nonce, user_agent, start_height,
                              relay, mnauth_challenge)


class DashPingMsg(DashMsgBase):
    '''Class representing ping message'''

    fields = 'nonce'.split()

    def __init__(self, *args, **kwargs):
        super(DashPingMsg, self).__init__(*args, **kwargs)

    def __str__(self):
        return 'DashPingMsg: nonce: %s' % self.nonce

    def serialize(self):
        return pack('<Q', self.nonce)                   # nonce

    @classmethod
    def read_vds(cls, vds, alone_data=False):
        nonce = vds.read_uint64()                       # nonce
        if alone_data and vds.can_read_more():
            raise SerializationError(f'{cls}: extra junk at the end')
        return DashPingMsg(nonce)


class DashPongMsg(DashPingMsg):
    '''Class representing pong message'''

    def __str__(self):
        return 'DashPongMsg: nonce: %s' % self.nonce

    @classmethod
    def read_vds(cls, vds, alone_data=False):
        nonce = vds.read_uint64()                       # nonce
        if alone_data and vds.can_read_more():
            raise SerializationError(f'{cls}: extra junk at the end')
        return DashPongMsg(nonce)


class DashAddrMsg(DashMsgBase):
    '''Class representing addr message'''

    fields = 'addresses'.split()

    def __init__(self, *args, **kwargs):
        super(DashAddrMsg, self).__init__(*args, **kwargs)

    def __str__(self):
        addr_str = [str(a) for a in self.addresses]
        return ('DashAddrMsg: addresses(%s): %s' %
                (len(self.addresses), addr_str))

    def serialize(self):
        addr_cnt = len(self.addresses)
        if addr_cnt > MAX_ADDRESSES:
            raise DashMsgError('addr msg: too many addresses to send')
        res = to_compact_size(addr_cnt)
        for a in self.addresses:
            ip_addr = serialize_ip(a)
            res += pack('<I', a.timestamp)              # time
            res += pack('<Q', a.services)               # services
            res += ip_addr                              # ip
            res += pack('>H', a.port)                   # port
        return res

    @classmethod
    def read_vds(cls, vds, alone_data=False):
        addr_cnt = vds.read_compact_size()
        if addr_cnt > MAX_ADDRESSES:
            raise DashMsgError('addr msg: too many addresses')
        addresses = []
        for addr_i in range(addr_cnt):
            time = vds.read_uint32()                    # time
            services = vds.read_uint64()                # services
            ip_addr = ip_address(vds.read_bytes(16))    # ip
            port = read_uint16_nbo(vds)                 # port
            addresses.append(DashNetIPAddr(time, services, ip_addr, port))
        if alone_data and vds.can_read_more():
            raise SerializationError(f'{cls}: extra junk at the end')
        return DashAddrMsg(addresses)


class DashInvMsg(DashMsgBase):
    '''Class representing inv message'''

    fields = 'inventory'.split()

    def __init__(self, *args, **kwargs):
        super(DashInvMsg, self).__init__(*args, **kwargs)

    def __str__(self):
        inv_str = [str(i) for i in self.inventory]
        return ('DashInvMsg: inventory(%s): %s' %
                (len(self.inventory), inv_str))

    def serialize(self):
        return self._serialize('inv')

    def _serialize(self, msg):
        inv_cnt = len(self.inventory)
        if inv_cnt > MAX_INV_ENTRIES:
            raise DashMsgError(f'{msg} msg: too long inventory to send')
        res = to_compact_size(inv_cnt)
        for i in self.inventory:
            res += pack('<I', i.type)                   # type
            assert len(i.hash) == 32
            res += i.hash                               # hash
        return res

    @classmethod
    def read_vds(cls, vds, alone_data=False):
        return DashInvMsg(cls._read_vds(vds, 'inv', alone_data))

    @classmethod
    def _read_vds(cls, vds, msg, alone_data=False):
        inv_cnt = vds.read_compact_size()
        if inv_cnt > MAX_INV_ENTRIES:
            raise DashMsgError(f'{msg} msg: too long inventory')
        inventory = []
        for inv_i in range(inv_cnt):
            inv_type = vds.read_uint32()                # type
            inv_hash = vds.read_bytes(32)               # hash
            inventory.append(DashInventory(inv_type, inv_hash))
        if alone_data and vds.can_read_more():
            raise SerializationError(f'{cls}: extra junk at the end')
        return inventory


class DashGetDataMsg(DashInvMsg):
    '''Class representing getdata message'''

    def __str__(self):
        inv_str = [str(i) for i in self.inventory]
        return ('DashGetDataMsg: inventory(%s): %s' %
                (len(self.inventory), inv_str))

    def serialize(self):
        return self._serialize('getdata')

    @classmethod
    def read_vds(cls, vds, alone_data=False):
        return DashGetDataMsg(cls._read_vds(vds, 'getdata', alone_data))


class DashSporkMsg(DashMsgBase):
    '''Class representing islock message'''

    fields = 'nSporkID nValue nTimeSigned vchSig'.split()

    def __init__(self, *args, **kwargs):
        super(DashSporkMsg, self).__init__(*args, **kwargs)

    def __str__(self):
        is_known_id = SporkID.has_value(self.nSporkID)
        spork_id = SporkID(self.nSporkID) if is_known_id else self.nSporkID
        return ('DashSporkMsg: nSporkID: %s, nValue: %s,'
                ' nTimeSigned: %s, vchSig: %s' %
                (spork_id, self.nValue, self.nTimeSigned, bh2u(self.vchSig)))

    @classmethod
    def read_vds(cls, vds, alone_data=False):
        nSporkID = vds.read_int32()                     # nSporkID
        nValue = vds.read_int64()                       # nValue
        nTimeSigned = vds.read_int64()                  # nTimeSigned
        vchSig_len = vds.read_compact_size()
        if vchSig_len != 65:
            raise DashMsgError(f'spork msg: wrong vchSig length')
        vchSig = vds.read_bytes(65)                     # vchSig
        if alone_data and vds.can_read_more():
            raise SerializationError(f'{cls}: extra junk at the end')
        return DashSporkMsg(nSporkID, nValue, nTimeSigned, vchSig)

    def msg_hash(self, new_sigs=True):
        if new_sigs:
            return sha256d(pack('<i', self.nSporkID) +
                           pack('<q', self.nValue) +
                           pack('<q', self.nTimeSigned))

        msg_str = str(self.nSporkID) + str(self.nValue) + str(self.nTimeSigned)
        return sha256d(msg_magic(msg_str.encode()))


class DashISLockMsg(DashMsgBase):
    '''Class representing islock message'''

    fields = 'inputs txid sig'.split()

    def __init__(self, *args, **kwargs):
        super(DashISLockMsg, self).__init__(*args, **kwargs)

    def __str__(self):
        inputs_str = [str(i) for i in self.inputs]
        return ('DashISLockMsg: inputs: %s, txid: %s, sig: %s' %
                (inputs_str, bh2u(self.txid[::-1]), self.sig))

    @classmethod
    def read_vds(cls, vds, alone_data=False):
        in_cnt = vds.read_compact_size()
        inputs = []
        for in_i in range(in_cnt):                      # read outpoints
            in_hash = vds.read_bytes(32)                # hash
            in_idx  = vds.read_uint32()                 # idx
            inputs.append(TxOutPoint(in_hash, in_idx))
        txid = vds.read_bytes(32)                       # txid
        sig = vds.read_bytes(96)                        # sig
        if alone_data and vds.can_read_more():
            raise SerializationError(f'{cls}: extra junk at the end')
        return DashISLockMsg(inputs, txid, sig)

    def calc_request_id(self):
        prehash = b'\x06islock' + to_compact_size(len(self.inputs))
        for in_i in self.inputs:
            prehash += in_i.serialize()
        return sha256d(prehash)

    def msg_hash(self, quorum, request_id):
        return sha256d(
            pack('B', quorum.llmqType) +
            quorum.quorumHash +
            request_id +
            self.txid
        )


class DashCLSigMsg(DashMsgBase):
    '''Class representing clsig message'''

    fields = 'nHeight blockHash sig'.split()

    def __init__(self, *args, **kwargs):
        super(DashCLSigMsg, self).__init__(*args, **kwargs)

    def __str__(self):
        return ('DashCLSigMsg: nHeight: %s, blockHash: %s, sig: %s' %
                (self.nHeight, bh2u(self.blockHash[::-1]), self.sig))

    @classmethod
    def read_vds(cls, vds, alone_data=False):
        nHeight = vds.read_uint32()                     # nHeight
        blockHash = vds.read_bytes(32)                  # blockHash
        sig = vds.read_bytes(96)                        # sig
        if alone_data and vds.can_read_more():
            raise SerializationError(f'{cls}: extra junk at the end')
        return DashCLSigMsg(nHeight, blockHash, sig)

    def calc_request_id(self):
        return sha256d(b'\x05clsig' + pack('<I', self.nHeight))

    def msg_hash(self, quorum, request_id):
        return sha256d(
            pack('B', quorum.llmqType) +
            quorum.quorumHash +
            request_id +
            self.blockHash
        )


class DashGetMNListDMsg(DashMsgBase):
    '''Class representing getmnlistd message'''

    fields = 'baseBlockHash blockHash'.split()

    def __init__(self, *args, **kwargs):
        super(DashGetMNListDMsg, self).__init__(*args, **kwargs)

    def __str__(self):
        return ('DashGetMNListDMsg: baseBlockHash: %s, blockHash: %s' %
                (bh2u(self.baseBlockHash[::-1]), bh2u(self.blockHash[::-1])))

    def serialize(self):
        assert len(self.baseBlockHash) == 32
        assert len(self.blockHash) == 32
        return (
            self.baseBlockHash +                        # baseBlockHash
            self.blockHash                              # blockHash
        )

    @classmethod
    def read_vds(cls, vds, alone_data=False):
        baseBlockHash = vds.read_bytes(32)              # baseBlockHash
        blockHash = vds.read_bytes(32)                  # blockHash
        if alone_data and vds.can_read_more():
            raise SerializationError(f'{cls}: extra junk at the end')
        return DashGetMNListDMsg(baseBlockHash, blockHash)


class DashMNListDiffMsg(DashMsgBase):
    '''Class representing mnlistdiff message'''

    fields = ('baseBlockHash blockHash totalTransactions merkleHashes'
              ' merkleFlags cbTx deletedMNs mnList deletedQuorums'
              ' newQuorums').split()

    def __init__(self, *args, **kwargs):
        super(DashMNListDiffMsg, self).__init__(*args, **kwargs)

    def __str__(self):
        mh_cnt = len(self.merkleHashes)
        merkleHashes = [bh2u(h[::-1])for h in self.merkleHashes]
        merkleFlags = self.merkleFlags
        dmns_cnt = len(self.deletedMNs)
        deletedMNs = [bh2u(h[::-1]) for h in self.deletedMNs]
        mnl_cnt = len(self.mnList)
        mnList = [str(smle) for smle in self.mnList]
        dq_cnt = len(self.deletedQuorums)
        deletedQuorums = [str(dq) for dq in self.deletedQuorums]
        nq_cnt = len(self.newQuorums)
        newQuorums = [str(qfc) for qfc in self.newQuorums]
        return ('DashMNListDiffMsg: baseBlockHash: %s, blockHash: %s,'
                ' totalTransactions: %s, merkleHashes(%s): %s,'
                ' merkleFlags: %s, cbTx: %s,'
                ' deletedMNs(%s): %s, mnList(%s): %s,'
                ' deletedQuorums(%s): %s, newQuorums(%s): %s' %
                (bh2u(self.baseBlockHash[::-1]), bh2u(self.blockHash[::-1]),
                 self.totalTransactions, mh_cnt, merkleHashes,
                 merkleFlags, bh2u(self.cbTx),
                 dmns_cnt, deletedMNs, mnl_cnt, mnList,
                 dq_cnt, deletedQuorums, nq_cnt, newQuorums))

    @classmethod
    def read_vds(cls, vds, alone_data=False):
        baseBlockHash = vds.read_bytes(32)              # baseBlockHash
        blockHash = vds.read_bytes(32)                  # blockHash
        totalTransactions = vds.read_uint32()           # totalTransactions

        mh_cnt = vds.read_compact_size()                # merkleHashes cnt
        merkleHashes = []                               # merkleHashes
        for mh_i in range(mh_cnt):
            merkleHashes.append(vds.read_bytes(32))

        mf_cnt = vds.read_compact_size()                # merkleFlags cnt
        merkleFlags = []                                # merkleFlags
        for mf_i in range(mf_cnt):
            merkleFlags.append(vds.read_bytes(1))

        cbTx = Transaction.read_vds(vds)                # cbTx

        dmns_cnt = vds.read_compact_size()              # deletedMNs cnt
        deletedMNs = []                                 # deletedMNs
        for dmn_i in range(dmns_cnt):
            deletedMNs.append(vds.read_bytes(32))

        mnl_cnt = vds.read_compact_size()               # mnList cnt
        mnList = []                                     # mnList
        for mn_i in range(mnl_cnt):
            mnList.append(DashSMLEntry.read_vds(vds))

        deletedQuorums = []                             # deletedQuorums
        newQuorums = []                                 # newQuorums
        if vds.can_read_more():
            dq_cnt = vds.read_compact_size()            # deletedQuorums cnt
            for dq_i in range(dq_cnt):
                deletedQuorums.append(DeletedQuorum.read_vds(vds))
            nq_cnt = vds.read_compact_size()            # newQuorums cnt
            for nq_i in range(nq_cnt):
                newQuorums.append(DashQFCommitMsg.read_vds(vds))
        if alone_data and vds.can_read_more():
            raise SerializationError(f'{cls}: extra junk at the end')
        return DashMNListDiffMsg(baseBlockHash, blockHash, totalTransactions,
                                 merkleHashes, merkleFlags, cbTx, deletedMNs,
                                 mnList, deletedQuorums, newQuorums)


class DashQFCommitMsg(DashMsgBase):
    '''Class representing qfcommit message'''

    fields = ('version llmqType quorumHash signersSize signers'
              ' validMembersSize validMembers quorumPublicKey quorumVvecHash'
              ' quorumSig sig').split()

    def __init__(self, *args, **kwargs):
        super(DashQFCommitMsg, self).__init__(*args, **kwargs)

    def __str__(self):
        llmqType = (LLMQType(self.llmqType)
                        if LLMQType.has_value(self.llmqType)
                        else self.llmqType)
        return ('DashQFCommitMsg: version: %s, llmqType: %s(%s),'
                ' quorumHash: %s, signers(%s): %s,'
                ' validMembers(%s): %s, quorumPublicKey: %s,'
                ' quorumVvecHash: %s, quorumSig: %s, sig: %s' %
                (self.version, llmqType, self.llmqType,
                 bh2u(self.quorumHash[::-1]), self.signersSize,
                 bh2u(self.signers), self.validMembersSize,
                 bh2u(self.validMembers), bh2u(self.quorumPublicKey),
                 bh2u(self.quorumVvecHash[::-1]), bh2u(self.quorumSig),
                 bh2u(self.sig)))

    def serialize(self, as_hex=False):
        assert (self.signersSize + 7) // 8 == len(self.signers)
        assert (self.validMembersSize + 7) // 8 == len(self.validMembers)
        assert len(self.quorumHash) == 32
        assert len(self.quorumPublicKey) == 48
        assert len(self.quorumVvecHash) == 32
        assert len(self.quorumSig) == 96
        assert len(self.sig) == 96
        res = (
            pack('<H', self.version) +                  # version
            pack('B', self.llmqType) +                  # llmqType
            self.quorumHash +                           # quorumHash
            to_compact_size(self.signersSize) +         # signersSize
            self.signers +                              # signers
            to_compact_size(self.validMembersSize) +    # validMembersSize
            self.validMembers +                         # validMembers
            self.quorumPublicKey +                      # quorumPublicKey
            self.quorumVvecHash +                       # quorumVvecHash
            self.quorumSig +                            # quorumSig
            self.sig                                    # sig
        )
        if as_hex:
            return bh2u(res)
        else:
            return res

    @classmethod
    def from_hex(cls, hex_str):
        vds = BCDataStream()
        vds.clear_and_set_bytes(bfh(hex_str))
        return cls.read_vds(vds)

    @classmethod
    def read_vds(cls, vds, alone_data=False):
        version = vds.read_uint16()                     # version
        llmqType = vds.read_uchar()                     # llmqType
        quorumHash = vds.read_bytes(32)                 # quorumHash
        signers_size = vds.read_compact_size()          # signersSize
        signers_bytes = (signers_size + 7) // 8
        signers = vds.read_bytes(signers_bytes)         # signers
        valid_m_size = vds.read_compact_size()          # validMembersSize
        valid_m_bytes = (valid_m_size + 7) // 8
        validMembers = vds.read_bytes(valid_m_bytes)    # validMembers
        quorumPublicKey = vds.read_bytes(48)            # quorumPublicKey
        quorumVvecHash = vds.read_bytes(32)             # quorumVvecHash
        quorumSig = vds.read_bytes(96)                  # quorumSig
        sig = vds.read_bytes(96)                        # sig
        if alone_data and vds.can_read_more():
            raise SerializationError(f'{cls}: extra junk at the end')
        return DashQFCommitMsg(version, llmqType, quorumHash,
                               signers_size, signers, valid_m_size,
                               validMembers, quorumPublicKey,
                               quorumVvecHash, quorumSig, sig)


class DashFliterLoadMsg(DashMsgBase):
    '''Class representing filterload message'''

    fields = 'filter nHashFuncs nTweak nFlags'.split()

    def __init__(self, *args, **kwargs):
        super(DashFliterLoadMsg, self).__init__(*args, **kwargs)

    def __str__(self):
        return ('DashFliterLoadMsg: filter: %s, nHashFuncs: %s,'
                ' nTweak: %s, nFlags: 0x%.2X' %
                (bh2u(self.filter), self.nHashFuncs, self.nTweak, self.nFlags))

    def serialize(self):
        assert self.nHashFuncs <= FILTERLOAD_MAX_HASH_FUNCS
        assert len(self.filter) <= FILTERLOAD_MAX_FILTER_BYTES
        return (
            self.filter +                               # filter
            pack('<I', self.nHashFuncs) +               # nHashFuncs
            pack('<I', self.nTweak) +                   # nTweak
            pack('B', self.nFlags)                      # nFlags
        )

    @classmethod
    def read_vds(cls, vds, alone_data=False):
        filter_bcnt = vds.read_compact_size()
        if filter_bcnt > FILTERLOAD_MAX_FILTER_BYTES:
            raise DashMsgError(f'filterload msg: too long filter filed')
        filter_bytes = vds.read_bytes(filter_bcnt)      # filter
        nHashFuncs = vds.read_uint32()                  # nHashFuncs
        if nHashFuncs > FILTERLOAD_MAX_HASH_FUNCS:
            raise DashMsgError(f'filterload msg: too high value of nHashFuncs')
        nTweak = vds.read_uint32()                      # nTweak
        nFlags = vds.read_uchar()                       # nFlags
        if alone_data and vds.can_read_more():
            raise SerializationError(f'{cls}: extra junk at the end')
        return DashFliterLoadMsg(filter_bytes, nHashFuncs, nTweak, nFlags)


class DashFilterAddMsg(DashMsgBase):
    '''Class representing filteradd message'''

    fields = 'element'.split()

    def __init__(self, *args, **kwargs):
        super(DashFilterAddMsg, self).__init__(*args, **kwargs)

    def __str__(self):
        return ('DashFilterAddMsg: element: %s' % self.element)

    def serialize(self):
        assert len(self.element) <= FILTERADD_MAX_ELEMENT_BYTES
        return self.element                             # element

    @classmethod
    def read_vds(cls, vds, alone_data=False):
        element_bcnt = vds.read_compact_size()
        if element_bcnt > FILTERADD_MAX_ELEMENT_BYTES:
            raise DashMsgError(f'filteradd msg: too long element field')
        element_bytes = vds.read_bytes(element_bcnt)    # element
        if alone_data and vds.can_read_more():
            raise SerializationError(f'{cls}: extra junk at the end')
        return DashFilterAddMsg(element_bytes)
