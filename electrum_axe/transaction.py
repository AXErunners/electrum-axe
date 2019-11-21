#!/usr/bin/env python
#
# Electrum - lightweight Bitcoin client
# Copyright (C) 2011 Thomas Voegtlin
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



# Note: The deserialization code originally comes from ABE.

import struct
import traceback
import sys
from typing import (Sequence, Union, NamedTuple, Tuple, Optional, Iterable,
                    Callable, List, Dict)

from . import ecc, bitcoin, constants
from .util import profiler, to_bytes, bh2u, bfh
from .bitcoin import (TYPE_ADDRESS, TYPE_PUBKEY, TYPE_SCRIPT, hash_160,
                      hash160_to_p2sh, hash160_to_p2pkh,
                      hash_encode, var_int, TOTAL_COIN_SUPPLY_LIMIT_IN_BTC, COIN,
                      push_script, int_to_hex, push_script, b58_address_to_hash160,
                      opcodes, add_number_to_script, base_decode)
from .crypto import sha256d
from .keystore import xpubkey_to_address, xpubkey_to_pubkey
from .axe_tx import (ProTxBase, read_extra_payload, serialize_extra_payload,
                      to_varbytes)
from .logging import get_logger


_logger = get_logger(__name__)


NO_SIGNATURE = 'ff'
PARTIAL_TXN_HEADER_MAGIC = b'EPTF\xff'


class SerializationError(Exception):
    """ Thrown when there's a problem deserializing or serializing """


class UnknownTxinType(Exception):
    pass


class NotRecognizedRedeemScript(Exception):
    pass


class MalformedBitcoinScript(Exception):
    pass


class TxOutput(NamedTuple):
    type: int
    address: str
    value: Union[int, str]  # str when the output is set to max: '!'


class TxOutputForUI(NamedTuple):
    address: str
    value: int


class TxOutputHwInfo(NamedTuple):
    address_index: Tuple
    sorted_xpubs: Iterable[str]
    num_sig: Optional[int]
    script_type: str


class BCDataStream(object):
    """Workalike python implementation of Bitcoin's CDataStream class."""

    def __init__(self):
        self.input = None
        self.read_cursor = 0

    def clear(self):
        self.input = None
        self.read_cursor = 0

    def clear_and_set_bytes(self, _bytes):
        self.read_cursor = 0
        if self.input is None:
            self.input = _bytes

    def write(self, _bytes):  # Initialize with string of _bytes
        if self.input is None:
            self.input = bytearray(_bytes)
        else:
            self.input += bytearray(_bytes)

    def read_string(self, encoding='ascii'):
        # Strings are encoded depending on length:
        # 0 to 252 :  1-byte-length followed by bytes (if any)
        # 253 to 65,535 : byte'253' 2-byte-length followed by bytes
        # 65,536 to 4,294,967,295 : byte '254' 4-byte-length followed by bytes
        # ... and the Bitcoin client is coded to understand:
        # greater than 4,294,967,295 : byte '255' 8-byte-length followed by bytes of string
        # ... but I don't think it actually handles any strings that big.
        if self.input is None:
            raise SerializationError("call write(bytes) before trying to deserialize")

        length = self.read_compact_size()

        return self.read_bytes(length).decode(encoding)

    def write_string(self, string, encoding='ascii'):
        string = to_bytes(string, encoding)
        # Length-encoded as with read-string
        self.write_compact_size(len(string))
        self.write(string)

    def read_bytes(self, length):
        try:
            result = self.input[self.read_cursor:self.read_cursor+length]
            self.read_cursor += length
            return result
        except IndexError:
            raise SerializationError("attempt to read past end of buffer") from None

    def can_read_more(self) -> bool:
        return self.bytes_left() > 0

    def bytes_left(self):
        if not self.input:
            return 0
        return len(self.input) - self.read_cursor

    def read_boolean(self): return self.read_bytes(1)[0] != chr(0)
    def read_char(self): return self._read_num('<b')
    def read_uchar(self): return self._read_num('<B')
    def read_int16(self): return self._read_num('<h')
    def read_uint16(self): return self._read_num('<H')
    def read_int32(self): return self._read_num('<i')
    def read_uint32(self): return self._read_num('<I')
    def read_int64(self): return self._read_num('<q')
    def read_uint64(self): return self._read_num('<Q')

    def write_boolean(self, val): return self.write(chr(1) if val else chr(0))
    def write_char(self, val): return self._write_num('<b', val)
    def write_uchar(self, val): return self._write_num('<B', val)
    def write_int16(self, val): return self._write_num('<h', val)
    def write_uint16(self, val): return self._write_num('<H', val)
    def write_int32(self, val): return self._write_num('<i', val)
    def write_uint32(self, val): return self._write_num('<I', val)
    def write_int64(self, val): return self._write_num('<q', val)
    def write_uint64(self, val): return self._write_num('<Q', val)

    def read_compact_size(self):
        try:
            size = self.input[self.read_cursor]
            self.read_cursor += 1
            if size == 253:
                size = self._read_num('<H')
            elif size == 254:
                size = self._read_num('<I')
            elif size == 255:
                size = self._read_num('<Q')
            return size
        except IndexError as e:
            raise SerializationError("attempt to read past end of buffer") from e

    def write_compact_size(self, size):
        if size < 0:
            raise SerializationError("attempt to write size < 0")
        elif size < 253:
            self.write(bytes([size]))
        elif size < 2**16:
            self.write(b'\xfd')
            self._write_num('<H', size)
        elif size < 2**32:
            self.write(b'\xfe')
            self._write_num('<I', size)
        elif size < 2**64:
            self.write(b'\xff')
            self._write_num('<Q', size)

    def _read_num(self, format):
        try:
            (i,) = struct.unpack_from(format, self.input, self.read_cursor)
            self.read_cursor += struct.calcsize(format)
        except Exception as e:
            raise SerializationError(e) from e
        return i

    def _write_num(self, format, num):
        s = struct.pack(format, num)
        self.write(s)


def script_GetOp(_bytes : bytes):
    i = 0
    while i < len(_bytes):
        vch = None
        opcode = _bytes[i]
        i += 1

        if opcode <= opcodes.OP_PUSHDATA4:
            nSize = opcode
            if opcode == opcodes.OP_PUSHDATA1:
                try: nSize = _bytes[i]
                except IndexError: raise MalformedBitcoinScript()
                i += 1
            elif opcode == opcodes.OP_PUSHDATA2:
                try: (nSize,) = struct.unpack_from('<H', _bytes, i)
                except struct.error: raise MalformedBitcoinScript()
                i += 2
            elif opcode == opcodes.OP_PUSHDATA4:
                try: (nSize,) = struct.unpack_from('<I', _bytes, i)
                except struct.error: raise MalformedBitcoinScript()
                i += 4
            vch = _bytes[i:i + nSize]
            i += nSize

        yield opcode, vch, i


class OPPushDataGeneric:
    def __init__(self, pushlen: Callable=None):
        if pushlen is not None:
            self.check_data_len = pushlen

    @classmethod
    def check_data_len(cls, datalen: int) -> bool:
        # Opcodes below OP_PUSHDATA4 all just push data onto stack, and are equivalent.
        return opcodes.OP_PUSHDATA4 >= datalen >= 0

    @classmethod
    def is_instance(cls, item):
        # accept objects that are instances of this class
        # or other classes that are subclasses
        return isinstance(item, cls) \
               or (isinstance(item, type) and issubclass(item, cls))


OPPushDataPubkey = OPPushDataGeneric(lambda x: x in (33, 65))
# note that this does not include x_pubkeys !


def match_decoded(decoded, to_match):
    if decoded is None:
        return False
    if len(decoded) != len(to_match):
        return False
    for i in range(len(decoded)):
        to_match_item = to_match[i]
        decoded_item = decoded[i]
        if OPPushDataGeneric.is_instance(to_match_item) and to_match_item.check_data_len(decoded_item[0]):
            continue
        if to_match_item != decoded_item[0]:
            return False
    return True


def parse_sig(x_sig):
    return [None if x == NO_SIGNATURE else x for x in x_sig]

def safe_parse_pubkey(x):
    try:
        return xpubkey_to_pubkey(x)
    except:
        return x

def parse_scriptSig(d, _bytes):
    try:
        decoded = [ x for x in script_GetOp(_bytes) ]
    except Exception as e:
        # coinbase transactions raise an exception
        _logger.info(f"parse_scriptSig: cannot find address in input script (coinbase?) {bh2u(_bytes)}")
        return

    match = [OPPushDataGeneric]
    if match_decoded(decoded, match):
        item = decoded[0][1]
        if item[0] != 0:
            # assert item[0] == 0x30
            # pay-to-pubkey
            d['type'] = 'p2pk'
            d['address'] = "(pubkey)"
            d['signatures'] = [bh2u(item)]
            d['num_sig'] = 1
            d['x_pubkeys'] = ["(pubkey)"]
            d['pubkeys'] = ["(pubkey)"]
        return

    # p2pkh TxIn transactions push a signature
    # (71-73 bytes) and then their public key
    # (33 or 65 bytes) onto the stack:
    match = [OPPushDataGeneric, OPPushDataGeneric]
    if match_decoded(decoded, match):
        sig = bh2u(decoded[0][1])
        x_pubkey = bh2u(decoded[1][1])
        try:
            signatures = parse_sig([sig])
            pubkey, address = xpubkey_to_address(x_pubkey)
        except:
            _logger.info(f"parse_scriptSig: cannot find address in input script (p2pkh?) {bh2u(_bytes)}")
            return
        d['type'] = 'p2pkh'
        d['signatures'] = signatures
        d['x_pubkeys'] = [x_pubkey]
        d['num_sig'] = 1
        d['pubkeys'] = [pubkey]
        d['address'] = address
        return

    # p2sh transaction, m of n
    match = [opcodes.OP_0] + [OPPushDataGeneric] * (len(decoded) - 1)
    if match_decoded(decoded, match):
        x_sig = [bh2u(x[1]) for x in decoded[1:-1]]
        redeem_script_unsanitized = decoded[-1][1]  # for partial multisig txn, this has x_pubkeys
        try:
            m, n, x_pubkeys, pubkeys, redeem_script = parse_redeemScript_multisig(redeem_script_unsanitized)
        except NotRecognizedRedeemScript:
            _logger.info(f"parse_scriptSig: cannot find address in input script (p2sh?) {bh2u(_bytes)}")

            # we could still guess:
            # d['address'] = hash160_to_p2sh(hash_160(decoded[-1][1]))
            return
        # write result in d
        d['type'] = 'p2sh'
        d['num_sig'] = m
        d['signatures'] = parse_sig(x_sig)
        d['x_pubkeys'] = x_pubkeys
        d['pubkeys'] = pubkeys
        d['redeem_script'] = redeem_script
        d['address'] = hash160_to_p2sh(hash_160(bfh(redeem_script)))
        return

    # custom partial format for imported addresses
    match = [opcodes.OP_INVALIDOPCODE, opcodes.OP_0, OPPushDataGeneric]
    if match_decoded(decoded, match):
        x_pubkey = bh2u(decoded[2][1])
        pubkey, address = xpubkey_to_address(x_pubkey)
        d['type'] = 'address'
        d['address'] = address
        d['num_sig'] = 1
        d['x_pubkeys'] = [x_pubkey]
        d['pubkeys'] = None  # get_sorted_pubkeys will populate this
        d['signatures'] = [None]
        return

    _logger.info(f"parse_scriptSig: cannot find address in input script (unknown) {bh2u(_bytes)}")


def parse_redeemScript_multisig(redeem_script: bytes):
    try:
        dec2 = [ x for x in script_GetOp(redeem_script) ]
    except MalformedBitcoinScript:
        raise NotRecognizedRedeemScript()
    try:
        m = dec2[0][0] - opcodes.OP_1 + 1
        n = dec2[-2][0] - opcodes.OP_1 + 1
    except IndexError:
        raise NotRecognizedRedeemScript()
    op_m = opcodes.OP_1 + m - 1
    op_n = opcodes.OP_1 + n - 1
    match_multisig = [op_m] + [OPPushDataGeneric] * n + [op_n, opcodes.OP_CHECKMULTISIG]
    if not match_decoded(dec2, match_multisig):
        raise NotRecognizedRedeemScript()
    x_pubkeys = [bh2u(x[1]) for x in dec2[1:-2]]
    pubkeys = [safe_parse_pubkey(x) for x in x_pubkeys]
    redeem_script2 = bfh(multisig_script(x_pubkeys, m))
    if redeem_script2 != redeem_script:
        raise NotRecognizedRedeemScript()
    redeem_script_sanitized = multisig_script(pubkeys, m)
    return m, n, x_pubkeys, pubkeys, redeem_script_sanitized


def get_address_from_output_script(_bytes: bytes, *, net=None) -> Tuple[int, str]:
    try:
        decoded = [x for x in script_GetOp(_bytes)]
    except MalformedBitcoinScript:
        decoded = None

    # p2pk
    match = [OPPushDataPubkey, opcodes.OP_CHECKSIG]
    if match_decoded(decoded, match) and ecc.ECPubkey.is_pubkey_bytes(decoded[0][1]):
        return TYPE_PUBKEY, bh2u(decoded[0][1])

    # p2pkh
    match = [opcodes.OP_DUP, opcodes.OP_HASH160, OPPushDataGeneric(lambda x: x == 20), opcodes.OP_EQUALVERIFY, opcodes.OP_CHECKSIG]
    if match_decoded(decoded, match):
        return TYPE_ADDRESS, hash160_to_p2pkh(decoded[2][1], net=net)

    # p2sh
    match = [opcodes.OP_HASH160, OPPushDataGeneric(lambda x: x == 20), opcodes.OP_EQUAL]
    if match_decoded(decoded, match):
        return TYPE_ADDRESS, hash160_to_p2sh(decoded[1][1], net=net)

    return TYPE_SCRIPT, bh2u(_bytes)


def parse_outpoint(vds):
    d = {}
    prevout_hash = hash_encode(vds.read_bytes(32))
    prevout_n = vds.read_uint32()
    d['prevout_hash'] = prevout_hash
    d['prevout_n'] = prevout_n
    return d


def parse_input(vds, full_parse: bool):
    d = {}
    prevout_hash = hash_encode(vds.read_bytes(32))
    prevout_n = vds.read_uint32()
    scriptSig = vds.read_bytes(vds.read_compact_size())
    sequence = vds.read_uint32()
    d['prevout_hash'] = prevout_hash
    d['prevout_n'] = prevout_n
    d['scriptSig'] = bh2u(scriptSig)
    d['sequence'] = sequence
    d['type'] = 'unknown' if prevout_hash != '00'*32 else 'coinbase'
    d['address'] = None
    d['num_sig'] = 0
    if not full_parse:
        return d
    d['x_pubkeys'] = []
    d['pubkeys'] = []
    d['signatures'] = {}
    if d['type'] != 'coinbase' and scriptSig:
        try:
            parse_scriptSig(d, scriptSig)
        except BaseException:
            _logger.exception(f'failed to parse scriptSig {bh2u(scriptSig)}')
    return d


def parse_output(vds, i):
    d = {}
    d['value'] = vds.read_int64()
    if d['value'] > TOTAL_COIN_SUPPLY_LIMIT_IN_BTC * COIN:
        raise SerializationError('invalid output amount (too large)')
    if d['value'] < 0:
        raise SerializationError('invalid output amount (negative)')
    scriptPubKey = vds.read_bytes(vds.read_compact_size())
    d['type'], d['address'] = get_address_from_output_script(scriptPubKey)
    d['scriptPubKey'] = bh2u(scriptPubKey)
    d['prevout_n'] = i
    return d


def deserialize(raw: str, force_full_parse=False) -> dict:
    raw_bytes = bfh(raw)
    d = {}
    if raw_bytes[:5] == PARTIAL_TXN_HEADER_MAGIC:
        d['partial'] = is_partial = True
        partial_format_version = raw_bytes[5]
        if partial_format_version != 0:
            raise SerializationError('unknown tx partial serialization format version: {}'
                                     .format(partial_format_version))
        raw_bytes = raw_bytes[6:]
    else:
        d['partial'] = is_partial = False
    full_parse = force_full_parse or is_partial
    vds = BCDataStream()
    vds.write(raw_bytes)
    return read_vds(vds, d, full_parse, alone_data=True)


def read_vds(vds, d, full_parse, alone_data=False):
    # support DIP2 deserialization
    header = vds.read_uint32()
    tx_type = header >> 16  # DIP2 tx type
    if tx_type:
        version = header & 0x0000ffff
    else:
        version = header

    if tx_type and version < 3:
        version = header
        tx_type = 0

    d['version'] = version
    d['tx_type'] = tx_type
    n_vin = vds.read_compact_size()
    d['inputs'] = [parse_input(vds, full_parse=full_parse) for i in range(n_vin)]
    n_vout = vds.read_compact_size()
    d['outputs'] = [parse_output(vds, i) for i in range(n_vout)]
    d['lockTime'] = vds.read_uint32()
    if tx_type:
        d['extra_payload'] = read_extra_payload(vds, tx_type)
    else:
        d['extra_payload'] = b''
    if alone_data and vds.can_read_more():
        raise SerializationError('extra junk at the end')
    return d


# pay & redeem scripts

def multisig_script(public_keys: Sequence[str], m: int) -> str:
    n = len(public_keys)
    assert 1 <= m <= n <= 15, f'm {m}, n {n}'
    op_m = bh2u(add_number_to_script(m))
    op_n = bh2u(add_number_to_script(n))
    keylist = [push_script(k) for k in public_keys]
    return op_m + ''.join(keylist) + op_n + opcodes.OP_CHECKMULTISIG.hex()




class Transaction:

    def __str__(self):
        if self.raw is None:
            self.raw = self.serialize()
        return self.raw

    def __init__(self, raw):
        if raw is None:
            self.raw = None
        elif isinstance(raw, str):
            self.raw = raw.strip() if raw else None
        elif isinstance(raw, dict):
            self.raw = raw['hex']
        else:
            raise Exception("cannot initialize transaction", raw)
        self._inputs = None
        self._outputs = None  # type: List[TxOutput]
        self.locktime = 0
        self.version = 2
        self.tx_type = 0
        self.extra_payload = b''
        # by default we assume this is a partial txn;
        # this value will get properly set when deserializing
        self.is_partial_originally = True
        self.output_info = None  # type: Optional[Dict[str, TxOutputHwInfo]]

    def update(self, raw):
        self.raw = raw
        self._inputs = None
        self.deserialize()

    def inputs(self):
        if self._inputs is None:
            self.deserialize()
        return self._inputs

    def outputs(self) -> List[TxOutput]:
        if self._outputs is None:
            self.deserialize()
        return self._outputs

    @classmethod
    def get_sorted_pubkeys(self, txin):
        # sort pubkeys and x_pubkeys, using the order of pubkeys
        if txin['type'] == 'coinbase':
            return [], []
        x_pubkeys = txin['x_pubkeys']
        pubkeys = txin.get('pubkeys')
        if pubkeys is None:
            pubkeys = [xpubkey_to_pubkey(x) for x in x_pubkeys]
            pubkeys, x_pubkeys = zip(*sorted(zip(pubkeys, x_pubkeys)))
            txin['pubkeys'] = pubkeys = list(pubkeys)
            txin['x_pubkeys'] = x_pubkeys = list(x_pubkeys)
        return pubkeys, x_pubkeys

    def update_signatures(self, signatures: Sequence[str]):
        """Add new signatures to a transaction

        `signatures` is expected to be a list of sigs with signatures[i]
        intended for self._inputs[i].
        This is used by the Trezor, KeepKey an Safe-T plugins.
        """
        if self.is_complete():
            return
        if len(self.inputs()) != len(signatures):
            raise Exception('expected {} signatures; got {}'.format(len(self.inputs()), len(signatures)))
        for i, txin in enumerate(self.inputs()):
            pubkeys, x_pubkeys = self.get_sorted_pubkeys(txin)
            sig = signatures[i]
            if sig in txin.get('signatures'):
                continue
            pre_hash = sha256d(bfh(self.serialize_preimage(i)))
            sig_string = ecc.sig_string_from_der_sig(bfh(sig[:-2]))
            for recid in range(4):
                try:
                    public_key = ecc.ECPubkey.from_sig_string(sig_string, recid, pre_hash)
                except ecc.InvalidECPointException:
                    # the point might not be on the curve for some recid values
                    continue
                pubkey_hex = public_key.get_public_key_hex(compressed=True)
                if pubkey_hex in pubkeys:
                    try:
                        public_key.verify_message_hash(sig_string, pre_hash)
                    except Exception:
                        _logger.exception('')
                        continue
                    j = pubkeys.index(pubkey_hex)
                    _logger.info(f"adding sig {i} {j} {pubkey_hex} {sig}")
                    self.add_signature_to_txin(i, j, sig)
                    break
        # redo raw
        self.raw = self.serialize()

    def add_signature_to_txin(self, i, signingPos, sig):
        txin = self._inputs[i]
        txin['signatures'][signingPos] = sig
        txin['scriptSig'] = None  # force re-serialization
        self.raw = None

    def add_inputs_info(self, wallet):
        if self.is_complete():
            return
        for txin in self.inputs():
            wallet.add_input_info(txin)

    def remove_signatures(self):
        for txin in self.inputs():
            txin['signatures'] = [None] * len(txin['signatures'])
            txin['scriptSig'] = None
        assert not self.is_complete()
        self.raw = None

    def deserialize(self, force_full_parse=False,
                    extra_payload_for_json=False):
        if self.raw is None:
            return
            #self.raw = self.serialize()
        if self._inputs is not None:
            return
        d = deserialize(self.raw, force_full_parse)
        res = self.set_data_from_dict(d)
        if extra_payload_for_json:
            extra_payload = self.extra_payload
            if isinstance(extra_payload, ProTxBase):
                extra_payload_json = extra_payload._asdict()
            else:
                extra_payload_json = bh2u(extra_payload)
            res.update({'extra_payload': extra_payload_json})
        return res

    def set_data_from_dict(self, d):
        self._inputs = d['inputs']
        self._outputs = [TxOutput(x['type'], x['address'], x['value']) for x in d['outputs']]
        self.locktime = d['lockTime']
        self.version = d['version']
        self.tx_type = d['tx_type']
        self.extra_payload = d['extra_payload']
        self.is_partial_originally = d['partial']
        return d

    @classmethod
    def read_vds(cls, vds, alone_data=False):
        d = {}
        d['partial'] = full_parse = False
        d = read_vds(vds, d, full_parse, alone_data)
        tx = cls(None)
        tx.set_data_from_dict(d)
        return tx

    @classmethod
    def from_io(klass, inputs, outputs, locktime=0, version=None,
                tx_type=0, extra_payload=b''):
        self = klass(None)
        self._inputs = inputs
        self._outputs = outputs
        self.locktime = locktime
        if version is not None:
            self.version = version
        if tx_type:
            self.version = 3
            self.tx_type = tx_type
            self.extra_payload = extra_payload
        self.BIP69_sort()
        return self

    @classmethod
    def pay_script(self, output_type, addr: str) -> str:
        """Returns scriptPubKey in hex form."""
        if output_type == TYPE_SCRIPT:
            return addr
        elif output_type == TYPE_ADDRESS:
            return bitcoin.address_to_script(addr)
        elif output_type == TYPE_PUBKEY:
            return bitcoin.public_key_to_p2pk_script(addr)
        else:
            raise TypeError('Unknown output type')

    @classmethod
    def estimate_pubkey_size_from_x_pubkey(cls, x_pubkey):
        try:
            if x_pubkey[0:2] in ['02', '03']:  # compressed pubkey
                return 0x21
            elif x_pubkey[0:2] == '04':  # uncompressed pubkey
                return 0x41
            elif x_pubkey[0:2] == 'ff':  # bip32 extended pubkey
                return 0x21
            elif x_pubkey[0:2] == 'fe':  # old electrum extended pubkey
                return 0x41
        except Exception as e:
            pass
        return 0x21  # just guess it is compressed

    @classmethod
    def estimate_pubkey_size_for_txin(cls, txin):
        pubkeys = txin.get('pubkeys', [])
        x_pubkeys = txin.get('x_pubkeys', [])
        if pubkeys and len(pubkeys) > 0:
            return cls.estimate_pubkey_size_from_x_pubkey(pubkeys[0])
        elif x_pubkeys and len(x_pubkeys) > 0:
            return cls.estimate_pubkey_size_from_x_pubkey(x_pubkeys[0])
        else:
            return 0x21  # just guess it is compressed

    @classmethod
    def get_siglist(self, txin, estimate_size=False):
        # if we have enough signatures, we use the actual pubkeys
        # otherwise, use extended pubkeys (with bip32 derivation)
        if txin['type'] == 'coinbase':
            return [], []
        num_sig = txin.get('num_sig', 1)
        if estimate_size:
            pubkey_size = self.estimate_pubkey_size_for_txin(txin)
            pk_list = ["00" * pubkey_size] * len(txin.get('x_pubkeys', [None]))
            # we assume that signature will be 0x48 bytes long
            sig_list = [ "00" * 0x48 ] * num_sig
        else:
            pubkeys, x_pubkeys = self.get_sorted_pubkeys(txin)
            x_signatures = txin['signatures']
            signatures = list(filter(None, x_signatures))
            is_complete = len(signatures) == num_sig
            if is_complete:
                pk_list = pubkeys
                sig_list = signatures
            else:
                pk_list = x_pubkeys
                sig_list = [sig if sig else NO_SIGNATURE for sig in x_signatures]
        return pk_list, sig_list

    @classmethod
    def guess_txintype_from_address(cls, addr):
        # It's not possible to tell the script type in general
        # just from an address.
        # - "1" addresses are of course p2pkh
        # - "3" addresses are p2sh but we don't know the redeem script..
        # If we don't know the script, we _guess_ it is pubkeyhash.
        # As this method is used e.g. for tx size estimation,
        # the estimation will not be precise.
        addrtype, hash_160_ = b58_address_to_hash160(addr)
        if addrtype == constants.net.ADDRTYPE_P2PKH:
            return 'p2pkh'

    @classmethod
    def input_script(self, txin, estimate_size=False):
        _type = txin['type']
        if _type == 'coinbase':
            return txin['scriptSig']

        # If there is already a saved scriptSig, just return that.
        # This allows manual creation of txins of any custom type.
        # However, if the txin is not complete, we might have some garbage
        # saved from our partial txn ser format, so we re-serialize then.
        script_sig = txin.get('scriptSig', None)
        if script_sig is not None and self.is_txin_complete(txin):
            return script_sig

        pubkeys, sig_list = self.get_siglist(txin, estimate_size)
        script = ''.join(push_script(x) for x in sig_list)
        if _type == 'address' and estimate_size:
            _type = self.guess_txintype_from_address(txin['address'])
        if _type == 'p2pk':
            pass
        elif _type == 'p2sh':
            # put op_0 before script
            script = '00' + script
            redeem_script = multisig_script(pubkeys, txin['num_sig'])
            script += push_script(redeem_script)
        elif _type == 'p2pkh':
            script += push_script(pubkeys[0])
        elif _type == 'address':
            return bytes([opcodes.OP_INVALIDOPCODE, opcodes.OP_0]).hex() + push_script(pubkeys[0])
        elif _type == 'unknown':
            return txin['scriptSig']
        return script

    @classmethod
    def is_txin_complete(cls, txin):
        if txin['type'] == 'coinbase':
            return True
        num_sig = txin.get('num_sig', 1)
        if num_sig == 0:
            return True
        x_signatures = txin['signatures']
        signatures = list(filter(None, x_signatures))
        return len(signatures) == num_sig

    @classmethod
    def get_preimage_script(self, txin):
        preimage_script = txin.get('preimage_script', None)
        if preimage_script is not None:
            return preimage_script

        pubkeys, x_pubkeys = self.get_sorted_pubkeys(txin)
        if txin['type'] == 'p2pkh':
            return bitcoin.address_to_script(txin['address'])
        elif txin['type'] in ['p2sh']:
            return multisig_script(pubkeys, txin['num_sig'])
        elif txin['type'] == 'p2pk':
            pubkey = pubkeys[0]
            return bitcoin.public_key_to_p2pk_script(pubkey)
        else:
            raise TypeError('Unknown txin type', txin['type'])

    @classmethod
    def serialize_outpoint(self, txin):
        return bh2u(bfh(txin['prevout_hash'])[::-1]) + int_to_hex(txin['prevout_n'], 4)

    @classmethod
    def get_outpoint_from_txin(cls, txin):
        if txin['type'] == 'coinbase':
            return None
        prevout_hash = txin['prevout_hash']
        prevout_n = txin['prevout_n']
        return prevout_hash + ':%d' % prevout_n

    @classmethod
    def serialize_input(self, txin, script):
        # Prev hash and index
        s = self.serialize_outpoint(txin)
        # Script length, script, sequence
        s += var_int(len(script)//2)
        s += script
        s += int_to_hex(txin.get('sequence', 0xffffffff - 1), 4)
        return s

    def BIP69_sort(self, inputs=True, outputs=True):
        if inputs:
            self._inputs.sort(key = lambda i: (i['prevout_hash'], i['prevout_n']))
        if outputs:
            self._outputs.sort(key = lambda o: (o.value, self.pay_script(o.type, o.address)))

    @classmethod
    def serialize_output(cls, output: TxOutput) -> str:
        s = int_to_hex(output.value, 8)
        script = cls.pay_script(output.type, output.address)
        s += var_int(len(script)//2)
        s += script
        return s

    def serialize_preimage(self, txin_index: int) -> str:
        nHashType = int_to_hex(1, 4)  # SIGHASH_ALL
        nLocktime = int_to_hex(self.locktime, 4)
        inputs = self.inputs()
        outputs = self.outputs()
        txin = inputs[txin_index]
        txins = var_int(len(inputs)) + ''.join(self.serialize_input(txin, self.get_preimage_script(txin) if txin_index==k else '')
                                               for k, txin in enumerate(inputs))
        txouts = var_int(len(outputs)) + ''.join(self.serialize_output(o) for o in outputs)
        if self.tx_type:
            uVersion = int_to_hex(self.version, 2)
            uTxType = int_to_hex(self.tx_type, 2)
            vExtra = bh2u(to_varbytes(serialize_extra_payload(self)))
            preimage = uVersion + uTxType + txins + txouts + nLocktime + vExtra + nHashType
        else:
            nVersion = int_to_hex(self.version, 4)
            preimage = nVersion + txins + txouts + nLocktime + nHashType
        return preimage

    def serialize(self, estimate_size=False):
        network_ser = self.serialize_to_network(estimate_size)
        if estimate_size:
            return network_ser
        if self.is_partial_originally and not self.is_complete():
            partial_format_version = '00'
            return bh2u(PARTIAL_TXN_HEADER_MAGIC) + partial_format_version + network_ser
        else:
            return network_ser

    def serialize_to_network(self, estimate_size=False):
        self.deserialize()
        nLocktime = int_to_hex(self.locktime, 4)
        inputs = self.inputs()
        outputs = self.outputs()
        txins = var_int(len(inputs)) + ''.join(self.serialize_input(txin, self.input_script(txin, estimate_size)) for txin in inputs)
        txouts = var_int(len(outputs)) + ''.join(self.serialize_output(o) for o in outputs)
        if self.tx_type:
            uVersion = int_to_hex(self.version, 2)
            uTxType = int_to_hex(self.tx_type, 2)
            vExtra = bh2u(to_varbytes(serialize_extra_payload(self)))
            return uVersion + uTxType + txins + txouts + nLocktime + vExtra
        else:
            nVersion = int_to_hex(self.version, 4)
            return nVersion + txins + txouts + nLocktime

    def txid(self):
        self.deserialize()
        if not self.is_complete():
            return None
        ser = self.serialize_to_network()
        return bh2u(sha256d(bfh(ser))[::-1])

    def add_inputs(self, inputs):
        self._inputs.extend(inputs)
        self.raw = None
        self.BIP69_sort(outputs=False)

    def add_outputs(self, outputs):
        self._outputs.extend(outputs)
        self.raw = None
        self.BIP69_sort(inputs=False)

    def input_value(self) -> int:
        return sum(x['value'] for x in self.inputs())

    def output_value(self) -> int:
        return sum(o.value for o in self.outputs())

    def get_fee(self) -> int:
        return self.input_value() - self.output_value()

    def is_final(self):
        return not any([x.get('sequence', 0xffffffff - 1) < 0xffffffff - 1 for x in self.inputs()])

    def estimated_size(self):
        """Return an estimated virtual tx size in vbytes.
        BIP-0141 defines 'Virtual transaction size' to be weight/4 rounded up.
        This definition is only for humans, and has little meaning otherwise.
        If we wanted sub-byte precision, fee calculation should use transaction
        weights, but for simplicity we approximate that with (virtual_size)x4
        """
        weight = self.estimated_weight()
        return self.virtual_size_from_weight(weight)

    @classmethod
    def estimated_input_weight(cls, txin):
        '''Return an estimate of serialized input weight in weight units.'''
        script = cls.input_script(txin, True)
        input_size = len(cls.serialize_input(txin, script)) // 2
        return 4 * input_size

    @classmethod
    def estimated_output_size(cls, address):
        """Return an estimate of serialized output size in bytes."""
        script = bitcoin.address_to_script(address)
        # 8 byte value + 1 byte script len + script
        return 9 + len(script) // 2

    @classmethod
    def virtual_size_from_weight(cls, weight):
        return weight // 4 + (weight % 4 > 0)

    def estimated_total_size(self):
        """Return an estimated total transaction size in bytes."""
        return len(self.serialize(True)) // 2 if not self.is_complete() or self.raw is None else len(self.raw) // 2  # ASCII hex string

    def estimated_base_size(self):
        """Return an estimated base transaction size in bytes."""
        return self.estimated_total_size()

    def estimated_weight(self):
        """Return an estimate of transaction weight."""
        total_tx_size = self.estimated_total_size()
        base_tx_size = self.estimated_base_size()
        return 3 * base_tx_size + total_tx_size

    def signature_count(self):
        r = 0
        s = 0
        for txin in self.inputs():
            if txin['type'] == 'coinbase':
                continue
            signatures = list(filter(None, txin.get('signatures',[])))
            s += len(signatures)
            r += txin.get('num_sig',-1)
        return s, r

    def is_complete(self):
        s, r = self.signature_count()
        return r == s

    def sign(self, keypairs) -> None:
        # keypairs:  (x_)pubkey -> secret_bytes
        for i, txin in enumerate(self.inputs()):
            pubkeys, x_pubkeys = self.get_sorted_pubkeys(txin)
            for j, (pubkey, x_pubkey) in enumerate(zip(pubkeys, x_pubkeys)):
                if self.is_txin_complete(txin):
                    break
                if pubkey in keypairs:
                    _pubkey = pubkey
                elif x_pubkey in keypairs:
                    _pubkey = x_pubkey
                else:
                    continue
                _logger.info(f"adding signature for {_pubkey}")
                sec, compressed = keypairs.get(_pubkey)
                sig = self.sign_txin(i, sec)
                self.add_signature_to_txin(i, j, sig)

        _logger.info(f"is_complete {self.is_complete()}")
        self.raw = self.serialize()

    def sign_txin(self, txin_index, privkey_bytes) -> str:
        pre_hash = sha256d(bfh(self.serialize_preimage(txin_index)))
        privkey = ecc.ECPrivkey(privkey_bytes)
        sig = privkey.sign_transaction(pre_hash)
        sig = bh2u(sig) + '01'
        return sig

    def get_outputs_for_UI(self) -> Sequence[TxOutputForUI]:
        outputs = []
        for o in self.outputs():
            if o.type == TYPE_ADDRESS:
                addr = o.address
            elif o.type == TYPE_PUBKEY:
                addr = 'PUBKEY ' + o.address
            else:
                addr = 'SCRIPT ' + o.address
            outputs.append(TxOutputForUI(addr, o.value))      # consider using yield
        return outputs

    def has_address(self, addr: str) -> bool:
        return (addr in (o.address for o in self.outputs())) \
               or (addr in (txin.get("address") for txin in self.inputs()))

    def as_dict(self):
        if self.raw is None:
            self.raw = self.serialize()
        self.deserialize()
        out = {
            'hex': self.raw,
            'complete': self.is_complete(),
            'final': self.is_final(),
        }
        return out


def tx_from_str(txt: str) -> str:
    """Sanitizes tx-describing input (json or raw hex or base43) into
    raw hex transaction."""
    assert isinstance(txt, str), f"txt must be str, not {type(txt)}"
    txt = txt.strip()
    if not txt:
        raise ValueError("empty string")
    # try hex
    try:
        bfh(txt)
        return txt
    except:
        pass
    # try base43
    try:
        return base_decode(txt, length=None, base=43).hex()
    except:
        pass
    # try json
    import json
    tx_dict = json.loads(str(txt))
    assert "hex" in tx_dict.keys()
    return tx_dict["hex"]
