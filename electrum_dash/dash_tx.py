#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Dash-Electrum - lightweight Dash client
# Copyright (C) 2018 Dash Developers
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


class DashTxError(Exception):
    """Thrown when there's a problem with Dash serialize/deserialize"""


# https://dash-docs.github.io/en/developer-reference#outpoint
class TxOutPoint(namedtuple('TxOutPoint', 'hash index')):
    '''Class representing tx output outpoint'''
    def serialize(self):
        assert len(self.hash) == 32
        return (
            self.hash +                         # hash
            struct.pack('<I', self.index)       # index
        )

    @classmethod
    def read_vds(cls, vds):
        return TxOutPoint(
            vds.read_bytes(32),                 # hash
            vds.read_uint32()                   # index
        )


# https://github.com/dashpay/dips/blob/master/dip-0002-special-transactions.md
class DashProRegTx(namedtuple('DashProRegTx',
                              'version type mode collateralOutpoint '
                              'ipAddress port KeyIdOwner PubKeyOperator '
                              'KeyIdVoting operatorReward scriptPayout '
                              'inputsHash payloadSig')):
    '''Class representing DIP3 ProRegTx'''
    def serialize(self):
        assert (len(self.ipAddress) == 16
                and len(self.KeyIdOwner) == 20
                and len(self.PubKeyOperator) == 48
                and len(self.KeyIdVoting) == 20
                and len(self.inputsHash) == 32)
        return (
            struct.pack('<H', self.version) +           # version
            struct.pack('<H', self.type) +              # type
            struct.pack('<H', self.mode) +              # mode
            self.collateralOutpoint.serialize() +       # collateralOutpoint
            self.ipAddress +                            # ipAddress
            struct.pack('<H', self.port) +              # port
            self.KeyIdOwner +                           # KeyIdOwner
            self.PubKeyOperator +                       # PubKeyOperator
            self.KeyIdVoting +                          # KeyIdVoting
            struct.pack('<H', self.operatorReward) +    # operatorReward
            to_varbytes(self.scriptPayout) +            # scriptPayout
            self.inputsHash +                           # inputsHash
            to_varbytes(self.payloadSig)                # payloadSig
        )

    @classmethod
    def read_vds(cls, vds):
        return DashProRegTx(
            vds.read_uint16(),                          # version
            vds.read_uint16(),                          # type
            vds.read_uint16(),                          # mode
            read_outpoint(vds),                         # collateralOutpoint
            vds.read_bytes(16),                         # ipAddress
            vds.read_uint16(),                          # port
            vds.read_bytes(20),                         # KeyIdOwner
            vds.read_bytes(48),                         # PubKeyOperator
            vds.read_bytes(20),                         # KeyIdVoting
            vds.read_uint16(),                          # operatorReward
            read_varbytes(vds),                         # scriptPayout
            vds.read_bytes(32),                         # inputsHash
            read_varbytes(vds)                          # payloadSig
        )


class DashProUpServTx(namedtuple('DashProUpServTx',
                                 'version proTxHash ipAddress port '
                                 'scriptOperatorPayout inputsHash '
                                 'payloadSig')):
    '''Class representing DIP3 ProUpServTx'''
    def serialize(self):
        assert (len(self.proTxHash) == 32
                and len(self.ipAddress) == 16
                and len(self.inputsHash) == 32
                and len(self.payloadSig) == 96)
        return (
            struct.pack('<H', self.version) +           # version
            self.proTxHash +                            # proTxHash
            self.ipAddress +                            # ipAddress
            struct.pack('<H', self.port) +              # port
            to_varbytes(self.scriptOperatorPayout) +    # scriptOperatorPayout
            self.inputsHash +                           # inputsHash
            self.payloadSig                             # payloadSig
        )

    @classmethod
    def read_vds(cls, vds):
        return DashProUpServTx(
            vds.read_uint16(),                          # version
            vds.read_bytes(32),                         # proTxHash
            vds.read_bytes(16),                         # ipAddress
            vds.read_uint16(),                          # port
            read_varbytes(vds),                         # scriptOperatorPayout
            vds.read_bytes(32),                         # inputsHash
            vds.read_bytes(96)                          # payloadSig
        )


class DashProUpRegTx(namedtuple('DashProUpRegTx',
                                'version proTxHash mode PubKeyOperator '
                                'KeyIdVoting scriptPayout inputsHash '
                                'payloadSig')):
    '''Class representing DIP3 ProUpRegTx'''
    def serialize(self):
        assert (len(self.proTxHash) == 32
                and len(self.PubKeyOperator) == 48
                and len(self.KeyIdVoting) == 20
                and len(self.inputsHash) == 32)
        return (
            struct.pack('<H', self.version) +           # version
            self.proTxHash +                            # proTxHash
            struct.pack('<H', self.mode) +              # mode
            self.PubKeyOperator +                       # PubKeyOperator
            self.KeyIdVoting +                          # KeyIdVoting
            to_varbytes(self.scriptPayout) +            # scriptPayout
            self.inputsHash +                           # inputsHash
            to_varbytes(self.payloadSig)                # payloadSig
        )

    @classmethod
    def read_vds(cls, vds):
        return DashProUpRegTx(
            vds.read_uint16(),                          # version
            vds.read_bytes(32),                         # proTxHash
            vds.read_uint16(),                          # mode
            vds.read_bytes(48),                         # PubKeyOperator
            vds.read_bytes(20),                         # KeyIdVoting
            read_varbytes(vds),                         # scriptPayout
            vds.read_bytes(32),                         # inputsHash
            read_varbytes(vds)                          # payloadSig
        )


class DashProUpRevTx(namedtuple('DashProUpRevTx',
                                'version proTxHash reason '
                                'inputsHash payloadSig')):
    '''Class representing DIP3 ProUpRevTx'''
    def serialize(self):
        assert (len(self.proTxHash) == 32
                and len(self.inputsHash) == 32
                and len(self.payloadSig) == 96)
        return (
            struct.pack('<H', self.version) +           # version
            self.proTxHash +                            # proTxHash
            struct.pack('<H', self.reason) +            # reason
            self.inputsHash +                           # inputsHash
            self.payloadSig                             # payloadSig
        )

    @classmethod
    def read_vds(cls, vds):
        return DashProUpRevTx(
            vds.read_uint16(),                          # version
            vds.read_bytes(32),                         # proTxHash
            vds.read_uint16(),                          # reason
            vds.read_bytes(32),                         # inputsHash
            vds.read_bytes(96)                          # payloadSig
        )


class DashCbTx(namedtuple('DashCbTx', 'version height merkleRootMNList')):
    '''Class representing DIP4 coinbase special tx'''
    def serialize(self):
        assert len(self.merkleRootMNList) == 32
        return (
            struct.pack('<H', self.version) +           # version
            struct.pack('<I', self.height) +            # height
            self.merkleRootMNList                       # merkleRootMNList
        )

    @classmethod
    def read_vds(cls, vds):
        return DashCbTx(
            vds.read_uint16(),                          # version
            vds.read_uint32(),                          # height
            vds.read_bytes(32)                          # merkleRootMNList
        )


class DashSubTxRegister(namedtuple('DashSubTxRegister',
                                   'version userName pubKey payloadSig')):
    '''Class representing DIP5 SubTxRegister'''
    def serialize(self):
        assert (len(self.pubKey) == 48
                and len(self.payloadSig) == 96)
        return (
            struct.pack('<H', self.version) +           # version
            to_varbytes(self.userName) +                # userName
            self.pubKey +                               # pubKey
            self.payloadSig                             # payloadSig
        )

    @classmethod
    def read_vds(cls, vds):
        return DashSubTxRegister(
            vds.read_uint16(),                          # version
            read_varbytes(vds),                         # userName
            vds.read_bytes(48),                         # pubKey
            vds.read_bytes(96)                          # payloadSig
        )


class DashSubTxTopup(namedtuple('DashSubTxTopup', 'version regTxHash')):
    '''Class representing DIP5 SubTxTopup'''
    def serialize(self):
        assert len(self.regTxHash) == 32
        return (
            struct.pack('<H', self.version) +           # version
            self.regTxHash                              # regTxHash
        )

    @classmethod
    def read_vds(cls, vds):
        return DashSubTxTopup(
            vds.read_uint16(),                          # version
            vds.read_bytes(32)                          # regTxHash
        )


class DashSubTxResetKey(namedtuple('DashSubTxResetKey',
                                   'version regTxHash hashPrevSubTx '
                                   'creditFee newPubKey payloadSig')):
    '''Class representing DIP5 SubTxResetKey'''
    def serialize(self):
        assert (len(self.regTxHash) == 32
                and len(self.hashPrevSubTx) == 32
                and len(self.newPubKey) == 48
                and len(self.payloadSig) == 96)
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
        return DashSubTxResetKey(
            vds.read_uint16(),                          # version
            vds.read_bytes(32),                         # regTxHash
            vds.read_bytes(32),                         # hashPrevSubTx
            vds.read_int64(),                           # creditFee
            vds.read_bytes(48),                         # newPubKey
            vds.read_bytes(96)                          # payloadSig
        )


class DashSubTxCloseAccount(namedtuple('DashSubTxCloseAccount',
                                       'version regTxHash hashPrevSubTx '
                                       'creditFee payloadSig')):
    '''Class representing DIP5 SubTxCloseAccount'''
    def serialize(self):
        assert (len(self.regTxHash) == 32
                and len(self.hashPrevSubTx) == 32
                and len(self.payloadSig) == 96)
        return (
            struct.pack('<H', self.version) +           # version
            self.regTxHash +                            # regTxHash
            self.hashPrevSubTx +                        # hashPrevSubTx
            struct.pack('<q', self.creditFee) +         # creditFee
            self.payloadSig                             # payloadSig
        )

    @classmethod
    def read_vds(cls, vds):
        return DashSubTxCloseAccount(
            vds.read_uint16(),                          # version
            vds.read_bytes(32),                         # regTxHash
            vds.read_bytes(32),                         # hashPrevSubTx
            vds.read_int64(),                           # creditFee
            vds.read_bytes(96)                          # payloadSig
        )


# Supported Spec Tx types and corresponding handlers mapping
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
    SPEC_PRO_REG_TX: DashProRegTx,
    SPEC_PRO_UP_SERV_TX: DashProUpServTx,
    SPEC_PRO_UP_REG_TX: DashProUpRegTx,
    SPEC_PRO_UP_REV_TX: DashProUpRevTx,
    SPEC_CB_TX: DashCbTx,
    SPEC_SUB_TX_REGISTER: DashSubTxRegister,
    SPEC_SUB_TX_TOPUP: DashSubTxTopup,
    SPEC_SUB_TX_RESET_KEY: DashSubTxResetKey,
    SPEC_SUB_TX_CLOSE_ACCOUNT: DashSubTxCloseAccount,
}


def read_extra_payload(vds, tx_type):
    if tx_type:
        extra_payload_size = vds.read_compact_size()
        end = vds.read_cursor + extra_payload_size
        spec_tx_class = SPEC_TX_HANDLERS.get(tx_type)
        if spec_tx_class:
            read_method = getattr(spec_tx_class, 'read_vds', None)
            if not read_method:
                raise NotImplementedError('Transaction method %s unknown' %
                                          read_method_name)
            extra_payload = read_method(vds)
            assert isinstance(extra_payload, spec_tx_class)
        else:
            extra_payload = vds.read_bytes(extra_payload_size)
        assert vds.read_cursor == end
    else:
        extra_payload = b''
    return extra_payload


def serialize_extra_payload(tx):
    tx_type = tx.tx_type
    if not tx_type:
        raise DashTxError('No special tx type set to serialize')

    extra = tx.extra_payload
    spec_tx_class = SPEC_TX_HANDLERS.get(tx_type)
    if not spec_tx_class:
        assert isinstance(extra, (bytes, bytearray))
        return extra

    if not isinstance(extra, spec_tx_class):
        raise DashTxError('Dash tx_type not conform with extra'
                          ' payload class: %s, %s' % (tx_type, extra))
    return extra.serialize()
