#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Axe-Electrum - lightweight Axe client
# Copyright (C) 2019 Axe Developers
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
from .axe_tx import (to_compact_size, to_varbytes, serialize_ip, str_ip,
                      service_to_ip_port, TxOutPoint, read_uint16_nbo,
                      CTxIn, CTxOut)
from .transaction import Transaction, BCDataStream, SerializationError
from .util import bh2u, bfh
from .i18n import _


# https://axe-docs.github.io/en/developer-reference#version
MAX_USER_AGENT_SIZE = 256
# https://axe-docs.github.io/en/developer-reference#addr
MAX_ADDRESSES = 1000
# https://axe-docs.github.io/en/developer-reference#inv
MAX_INV_ENTRIES = 50000
# https://axe-docs.github.io/en/developer-reference#filterload
FILTERLOAD_MAX_HASH_FUNCS = 50
FILTERLOAD_MAX_FILTER_BYTES = 36000
# https://axe-docs.github.io/en/developer-reference#filteradd
FILTERADD_MAX_ELEMENT_BYTES = 520
# https://github.com/axerunners/axe/blob/
# e9f7142ed01c0d7b53ef8b5f6f3f6375a68ef422/src/privatesend.h#L29
PRIVATESEND_ENTRY_MAX_SIZE = 9


class AxeMsgError(Exception):
    """Thrown when there's a problem with Axe message serialize/deserialize"""


class IntEnumWithCheck(IntEnum):
    '''IntEnum with hash_value class method'''
    @classmethod
    def has_value(cls, value):
        return any(value == item.value for item in cls)


class AxeType(IntEnumWithCheck):
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
    '''Enum representing known Axe spork IDs'''
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


class DSPoolState(IntEnumWithCheck):
    '''Enum representing pool state in dssu messages'''
    IDLE = 0
    QUEUE = 1
    ACCEPTING_ENTRIES = 2
    SIGNING = 3
    ERROR = 4
    SUCCESS = 5


DS_POOL_STATE_STR = {
    int(DSPoolState.IDLE): _('IDLE'),
    int(DSPoolState.QUEUE): _('QUEUE'),
    int(DSPoolState.ACCEPTING_ENTRIES): _('ACCEPTING_ENTRIES'),
    int(DSPoolState.SIGNING): _('SIGNING'),
    int(DSPoolState.ERROR): _('ERROR'),
    int(DSPoolState.SUCCESS): _('SUCCESS'),
}


def ds_pool_state_str(pool_state):
    if pool_state not in DS_POOL_STATE_STR:
        return _('UNKNOWN')
    return DS_POOL_STATE_STR[int(pool_state)]


class DSPoolStatusUpdate(IntEnumWithCheck):
    '''Enum representing pool status update in dssu messages'''
    REJECTED = 0
    ACCEPTED = 1


class DSMessageIDs(IntEnumWithCheck):
    '''Enum representing message ids in dssu messages'''
    ERR_ALREADY_HAVE = 0x00
    ERR_DENOM = 0x01
    ERR_ENTRIES_FULL = 0x02
    ERR_EXISTING_TX = 0x03
    ERR_FEES = 0x04
    ERR_INVALID_COLLATERAL = 0x05
    ERR_INVALID_INPUT = 0x06
    ERR_INVALID_SCRIPT = 0x07
    ERR_INVALID_TX = 0x08
    ERR_MAXIMUM = 0x09
    ERR_MN_LIST = 0x0a
    ERR_MODE = 0x0b
    ERR_NON_STANDARD_PUBKEY = 0x0c
    ERR_NOT_A_MN = 0x0d  # not used
    ERR_QUEUE_FULL = 0x0e
    ERR_RECENT = 0x0f
    ERR_SESSION = 0x10
    ERR_MISSING_TX = 0x11
    ERR_VERSION = 0x12
    MSG_NOERR = 0x13
    MSG_SUCCESS = 0x14
    MSG_ENTRIES_ADDED = 0x15


DS_MSG_STR = {
    int(DSMessageIDs.ERR_ALREADY_HAVE): _('Already have that input.'),
    int(DSMessageIDs.ERR_DENOM): _('No matching denominations found'
                                   ' for mixing.'),
    int(DSMessageIDs.ERR_ENTRIES_FULL): _('Entries are full.'),
    int(DSMessageIDs.ERR_EXISTING_TX): _('Not compatible with existing'
                                         ' transactions.'),
    int(DSMessageIDs.ERR_FEES): _('Transaction fees are too high.'),
    int(DSMessageIDs.ERR_INVALID_COLLATERAL): _('Collateral not valid.'),
    int(DSMessageIDs.ERR_INVALID_INPUT): _('Input is not valid.'),
    int(DSMessageIDs.ERR_INVALID_SCRIPT): _('Invalid script detected.'),
    int(DSMessageIDs.ERR_INVALID_TX): _('Transaction not valid.'),
    int(DSMessageIDs.ERR_MAXIMUM): _('Entry exceeds maximum size.'),
    int(DSMessageIDs.ERR_MN_LIST): _('Not in the Masternode list.'),
    int(DSMessageIDs.ERR_MODE): _('Incompatible mode.'),
    int(DSMessageIDs.ERR_NON_STANDARD_PUBKEY): _('Non-standard public key'
                                                 ' detected.'),
    int(DSMessageIDs.ERR_NOT_A_MN): _('This is not a Masternode.'),  # not used
    int(DSMessageIDs.ERR_QUEUE_FULL): _('Masternode queue is full.'),
    int(DSMessageIDs.ERR_RECENT): _('Last PrivateSend was too recent.'),
    int(DSMessageIDs.ERR_SESSION): _('Session not complete!'),
    int(DSMessageIDs.ERR_MISSING_TX): _('Missing input transaction'
                                        ' information.'),
    int(DSMessageIDs.ERR_VERSION): _('Incompatible version.'),
    int(DSMessageIDs.MSG_NOERR): _('No errors detected.'),
    int(DSMessageIDs.MSG_SUCCESS): _('Transaction created successfully.'),
    int(DSMessageIDs.MSG_ENTRIES_ADDED): _('Your entries added successfully.'),
}


def ds_msg_str(msg_id):
    if msg_id not in DS_MSG_STR:
        return _('Unknown response.')
    return DS_MSG_STR[int(msg_id)]


class AxeNetIPAddr(namedtuple('AxeNetIPAddr', 'time services ip port')):
    '''Class representing addr mesage payload'''

    def __str__(self):
        return ('AxeNetIPAddr: time: %s,'
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


class AxeSMLEntry(namedtuple('AxeSMLEntry',
                              'proRegTxHash confirmedHash ipAddress port'
                              ' pubKeyOperator keyIDVoting isValid')):
    '''Class representing Simplified Masternode List entry'''

    def __str__(self):
        return ('AxeSMLEntry: proRegTxHash: %s, confirmedHash: %s,'
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
        return AxeSMLEntry(proRegTxHash, confirmedHash, ipAddress,
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
        return AxeSMLEntry(proRegTxHash, confirmedHash, ipAddress,
                            port, pubKeyOperator, keyIDVoting, isValid)


class AxeInventory(namedtuple('AxeInventory', 'type hash')):
    '''Class representing addr mesage payload'''

    def __str__(self):
        tv = self.type
        tn = AxeType(tv).name if AxeType.has_value(tv) else tv
        return ('AxeInventory: %s %s' % (tn, bh2u(self.hash[::-1])))


class AxeCmd:
    '''Class representing Axe network message packed with msg header cmd'''

    def __init__(self, cmd, payload=None):
        lcmd = cmd.lower()
        vds = BCDataStream()
        vds.clear_and_set_bytes(payload)
        if lcmd == 'version':
            self.payload = AxeVersionMsg.read_vds(vds, alone_data=True)
        elif lcmd == 'ping':
            self.payload = AxePingMsg.read_vds(vds, alone_data=True)
        elif lcmd == 'pong':
            self.payload = AxePongMsg.read_vds(vds, alone_data=True)
        elif lcmd == 'addr':
            self.payload = AxeAddrMsg.read_vds(vds, alone_data=True)
        elif lcmd == 'inv':
            self.payload = AxeInvMsg.read_vds(vds, alone_data=True)
        elif lcmd == 'spork':
            self.payload = AxeSporkMsg.read_vds(vds, alone_data=True)
        elif lcmd == 'islock':
            self.payload = AxeISLockMsg.read_vds(vds, alone_data=True)
        elif lcmd == 'mnlistdiff':
            self.payload = AxeMNListDiffMsg.read_vds(vds, alone_data=True)
        elif lcmd == 'qfcommit':
            self.payload = AxeQFCommitMsg.read_vds(vds, alone_data=True)
        elif lcmd == 'senddsq':
            self.payload = AxeSendDsqMsg.read_vds(vds, alone_data=True)
        elif lcmd == 'dsa':
            self.payload = AxeDsaMsg.read_vds(vds, alone_data=True)
        elif lcmd == 'dsc':
            self.payload = AxeDscMsg.read_vds(vds, alone_data=True)
        elif lcmd == 'dsf':
            self.payload = AxeDsfMsg.read_vds(vds, alone_data=True)
        elif lcmd == 'dsi':
            self.payload = AxeDsiMsg.read_vds(vds, alone_data=True)
        elif lcmd == 'dsq':
            self.payload = AxeDsqMsg.read_vds(vds, alone_data=True)
        elif lcmd == 'dss':
            self.payload = AxeDssMsg.read_vds(vds, alone_data=True)
        elif lcmd == 'dssu':
            self.payload = AxeDssuMsg.read_vds(vds, alone_data=True)
        else:
            self.payload = payload
        self.cmd = lcmd

    def __str__(self):
        if not self.payload:
            return f'{self.cmd}'
        elif isinstance(self.payload, bytes):
            return f'{self.cmd}: {bh2u(self.payload)}'
        else:
            return f'{self.cmd}: {self.payload}'


class AxeMsgBase:
    '''Base Class representing Axe Network messages'''
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

    @classmethod
    def from_hex(cls, hex_str):
        vds = BCDataStream()
        vds.clear_and_set_bytes(bfh(hex_str))
        return cls.read_vds(vds)


class AxeVersionMsg(AxeMsgBase):
    '''Class representing version message'''

    fields = ('version services timestamp '
              'recv_services recv_ip recv_port '
              'trans_services trans_ip trans_port '
              'nonce user_agent start_height '
              'relay mnauth_challenge fMasternode').split()

    def __init__(self, *args, **kwargs):
        super(AxeVersionMsg, self).__init__(*args, **kwargs)

    def __str__(self):
        res = ('AxeVersionMsg: version: %s,'
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
        if self.fMasternode is not None:
            res += (', fMasternode: %s' % self.fMasternode)
        return res

    def serialize(self):
        if self.mnauth_challenge is not None:
            assert len(self.mnauth_challenge) == 32
        recv_ip = serialize_ip(self.recv_ip)
        trans_ip = serialize_ip(self.trans_ip)
        if self.user_agent:
            if isinstance(self.user_agent, str):
                user_agent = self.user_agent.encode()
                user_agent_bytes = to_varbytes(user_agent)
            else:
                user_agent_bytes = to_varbytes(self.user_agent)
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
        if self.fMasternode is not None:
            res += pack('B', self.fMasternode)          # fMasternode
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
            raise AxeMsgError('version msg: user_agent too long')
        user_agent = vds.read_bytes(user_agent_csize)   # user_agent
        start_height = vds.read_int32()                 # start_height

        relay = None
        mnauth_challenge = None
        fMasternode = None
        bleft = vds.bytes_left()
        if bleft > 0:
            relay = vds.read_uchar()                    # relay
        bleft = vds.bytes_left()
        if bleft > 0:
            mnauth_challenge = vds.read_bytes(32)       # mnauth_challenge
        bleft = vds.bytes_left()
        if bleft > 0:
            fMasternode = vds.read_uchar()              # fMasternode
        if alone_data and vds.can_read_more():
            raise SerializationError(f'{cls}: extra junk at the end')
        return AxeVersionMsg(version, services, timestamp,
                              recv_services, recv_ip, recv_port,
                              trans_services, trans_ip, trans_port,
                              nonce, user_agent, start_height,
                              relay, mnauth_challenge, fMasternode)


class AxeSendDsqMsg(AxeMsgBase):
    '''Class representing ping message'''

    fields = 'fSendDSQueue'.split()

    def __init__(self, *args, **kwargs):
        super(AxeSendDsqMsg, self).__init__(*args, **kwargs)

    def __str__(self):
        return 'AxeSendDsqMsg: fSendDSQueue: %s' % self.fSendDSQueue

    def serialize(self):
        return pack('B', self.fSendDSQueue)             # fSendDSQueue

    @classmethod
    def read_vds(cls, vds, alone_data=False):
        fSendDSQueue = vds.read_uchar()                 # fSendDSQueue
        return AxeSendDsqMsg(fSendDSQueue)


class AxePingMsg(AxeMsgBase):
    '''Class representing ping message'''

    fields = 'nonce'.split()

    def __init__(self, *args, **kwargs):
        super(AxePingMsg, self).__init__(*args, **kwargs)

    def __str__(self):
        return 'AxePingMsg: nonce: %s' % self.nonce

    def serialize(self):
        return pack('<Q', self.nonce)                   # nonce

    @classmethod
    def read_vds(cls, vds, alone_data=False):
        nonce = vds.read_uint64()                       # nonce
        if alone_data and vds.can_read_more():
            raise SerializationError(f'{cls}: extra junk at the end')
        return AxePingMsg(nonce)


class AxePongMsg(AxePingMsg):
    '''Class representing pong message'''

    def __str__(self):
        return 'AxePongMsg: nonce: %s' % self.nonce

    @classmethod
    def read_vds(cls, vds, alone_data=False):
        nonce = vds.read_uint64()                       # nonce
        if alone_data and vds.can_read_more():
            raise SerializationError(f'{cls}: extra junk at the end')
        return AxePongMsg(nonce)


class AxeAddrMsg(AxeMsgBase):
    '''Class representing addr message'''

    fields = 'addresses'.split()

    def __init__(self, *args, **kwargs):
        super(AxeAddrMsg, self).__init__(*args, **kwargs)

    def __str__(self):
        addr_str = [str(a) for a in self.addresses]
        return ('AxeAddrMsg: addresses(%s): %s' %
                (len(self.addresses), addr_str))

    def serialize(self):
        addr_cnt = len(self.addresses)
        if addr_cnt > MAX_ADDRESSES:
            raise AxeMsgError('addr msg: too many addresses to send')
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
            raise AxeMsgError('addr msg: too many addresses')
        addresses = []
        for addr_i in range(addr_cnt):
            time = vds.read_uint32()                    # time
            services = vds.read_uint64()                # services
            ip_addr = ip_address(vds.read_bytes(16))    # ip
            port = read_uint16_nbo(vds)                 # port
            addresses.append(AxeNetIPAddr(time, services, ip_addr, port))
        if alone_data and vds.can_read_more():
            raise SerializationError(f'{cls}: extra junk at the end')
        return AxeAddrMsg(addresses)


class AxeInvMsg(AxeMsgBase):
    '''Class representing inv message'''

    fields = 'inventory'.split()

    def __init__(self, *args, **kwargs):
        super(AxeInvMsg, self).__init__(*args, **kwargs)

    def __str__(self):
        inv_str = [str(i) for i in self.inventory]
        return ('AxeInvMsg: inventory(%s): %s' %
                (len(self.inventory), inv_str))

    def serialize(self):
        return self._serialize('inv')

    def _serialize(self, msg):
        inv_cnt = len(self.inventory)
        if inv_cnt > MAX_INV_ENTRIES:
            raise AxeMsgError(f'{msg} msg: too long inventory to send')
        res = to_compact_size(inv_cnt)
        for i in self.inventory:
            res += pack('<I', i.type)                   # type
            assert len(i.hash) == 32
            res += i.hash                               # hash
        return res

    @classmethod
    def read_vds(cls, vds, alone_data=False):
        return AxeInvMsg(cls._read_vds(vds, 'inv', alone_data))

    @classmethod
    def _read_vds(cls, vds, msg, alone_data=False):
        inv_cnt = vds.read_compact_size()
        if inv_cnt > MAX_INV_ENTRIES:
            raise AxeMsgError(f'{msg} msg: too long inventory')
        inventory = []
        for inv_i in range(inv_cnt):
            inv_type = vds.read_uint32()                # type
            inv_hash = vds.read_bytes(32)               # hash
            inventory.append(AxeInventory(inv_type, inv_hash))
        if alone_data and vds.can_read_more():
            raise SerializationError(f'{cls}: extra junk at the end')
        return inventory


class AxeGetDataMsg(AxeInvMsg):
    '''Class representing getdata message'''

    def __str__(self):
        inv_str = [str(i) for i in self.inventory]
        return ('AxeGetDataMsg: inventory(%s): %s' %
                (len(self.inventory), inv_str))

    def serialize(self):
        return self._serialize('getdata')

    @classmethod
    def read_vds(cls, vds, alone_data=False):
        return AxeGetDataMsg(cls._read_vds(vds, 'getdata', alone_data))


class AxeSporkMsg(AxeMsgBase):
    '''Class representing islock message'''

    fields = 'nSporkID nValue nTimeSigned vchSig'.split()

    def __init__(self, *args, **kwargs):
        super(AxeSporkMsg, self).__init__(*args, **kwargs)

    def __str__(self):
        is_known_id = SporkID.has_value(self.nSporkID)
        spork_id = SporkID(self.nSporkID) if is_known_id else self.nSporkID
        return ('AxeSporkMsg: nSporkID: %s, nValue: %s,'
                ' nTimeSigned: %s, vchSig: %s' %
                (spork_id, self.nValue, self.nTimeSigned, bh2u(self.vchSig)))

    @classmethod
    def read_vds(cls, vds, alone_data=False):
        nSporkID = vds.read_int32()                     # nSporkID
        nValue = vds.read_int64()                       # nValue
        nTimeSigned = vds.read_int64()                  # nTimeSigned
        vchSig_len = vds.read_compact_size()
        if vchSig_len != 65:
            raise AxeMsgError(f'spork msg: wrong vchSig length')
        vchSig = vds.read_bytes(65)                     # vchSig
        if alone_data and vds.can_read_more():
            raise SerializationError(f'{cls}: extra junk at the end')
        return AxeSporkMsg(nSporkID, nValue, nTimeSigned, vchSig)

    def msg_hash(self, new_sigs=True):
        if new_sigs:
            return sha256d(pack('<i', self.nSporkID) +
                           pack('<q', self.nValue) +
                           pack('<q', self.nTimeSigned))

        msg_str = str(self.nSporkID) + str(self.nValue) + str(self.nTimeSigned)
        return sha256d(msg_magic(msg_str.encode()))


class AxeISLockMsg(AxeMsgBase):
    '''Class representing islock message'''

    fields = 'inputs txid sig'.split()

    def __init__(self, *args, **kwargs):
        super(AxeISLockMsg, self).__init__(*args, **kwargs)

    def __str__(self):
        inputs_str = [str(i) for i in self.inputs]
        return ('AxeISLockMsg: inputs: %s, txid: %s, sig: %s' %
                (inputs_str, bh2u(self.txid[::-1]), self.sig))

    @classmethod
    def read_vds(cls, vds, alone_data=False):
        in_cnt = vds.read_compact_size()
        inputs = []
        for in_i in range(in_cnt):                      # read outpoints
            in_hash = vds.read_bytes(32)                # hash
            in_idx = vds.read_uint32()                  # idx
            inputs.append(TxOutPoint(in_hash, in_idx))
        txid = vds.read_bytes(32)                       # txid
        sig = vds.read_bytes(96)                        # sig
        if alone_data and vds.can_read_more():
            raise SerializationError(f'{cls}: extra junk at the end')
        return AxeISLockMsg(inputs, txid, sig)

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


class AxeCLSigMsg(AxeMsgBase):
    '''Class representing clsig message'''

    fields = 'nHeight blockHash sig'.split()

    def __init__(self, *args, **kwargs):
        super(AxeCLSigMsg, self).__init__(*args, **kwargs)

    def __str__(self):
        return ('AxeCLSigMsg: nHeight: %s, blockHash: %s, sig: %s' %
                (self.nHeight, bh2u(self.blockHash[::-1]), self.sig))

    @classmethod
    def read_vds(cls, vds, alone_data=False):
        nHeight = vds.read_uint32()                     # nHeight
        blockHash = vds.read_bytes(32)                  # blockHash
        sig = vds.read_bytes(96)                        # sig
        if alone_data and vds.can_read_more():
            raise SerializationError(f'{cls}: extra junk at the end')
        return AxeCLSigMsg(nHeight, blockHash, sig)

    def calc_request_id(self):
        return sha256d(b'\x05clsig' + pack('<I', self.nHeight))

    def msg_hash(self, quorum, request_id):
        return sha256d(
            pack('B', quorum.llmqType) +
            quorum.quorumHash +
            request_id +
            self.blockHash
        )


class AxeGetMNListDMsg(AxeMsgBase):
    '''Class representing getmnlistd message'''

    fields = 'baseBlockHash blockHash'.split()

    def __init__(self, *args, **kwargs):
        super(AxeGetMNListDMsg, self).__init__(*args, **kwargs)

    def __str__(self):
        return ('AxeGetMNListDMsg: baseBlockHash: %s, blockHash: %s' %
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
        return AxeGetMNListDMsg(baseBlockHash, blockHash)


class AxeMNListDiffMsg(AxeMsgBase):
    '''Class representing mnlistdiff message'''

    fields = ('baseBlockHash blockHash totalTransactions merkleHashes'
              ' merkleFlags cbTx deletedMNs mnList deletedQuorums'
              ' newQuorums').split()

    def __init__(self, *args, **kwargs):
        super(AxeMNListDiffMsg, self).__init__(*args, **kwargs)

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
        return ('AxeMNListDiffMsg: baseBlockHash: %s, blockHash: %s,'
                ' totalTransactions: %s, merkleHashes(%s): %s,'
                ' merkleFlags: %s, cbTx: %s,'
                ' deletedMNs(%s): %s, mnList(%s): %s,'
                ' deletedQuorums(%s): %s, newQuorums(%s): %s' %
                (bh2u(self.baseBlockHash[::-1]), bh2u(self.blockHash[::-1]),
                 self.totalTransactions, mh_cnt, merkleHashes,
                 merkleFlags, self.cbTx,
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
            mnList.append(AxeSMLEntry.read_vds(vds))

        deletedQuorums = []                             # deletedQuorums
        newQuorums = []                                 # newQuorums
        if vds.can_read_more():
            dq_cnt = vds.read_compact_size()            # deletedQuorums cnt
            for dq_i in range(dq_cnt):
                deletedQuorums.append(DeletedQuorum.read_vds(vds))
            nq_cnt = vds.read_compact_size()            # newQuorums cnt
            for nq_i in range(nq_cnt):
                newQuorums.append(AxeQFCommitMsg.read_vds(vds))
        if alone_data and vds.can_read_more():
            raise SerializationError(f'{cls}: extra junk at the end')
        return AxeMNListDiffMsg(baseBlockHash, blockHash, totalTransactions,
                                 merkleHashes, merkleFlags, cbTx, deletedMNs,
                                 mnList, deletedQuorums, newQuorums)


class AxeQFCommitMsg(AxeMsgBase):
    '''Class representing qfcommit message'''

    fields = ('version llmqType quorumHash signersSize signers'
              ' validMembersSize validMembers quorumPublicKey quorumVvecHash'
              ' quorumSig sig').split()

    def __init__(self, *args, **kwargs):
        super(AxeQFCommitMsg, self).__init__(*args, **kwargs)

    def __str__(self):
        llmqType = (LLMQType(self.llmqType)
                    if LLMQType.has_value(self.llmqType)
                    else self.llmqType)
        return ('AxeQFCommitMsg: version: %s, llmqType: %s(%s),'
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
        return AxeQFCommitMsg(version, llmqType, quorumHash,
                               signers_size, signers, valid_m_size,
                               validMembers, quorumPublicKey,
                               quorumVvecHash, quorumSig, sig)


class AxeFliterLoadMsg(AxeMsgBase):
    '''Class representing filterload message'''

    fields = 'filter nHashFuncs nTweak nFlags'.split()

    def __init__(self, *args, **kwargs):
        super(AxeFliterLoadMsg, self).__init__(*args, **kwargs)

    def __str__(self):
        return ('AxeFliterLoadMsg: filter: %s, nHashFuncs: %s,'
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
            raise AxeMsgError(f'filterload msg: too long filter filed')
        filter_bytes = vds.read_bytes(filter_bcnt)      # filter
        nHashFuncs = vds.read_uint32()                  # nHashFuncs
        if nHashFuncs > FILTERLOAD_MAX_HASH_FUNCS:
            raise AxeMsgError(f'filterload msg: too high value of nHashFuncs')
        nTweak = vds.read_uint32()                      # nTweak
        nFlags = vds.read_uchar()                       # nFlags
        if alone_data and vds.can_read_more():
            raise SerializationError(f'{cls}: extra junk at the end')
        return AxeFliterLoadMsg(filter_bytes, nHashFuncs, nTweak, nFlags)


class AxeFilterAddMsg(AxeMsgBase):
    '''Class representing filteradd message'''

    fields = 'element'.split()

    def __init__(self, *args, **kwargs):
        super(AxeFilterAddMsg, self).__init__(*args, **kwargs)

    def __str__(self):
        return ('AxeFilterAddMsg: element: %s' % self.element)

    def serialize(self):
        assert len(self.element) <= FILTERADD_MAX_ELEMENT_BYTES
        return self.element                             # element

    @classmethod
    def read_vds(cls, vds, alone_data=False):
        element_bcnt = vds.read_compact_size()
        if element_bcnt > FILTERADD_MAX_ELEMENT_BYTES:
            raise AxeMsgError(f'filteradd msg: too long element field')
        element_bytes = vds.read_bytes(element_bcnt)    # element
        if alone_data and vds.can_read_more():
            raise SerializationError(f'{cls}: extra junk at the end')
        return AxeFilterAddMsg(element_bytes)


class AxeDsaMsg(AxeMsgBase):
    '''Class representing dsa message'''

    fields = 'nDenom txCollateral'.split()

    def __init__(self, *args, **kwargs):
        super(AxeDsaMsg, self).__init__(*args, **kwargs)

    def __str__(self):
        return ('AxeDsaMsg: nDenom: %s, txCollateral: %s' %
                (self.nDenom, self.txCollateral))

    @classmethod
    def read_vds(cls, vds, alone_data=False):
        nDenom = vds.read_int32()                       # nDenom
        txCollateral = Transaction.read_vds(vds)        # txCollateral
        if alone_data and vds.can_read_more():
            raise SerializationError(f'{cls}: extra junk at the end')
        return AxeDsaMsg(nDenom, str(txCollateral))

    def serialize(self):
        return (
            pack('<i', self.nDenom) +                   # nDenom
            bfh(self.txCollateral)                      # txCollateral
        )


class AxeDssuMsg(AxeMsgBase):
    '''Class representing dssu message'''

    fields = 'sessionID state entriesCount statusUpdate messageID'.split()

    def __init__(self, *args, **kwargs):
        super(AxeDssuMsg, self).__init__(*args, **kwargs)

    def __str__(self):
        state = (DSPoolState(self.state).name
                 if DSPoolState.has_value(self.state)
                 else self.state)
        statusUpdate = (DSPoolStatusUpdate(self.statusUpdate).name
                        if DSPoolStatusUpdate.has_value(self.statusUpdate)
                        else self.statusUpdate)
        messageID = (DSMessageIDs(self.messageID).name
                     if DSMessageIDs.has_value(self.messageID)
                     else self.messageID)
        return ('AxeDssuMsg: sessionID: %s, state: %s,'
                ' entriesCount: %s, statusUpdate: %s,'
                ' messageID: %s' %
                (self.sessionID, state,
                 self.entriesCount, statusUpdate, messageID))

    @classmethod
    def read_vds(cls, vds, alone_data=False):
        sessionID = vds.read_int32()                    # sessionID
        state = vds.read_int32()                        # state
        entriesCount = vds.read_int32()                 # entriesCount
        statusUpdate = vds.read_int32()                 # statusUpdate
        messageID = vds.read_int32()                    # messageID
        if alone_data and vds.can_read_more():
            raise SerializationError(f'{cls}: extra junk at the end')
        return AxeDssuMsg(sessionID, state, entriesCount,
                           statusUpdate, messageID)

    def serialize(self):
        return (
            pack('<i', self.sessionID) +                # sessionID
            pack('<i', self.state) +                    # state
            pack('<i', self.entriesCount) +             # entriesCount
            pack('<i', self.statusUpdate) +             # statusUpdate
            pack('<i', self.messageID)                  # messageID
        )


class AxeDstxMsg(AxeMsgBase):
    '''Class representing dstx message'''

    fields = 'tx masternodeOutPoint vchSig sigTime'.split()

    def __init__(self, *args, **kwargs):
        super(AxeDstxMsg, self).__init__(*args, **kwargs)

    def __str__(self):
        return ('AxeDstxMsg: masternodeOutPoint: %s, sigTime: %s' %
                (self.masternodeOutPoint, self.sigTime))

    @classmethod
    def read_vds(cls, vds, alone_data=False):
        tx = Transaction.read_vds(vds)                  # tx
        masternodeOutPoint = TxOutPoint.read_vds(vds)   # masternodeOutPoint
        vchSig_len = vds.read_compact_size()
        if vchSig_len != 96:
            raise AxeMsgError(f'dsq msg: wrong vchSig length')
        vchSig = vds.read_bytes(96)                     # vchSig
        sigTime = vds.read_int64()                      # sigTime
        if alone_data and vds.can_read_more():
            raise SerializationError(f'{cls}: extra junk at the end')
        return AxeDstxMsg(tx, masternodeOutPoint, vchSig, sigTime)

    def msg_hash(self):
        return sha256d(bfh(self.tx.serialize()) +
                       self.masternodeOutPoint.serialize() +
                       pack('<q', self.sigTime))


class AxeDsqMsg(AxeMsgBase):
    '''Class representing dsq message'''

    fields = 'nDenom masternodeOutPoint nTime fReady vchSig'.split()

    def __init__(self, *args, **kwargs):
        super(AxeDsqMsg, self).__init__(*args, **kwargs)

    def __str__(self):
        return ('AxeDsqMsg: nDenom: %s, masternodeOutPoint: %s,'
                ' nTime: %s, fReady: %s' %
                (self.nDenom, self.masternodeOutPoint,
                 self.nTime, self.fReady))

    @classmethod
    def read_vds(cls, vds, alone_data=False):
        nDenom = vds.read_int32()                       # nDenom
        masternodeOutPoint = TxOutPoint.read_vds(vds)   # masternodeOutPoint
        nTime = vds.read_int64()                        # nTime
        fReady = vds.read_uchar()                       # fReady
        vchSig_len = vds.read_compact_size()
        if vchSig_len != 96:
            raise AxeMsgError(f'dsq msg: wrong vchSig length')
        vchSig = vds.read_bytes(96)                     # vchSig
        if alone_data and vds.can_read_more():
            raise SerializationError(f'{cls}: extra junk at the end')
        return AxeDsqMsg(nDenom, masternodeOutPoint, nTime,
                          fReady, vchSig)

    def serialize(self):
        return (
            pack('<i', self.nDenom) +                   # nDenom
            self.masternodeOutPoint.serialize() +       # masternodeOutPoint
            pack('<q', self.nTime) +                    # nTime
            pack('B', self.fReady) +                    # fReady
            to_compact_size(len(self.vchSig)) +         # vchSig
            self.vchSig
        )

    def msg_hash(self):
        return sha256d(pack('<i', self.nDenom) +
                       self.masternodeOutPoint.serialize() +
                       pack('<q', self.nTime) +
                       pack('B', self.fReady))


class AxeDsiMsg(AxeMsgBase):
    '''Class representing dsi message'''

    fields = 'vecTxDSIn txCollateral vecTxDSOut'.split()

    def __init__(self, *args, **kwargs):
        super(AxeDsiMsg, self).__init__(*args, **kwargs)

    def __str__(self):
        vecTxDSInCnt = len(self.vecTxDSIn)
        vecTxDSOutCnt = len(self.vecTxDSIn)
        return ('AxeDsiMsg: vecTxDSIn (%s): %s, txCollateral: %s,'
                ' vecTxDSOut (%s): %s' %
                (vecTxDSInCnt, self.vecTxDSIn, self.txCollateral,
                 vecTxDSOutCnt, self.vecTxDSOut))

    @classmethod
    def read_vds(cls, vds, alone_data=False):
        txin_cnt = vds.read_compact_size()
        if txin_cnt > PRIVATESEND_ENTRY_MAX_SIZE:
            raise AxeMsgError('dsi msg: too many inputs')
        vecTxDSIn = []                                  # vecTxDSIn
        for txin_i in range(txin_cnt):
            vecTxDSIn.append(CTxIn.read_vds(vds))
        txCollateral = Transaction.read_vds(vds)        # txCollateral
        txout_cnt = vds.read_compact_size()
        if txout_cnt > PRIVATESEND_ENTRY_MAX_SIZE:
            raise AxeMsgError('dsi msg: too many outputs')
        vecTxDSOut = []                                 # vecTxDSOut
        for txout_i in range(txout_cnt):
            vecTxDSOut.append(CTxOut.read_vds(vds))
        if alone_data and vds.can_read_more():
            raise SerializationError(f'{cls}: extra junk at the end')
        return AxeDsiMsg(vecTxDSIn, str(txCollateral), vecTxDSOut)

    def serialize(self):
        res = to_compact_size(len(self.vecTxDSIn))      # vecTxDSIn
        for txin in self.vecTxDSIn:
            res += txin.serialize()
        res += bfh(self.txCollateral)                   # txCollateral
        res += to_compact_size(len(self.vecTxDSOut))    # vecTxDSOut
        for txout in self.vecTxDSOut:
            res += txout.serialize()
        return res


class AxeDsfMsg(AxeMsgBase):
    '''Class representing dsf message'''

    fields = 'sessionID txFinal'.split()

    def __init__(self, *args, **kwargs):
        super(AxeDsfMsg, self).__init__(*args, **kwargs)

    def __str__(self):
        return ('AxeDsfMsg: sessionID: %s, txFinal: %s,' %
                (self.sessionID, self.txFinal))

    @classmethod
    def read_vds(cls, vds, alone_data=False):
        sessionID = vds.read_int32()                    # sessionID
        txFinal = Transaction.read_vds(vds)             # txFinal
        if alone_data and vds.can_read_more():
            raise SerializationError(f'{cls}: extra junk at the end')
        return AxeDsfMsg(sessionID, txFinal)

    def serialize(self):
        return (
            pack('<i', self.sessionID) +                # sessionID
            bfh(self.txFinal.serialize())               # txFinal
        )


class AxeDssMsg(AxeMsgBase):
    '''Class representing dss message'''

    fields = 'inputs'.split()

    def __init__(self, *args, **kwargs):
        super(AxeDssMsg, self).__init__(*args, **kwargs)

    def __str__(self):
        inputsCnt = len(self.inputs)
        return ('AxeDssMsg: inputs (%s): %s' % (inputsCnt, self.inputs))

    @classmethod
    def read_vds(cls, vds, alone_data=False):
        txin_cnt = vds.read_compact_size()
        if txin_cnt > PRIVATESEND_ENTRY_MAX_SIZE:
            raise AxeMsgError('dss msg: too many inputs')
        inputs = []                                     # inputs
        for txin_i in range(txin_cnt):
            inputs.append(CTxIn.read_vds(vds))
        if alone_data and vds.can_read_more():
            raise SerializationError(f'{cls}: extra junk at the end')
        return AxeDssMsg(inputs)

    def serialize(self):
        res = to_compact_size(len(self.inputs))         # inputs
        for txin in self.inputs:
            res += txin.serialize()
        return res


class AxeDscMsg(AxeMsgBase):
    '''Class representing dsc message'''

    fields = 'sessionID messageID'.split()

    def __init__(self, *args, **kwargs):
        super(AxeDscMsg, self).__init__(*args, **kwargs)

    def __str__(self):
        messageID = (DSMessageIDs(self.messageID).name
                     if DSMessageIDs.has_value(self.messageID)
                     else self.messageID)
        return ('AxeDscMsg: sessionID: %s, messageID: %s' %
                (self.sessionID, messageID))

    @classmethod
    def read_vds(cls, vds, alone_data=False):
        sessionID = vds.read_int32()                    # sessionID
        messageID = vds.read_int32()                    # messageID
        if alone_data and vds.can_read_more():
            raise SerializationError(f'{cls}: extra junk at the end')
        return AxeDscMsg(sessionID, messageID)

    def serialize(self):
        return (
            pack('<i', self.sessionID) +                # sessionID
            pack('<i', self.messageID)                  # messageID
        )
