import asyncio
import copy
import logging
import re
import random
import time
import threading
from bls_py import bls
from enum import IntEnum
from collections import defaultdict, deque, Counter
from decimal import Decimal
from math import floor, ceil
from uuid import uuid4

from . import constants
from .bitcoin import (COIN, TYPE_ADDRESS, TYPE_SCRIPT, address_to_script,
                      is_address, pubkey_to_address)
from .axe_tx import (STANDARD_TX, PSTxTypes, SPEC_TX_NAMES, PSCoinRounds,
                      str_ip, CTxIn, CTxOut)
from .axe_msg import (DSPoolStatusUpdate, DSMessageIDs, ds_msg_str,
                       ds_pool_state_str, AxeDsaMsg, AxeDsiMsg, AxeDssMsg,
                       PRIVATESEND_ENTRY_MAX_SIZE)
from .keystore import xpubkey_to_address, load_keystore, from_seed
from .logging import Logger
from .transaction import Transaction, TxOutput
from .util import (NoDynamicFeeEstimates, log_exceptions, SilentTaskGroup,
                   NotEnoughFunds, bfh, is_android, profiler, InvalidPassword)
from .i18n import _


TXID_PATTERN = re.compile('([0123456789ABCDEFabcdef]{64})')
ADDR_PATTERN = re.compile(
    '([123456789ABCDEFGHJKLMNPQRSTUVWXYZ'
    'abcdefghijkmnopqrstuvwxyz]{20,80})')
FILTERED_TXID = '<filtered txid>'
FILTERED_ADDR = '<filtered address>'


def filter_log_line(line):
    pos = 0
    output_line = ''
    while pos < len(line):
        m = TXID_PATTERN.search(line, pos)
        if m:
            output_line += line[pos:m.start()]
            output_line += FILTERED_TXID
            pos = m.end()
            continue

        m = ADDR_PATTERN.search(line, pos)
        if m:
            addr = m.group()
            if is_address(addr, net=constants.net):
                output_line += line[pos:m.start()]
                output_line += FILTERED_ADDR
                pos = m.end()
                continue

        output_line += line[pos:]
        break
    return output_line


def varint_size(size):
    if size < 253:
        return 1
    elif size < 2**16:
        return 3
    elif size < 2**32:
        return 5
    elif size < 2**64:
        return 9


def calc_tx_size(in_cnt, out_cnt, max_size=False):
    # base size is 4 bytes version + 4 bytes lock_time
    max_tx_size = 4 + 4
    # in size is 36 bytes outpoint + 1b len + iscript + 4 bytes sequence_no
    # iscript is 1b varint + sig (71-73 bytes) + 1b varint + 33 bytes pubk
    # max in size is 36 + 1 + (1 + 73 + 1 + 33) + 4 = 149
    max_tx_size += varint_size(in_cnt) + in_cnt * (149 if max_size else 148)

    # out size is 8 byte value + 1b varint + 25 bytes p2phk script
    # out size is 8 + 1 + 25 = 34
    max_tx_size += varint_size(out_cnt) + out_cnt * 34
    return max_tx_size


def calc_tx_fee(in_cnt, out_cnt, fee_per_kb, max_size=False):
    return round(calc_tx_size(in_cnt, out_cnt, max_size) * fee_per_kb / 1000)


def to_haks(amount):
    return round(Decimal(amount)*COIN)


def sort_utxos_by_ps_rounds(x):
    ps_rounds = x['ps_rounds']
    if ps_rounds is None:
        return PSCoinRounds.MINUSINF
    return ps_rounds


class PSDenoms(IntEnum):
    D10 = 1
    D1 = 2
    D0_1 = 4
    D0_01 = 8
    D0_001 = 16


PS_DENOMS_DICT = {
    to_haks(10.0001): PSDenoms.D10,
    to_haks(1.00001): PSDenoms.D1,
    to_haks(0.100001): PSDenoms.D0_1,
    to_haks(0.0100001): PSDenoms.D0_01,
    to_haks(0.00100001): PSDenoms.D0_001,
}


PS_DENOM_REVERSE_DICT = {int(v): k for k, v in PS_DENOMS_DICT.items()}


COLLATERAL_VAL = to_haks(0.0001)
CREATE_COLLATERAL_VAL = COLLATERAL_VAL*4
CREATE_COLLATERAL_VALS = [COLLATERAL_VAL*i for i in range(1,11)]
MAX_COLLATERAL_VAL = CREATE_COLLATERAL_VALS[-1]
PS_DENOMS_VALS = sorted(PS_DENOMS_DICT.keys())
MIN_DENOM_VAL = PS_DENOMS_VALS[0]
PS_VALS = PS_DENOMS_VALS + CREATE_COLLATERAL_VALS

PS_MIXING_TX_TYPES = list(map(lambda x: x.value, [PSTxTypes.NEW_DENOMS,
                                                  PSTxTypes.NEW_COLLATERAL,
                                                  PSTxTypes.PAY_COLLATERAL,
                                                  PSTxTypes.DENOMINATE]))

PS_SAVED_TX_TYPES = list(map(lambda x: x.value, [PSTxTypes.NEW_DENOMS,
                                                 PSTxTypes.NEW_COLLATERAL,
                                                 PSTxTypes.PAY_COLLATERAL,
                                                 PSTxTypes.DENOMINATE,
                                                 PSTxTypes.PRIVATESEND,
                                                 PSTxTypes.SPEND_PS_COINS,
                                                 PSTxTypes.OTHER_PS_COINS]))

DEFAULT_KEEP_AMOUNT = 2
MIN_KEEP_AMOUNT = 2
MAX_KEEP_AMOUNT = 21000000

DEFAULT_MIX_ROUNDS = 4
MIN_MIX_ROUNDS = 2
MAX_MIX_ROUNDS = 16
MAX_MIX_ROUNDS_TESTNET = 256

DEFAULT_PRIVATESEND_SESSIONS = 4
MIN_PRIVATESEND_SESSIONS = 1
MAX_PRIVATESEND_SESSIONS = 10

DEFAULT_GROUP_HISTORY = True
DEFAULT_NOTIFY_PS_TXS = False
DEFAULT_SUBSCRIBE_SPENT = False
DEFAULT_ALLOW_OTHERS = False

POOL_MIN_PARTICIPANTS = 3
POOL_MAX_PARTICIPANTS = 5

PRIVATESEND_QUEUE_TIMEOUT = 30
PRIVATESEND_SESSION_MSG_TIMEOUT = 40

WAIT_FOR_MN_TXS_TIME_SEC = 120


# PSManager states
class PSStates(IntEnum):
    Unsupported = 0
    Disabled = 1
    Initializing = 2
    Ready = 3
    StartMixing = 4
    Mixing = 5
    StopMixing = 6
    FindingUntracked = 7
    Errored = 8
    Cleaning = 9


# Keypairs cache types
KP_INCOMING = 'incoming'            # future incoming funds on main keystore
KP_SPENDABLE = 'spendable'          # regular utxos
KP_PS_SPENDABLE = 'ps_spendable'    # ps_denoms/ps_collateral utxos
KP_PS_COINS = 'ps_coins'            # output addressess for denominate tx
KP_PS_CHANGE = 'ps_change'          # output addressess for pay collateral tx
KP_ALL_TYPES = [KP_INCOMING, KP_SPENDABLE,
                KP_PS_SPENDABLE, KP_PS_COINS, KP_PS_CHANGE]
KP_MAX_INCOMING_TXS = 5             # max count of txs to split on denoms
                                    # need to calc keypairs count to cache


# Keypairs cache states
class KPStates(IntEnum):
    Empty = 0
    NeedCache = 1
    Caching = 2
    Ready = 3
    Unused = 4


# Keypairs cleanup timeout when mixing is stopped
DEFAULT_KP_TIMEOUT = 0
MIN_KP_TIMEOUT = 0
MAX_KP_TIMEOUT = 5


class PSTxData:
    '''
    uuid: unique id for addresses reservation
    tx_type: PSTxTypes type
    txid: tx hash
    raw_tx: raw tx data
    sent: time when tx was sent to network
    next_send: minimal time when next send attempt should occur
    '''

    __slots__ = 'uuid tx_type txid raw_tx sent next_send'.split()

    def __init__(self, **kwargs):
        for k in self.__slots__:
            if k in kwargs:
                if k == 'tx_type':
                    setattr(self, k, int(kwargs[k]))
                else:
                    setattr(self, k, kwargs[k])
            else:
                setattr(self, k, None)

    def _as_dict(self):
        '''return dict txid -> (uuid, sent, next_send, tx_type, raw_tx)'''
        return {self.txid: (self.uuid, self.sent, self.next_send,
                            self.tx_type, self.raw_tx)}

    @classmethod
    def _from_txid_and_tuple(cls, txid, data_tuple):
        '''
        New instance from txid
        and (uuid, sent, next_send, tx_type, raw_tx) tuple
        '''
        uuid, sent, next_send, tx_type, raw_tx = data_tuple
        return cls(uuid=uuid, txid=txid, raw_tx=raw_tx,
                   tx_type=tx_type, sent=sent, next_send=next_send)

    def __eq__(self, other):
        if type(other) != PSTxData:
            return False
        if id(self) == id(other):
            return True
        for k in self.__slots__:
            if getattr(self, k) != getattr(other, k):
                return False
        return True

    async def send(self, psman, ignore_next_send=False):
        err = ''
        if self.sent:
            return False, err
        now = time.time()
        if not ignore_next_send:
            next_send = self.next_send
            if next_send and next_send > now:
                return False, err
        try:
            tx = Transaction(self.raw_tx)
            await psman.network.broadcast_transaction(tx)
            self.sent = time.time()
            return True, err
        except Exception as e:
            err = str(e)
            self.next_send = now + 10
            return False, err


class PSTxWorkflow:
    '''
    uuid: unique id for addresses reservation
    completed: workflow creation completed
    tx_data: txid -> PSTxData
    tx_order: creation order of workflow txs
    '''

    __slots__ = 'uuid completed tx_data tx_order'.split()

    def __init__(self, **kwargs):
        uuid = kwargs.pop('uuid', None)
        if uuid is None:
            raise TypeError('missing required uuid argument')
        self.uuid = uuid
        self.completed = kwargs.pop('completed', False)
        self.tx_order = kwargs.pop('tx_order', [])[:]  # copy
        tx_data = kwargs.pop('tx_data', {})
        self.tx_data = {}  # copy
        for txid, v in tx_data.items():
            if type(v) in (tuple, list):
                self.tx_data[txid] = PSTxData._from_txid_and_tuple(txid, v)
            else:
                self.tx_data[txid] = v

    @property
    def lid(self):
        return self.uuid[:8] if self.uuid else self.uuid

    def _as_dict(self):
        '''return dict with keys from __slots__ and corresponding values'''
        tx_data = {}  # copy
        for v in self.tx_data.values():
            tx_data.update(v._as_dict())
        return {
            'uuid': self.uuid,
            'completed': self.completed,
            'tx_data': tx_data,
            'tx_order': self.tx_order[:],  # copy
        }

    @classmethod
    def _from_dict(cls, data_dict):
        return cls(**data_dict)

    def __eq__(self, other):
        if type(other) != PSTxWorkflow:
            return False
        elif id(self) == id(other):
            return True
        elif self.uuid != other.uuid:
            return False
        elif self.completed != other.completed:
            return False
        elif self.tx_order != other.tx_order:
            return False
        elif set(self.tx_data.keys()) != set(other.tx_data.keys()):
            return False
        for k in self.tx_data.keys():
            if self.tx_data[k] != other.tx_data[k]:
                return False
        else:
            return True

    def next_to_send(self, wallet):
        for txid in self.tx_order:
            tx_data = self.tx_data[txid]
            if not tx_data.sent and wallet.is_local_tx(txid):
                return tx_data

    def add_tx(self, **kwargs):
        txid = kwargs.pop('txid')
        raw_tx = kwargs.pop('raw_tx', None)
        tx_type = kwargs.pop('tx_type')
        if not txid or not tx_type:
            return
        tx_data = PSTxData(uuid=self.uuid, txid=txid,
                           raw_tx=raw_tx, tx_type=tx_type)
        self.tx_data[txid] = tx_data
        self.tx_order.append(txid)
        return tx_data

    def pop_tx(self, txid):
        if txid in self.tx_data:
            res = self.tx_data.pop(txid)
        else:
            res = None
        self.tx_order = [tid for tid in self.tx_order if tid != txid]
        return res


class PSDenominateWorkflow:
    '''
    uuid: unique id for spending denoms reservation
    denom: workflow denom value
    rounds: workflow inputs mix rounds (legacy field, not used)
    inputs: list of spending denoms outpoints
    outputs: list of reserved output addresses
    completed: time when dsc message received
    '''

    __slots__ = 'uuid denom rounds inputs outputs completed'.split()

    def __init__(self, **kwargs):
        uuid = kwargs.pop('uuid', None)
        if uuid is None:
            raise TypeError('missing required uuid argument')
        self.uuid = uuid
        self.denom = kwargs.pop('denom', 0)
        self.rounds = kwargs.pop('rounds', 0)
        self.inputs = kwargs.pop('inputs', [])[:]  # copy
        self.outputs = kwargs.pop('outputs', [])[:]  # copy
        self.completed = kwargs.pop('completed', 0)

    @property
    def lid(self):
        return self.uuid[:8] if self.uuid else self.uuid

    def _as_dict(self):
        '''return dict uuid -> (denom, rounds, inputs, outputs, completed)'''
        return {
            self.uuid: (
                self.denom,
                self.rounds,
                self.inputs[:],  # copy
                self.outputs[:],  # copy
                self.completed,
            )
        }

    @classmethod
    def _from_uuid_and_tuple(cls, uuid, data_tuple):
        '''New from uuid, (denom, rounds, inputs, outputs, completed) tuple'''
        denom, rounds, inputs, outputs, completed = data_tuple[:5]
        return cls(uuid=uuid, denom=denom, rounds=rounds,
                   inputs=inputs[:], outputs=outputs[:],  # copy
                   completed=completed)

    def __eq__(self, other):
        if type(other) != PSDenominateWorkflow:
            return False
        elif id(self) == id(other):
            return True
        return not any(getattr(self, field) != getattr(other, field)
                       for field in self.__slots__)


class PSMinRoundsCheckFailed(Exception):
    """Thrown when check for coins minimum mixing rounds failed"""


class PSPossibleDoubleSpendError(Exception):
    """Thrown when trying to broadcast recently used ps denoms/collateral"""


class PSSpendToPSAddressesError(Exception):
    """Thrown when trying to broadcast tx with ps coins spent to ps addrs"""


class NotFoundInKeypairs(Exception):
    """Thrown when output address not found in keypairs cache"""


class TooManyUtxos(Exception):
    """Thrown when creating new denoms/collateral txs from coins"""


class TooLargeUtxoVal(Exception):
    """Thrown when creating new collateral txs from coins"""


class SignWithKeypairsFailed(Exception):
    """Thrown when transaction signing with keypairs reserved failed"""


class AddPSDataError(Exception):
    """Thrown when failed _add_*_ps_data method"""


class RmPSDataError(Exception):
    """Thrown when failed _rm_*_ps_data method"""


class PSKsInternalAddressCorruption(Exception):

    def __str__(self):
        return _('PS Keystore addresses data corruption detected.'
                 ' Please restore your wallet from seed, and compare'
                 ' the addresses in both files')


class PSMixSession:

    def __init__(self, psman, denom_value, denom, dsq, wfl_lid):
        self.logger = psman.logger
        self.denom_value = denom_value
        self.denom = denom
        self.wfl_lid = wfl_lid

        network = psman.wallet.network
        self.axe_net = network.axe_net
        self.mn_list = network.mn_list

        self.axe_peer = None
        self.sml_entry = None

        if dsq:
            outpoint = str(dsq.masternodeOutPoint)
            self.sml_entry = self.mn_list.get_mn_by_outpoint(outpoint)
        if not self.sml_entry:
            try_cnt = 0
            while True:
                try_cnt += 1
                self.sml_entry = self.mn_list.get_random_mn()
                if self.peer_str not in psman.recent_mixes_mns:
                    break
                if try_cnt >= 10:
                    raise Exception('Can not select random'
                                    ' not recently used  MN')
        if not self.sml_entry:
            raise Exception('No SML entries found')
        psman.recent_mixes_mns.append(self.peer_str)
        self.msg_queue = asyncio.Queue()

        self.session_id = 0
        self.state = None
        self.msg_id = None
        self.entries_count = 0
        self.masternodeOutPoint = None
        self.fReady = False
        self.nTime = 0
        self.start_time = time.time()

    @property
    def peer_str(self):
        return f'{str_ip(self.sml_entry.ipAddress)}:{self.sml_entry.port}'

    async def run_peer(self):
        if self.axe_peer:
            raise Exception('Session already have running AxePeer')
        self.axe_peer = await self.axe_net.run_mixing_peer(self.peer_str,
                                                             self.sml_entry,
                                                             self)
        if not self.axe_peer:
            raise Exception(f'Peer {self.peer_str} connection failed')
        self.logger.info(f'Started mixing session for {self.wfl_lid},'
                         f' peer: {self.peer_str}, denom={self.denom_value}'
                         f' (nDenom={self.denom})')

    def close_peer(self):
        if not self.axe_peer:
            return
        self.axe_peer.close()
        self.logger.info(f'Stopped mixing session for {self.wfl_lid},'
                         f' peer: {self.peer_str}')

    def verify_ds_msg_sig(self, ds_msg):
        if not self.sml_entry:
            return False
        mn_pub_key = self.sml_entry.pubKeyOperator
        pubk = bls.PublicKey.from_bytes(mn_pub_key)
        sig = bls.Signature.from_bytes(ds_msg.vchSig)
        msg_hash = ds_msg.msg_hash()
        aggr_info = bls.AggregationInfo.from_msg_hash(pubk, msg_hash)
        sig.set_aggregation_info(aggr_info)
        return bls.BLS.verify(sig)

    def verify_final_tx(self, tx, denominate_wfl):
        inputs = denominate_wfl.inputs
        outputs = denominate_wfl.outputs
        icnt = 0
        ocnt = 0
        for i in tx.inputs():
            prev_h = i['prevout_hash']
            prev_n = i['prevout_n']
            if f'{prev_h}:{prev_n}' in inputs:
                icnt += 1
        for o in tx.outputs():
            if o.address in outputs:
                ocnt += 1
        if icnt == len(inputs) and ocnt == len(outputs):
            return True
        else:
            return False

    async def send_dsa(self, pay_collateral_tx):
        msg = AxeDsaMsg(self.denom, pay_collateral_tx)
        await self.axe_peer.send_msg('dsa', msg.serialize())
        self.logger.debug(f'{self.wfl_lid}: dsa sent')

    async def send_dsi(self, inputs, pay_collateral_tx, outputs):
        scriptSig = b''
        sequence = 0xffffffff
        vecTxDSIn = []
        for i in inputs:
            prev_h, prev_n = i.split(':')
            prev_h = bfh(prev_h)[::-1]
            prev_n = int(prev_n)
            vecTxDSIn.append(CTxIn(prev_h, prev_n, scriptSig, sequence))
        vecTxDSOut = []
        for o in outputs:
            scriptPubKey = bfh(address_to_script(o))
            vecTxDSOut.append(CTxOut(self.denom_value, scriptPubKey))
        msg = AxeDsiMsg(vecTxDSIn, pay_collateral_tx, vecTxDSOut)
        await self.axe_peer.send_msg('dsi', msg.serialize())
        self.logger.debug(f'{self.wfl_lid}: dsi sent')

    async def send_dss(self, signed_inputs):
        msg = AxeDssMsg(signed_inputs)
        await self.axe_peer.send_msg('dss', msg.serialize())

    async def read_next_msg(self, denominate_wfl, timeout=None):
        '''Read next msg from msg_queue, process and return (cmd, res) tuple'''
        try:
            if timeout is None:
                timeout = PRIVATESEND_SESSION_MSG_TIMEOUT
            res = await asyncio.wait_for(self.msg_queue.get(), timeout)
        except asyncio.TimeoutError:
            raise Exception('Session Timeout, Reset')
        if not res:  # axe_peer is closed
            raise Exception('peer connection closed')
        elif type(res) == Exception:
            raise res
        cmd = res.cmd
        payload = res.payload
        if cmd == 'dssu':
            res = self.on_dssu(payload)
            return cmd, res
        elif cmd == 'dsq':
            self.logger.debug(f'{self.wfl_lid}: dsq read: {payload}')
            res = self.on_dsq(payload)
            return cmd, res
        elif cmd == 'dsf':
            self.logger.debug(f'{self.wfl_lid}: dsf read: {payload}')
            res = self.on_dsf(payload, denominate_wfl)
            return cmd, res
        elif cmd == 'dsc':
            self.logger.wfl_ok(f'{self.wfl_lid}: dsc read: {payload}')
            res = self.on_dsc(payload)
            return cmd, res
        else:
            self.logger.debug(f'{self.wfl_lid}: unknown msg read, cmd: {cmd}')
            return None, None

    def on_dssu(self, dssu):
        session_id = dssu.sessionID
        if not self.session_id:
            if session_id:
                self.session_id = session_id

        if self.session_id != session_id:
            raise Exception(f'Wrong session id {session_id},'
                            f' was {self.session_id}')

        self.state = dssu.state
        self.msg_id = dssu.messageID
        self.entries_count = dssu.entriesCount

        state = ds_pool_state_str(self.state)
        msg = ds_msg_str(self.msg_id)
        if (dssu.statusUpdate == DSPoolStatusUpdate.ACCEPTED
                and dssu.messageID != DSMessageIDs.ERR_QUEUE_FULL):
            self.logger.debug(f'{self.wfl_lid}: dssu read:'
                              f' state={state}, msg={msg},'
                              f' entries_count={self.entries_count}')
        elif dssu.statusUpdate == DSPoolStatusUpdate.ACCEPTED:
            raise Exception('MN queue is full')
        elif dssu.statusUpdate == DSPoolStatusUpdate.REJECTED:
            raise Exception(f'Get reject status update from MN: {msg}')
        else:
            raise Exception(f'Unknown dssu statusUpdate: {dssu.statusUpdate}')

    def on_dsq(self, dsq):
        denom = dsq.nDenom
        if denom != self.denom:
            raise Exception(f'Wrong denom in dsq msg: {denom},'
                            f' session denom is {self.denom}.')
        # signature verified in axe_peer on receiving dsq message for session
        # signature not verifed for dsq with fReady not set (go to recent dsq)
        if not dsq.fReady:  # additional check
            raise Exception(f'Get dsq with fReady not set')
        if self.fReady:
            raise Exception(f'Another dsq on session with fReady set')
        self.masternodeOutPoint = dsq.masternodeOutPoint
        self.fReady = dsq.fReady
        self.nTime = dsq.nTime

    def on_dsf(self, dsf, denominate_wfl):
        session_id = dsf.sessionID
        if self.session_id != session_id:
            raise Exception(f'Wrong session id {session_id},'
                            f' was {self.session_id}')
        if not self.verify_final_tx(dsf.txFinal, denominate_wfl):
            raise Exception(f'Wrong txFinal')
        return dsf.txFinal

    def on_dsc(self, dsc):
        session_id = dsc.sessionID
        if self.session_id != session_id:
            raise Exception(f'Wrong session id {session_id},'
                            f' was {self.session_id}')
        msg_id = dsc.messageID
        if msg_id != DSMessageIDs.MSG_SUCCESS:
            raise Exception(ds_msg_str(msg_id))


class PSLogSubCat(IntEnum):
    NoCategory = 0
    WflOk = 1
    WflErr = 2
    WflDone = 3


class PSManLogAdapter(logging.LoggerAdapter):

    def __init__(self, logger, extra):
        super(PSManLogAdapter, self).__init__(logger, extra)

    def process(self, msg, kwargs):
        msg, kwargs = super(PSManLogAdapter, self).process(msg, kwargs)
        subcat = kwargs.pop('subcat', None)
        if subcat:
            kwargs['extra']['subcat'] = subcat
        else:
            kwargs['extra']['subcat'] = PSLogSubCat.NoCategory
        return msg, kwargs

    def wfl_done(self, msg, *args, **kwargs):
        self.info(msg, *args, **kwargs, subcat=PSLogSubCat.WflDone)

    def wfl_ok(self, msg, *args, **kwargs):
        self.info(msg, *args, **kwargs, subcat=PSLogSubCat.WflOk)

    def wfl_err(self, msg, *args, **kwargs):
        self.info(msg, *args, **kwargs, subcat=PSLogSubCat.WflErr)


class PSGUILogHandler(logging.Handler):
    '''Write log to maxsize limited queue'''

    def __init__(self, psman):
        super(PSGUILogHandler, self).__init__()
        self.shortcut = psman.LOGGING_SHORTCUT
        self.psman = psman
        self.psman_id = id(psman)
        self.head = 0
        self.tail = 0
        self.log = dict()
        self.setLevel(logging.INFO)
        psman.logger.addHandler(self)
        self.notify = False

    def handle(self, record):
        if record.psman_id != self.psman_id:
            return False
        self.log[self.tail] = record
        self.tail += 1
        if self.tail - self.head > 1000:
            self.clear_log(100)
        if self.notify:
            self.psman.postpone_notification('ps-log-changes', self.psman)
        return True

    def clear_log(self, count=0):
        head = self.head
        if not count:
            count = self.tail - head
        for i in range(head, head+count):
            self.log.pop(i, None)
        self.head = head + count
        if self.notify:
            self.psman.postpone_notification('ps-log-changes', self.psman)


class PSManager(Logger):
    '''Class representing wallet PrivateSend manager'''

    LOGGING_SHORTCUT = 'A'
    NOT_FOUND_KEYS_MSG = _('Insufficient keypairs cached to continue mixing.'
                           ' You can restart mixing to reserve more keypairs')
    SIGN_WIHT_KP_FAILED_MSG = _('Sign with keypairs failed.')
    ADD_PS_DATA_ERR_MSG = _('Error on adding PrivateSend transaction data.')
    SPEND_TO_PS_ADDRS_MSG = _('For privacy reasons blocked attempt to'
                              ' transfer coins to PrivateSend address.')
    WATCHING_ONLY_MSG = _('This is a watching-only wallet.'
                          ' Mixing can not be run.')
    ALL_MIXED_MSG = _('PrivateSend mixing is done')
    CLEAR_PS_DATA_MSG = _('Are you sure to clear all wallet PrivateSend data?'
                          ' This is not recommended if there is'
                          ' no particular need.')
    NO_NETWORK_MSG = _('Can not start mixing. Network is not available')
    NO_AXE_NET_MSG = _('Can not start mixing. AxeNet is not available')
    LLMQ_DATA_NOT_READY = _('LLMQ quorums data is not fully loaded.')
    MNS_DATA_NOT_READY = _('Masternodes data is not fully loaded.')
    NOT_ENABLED_MSG = _('PrivateSend mixing is not enabled')
    INITIALIZING_MSG = _('PrivateSend mixing is initializing.'
                         ' Please try again soon')
    MIXING_ALREADY_RUNNING_MSG = _('PrivateSend mixing is already running.')
    MIXING_NOT_RUNNING_MSG = _('PrivateSend mixing is not running.')
    FIND_UNTRACKED_RUN_MSG = _('PrivateSend mixing can not start. Process of'
                               ' finding untracked PS transactions'
                               ' is currently run')
    ERRORED_MSG = _('PrivateSend mixing can not start.'
                    ' Please check errors in PS Log tab')
    UNKNOWN_STATE_MSG = _('PrivateSend mixing can not start.'
                          ' Unknown state: {}')
    WALLET_PASSWORD_SET_MSG = _('Wallet password has set. Need to restart'
                                ' mixing for generating keypairs cache')
    WAIT_MIXING_STOP_MSG = _('Mixing is not stopped. If mixing sessions ends'
                             ' prematurely additional pay collateral may be'
                             ' paid. Do you really want to close wallet?')
    NO_NETWORK_STOP_MSG = _('Network is not available')
    OTHER_COINS_ARRIVED_MSG1 = _('Some unknown coins arrived on addresses'
                                 ' reserved for PrivateSend use, txid: {}.')
    OTHER_COINS_ARRIVED_MSG2 = _('WARNING: it is not recommended to spend'
                                 ' these coins in regular transactions!')
    OTHER_COINS_ARRIVED_MSG3 = _('You can use these coins in PrivateSend'
                                 ' mixing process by manually selecting UTXO'
                                 ' and creating new denoms or new collateral,'
                                 ' depending on UTXO value.')
    OTHER_COINS_ARRIVED_Q = _('Do you want to use other coins now?')
    if is_android():
        NO_DYNAMIC_FEE_MSG = _('{}\n\nYou can switch fee estimation method'
                               ' on send screen')
        OTHER_COINS_ARRIVED_MSG4 = _('You can view and use these coins from'
                                     ' Coins popup from PrivateSend options.')
    else:
        NO_DYNAMIC_FEE_MSG = _('{}\n\nYou can switch to static fee estimation'
                               ' on Fees Preferences tab')
        OTHER_COINS_ARRIVED_MSG4 = _('You can view and use these coins from'
                                     ' Coins tab.')

    gap_limit = 20
    gap_limit_for_change = 6

    def __init__(self, wallet):
        Logger.__init__(self)
        self.log_handler = PSGUILogHandler(self)
        self.logger = PSManLogAdapter(self.logger, {'psman_id': id(self)})

        self.state_lock = threading.Lock()
        self.states = s = PSStates
        self.mixing_running_states = [s.StartMixing, s.Mixing, s.StopMixing]
        self.no_clean_history_states = [s.Initializing, s.Errored,
                                        s.StartMixing, s.Mixing, s.StopMixing,
                                        s.FindingUntracked]
        self.wallet = wallet
        self.ps_keystore = None
        self.ps_ks_txin_type = 'p2pkh'
        self.config = None
        self._state = PSStates.Unsupported
        self.wallet_types_supported = ['standard']
        self.keystore_types_supported = ['bip32', 'hardware']
        keystore = wallet.db.get('keystore')
        self._allow_others = DEFAULT_ALLOW_OTHERS
        if keystore:
            self.w_ks_type = keystore.get('type', 'unknown')
        else:
            self.w_ks_type = 'unknown'
        self.w_type = wallet.wallet_type
        if (self.w_type in self.wallet_types_supported
                and self.w_ks_type in self.keystore_types_supported):
            if wallet.db.get_ps_data('ps_enabled', False):
                self.state = PSStates.Initializing
            else:
                self.state = PSStates.Disabled
        if self.unsupported:
            supported_w = ', '.join(self.wallet_types_supported)
            supported_ks = ', '.join(self.keystore_types_supported)
            this_type = self.w_type
            this_ks_type = self.w_ks_type
            self.unsupported_msg = _(f'PrivateSend is currently supported on'
                                     f' next wallet types: "{supported_w}"'
                                     f' and keystore types: "{supported_ks}".'
                                     f'\n\nThis wallet has type "{this_type}"'
                                     f' and kestore type "{this_ks_type}".')
        else:
            self.unsupported_msg = ''

        if self.is_hw_ks:
            self.enable_ps_keystore()

        self.network = None
        self.axe_net = None
        self.loop = None
        self._loop_thread = None
        self.main_taskgroup = None

        self.keypairs_state_lock = threading.Lock()
        self._keypairs_state = KPStates.Empty
        self._keypairs_cache = {}

        self.callback_lock = threading.Lock()
        self.callbacks = defaultdict(list)

        self.mix_sessions_lock = asyncio.Lock()
        self.mix_sessions = {}  # dict peer -> PSMixSession
        self.recent_mixes_mns = deque([], 10)  # added from mixing sessions

        self.denoms_lock = threading.Lock()
        self.collateral_lock = threading.Lock()
        self.others_lock = threading.Lock()

        self.new_denoms_wfl_lock = threading.Lock()
        self.new_collateral_wfl_lock = threading.Lock()
        self.pay_collateral_wfl_lock = threading.Lock()
        self.denominate_wfl_lock = threading.Lock()
        self._not_enough_funds = False

        # _ps_denoms_amount_cache recalculated in add_ps_denom/pop_ps_denom
        self._ps_denoms_amount_cache = 0
        denoms = wallet.db.get_ps_denoms()
        for addr, value, rounds in denoms.values():
            self._ps_denoms_amount_cache += value
        # _denoms_to_mix_cache recalculated on mix_rounds change and
        # in add[_mixing]_denom/pop[_mixing]_denom methods
        self._denoms_to_mix_cache = self.denoms_to_mix()

        # sycnhronizer unsubsribed addresses
        self.spent_addrs = set()
        self.unsubscribed_addrs = set()

        # postponed notification sent by trigger_postponed_notifications
        self.postponed_notifications = {}
        # electrum network disconnect time
        self.disconnect_time = 0

    @property
    def unsupported(self):
        return self.state == PSStates.Unsupported

    @property
    def enabled(self):
        return self.state not in [PSStates.Unsupported, PSStates.Disabled]

    @property
    def is_hw_ks(self):
        return self.w_ks_type == 'hardware'

    def enable_ps(self):
        if (self.w_type == 'standard' and self.is_hw_ks
                and 'ps_keystore' not in self.wallet.db.data):
            self.logger.info(f'ps_keystore for hw wallets must be created')
            return
        if not self.enabled:
            self.wallet.db.set_ps_data('ps_enabled', True)
            coro = self._enable_ps()
            asyncio.run_coroutine_threadsafe(coro, self.loop)

    async def _enable_ps(self):
        if self.enabled:
            return
        self.state = PSStates.Initializing
        self.trigger_callback('ps-state-changes', self.wallet, None, None)
        _load_and_cleanup = self.load_and_cleanup
        await self.loop.run_in_executor(None, _load_and_cleanup)
        await self.find_untracked_ps_txs()
        self.wallet.storage.write()

    @property
    def state(self):
        return self._state

    @property
    def is_waiting(self):
        if self.state not in self.mixing_running_states:
            return False
        if self.keypairs_state in [KPStates.NeedCache, KPStates.Caching]:
            return False

        active_wfls_cnt = 0
        active_wfls_cnt += len(self.denominate_wfl_list)
        if self.new_denoms_wfl:
            active_wfls_cnt += 1
        if self.new_collateral_wfl:
            active_wfls_cnt += 1
        return (active_wfls_cnt == 0)

    @state.setter
    def state(self, state):
        self._state = state

    @property
    def keypairs_state(self):
        return self._keypairs_state

    @keypairs_state.setter
    def keypairs_state(self, keypairs_state):
        self._keypairs_state = keypairs_state
        self.postpone_notification('ps-keypairs-changes', self.wallet)

    # enable and load ps_keystore
    def copy_standard_bip32_keystore(self):
        w = self.wallet
        main_ks_copy = copy.deepcopy(w.storage.get('keystore'))
        main_ks_copy['type'] = 'ps_bip32'
        if self.ps_keystore:
            ps_ks_copy = copy.deepcopy(w.storage.get('ps_keystore'))
            addr_deriv_offset = ps_ks_copy.get('addr_deriv_offset', None)
            if addr_deriv_offset is not None:
                main_ks_copy['addr_deriv_offset'] = addr_deriv_offset
        w.storage.put('ps_keystore', main_ks_copy)

    def load_ps_keystore(self):
        w = self.wallet
        if 'ps_keystore' in w.db.data:
            self.ps_keystore = load_keystore(w.storage, 'ps_keystore')

    def enable_ps_keystore(self):
        if self.w_type == 'standard':
            if self.w_ks_type == 'bip32':
                self.copy_standard_bip32_keystore()
                self.load_ps_keystore()
            elif self.is_hw_ks:
                self.load_ps_keystore()
        if self.ps_keystore:
            self.synchronize()

    def after_wallet_password_set(self, old_pw, new_pw):
        if not self.ps_keystore:
            return
        if self.w_type == 'standard':
            if self.w_ks_type == 'bip32':
                self.copy_standard_bip32_keystore()
                self.load_ps_keystore()

    def create_ps_ks_from_seed_ext_password(self, seed, seed_ext, password):
        if not self.is_hw_ks:
            raise Exception(f'can not create ps_keystore when main keystore'
                            f' type: "{self.w_ks_type}"')
        w = self.wallet
        if w.storage.get('ps_keystore', {}):
            raise Exception('ps_keystore already exists')
        keystore = from_seed(seed, seed_ext, False)
        keystore.update_password(None, password)
        ps_keystore = keystore.dump()
        ps_keystore.update({'type': 'ps_bip32'})
        w.storage.put('ps_keystore', ps_keystore)
        self.enable_ps_keystore()

    def is_ps_ks_encrypted(self):
        if self.ps_keystore:
            try:
                self.ps_keystore.check_password(None)
                return False
            except:
                return True

    def need_password(self):
        return (self.wallet.has_keystore_encryption()
                or self.is_hw_ks and self.is_ps_ks_encrypted())

    def update_ps_ks_password(self, old_pw, new_pw):
        if not self.is_hw_ks:
            raise Exception(f'can not create ps_keystore for main keystore'
                            f' type: "{self.w_ks_type}"')
        if old_pw is None and self.is_ps_ks_encrypted():
            raise InvalidPassword()
        self.ps_keystore.check_password(old_pw)

        if old_pw is None and new_pw:
            self.on_wallet_password_set()

        self.ps_keystore.update_password(old_pw, new_pw)
        self.wallet.storage.put('ps_keystore', self.ps_keystore.dump())
        self.wallet.storage.write()

    def is_ps_ks_inputs_in_tx(self, tx):
        for txin in tx.inputs():
            if self.is_ps_ks(txin['address']):
                return True

    # methods related to ps_keystore
    def pubkeys_to_address(self, pubkey):
        return pubkey_to_address(self.ps_ks_txin_type, pubkey)

    def derive_pubkeys(self, c, i):
        return self.ps_keystore.derive_pubkey(c, i)

    def derive_address(self, for_change, i):
        x = self.derive_pubkeys(for_change, i)
        return self.pubkeys_to_address(x)

    def get_pubkey(self, c, i):
        return self.derive_pubkeys(c, i)

    def get_address_index(self, address):
        return self.wallet.db.get_address_index(address, ps_ks=True)

    def is_ps_ks(self, address):
        return bool(self.wallet.db.get_address_index(address, ps_ks=True))

    def get_public_key(self, address):
        sequence = self.get_address_index(address)
        return self.get_pubkey(*sequence)

    def get_public_keys(self, address):
        return [self.get_public_key(address)]

    def check_address(self, addr):
        idx = self.get_address_index(addr)
        if addr and bool(idx):
            if addr != self.derive_address(*idx):
                raise PSKsInternalAddressCorruption()

    def create_new_address(self, for_change=False):
        with self.wallet.lock:
            if for_change:
                n = self.wallet.db.num_change_addresses(ps_ks=True)
            else:
                n = self.wallet.db.num_receiving_addresses(ps_ks=True)
            address = self.derive_address(for_change, n)
            if for_change:
                self.wallet.db.add_change_address(address, ps_ks=True)
            else:
                self.wallet.db.add_receiving_address(address, ps_ks=True)
            self.wallet.add_address(address, ps_ks=True)  # addr synchronizer
            return address

    def address_is_old(self, address, age_limit=2):
        age = -1
        h = self.wallet.db.get_addr_history(address)
        for tx_hash, tx_height in h:
            if tx_height <= 0:
                tx_age = 0
            else:
                tx_age = self.wallet.get_local_height() - tx_height + 1
            if tx_age > age:
                age = tx_age
        return age > age_limit

    def synchronize_sequence(self, for_change):
        limit = self.gap_limit_for_change if for_change else self.gap_limit
        while True:
            if for_change:
                addrs = self.get_change_addresses()
            else:
                addrs = self.get_receiving_addresses()
            num_addrs = len(addrs)
            if num_addrs < limit:
                self.create_new_address(for_change)
                continue
            last_few_addresses = addrs[-limit:]
            if any(map(self.address_is_old, last_few_addresses)):
                self.create_new_address(for_change)
            else:
                break

    def synchronize(self):
        with self.wallet.lock:
            self.synchronize_sequence(False)
            self.synchronize_sequence(True)

    def is_beyond_limit(self, address):
        is_change, i = self.get_address_index(address)
        limit = self.gap_limit_for_change if is_change else self.gap_limit
        if i < limit:
            return False
        slice_start = max(0, i - limit)
        slice_stop = max(0, i)
        if is_change:
            prev_addrs = self.get_change_addresses(slice_start=slice_start,
                                                   slice_stop=slice_stop)
        else:
            prev_addrs = self.get_receiving_addresses(slice_start=slice_start,
                                                      slice_stop=slice_stop)
        for addr in prev_addrs:
            if self.wallet.db.get_addr_history(addr):
                return False
        return True

    def get_receiving_addresses(self, *, slice_start=None, slice_stop=None):
        return self.wallet.db.get_receiving_addresses(slice_start=slice_start,
                                                      slice_stop=slice_stop,
                                                      ps_ks=True)

    def get_change_addresses(self, *, slice_start=None, slice_stop=None):
        return self.wallet.db.get_change_addresses(slice_start=slice_start,
                                                   slice_stop=slice_stop,
                                                   ps_ks=True)

    def get_addresses(self):
        return self.get_receiving_addresses() + self.get_change_addresses()

    def get_unused_addresses(self, for_change=False):
        if for_change:
            domain = self.get_change_addresses()
        else:
            domain = self.get_receiving_addresses()
        ps_reserved = self.wallet.db.get_ps_reserved()
        tmp_reserved_addr = self.get_tmp_reserved_address()
        tmp_reserved_addrs = [tmp_reserved_addr] if tmp_reserved_addr else []
        return [addr for addr in domain if not self.wallet.is_used(addr)
                and addr not in self.wallet.receive_requests.keys()
                and addr not in ps_reserved
                and addr not in tmp_reserved_addrs]

    def add_input_info(self, txin):
        w = self.wallet
        address = w.get_txin_address(txin)
        if w.is_mine(address):
            if self.is_ps_ks(address):
                txin['address'] = address
                txin['type'] = self.ps_ks_txin_type
                self.add_input_sig_info(txin, address)
            else:
                txin['address'] = address
                txin['type'] = w.get_txin_type(address)
                w.add_input_sig_info(txin, address)

    def add_input_sig_info(self, txin, address):
        derivation = self.get_address_index(address)
        x_pubkey = self.ps_keystore.get_xpubkey(*derivation)
        txin['x_pubkeys'] = [x_pubkey]
        txin['signatures'] = [None]
        txin['num_sig'] = 1

    # load ps related data
    def load_and_cleanup(self):
        if not self.enabled:
            return
        w = self.wallet
        # enable ps_keystore and syncronize addresses
        if not self.ps_keystore:
            self.enable_ps_keystore()
        # check last_mix_stop_time if it was not saved on wallet crash
        last_mix_start_time = self.last_mix_start_time
        last_mix_stop_time = self.last_mix_stop_time
        if last_mix_stop_time < last_mix_start_time:
            last_mixed_tx_time = self.last_mixed_tx_time
            wait_time = self.wait_for_mn_txs_time
            if last_mixed_tx_time > last_mix_start_time:
                self.last_mix_stop_time = last_mixed_tx_time + wait_time
            else:
                self.last_mix_stop_time = last_mix_start_time + wait_time
        # load and unsubscribe spent ps addresses
        unspent = w.db.get_unspent_ps_addresses()
        for addr in w.db.get_ps_addresses():
            if addr in unspent:
                continue
            self.spent_addrs.add(addr)
            if self.subscribe_spent:
                continue
            hist = w.db.get_addr_history(addr)
            self.unsubscribe_spent_addr(addr, hist)
        self._fix_uncompleted_ps_txs()

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
        try:
            with self.callback_lock:
                callbacks = self.callbacks[event][:]
            [callback(event, *args) for callback in callbacks]
        except Exception as e:
            self.logger.info(f'Error in trigger_callback: {str(e)}')

    def postpone_notification(self, event, *args):
        self.postponed_notifications[event] = args

    async def trigger_postponed_notifications(self):
        while True:
            await asyncio.sleep(0.5)
            if self.enabled:
                for event in list(self.postponed_notifications.keys()):
                    args = self.postponed_notifications.pop(event, None)
                    if args is not None:
                        self.trigger_callback(event, *args)

    def on_network_start(self, network):
        self.network = network
        self.network.register_callback(self.on_wallet_updated,
                                       ['wallet_updated'])
        self.network.register_callback(self.on_network_status,
                                       ['status'])
        self.axe_net = network.axe_net
        self.loop = network.asyncio_loop
        self._loop_thread = network._loop_thread
        asyncio.ensure_future(self.clean_keypairs_on_timeout())
        asyncio.ensure_future(self.cleanup_staled_denominate_wfls())
        asyncio.ensure_future(self.trigger_postponed_notifications())
        asyncio.ensure_future(self.broadcast_new_denoms_new_collateral_wfls())

    def on_stop_threads(self):
        if self.state == PSStates.Mixing:
            self.stop_mixing()
        self.network.unregister_callback(self.on_wallet_updated)
        self.network.unregister_callback(self.on_network_status)

    def on_network_status(self, event, *args):
        connected = self.network.is_connected()
        if connected:
            self.disconnect_time = 0
        else:
            now = time.time()
            if self.disconnect_time == 0:
                self.disconnect_time = now
            if now - self.disconnect_time > 30:  # disconnected for 30 seconds
                if self.state == PSStates.Mixing:
                    self.stop_mixing(self.NO_NETWORK_STOP_MSG)

    async def on_wallet_updated(self, event, *args):
        if not self.enabled:
            return
        w = args[0]
        if w != self.wallet:
            return
        if w.is_up_to_date():
            self._not_enough_funds = False
            if self.state in [PSStates.Initializing, PSStates.Ready]:
                await self.find_untracked_ps_txs()

    async def broadcast_transaction(self, tx, *, timeout=None) -> None:
        if self.enabled:
            w = self.wallet

            def check_spend_to_ps_addresses():
                for o in tx.outputs():
                    addr = o.address
                    if addr in w.db.get_ps_addresses():
                        msg = self.SPEND_TO_PS_ADDRS_MSG
                        raise PSSpendToPSAddressesError(msg)
            await self.loop.run_in_executor(None, check_spend_to_ps_addresses)

            def check_possible_dspend():
                with self.denoms_lock, self.collateral_lock:
                    warn = self.double_spend_warn
                    if not warn:
                        return
                    for txin in tx.inputs():
                        prev_h = txin['prevout_hash']
                        prev_n = txin['prevout_n']
                        outpoint = f'{prev_h}:{prev_n}'
                        if (w.db.get_ps_spending_collateral(outpoint)
                                or w.db.get_ps_spending_denom(outpoint)):
                            raise PSPossibleDoubleSpendError(warn)
            await self.loop.run_in_executor(None, check_possible_dspend)
        await self.network.broadcast_transaction(tx, timeout=timeout)

    @property
    def keep_amount(self):
        return self.wallet.db.get_ps_data('keep_amount', DEFAULT_KEEP_AMOUNT)

    @keep_amount.setter
    def keep_amount(self, amount):
        if self.state in self.mixing_running_states:
            return
        if self.keep_amount == amount:
            return
        amount = max(self.min_keep_amount, int(amount))
        amount = min(self.max_keep_amount, int(amount))
        self.wallet.db.set_ps_data('keep_amount', amount)

    @property
    def min_keep_amount(self):
        return MIN_KEEP_AMOUNT

    @property
    def max_keep_amount(self):
        return MAX_KEEP_AMOUNT

    def keep_amount_data(self, full_txt=False):
        if full_txt:
            return _('This amount acts as a threshold to turn off'
                     " PrivateSend mixing once it's reached.")
        else:
            return _('Amount of Axe to keep anonymized')

    @property
    def mix_rounds(self):
        return self.wallet.db.get_ps_data('mix_rounds', DEFAULT_MIX_ROUNDS)

    @mix_rounds.setter
    def mix_rounds(self, rounds):
        if self.state in self.mixing_running_states:
            return
        if self.mix_rounds == rounds:
            return
        rounds = max(self.min_mix_rounds, int(rounds))
        rounds = min(self.max_mix_rounds, int(rounds))
        self.wallet.db.set_ps_data('mix_rounds', rounds)
        with self.denoms_lock:
            self._denoms_to_mix_cache = self.denoms_to_mix()

    @property
    def min_mix_rounds(self):
        return MIN_MIX_ROUNDS

    @property
    def max_mix_rounds(self):
        if constants.net.TESTNET:
            return MAX_MIX_ROUNDS_TESTNET
        else:
            return MAX_MIX_ROUNDS

    def mix_rounds_data(self, full_txt=False):
        if full_txt:
            return _('This setting determines the amount of individual'
                     ' masternodes that an input will be anonymized through.'
                     ' More rounds of anonymization gives a higher degree'
                     ' of privacy, but also costs more in fees.')
        else:
            return _('PrivateSend rounds to use')

    def create_sm_denoms_data(self, full_txt=False, enough_txt=False,
                              no_denoms_txt=False, confirm_txt=False):
        confirm_str_end = _('Do you want to create small denoms from one big'
                            ' denom utxo? No change value will be created'
                            ' for privacy reasons.')
        if full_txt:
            return _('Create small denominations from big one')
        elif enough_txt:
            return '%s %s' % (_('There is enough small denoms.'),
                              confirm_str_end)
        elif confirm_txt:
            return '%s %s' % (_('There is not enough small denoms to make'
                                ' PrivateSend transactions with reasonable'
                                ' fees.'),
                              confirm_str_end)
        elif no_denoms_txt:
            return _('There is no denoms to create small denoms from big one.')
        else:
            return _('Create small denominations')

    @property
    def group_history(self):
        if self.unsupported:
            return False
        return self.wallet.db.get_ps_data('group_history',
                                          DEFAULT_GROUP_HISTORY)

    @group_history.setter
    def group_history(self, group_history):
        if self.group_history == group_history:
            return
        self.wallet.db.set_ps_data('group_history', bool(group_history))

    def group_history_data(self, full_txt=False):
        if full_txt:
            return _('Group PrivateSend mixing transactions in wallet history')
        else:
            return _('Group PrivateSend transactions')

    @property
    def notify_ps_txs(self):
        return self.wallet.db.get_ps_data('notify_ps_txs',
                                          DEFAULT_NOTIFY_PS_TXS)

    @notify_ps_txs.setter
    def notify_ps_txs(self, notify_ps_txs):
        if self.notify_ps_txs == notify_ps_txs:
            return
        self.wallet.db.set_ps_data('notify_ps_txs', bool(notify_ps_txs))

    def notify_ps_txs_data(self, full_txt=False):
        if full_txt:
            return _('Notify when PrivateSend mixing transactions'
                     ' have arrived')
        else:
            return _('Notify on PrivateSend transactions')

    def need_notify(self, txid):
        if self.notify_ps_txs:
            return True
        tx_type, completed = self.wallet.db.get_ps_tx(txid)
        if tx_type not in PS_MIXING_TX_TYPES:
            return True
        else:
            return False

    @property
    def max_sessions(self):
        return self.wallet.db.get_ps_data('max_sessions',
                                          DEFAULT_PRIVATESEND_SESSIONS)

    @max_sessions.setter
    def max_sessions(self, max_sessions):
        if self.max_sessions == max_sessions:
            return
        self.wallet.db.set_ps_data('max_sessions', int(max_sessions))

    @property
    def min_max_sessions(self):
        return MIN_PRIVATESEND_SESSIONS

    @property
    def max_max_sessions(self):
        return MAX_PRIVATESEND_SESSIONS

    def max_sessions_data(self, full_txt=False):
        if full_txt:
            return _('Count of PrivateSend mixing session')
        else:
            return _('PrivateSend sessions')

    @property
    def kp_timeout(self):
        return self.wallet.db.get_ps_data('kp_timeout', DEFAULT_KP_TIMEOUT)

    @kp_timeout.setter
    def kp_timeout(self, kp_timeout):
        if self.kp_timeout == kp_timeout:
            return
        kp_timeout = min(int(kp_timeout), MAX_KP_TIMEOUT)
        kp_timeout = max(kp_timeout, MIN_KP_TIMEOUT)
        self.wallet.db.set_ps_data('kp_timeout', kp_timeout)

    @property
    def min_kp_timeout(self):
        return MIN_KP_TIMEOUT

    @property
    def max_kp_timeout(self):
        return MAX_KP_TIMEOUT

    def kp_timeout_data(self, full_txt=False):
        if full_txt:
            return _('Time in minutes to keep keypairs after mixing stopped.'
                     ' Keypairs is cached before mixing starts on wallets with'
                     ' encrypted keystore.')
        else:
            return _('Keypairs cache timeout')

    @property
    def subscribe_spent(self):
        return self.wallet.db.get_ps_data('subscribe_spent',
                                          DEFAULT_SUBSCRIBE_SPENT)

    @subscribe_spent.setter
    def subscribe_spent(self, subscribe_spent):
        if self.subscribe_spent == subscribe_spent:
            return
        self.wallet.db.set_ps_data('subscribe_spent', bool(subscribe_spent))
        w = self.wallet
        if subscribe_spent:
            for addr in self.spent_addrs:
                self.subscribe_spent_addr(addr)
        else:
            for addr in self.spent_addrs:
                hist = w.db.get_addr_history(addr)
                self.unsubscribe_spent_addr(addr, hist)

    def subscribe_spent_data(self, full_txt=False):
        if full_txt:
            return _('Subscribe to spent PS addresses'
                     ' on electrum servers')
        else:
            return _('Subscribe to spent PS addresses')

    @property
    def allow_others(self):
        return self._allow_others

    @allow_others.setter
    def allow_others(self, allow_others):
        if self._allow_others == allow_others:
            return
        self._allow_others = allow_others

    def allow_others_data(self, full_txt=False,
                          qt_question=False, kv_question=False):
        expl = _('Other PS coins appears if some transaction other than'
                 ' mixing PrivateSend transactions types send funds to one'
                 ' of addresses used for PrivateSend mixing.\n\nIt is not'
                 ' recommended for privacy reasons to spend these funds'
                 ' in regular way. However, you can mix these funds manually'
                 ' with PrivateSend mixing process.')

        expl2_qt =  _('You can create new denoms or new collateral from other'
                      ' PS coins on Coins tab. You can also select individual'
                      ' coin to spend and return to originating address.')

        expl2_kv =  _('You can create new denoms or new collateral from other'
                      ' PS coins with Coins dialog from PrivateSend options.')

        q = _('This option allow spend other PS coins as a regular coins'
              ' without coins selection.'
              ' Are you sure to enable this option?')
        if full_txt:
            return _('Allow spend other PS coins in regular transactions')
        elif qt_question:
            return '%s\n\n%s\n\n%s' % (expl, expl2_qt, q)
        elif kv_question:
            return '%s\n\n%s\n\n%s' % (expl, expl2_kv, q)
        else:
            return _('Allow spend other PS coins')

    @property
    def ps_collateral_cnt(self):
        return len(self.wallet.db.get_ps_collaterals())

    def add_ps_spending_collateral(self, outpoint, wfl_uuid):
        self.wallet.db._add_ps_spending_collateral(outpoint, wfl_uuid)

    def pop_ps_spending_collateral(self, outpoint):
        return self.wallet.db._pop_ps_spending_collateral(outpoint)

    def add_ps_reserved(self, addr, data):
        self.wallet.db._add_ps_reserved(addr, data)
        self.postpone_notification('ps-reserved-changes', self.wallet)

    def pop_ps_reserved(self, addr):
        data = self.wallet.db._pop_ps_reserved(addr)
        self.postpone_notification('ps-reserved-changes', self.wallet)
        return data

    def add_ps_denom(self, outpoint, denom):  # denom is (addr, value, rounds)
        self.wallet.db._add_ps_denom(outpoint, denom)
        self._ps_denoms_amount_cache += denom[1]
        if denom[2] < self.mix_rounds:  # if rounds < mix_rounds
            self._denoms_to_mix_cache[outpoint] = denom

    def pop_ps_denom(self, outpoint):
        denom = self.wallet.db._pop_ps_denom(outpoint)
        if denom:
            self._ps_denoms_amount_cache -= denom[1]
            self._denoms_to_mix_cache.pop(outpoint, None)
        return denom

    def calc_denoms_by_values(self):
        denoms_values = [denom[1]
                         for denom in self.wallet.db.get_ps_denoms().values()]
        if not denoms_values:
            return {}
        denoms_by_values = {denom_val: 0 for denom_val in PS_DENOMS_VALS}
        denoms_by_values.update(Counter(denoms_values))
        return denoms_by_values

    def add_ps_spending_denom(self, outpoint, wfl_uuid):
        self.wallet.db._add_ps_spending_denom(outpoint, wfl_uuid)
        self._denoms_to_mix_cache.pop(outpoint, None)

    def pop_ps_spending_denom(self, outpoint):
        db = self.wallet.db
        denom = db.get_ps_denom(outpoint)
        if denom and denom[2] < self.mix_rounds:  # if rounds < mix_rounds
            self._denoms_to_mix_cache[outpoint] = denom
        return db._pop_ps_spending_denom(outpoint)

    @property
    def pay_collateral_wfl(self):
        d = self.wallet.db.get_ps_data('pay_collateral_wfl')
        if d:
            return PSTxWorkflow._from_dict(d)

    def set_pay_collateral_wfl(self, workflow):
        self.wallet.db.set_ps_data('pay_collateral_wfl', workflow._as_dict())
        self.postpone_notification('ps-wfl-changes', self.wallet)

    def clear_pay_collateral_wfl(self):
        self.wallet.db.set_ps_data('pay_collateral_wfl', {})
        self.postpone_notification('ps-wfl-changes', self.wallet)

    @property
    def new_collateral_wfl(self):
        d = self.wallet.db.get_ps_data('new_collateral_wfl')
        if d:
            return PSTxWorkflow._from_dict(d)

    def set_new_collateral_wfl(self, workflow):
        self.wallet.db.set_ps_data('new_collateral_wfl', workflow._as_dict())
        self.postpone_notification('ps-wfl-changes', self.wallet)

    def clear_new_collateral_wfl(self):
        self.wallet.db.set_ps_data('new_collateral_wfl', {})
        self.postpone_notification('ps-wfl-changes', self.wallet)

    @property
    def new_denoms_wfl(self):
        d = self.wallet.db.get_ps_data('new_denoms_wfl')
        if d:
            return PSTxWorkflow._from_dict(d)

    def set_new_denoms_wfl(self, workflow):
        self.wallet.db.set_ps_data('new_denoms_wfl', workflow._as_dict())
        self.postpone_notification('ps-wfl-changes', self.wallet)

    def clear_new_denoms_wfl(self):
        self.wallet.db.set_ps_data('new_denoms_wfl', {})
        self.postpone_notification('ps-wfl-changes', self.wallet)

    @property
    def denominate_wfl_list(self):
        wfls = self.wallet.db.get_ps_data('denominate_workflows', {})
        return list(wfls.keys())

    @property
    def active_denominate_wfl_cnt(self):
        cnt = 0
        for uuid in self.denominate_wfl_list:
            wfl = self.get_denominate_wfl(uuid)
            if wfl and not wfl.completed:
                cnt += 1
        return cnt

    def get_denominate_wfl(self, uuid):
        wfls = self.wallet.db.get_ps_data('denominate_workflows', {})
        wfl = wfls.get(uuid)
        if wfl:
            return PSDenominateWorkflow._from_uuid_and_tuple(uuid, wfl)

    def clear_denominate_wfl(self, uuid):
        self.wallet.db.pop_ps_data('denominate_workflows', uuid)
        self.postpone_notification('ps-wfl-changes', self.wallet)

    def set_denominate_wfl(self, workflow):
        wfl_dict = workflow._as_dict()
        self.wallet.db.update_ps_data('denominate_workflows', wfl_dict)
        self.postpone_notification('ps-wfl-changes', self.wallet)

    def set_tmp_reserved_address(self, address):
        '''Used to reserve address to not be used in ps reservation'''
        self.wallet.db.set_ps_data('tmp_reserved_address', address)

    def get_tmp_reserved_address(self):
        return self.wallet.db.get_ps_data('tmp_reserved_address', '')

    def mixing_control_data(self, full_txt=False):
        if full_txt:
            return _('Control PrivateSend mixing process')
        else:
            if self.state == PSStates.Ready:
                return _('Start Mixing')
            elif self.state == PSStates.Mixing:
                return _('Stop Mixing')
            elif self.state == PSStates.StartMixing:
                return _('Starting Mixing ...')
            elif self.state == PSStates.StopMixing:
                return _('Stopping Mixing ...')
            elif self.state == PSStates.FindingUntracked:
                return _('Finding PS Data ...')
            elif self.state == PSStates.Disabled:
                return _('Enable PrivateSend')
            elif self.state == PSStates.Initializing:
                return _('Initializing ...')
            elif self.state == PSStates.Cleaning:
                return _('Cleaning PS Data ...')
            else:
                return _('Check Log For Errors')

    @property
    def last_mix_start_time(self):
        return self.wallet.db.get_ps_data('last_mix_start_time', 0)  # Jan 1970

    @last_mix_start_time.setter
    def last_mix_start_time(self, time):
        self.wallet.db.set_ps_data('last_mix_start_time', time)

    @property
    def last_mix_stop_time(self):
        return self.wallet.db.get_ps_data('last_mix_stop_time', 0)  # Jan 1970

    @last_mix_stop_time.setter
    def last_mix_stop_time(self, time):
        self.wallet.db.set_ps_data('last_mix_stop_time', time)

    @property
    def last_mixed_tx_time(self):
        return self.wallet.db.get_ps_data('last_mixed_tx_time', 0)  # Jan 1970

    @last_mixed_tx_time.setter
    def last_mixed_tx_time(self, time):
        self.wallet.db.set_ps_data('last_mixed_tx_time', time)

    @property
    def wait_for_mn_txs_time(self):
        return WAIT_FOR_MN_TXS_TIME_SEC

    @property
    def mix_stop_secs_ago(self):
        return round(time.time() - self.last_mix_stop_time)

    @property
    def mix_recently_run(self):
        return self.mix_stop_secs_ago < self.wait_for_mn_txs_time

    @property
    def double_spend_warn(self):
        if self.state in self.mixing_running_states:
            wait_time = self.wait_for_mn_txs_time
            return _('PrivateSend mixing is currently run. To prevent'
                     ' double spending it is recommended to stop mixing'
                     ' and wait {} seconds before spending PrivateSend'
                     ' coins.'.format(wait_time))
        if self.mix_recently_run:
            wait_secs = self.wait_for_mn_txs_time - self.mix_stop_secs_ago
            if wait_secs > 0:
                return _('PrivateSend mixing is recently run. To prevent'
                         ' double spending It is recommended to wait'
                         ' {} seconds before spending PrivateSend'
                         ' coins.'.format(wait_secs))
        return ''

    def dn_balance_data(self, full_txt=False):
        if full_txt:
            return _('Currently available denominated balance')
        else:
            return _('Denominated Balance')

    def ps_balance_data(self, full_txt=False):
        if full_txt:
            return _('Currently available anonymized balance')
        else:
            return _('PrivateSend Balance')

    @property
    def show_warn_electrumx(self):
        return self.wallet.db.get_ps_data('show_warn_electrumx', True)

    @show_warn_electrumx.setter
    def show_warn_electrumx(self, show):
        self.wallet.db.set_ps_data('show_warn_electrumx', show)

    def warn_electrumx_data(self, full_txt=False, help_txt=False):
        if full_txt:
            return _('Privacy Warning: ElectrumX is a weak spot'
                     ' in PrivateSend privacy and knows all your'
                     ' wallet UTXO including PrivateSend mixed denoms.'
                     ' You should use trusted ElectrumX server'
                     ' for PrivateSend operation.')
        elif help_txt:
            return _('Show privacy warning about ElectrumX servers usage')
        else:
            return _('Privacy Warning ...')

    @property
    def show_warn_ps_ks(self):
        return self.wallet.db.get_ps_data('show_warn_ps_ks', True)

    @show_warn_ps_ks.setter
    def show_warn_ps_ks(self, show):
        self.wallet.db.set_ps_data('show_warn_ps_ks', show)

    def warn_ps_ks_data(self):
        return _('Show warning on exit if PS Keystore contain funds')

    def get_ps_data_info(self):
        res = []
        w = self.wallet
        data = w.db.get_ps_txs()
        res.append(f'PrivateSend transactions count: {len(data)}')
        data = w.db.get_ps_txs_removed()
        res.append(f'Removed PrivateSend transactions count: {len(data)}')

        data = w.db.get_ps_denoms()
        res.append(f'ps_denoms count: {len(data)}')
        data = w.db.get_ps_spent_denoms()
        res.append(f'ps_spent_denoms count: {len(data)}')
        data = w.db.get_ps_spending_denoms()
        res.append(f'ps_spending_denoms count: {len(data)}')

        data = w.db.get_ps_collaterals()
        res.append(f'ps_collaterals count: {len(data)}')
        data = w.db.get_ps_spent_collaterals()
        res.append(f'ps_spent_collaterals count: {len(data)}')
        data = w.db.get_ps_spending_collaterals()
        res.append(f'ps_spending_collaterals count: {len(data)}')

        data = w.db.get_ps_others()
        res.append(f'ps_others count: {len(data)}')
        data = w.db.get_ps_spent_others()
        res.append(f'ps_spent_others count: {len(data)}')

        data = w.db.get_ps_reserved()
        res.append(f'Reserved addresses count: {len(data)}')

        if self.pay_collateral_wfl:
            res.append(f'Pay collateral workflow data exists')

        if self.new_collateral_wfl:
            res.append(f'New collateral workflow data exists')

        if self.new_denoms_wfl:
            res.append(f'New denoms workflow data exists')

        completed_dwfl_cnt = 0
        dwfl_list = self.denominate_wfl_list
        dwfl_cnt = len(dwfl_list)
        for uuid in dwfl_list:
            wfl = self.get_denominate_wfl(uuid)
            if wfl and wfl.completed:
                completed_dwfl_cnt += 1
        if dwfl_cnt:
            res.append(f'Denominate workflow count: {dwfl_cnt},'
                       f' completed: {completed_dwfl_cnt}')

        if self._keypairs_cache:
            for cache_type in KP_ALL_TYPES:
                if cache_type in self._keypairs_cache:
                    cnt = len(self._keypairs_cache[cache_type])
                    res.append(f'Keypairs cache type: {cache_type}'
                               f' cached keys: {cnt}')
        return res

    def mixing_progress(self, count_on_rounds=None):
        w = self.wallet
        dn_balance = sum(w.get_balance(include_ps=False, min_rounds=0))
        if dn_balance == 0:
            return 0
        r = self.mix_rounds if count_on_rounds is None else count_on_rounds
        ps_balance = sum(w.get_balance(include_ps=False, min_rounds=r))
        if dn_balance == ps_balance:
            return 100
        res = 0
        for i in range(1, r+1):
            ri_balance = sum(w.get_balance(include_ps=False, min_rounds=i))
            res += ri_balance/dn_balance/r
        res = round(res*100)
        if res < 100:  # on small amount differences show 100 percents to early
            return res
        else:
            return 99

    def mixing_progress_data(self, full_txt=False):
        if full_txt:
            return _('Mixing Progress in percents')
        else:
            return _('Mixing Progress')

    @property
    def all_mixed(self):
        w = self.wallet
        dn_balance = sum(w.get_balance(include_ps=False, min_rounds=0))
        if dn_balance == 0:
            return False

        r = self.mix_rounds
        ps_balance = sum(w.get_balance(include_ps=False, min_rounds=r))
        if ps_balance < dn_balance:
            return False

        need_val = to_haks(self.keep_amount) + CREATE_COLLATERAL_VAL
        approx_val = need_val - dn_balance
        outputs_amounts = self.find_denoms_approx(approx_val)
        if outputs_amounts:
            return False
        return True

    # Methods related to keypairs cache
    def on_wallet_password_set(self):
        if self.state == PSStates.Mixing:
            self.stop_mixing(self.WALLET_PASSWORD_SET_MSG)

    async def clean_keypairs_on_timeout(self):
        def _clean_kp_on_timeout():
            with self.keypairs_state_lock:
                if self.keypairs_state == KPStates.Unused:
                    self.logger.info('Cleaning Keyparis Cache'
                                     ' on inactivity timeout')
                    self._cleanup_all_keypairs_cache()
                    self.logger.info('Cleaned Keyparis Cache')
                    self.keypairs_state = KPStates.Empty
        while True:
            if self.enabled:
                if (self.state not in self.mixing_running_states
                        and self.keypairs_state == KPStates.Unused
                        and self.mix_stop_secs_ago >= self.kp_timeout * 60):
                    await self.loop.run_in_executor(None, _clean_kp_on_timeout)
            await asyncio.sleep(1)

    async def _make_keypairs_cache(self, password):
        _make_cache = self._cache_keypairs
        if password is None:
            return
        while True:
            if self.keypairs_state == KPStates.NeedCache:
                try:
                    await self.loop.run_in_executor(None, _make_cache,
                                                    password)
                except Exception as e:
                    self.logger.info(f'_make_keypairs_cache: {str(e)}')
                    self._cleanup_unfinished_keypairs_cache()
                return
            await asyncio.sleep(1)

    def calc_need_sign_cnt(self, new_denoms_cnt):
        w = self.wallet
        # calc already presented ps_denoms
        old_denoms_cnt = len(w.db.get_ps_denoms(min_rounds=0))
        # calc need sign denoms for each round
        total_denoms_cnt = old_denoms_cnt + new_denoms_cnt
        sign_denoms_cnt = 0
        for r in range(1, self.mix_rounds):  # round 0 calculated later
            next_rounds_denoms_cnt = len(w.db.get_ps_denoms(min_rounds=r+1))
            sign_denoms_cnt += (total_denoms_cnt - next_rounds_denoms_cnt)

        # additional reserve for addrs used by denoms with rounds eq mix_rounds
        sign_denoms_cnt += (total_denoms_cnt - next_rounds_denoms_cnt)

        # Axe Core charges the collateral randomly in 1/10 mixing transactions
        # * avg denoms in mixing transactions is 5 (1-9), but real count
        #   currently is about ~1.1 on testnet, use same for mainnet
        pay_collateral_cnt = ceil(sign_denoms_cnt/10/1.1)
        # new collateral contain 4 pay collateral amounts
        new_collateral_cnt = ceil(pay_collateral_cnt*0.25)
        # * pay collateral uses change in 3/4 of cases (1/4 OP_RETURN output)
        need_sign_change_cnt = ceil(pay_collateral_cnt*0.75)

        # calc existing ps_collaterals by amounts
        old_collaterals_val = 0
        for ps_collateral in w.db.get_ps_collaterals().values():
            old_collaterals_val += ps_collateral[1]
        old_collaterals_cnt = floor(old_collaterals_val/CREATE_COLLATERAL_VAL)
        new_collateral_cnt = max(0, new_collateral_cnt - old_collaterals_cnt)

        # add round 0 denoms (no pay collaterals need to create)
        sign_denoms_cnt += (total_denoms_cnt - old_denoms_cnt)

        need_sign_cnt = sign_denoms_cnt + new_collateral_cnt
        return need_sign_cnt, need_sign_change_cnt, new_collateral_cnt

    def calc_need_new_keypairs_cnt(self):
        new_denoms_amounts_real = self.calc_need_denoms_amounts()
        new_denoms_cnt_real = sum([len(a) for a in new_denoms_amounts_real])
        new_denoms_val_real = sum([sum(a) for a in new_denoms_amounts_real])

        new_denoms_amounts = self.calc_need_denoms_amounts(on_keep_amount=True)
        new_denoms_val = sum([sum(a) for a in new_denoms_amounts])
        if new_denoms_val > new_denoms_val_real:
            part_val = ceil(new_denoms_val / KP_MAX_INCOMING_TXS)
            part_amounts = self.find_denoms_approx(part_val)
            part_amounts_cnt = sum([len(a) for a in part_amounts])
            need_sign_cnt, need_sign_change_cnt = \
                self.calc_need_sign_cnt(part_amounts_cnt)[0:2]
            need_sign_cnt *= KP_MAX_INCOMING_TXS
            need_sign_change_cnt *= KP_MAX_INCOMING_TXS
            return need_sign_cnt, need_sign_change_cnt, True
        else:
            need_sign_cnt, need_sign_change_cnt = \
                self.calc_need_sign_cnt(new_denoms_cnt_real)[0:2]
            return need_sign_cnt, need_sign_change_cnt, False

    def check_need_new_keypairs(self):
        w = self.wallet
        if not self.need_password():
            return False, None

        with self.keypairs_state_lock:
            prev_kp_state = self.keypairs_state
            if prev_kp_state in [KPStates.NeedCache, KPStates.Caching]:
                return False, None
            self.keypairs_state = KPStates.NeedCache

        if prev_kp_state == KPStates.Empty:
            return True, prev_kp_state

        for cache_type in KP_ALL_TYPES:
            if cache_type not in self._keypairs_cache:
                return True, prev_kp_state

        with w.lock:
            # check spendable regular coins keys
            utxos = w.get_utxos(None,
                                excluded_addresses=w.frozen_addresses,
                                mature_only=True)
            utxos = [utxo for utxo in utxos if not w.is_frozen_coin(utxo)]
            for c in utxos:
                if c['address'] not in self._keypairs_cache[KP_SPENDABLE]:
                    return True, prev_kp_state

            sign_cnt, sign_change_cnt, small_mix_funds = \
                self.calc_need_new_keypairs_cnt()

            # check cache for incoming addresses on small mix funds
            if not self.is_hw_ks and small_mix_funds:
                cache_incoming = self._keypairs_cache[KP_INCOMING]
                if len(cache_incoming) < KP_MAX_INCOMING_TXS:
                    return True, prev_kp_state

            # check spendable ps coins keys (already saved denoms/collateral)
            for c in w.get_utxos(None, min_rounds=PSCoinRounds.COLLATERAL):
                ps_rounds = c['ps_rounds']
                if ps_rounds >= self.mix_rounds:
                    continue
                addr = c['address']
                if addr not in self._keypairs_cache[KP_PS_SPENDABLE]:
                    return True, prev_kp_state
                else:
                    if w.is_change(addr):
                        sign_change_cnt -= 1
                    else:
                        sign_cnt -= 1

            # check new denoms/collateral signing keys to future coins
            if sign_cnt - len(self._keypairs_cache[KP_PS_COINS]) > 0:
                return True, prev_kp_state
            if sign_change_cnt - len(self._keypairs_cache[KP_PS_CHANGE]) > 0:
                return True, prev_kp_state
        with self.keypairs_state_lock:
            self.keypairs_state = KPStates.Ready
        return False, None

    def _cache_keypairs(self, password):
        self.logger.info('Making Keyparis Cache')
        with self.keypairs_state_lock:
            self.keypairs_state = KPStates.Caching

        for cache_type in KP_ALL_TYPES:
            if cache_type not in self._keypairs_cache:
                self._keypairs_cache[cache_type] = {}

        if not self._cache_kp_spendable(password):
            return

        if not self._cache_kp_ps_spendable(password):
            return

        kp_left, kp_chg_left, small_mix_funds = \
            self.calc_need_new_keypairs_cnt()

        if not self.is_hw_ks and small_mix_funds:
            self._cache_kp_incoming(password)

        kp_left, kp_chg_left = self._cache_kp_ps_reserved(password,
                                                          kp_left, kp_chg_left)
        if kp_left is None:
            return

        kp_left, kp_chg_left = self._cache_kp_ps_change(password,
                                                        kp_left, kp_chg_left)
        if kp_left is None:
            return

        kp_left, kp_chg_left = self._cache_kp_ps_coins(password,
                                                       kp_left, kp_chg_left)
        if kp_left is None:
            return

        if self._cache_kp_tmp_reserved(password):
            kp_left, kp_chg_left = self._cache_kp_ps_coins(password,
                                                           kp_left + 1,
                                                           kp_chg_left)
            if kp_left is None:
                return

        with self.keypairs_state_lock:
            self.keypairs_state = KPStates.Ready
        self.logger.info('Keyparis Cache Done')

    def _cache_kp_incoming(self, password):
        w = self.wallet
        first_recv_index = self.first_unused_index(for_change=False,
                                                   force_main_ks=True)
        ps_incoming_cache = self._keypairs_cache[KP_INCOMING]
        cached = 0
        ri = first_recv_index
        while cached < KP_MAX_INCOMING_TXS:
            if self.state != PSStates.Mixing:
                self._cleanup_unfinished_keypairs_cache()
                return
            sequence = [0, ri]
            x_pubkey = w.keystore.get_xpubkey(*sequence)
            _, addr = xpubkey_to_address(x_pubkey)
            ri += 1
            if w.is_used(addr):
                continue
            if addr in ps_incoming_cache:
                continue
            sec = w.keystore.get_private_key(sequence, password)
            ps_incoming_cache[addr] = (x_pubkey, sec)
            cached += 1
        self.logger.info(f'Cached {cached} keys'
                         f' of {KP_INCOMING} type')
        self.postpone_notification('ps-keypairs-changes', self.wallet)

    def _cache_kp_spendable(self, password):
        '''Cache spendable regular coins keys'''
        w = self.wallet
        cached = 0
        utxos = w.get_utxos(None,
                            excluded_addresses=w.frozen_addresses,
                            mature_only=True)
        utxos = [utxo for utxo in utxos if not w.is_frozen_coin(utxo)]
        if self.is_hw_ks:
            utxos = [utxo for utxo in utxos if utxo['is_ps_ks']]
        for c in utxos:
            if self.state != PSStates.Mixing:
                self._cleanup_unfinished_keypairs_cache()
                return
            addr = c['address']
            if addr in self._keypairs_cache[KP_SPENDABLE]:
                continue
            sequence = None
            if self.ps_keystore:
                sequence = self.get_address_index(addr)
            if sequence:
                x_pubkey = self.ps_keystore.get_xpubkey(*sequence)
                sec = self.ps_keystore.get_private_key(sequence, password)
            else:
                sequence = w.get_address_index(addr)
                x_pubkey = w.keystore.get_xpubkey(*sequence)
                sec = w.keystore.get_private_key(sequence, password)
            self._keypairs_cache[KP_SPENDABLE][addr] = (x_pubkey, sec)
            cached += 1
        if cached:
            self.logger.info(f'Cached {cached} keys of {KP_SPENDABLE} type')
            self.postpone_notification('ps-keypairs-changes', self.wallet)
        return True

    def _cache_kp_ps_spendable(self, password):
        '''Cache spendable ps coins keys (existing denoms/collaterals)'''
        w = self.wallet
        cached = 0
        ps_spendable_cache = self._keypairs_cache[KP_PS_SPENDABLE]
        for c in w.get_utxos(None, min_rounds=PSCoinRounds.COLLATERAL):
            if self.state != PSStates.Mixing:
                self._cleanup_unfinished_keypairs_cache()
                return
            prev_h = c['prevout_hash']
            prev_n = c['prevout_n']
            outpoint = f'{prev_h}:{prev_n}'
            ps_denom = w.db.get_ps_denom(outpoint)
            if ps_denom and ps_denom[2] >= self.mix_rounds:
                continue
            addr = c['address']
            if self.is_hw_ks and not self.is_ps_ks(addr):
                continue  # skip denoms on hw keystore
            if addr in ps_spendable_cache:
                continue
            sequence = None
            if self.ps_keystore:
                sequence = self.get_address_index(addr)
            if sequence:
                x_pubkey = self.ps_keystore.get_xpubkey(*sequence)
                sec = self.ps_keystore.get_private_key(sequence, password)
            else:
                sequence = w.get_address_index(addr)
                x_pubkey = w.keystore.get_xpubkey(*sequence)
                sec = w.keystore.get_private_key(sequence, password)
            ps_spendable_cache[addr] = (x_pubkey, sec)
            cached += 1
        if cached:
            self.logger.info(f'Cached {cached} keys of {KP_PS_SPENDABLE} type')
            self.postpone_notification('ps-keypairs-changes', self.wallet)
        return True

    def _cache_kp_ps_reserved(self, password, sign_cnt, sign_change_cnt):
        w = self.wallet
        ps_change_cache = self._keypairs_cache[KP_PS_CHANGE]
        ps_coins_cache = self._keypairs_cache[KP_PS_COINS]
        cached = 0
        for addr, data in self.wallet.db.get_ps_reserved().items():
            if self.state != PSStates.Mixing:
                self._cleanup_unfinished_keypairs_cache()
                return None, None
            if w.is_used(addr):
                continue
            if self.is_hw_ks and not self.is_ps_ks(addr):
                continue  # skip denoms on hw keystore
            if w.is_change(addr):
                sign_change_cnt -= 1
                if addr in ps_change_cache:
                    continue
                sequence = None
                if self.ps_keystore:
                    sequence = self.get_address_index(addr)
                if sequence:
                    x_pubkey = self.ps_keystore.get_xpubkey(*sequence)
                    sec = self.ps_keystore.get_private_key(sequence, password)
                else:
                    sequence = w.get_address_index(addr)
                    x_pubkey = w.keystore.get_xpubkey(*sequence)
                    sec = w.keystore.get_private_key(sequence, password)
                ps_change_cache[addr] = (x_pubkey, sec)
                cached += 1
            else:
                sign_cnt -= 1
                if addr in ps_coins_cache:
                    continue
                sequence = None
                if self.ps_keystore:
                    sequence = self.get_address_index(addr)
                if sequence:
                    x_pubkey = self.ps_keystore.get_xpubkey(*sequence)
                    sec = self.ps_keystore.get_private_key(sequence, password)
                else:
                    sequence = w.get_address_index(addr)
                    x_pubkey = w.keystore.get_xpubkey(*sequence)
                    sec = w.keystore.get_private_key(sequence, password)
                ps_coins_cache[addr] = (x_pubkey, sec)
                cached += 1
        if cached:
            self.logger.info(f'Cached {cached} keys for ps_reserved addresses')
            self.postpone_notification('ps-keypairs-changes', self.wallet)
        return sign_cnt, sign_change_cnt

    def _cache_kp_ps_change(self, password, sign_cnt, sign_change_cnt):
        if sign_change_cnt > 0:
            w = self.wallet
            first_change_index = self.first_unused_index(for_change=True)
            ps_change_cache = self._keypairs_cache[KP_PS_CHANGE]
            cached = 0
            ci = first_change_index
            while sign_change_cnt > 0:
                if self.state != PSStates.Mixing:
                    self._cleanup_unfinished_keypairs_cache()
                    return None, None
                sequence = [1, ci]
                if self.ps_keystore:
                    x_pubkey = self.ps_keystore.get_xpubkey(*sequence)
                else:
                    x_pubkey = w.keystore.get_xpubkey(*sequence)
                _, addr = xpubkey_to_address(x_pubkey)
                ci += 1
                if w.is_used(addr):
                    continue
                sign_change_cnt -= 1
                if addr in ps_change_cache:
                    continue
                if self.ps_keystore:
                    sec = self.ps_keystore.get_private_key(sequence, password)
                else:
                    sec = w.keystore.get_private_key(sequence, password)
                ps_change_cache[addr] = (x_pubkey, sec)
                cached += 1
                if not cached % 100:
                    self.logger.info(f'Cached {cached} keys'
                                     f' of {KP_PS_CHANGE} type')
            if cached:
                self.logger.info(f'Cached {cached} keys'
                                 f' of {KP_PS_CHANGE} type')
                self.postpone_notification('ps-keypairs-changes', self.wallet)
        return sign_cnt, sign_change_cnt

    def _cache_kp_ps_coins(self, password, sign_cnt, sign_change_cnt):
        if sign_cnt > 0:
            w = self.wallet
            first_recv_index = self.first_unused_index(for_change=False)
            ps_coins_cache = self._keypairs_cache[KP_PS_COINS]
            cached = 0
            ri = first_recv_index
            while sign_cnt > 0:
                if self.state != PSStates.Mixing:
                    self._cleanup_unfinished_keypairs_cache()
                    return None, None
                sequence = [0, ri]
                if self.ps_keystore:
                    x_pubkey = self.ps_keystore.get_xpubkey(*sequence)
                else:
                    x_pubkey = w.keystore.get_xpubkey(*sequence)
                _, addr = xpubkey_to_address(x_pubkey)
                ri += 1
                if w.is_used(addr):
                    continue
                sign_cnt -= 1
                if addr in ps_coins_cache:
                    continue
                if self.ps_keystore:
                    sec = self.ps_keystore.get_private_key(sequence, password)
                else:
                    sec = w.keystore.get_private_key(sequence, password)
                ps_coins_cache[addr] = (x_pubkey, sec)
                cached += 1
                if not cached % 100:
                    self.logger.info(f'Cached {cached} keys'
                                     f' of {KP_PS_COINS} type')
            if cached:
                self.logger.info(f'Cached {cached} keys'
                                 f' of {KP_PS_COINS} type')
                self.postpone_notification('ps-keypairs-changes', self.wallet)
        return sign_cnt, sign_change_cnt

    def _cache_kp_tmp_reserved(self, password):
        w = self.wallet
        addr = self.get_tmp_reserved_address()
        if not addr:
            return False
        if self.ps_keystore:
            sequence = self.get_address_index(addr)
        if sequence:
            x_pubkey = self.ps_keystore.get_xpubkey(*sequence)
            sec = self.ps_keystore.get_private_key(sequence, password)
        else:
            sequence = w.get_address_index(addr)
            x_pubkey = w.keystore.get_xpubkey(*sequence)
            sec = w.keystore.get_private_key(sequence, password)
        spendable_cache = self._keypairs_cache[KP_SPENDABLE]
        spendable_cache[addr] = (x_pubkey, sec)
        self.logger.info(f'Cached key of {KP_SPENDABLE} type'
                         f' for tmp reserved address')
        self.postpone_notification('ps-keypairs-changes', self.wallet)
        ps_coins_cache = self._keypairs_cache[KP_PS_COINS]
        if addr in ps_coins_cache:
            ps_coins_cache.pop(addr, None)
            return True
        else:
            return False

    def _find_addrs_not_in_keypairs(self, addrs):
        addrs = set(addrs)
        keypairs_addrs = set()
        for cache_type in KP_ALL_TYPES:
            if cache_type in self._keypairs_cache:
                keypairs_addrs |= self._keypairs_cache[cache_type].keys()
        return addrs - keypairs_addrs

    def unpack_mine_input_addrs(func):
        '''Decorator to prepare tx inputs addresses'''
        def func_wrapper(self, txid, tx, tx_type):
            w = self.wallet
            inputs = []
            for i in tx.inputs():
                prev_h = i['prevout_hash']
                prev_n = i['prevout_n']
                outpoint = f'{prev_h}:{prev_n}'
                prev_tx = w.db.get_transaction(prev_h)
                if prev_tx:
                    o = prev_tx.outputs()[prev_n]
                    if w.is_mine(o.address):
                        inputs.append((outpoint, o.address))
            return func(self, txid, tx_type, inputs, tx.outputs())
        return func_wrapper

    @unpack_mine_input_addrs
    def _cleanup_spendable_keypairs(self, txid, tx_type, inputs, outputs):
        spendable_cache = self._keypairs_cache.get(KP_SPENDABLE, {})
        # first input addr used for change in new denoms/collateral txs
        first_input_addr = inputs[0][1]
        if first_input_addr in [o.address for o in outputs]:
            change_addr = first_input_addr
        else:
            change_addr = None
        # cleanup spendable keypairs excluding change address
        for outpoint, addr in inputs:
            if change_addr and change_addr == addr:
                continue
            spendable_cache.pop(addr, None)

        # move ps coins keypairs to ps spendable cache
        ps_coins_cache = self._keypairs_cache.get(KP_PS_COINS, {})
        ps_spendable_cache = self._keypairs_cache.get(KP_PS_SPENDABLE, {})
        for o in outputs:
            addr = o.address
            if addr in ps_coins_cache:
                keypair = ps_coins_cache.pop(addr, None)
                if keypair is not None:
                    ps_spendable_cache[addr] = keypair

    @unpack_mine_input_addrs
    def _cleanup_ps_keypairs(self, txid, tx_type, inputs, outputs):
        ps_spendable_cache = self._keypairs_cache.get(KP_PS_SPENDABLE, {})
        ps_coins_cache = self._keypairs_cache.get(KP_PS_COINS, {})
        ps_change_cache = self._keypairs_cache.get(KP_PS_CHANGE, {})

        # cleanup ps spendable keypairs
        for outpoint, addr in inputs:
            if addr in ps_spendable_cache:
                ps_spendable_cache.pop(addr, None)

        # move ps change, ps coins keypairs to ps spendable cache
        w = self.wallet
        for i, o in enumerate(outputs):
            addr = o.address
            if addr in ps_change_cache:
                keypair = ps_change_cache.pop(addr, None)
                if keypair is not None and tx_type == PSTxTypes.PAY_COLLATERAL:
                    ps_spendable_cache[addr] = keypair
            elif addr in ps_coins_cache:
                keypair = ps_coins_cache.pop(addr, None)
                if keypair is not None and tx_type == PSTxTypes.DENOMINATE:
                    outpoint = f'{txid}:{i}'
                    ps_denom = w.db.get_ps_denom(outpoint)
                    if ps_denom and ps_denom[2] < self.mix_rounds:
                        ps_spendable_cache[addr] = keypair

    def _cleanup_unfinished_keypairs_cache(self):
        with self.keypairs_state_lock:
            self.logger.info('Cleaning unfinished Keyparis Cache')
            self._cleanup_all_keypairs_cache()
            self.keypairs_state = KPStates.Empty
            self.logger.info('Cleaned Keyparis Cache')

    def _cleanup_all_keypairs_cache(self):
        if not self._keypairs_cache:
            return
        for cache_type in KP_ALL_TYPES:
            if cache_type not in self._keypairs_cache:
                continue
            for addr in list(self._keypairs_cache[cache_type].keys()):
                self._keypairs_cache[cache_type].pop(addr)
            self._keypairs_cache.pop(cache_type)

    def get_keypairs(self):
        keypairs = {}
        for cache_type in KP_ALL_TYPES:
            if cache_type not in self._keypairs_cache:
                continue
            for x_pubkey, sec in self._keypairs_cache[cache_type].values():
                keypairs[x_pubkey] = sec
        return keypairs

    def add_tx_inputs_info(self, tx):
        if tx.is_complete():
            return
        for txin in tx.inputs():
            self.add_input_info(txin)

    def sign_transaction(self, tx, password, mine_txins_cnt=None):
        if self._keypairs_cache:
            if mine_txins_cnt is None:
                self.add_tx_inputs_info(tx)
            keypairs = self.get_keypairs()
            signed_txins_cnt = tx.sign(keypairs)
            keypairs.clear()
            if mine_txins_cnt is None:
                mine_txins_cnt = len(tx.inputs())
            if signed_txins_cnt < mine_txins_cnt:
                self.logger.debug(f'mine txins cnt: {mine_txins_cnt},'
                                  f' signed txins cnt: {signed_txins_cnt}')
                raise SignWithKeypairsFailed('Tx signing failed')
        else:
            self.wallet.sign_transaction(tx, password)
        return tx

    # Methods related to mixing process
    def check_enough_sm_denoms(self, denoms_by_values):
        if not denoms_by_values:
            return False
        for dval in PS_DENOMS_VALS[:-1]:
            if denoms_by_values[dval] < denoms_by_values[dval*10]:
                return False
        return True

    def check_big_denoms_presented(self, denoms_by_values):
        if not denoms_by_values:
            return False
        for dval in PS_DENOMS_VALS[1:]:
            if denoms_by_values[dval] > 0:
                return True
        return False

    def get_biggest_denoms_by_min_round(self):
        w = self.wallet
        coins = w.get_utxos(None,
                            mature_only=True, confirmed_only=True,
                            consider_islocks=True, min_rounds=0)
        coins = [c for c in coins if c['value'] > MIN_DENOM_VAL]
        return sorted(coins, key=lambda x: (x['ps_rounds'], -x['value']))

    def check_protx_info_completeness(self):
        if not self.network:
            return False
        mn_list = self.network.mn_list
        if mn_list.protx_info_completeness < 0.75:
            return False
        else:
            return True

    def check_llmq_ready(self):
        if not self.network:
            return False
        mn_list = self.network.mn_list
        return mn_list.llmq_ready

    def start_mixing(self, password, nowait=True):
        w = self.wallet
        msg = None
        if w.is_watching_only():
            msg = self.WATCHING_ONLY_MSG, 'err'
        elif self.all_mixed:
            msg = self.ALL_MIXED_MSG, 'inf'
        elif not self.network or not self.network.is_connected():
            msg = self.NO_NETWORK_MSG, 'err'
        elif not self.axe_net.run_axe_net:
            msg = self.NO_AXE_NET_MSG, 'err'
        if msg:
            msg, inf = msg
            self.logger.info(f'Can not start PrivateSend Mixing: {msg}')
            self.trigger_callback('ps-state-changes', w, msg, inf)
            return

        coro = self.find_untracked_ps_txs()
        asyncio.run_coroutine_threadsafe(coro, self.loop).result()

        with self.state_lock:
            if self.state == PSStates.Ready:
                self.state = PSStates.StartMixing
            elif self.state in [PSStates.Unsupported, PSStates.Disabled]:
                msg = self.NOT_ENABLED_MSG
            elif self.state == PSStates.Initializing:
                msg = self.INITIALIZING_MSG
            elif self.state in self.mixing_running_states:
                msg = self.MIXING_ALREADY_RUNNING_MSG
            elif self.state == PSStates.FindingUntracked:
                msg = self.FIND_UNTRACKED_RUN_MSG
            elif self.state == PSStates.FindingUntracked:
                msg = self.ERRORED_MSG
            else:
                msg = self.UNKNOWN_STATE_MSG.format(self.state)
        if msg:
            self.trigger_callback('ps-state-changes', w, msg, None)
            self.logger.info(f'Can not start PrivateSend Mixing: {msg}')
            return
        else:
            self.trigger_callback('ps-state-changes', w, None, None)

        fut = asyncio.run_coroutine_threadsafe(self._start_mixing(password),
                                               self.loop)
        if nowait:
            return
        try:
            fut.result(timeout=2)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            pass

    async def _start_mixing(self, password):
        if not self.enabled or not self.network:
            return

        assert not self.main_taskgroup
        self._not_enough_funds = False
        self.main_taskgroup = main_taskgroup = SilentTaskGroup()
        self.logger.info('Starting PrivateSend Mixing')

        async def main():
            try:
                async with main_taskgroup as group:
                    if (self.w_type == 'standard'
                            and self.is_hw_ks):
                        await group.spawn(self._prepare_funds_from_hw_wallet())
                    await group.spawn(self._make_keypairs_cache(password))
                    await group.spawn(self._check_not_enough_funds())
                    await group.spawn(self._check_all_mixed())
                    await group.spawn(self._maintain_pay_collateral_tx())
                    await group.spawn(self._maintain_collateral_amount())
                    await group.spawn(self._maintain_denoms())
                    await group.spawn(self._mix_denoms())
            except Exception as e:
                self.logger.info(f'error starting mixing: {str(e)}')
                raise e
        asyncio.run_coroutine_threadsafe(main(), self.loop)
        with self.state_lock:
            self.state = PSStates.Mixing
        self.last_mix_start_time = time.time()
        self.logger.info('Started PrivateSend Mixing')
        w = self.wallet
        self.trigger_callback('ps-state-changes', w, None, None)

    async def stop_mixing_from_async_thread(self, msg, msg_type=None):
        await self.loop.run_in_executor(None, self.stop_mixing, msg, msg_type)

    def stop_mixing(self, msg=None, msg_type=None, nowait=True):
        w = self.wallet
        with self.state_lock:
            if self.state == PSStates.Mixing:
                self.state = PSStates.StopMixing
            elif self.state == PSStates.StopMixing:
                return
            else:
                msg = self.MIXING_NOT_RUNNING_MSG
                self.trigger_callback('ps-state-changes', w, msg, 'inf')
                self.logger.info(f'Can not stop PrivateSend Mixing: {msg}')
                return
        if msg:
            self.logger.info(f'Stopping PrivateSend Mixing: {msg}')
            if not msg_type or not msg_type.startswith('inf'):
                stopped_prefix = _('PrivateSend mixing is stopping!')
                msg = f'{stopped_prefix}\n\n{msg}'
            self.trigger_callback('ps-state-changes', w, msg, msg_type)
        else:
            self.logger.info('Stopping PrivateSend Mixing')
            self.trigger_callback('ps-state-changes', w, None, None)

        self.last_mix_stop_time = time.time()  # write early if later time lost
        fut = asyncio.run_coroutine_threadsafe(self._stop_mixing(), self.loop)
        if nowait:
            return
        try:
            fut.result(timeout=PRIVATESEND_SESSION_MSG_TIMEOUT+5)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            pass

    @log_exceptions
    async def _stop_mixing(self):
        if self.keypairs_state == KPStates.Caching:
            self.logger.info(f'Waiting for keypairs caching to finish')
            while self.keypairs_state == KPStates.Caching:
                await asyncio.sleep(0.5)
        if self.main_taskgroup:
            sess_cnt = len(self.mix_sessions)
            if sess_cnt > 0:
                self.logger.info(f'Waiting for {sess_cnt}'
                                 f' mixing sessions to finish')
                while sess_cnt > 0:
                    await asyncio.sleep(0.5)
                    sess_cnt = len(self.mix_sessions)
            try:
                await asyncio.wait_for(self.main_taskgroup.cancel_remaining(),
                                       timeout=2)
            except (asyncio.TimeoutError, asyncio.CancelledError) as e:
                self.logger.debug(f'Exception during main_taskgroup'
                                  f' cancellation: {repr(e)}')
            self.main_taskgroup = None
        with self.keypairs_state_lock:
            if self.keypairs_state == KPStates.Ready:
                self.logger.info(f'Mark keypairs as unused')
                self.keypairs_state = KPStates.Unused
        self.logger.info('Stopped PrivateSend Mixing')
        self.last_mix_stop_time = time.time()
        with self.state_lock:
            self.state = PSStates.Ready
        w = self.wallet
        self.trigger_callback('ps-state-changes', w, None, None)

    async def _check_all_mixed(self):
        while not self.main_taskgroup.closed():
            await asyncio.sleep(10)
            if self.all_mixed:
                await self.stop_mixing_from_async_thread(self.ALL_MIXED_MSG,
                                                         'inf')

    async def _check_not_enough_funds(self):
        while not self.main_taskgroup.closed():
            if self._not_enough_funds:
                await asyncio.sleep(30)
                self._not_enough_funds = False
            await asyncio.sleep(5)

    async def _maintain_pay_collateral_tx(self):
        kp_wait_state = KPStates.Ready if self.need_password() else None

        while not self.main_taskgroup.closed():
            wfl = self.pay_collateral_wfl
            if wfl:
                if not wfl.completed or not wfl.tx_order:
                    await self.cleanup_pay_collateral_wfl()
            elif self.ps_collateral_cnt > 0:
                if kp_wait_state and self.keypairs_state != kp_wait_state:
                    self.logger.info(f'Pay collateral workflow waiting'
                                     f' for keypairs generation')
                    await asyncio.sleep(5)
                    continue
                if not self.get_confirmed_ps_collateral_data():
                    await asyncio.sleep(5)
                    continue
                await self.prepare_pay_collateral_wfl()
            await asyncio.sleep(0.25)

    async def broadcast_new_denoms_new_collateral_wfls(self):
        w = self.wallet
        while True:
            if self.enabled:
                wfl = self.new_denoms_wfl
                if wfl and wfl.completed and wfl.next_to_send(w):
                    await self.broadcast_new_denoms_wfl()
                await asyncio.sleep(0.25)
                wfl = self.new_collateral_wfl
                if wfl and wfl.completed and wfl.next_to_send(w):
                    await self.broadcast_new_collateral_wfl()
                await asyncio.sleep(0.25)
            else:
                await asyncio.sleep(1)

    async def _maintain_collateral_amount(self):
        w = self.wallet
        kp_wait_state = KPStates.Ready if self.need_password() else None

        while not self.main_taskgroup.closed():
            wfl = self.new_collateral_wfl
            if wfl:
                if not wfl.completed or not wfl.tx_order:
                    await self.cleanup_new_collateral_wfl()
            elif (not self._not_enough_funds
                    and not self.ps_collateral_cnt
                    and not self.calc_need_denoms_amounts(use_cache=True)):
                coins = w.get_utxos(None,
                                    excluded_addresses=w.frozen_addresses)
                coins = [c for c in coins if not w.is_frozen_coin(c)]
                if not coins:
                    await asyncio.sleep(5)
                    continue
                if not self.check_llmq_ready():
                    self.logger.info(_('New collateral workflow: {}')
                                     .format(self.LLMQ_DATA_NOT_READY))
                    await asyncio.sleep(5)
                    continue
                elif kp_wait_state and self.keypairs_state != kp_wait_state:
                    self.logger.info(f'New collateral workflow waiting'
                                     f' for keypairs generation')
                    await asyncio.sleep(5)
                    continue
                await self.create_new_collateral_wfl()
            await asyncio.sleep(0.25)

    async def _maintain_denoms(self):
        w = self.wallet
        kp_wait_state = KPStates.Ready if self.need_password() else None

        while not self.main_taskgroup.closed():
            wfl = self.new_denoms_wfl
            if wfl:
                if not wfl.completed or not wfl.tx_order:
                    await self.cleanup_new_denoms_wfl()
            elif (not self._not_enough_funds
                    and self.calc_need_denoms_amounts(use_cache=True)):
                coins = w.get_utxos(None,
                                    excluded_addresses=w.frozen_addresses)
                coins = [c for c in coins if not w.is_frozen_coin(c)]
                if not coins:
                    await asyncio.sleep(5)
                    continue
                if not self.check_llmq_ready():
                    self.logger.info(_('New denoms workflow: {}')
                                     .format(self.LLMQ_DATA_NOT_READY))
                    await asyncio.sleep(5)
                    continue
                elif kp_wait_state and self.keypairs_state != kp_wait_state:
                    self.logger.info(f'New denoms workflow waiting'
                                     f' for keypairs generation')
                    await asyncio.sleep(5)
                    continue
                await self.create_new_denoms_wfl()
            await asyncio.sleep(0.25)

    async def _mix_denoms(self):
        kp_wait_state = KPStates.Ready if self.need_password() else None

        def _cleanup():
            for uuid in self.denominate_wfl_list:
                wfl = self.get_denominate_wfl(uuid)
                if wfl and not wfl.completed:
                    self._cleanup_denominate_wfl(wfl)
        await self.loop.run_in_executor(None, _cleanup)

        main_taskgroup = self.main_taskgroup
        while not main_taskgroup.closed():
            if (self._denoms_to_mix_cache
                    and self.pay_collateral_wfl
                    and self.active_denominate_wfl_cnt < self.max_sessions):
                if not self.check_llmq_ready():
                    self.logger.info(_('Denominate workflow: {}')
                                     .format(self.LLMQ_DATA_NOT_READY))
                    await asyncio.sleep(5)
                    continue
                elif not self.check_protx_info_completeness():
                    self.logger.info(_('Denominate workflow: {}')
                                     .format(self.MNS_DATA_NOT_READY))
                    await asyncio.sleep(5)
                    continue
                elif kp_wait_state and self.keypairs_state != kp_wait_state:
                    self.logger.info(f'Denominate workflow waiting'
                                     f' for keypairs generation')
                    await asyncio.sleep(5)
                    continue
                if self.state == PSStates.Mixing:
                    await main_taskgroup.spawn(self.start_denominate_wfl())
            await asyncio.sleep(0.25)

    def check_min_rounds(self, coins, min_rounds):
        for c in coins:
            ps_rounds = c['ps_rounds']
            if ps_rounds is None or ps_rounds < min_rounds:
                raise PSMinRoundsCheckFailed(f'Check for mininum {min_rounds}'
                                             f' PrivateSend mixing rounds'
                                             f' failed')

    async def start_mix_session(self, denom_value, dsq, wfl_lid):
        n_denom = PS_DENOMS_DICT[denom_value]
        sess = PSMixSession(self, denom_value, n_denom, dsq, wfl_lid)
        peer_str = sess.peer_str
        async with self.mix_sessions_lock:
            if peer_str in self.mix_sessions:
                raise Exception(f'Session with {peer_str} already exists')
            await sess.run_peer()
            self.mix_sessions[peer_str] = sess
            return sess

    async def stop_mix_session(self, peer_str):
        async with self.mix_sessions_lock:
            sess = self.mix_sessions.pop(peer_str)
            if not sess:
                self.logger.debug(f'Peer {peer_str} not found in mix_session')
                return
            sess.close_peer()
            return sess

    def reserve_addresses(self, addrs_count, for_change=False,
                          data=None, force_main_ks=False, tmp=False):
        '''Reserve addresses for PS use or if tmp is True reserve one
           receiving address temporarily to not be reserved for ps
           during funds are sent to it'''
        if tmp and addrs_count > 1:
            raise Exception('tmp can be used only for one address reservation')
        if tmp and for_change:
            raise Exception('tmp param can not be used with for_change param')
        if tmp and data is not None:
            raise Exception('tmp param can not be used with data param')

        result = []
        w = self.wallet
        ps_ks = self.ps_keystore and not force_main_ks
        with w.lock:
            while len(result) < addrs_count:
                if for_change:
                    unused = (self.get_unused_addresses(for_change) if ps_ks
                              else w.calc_unused_change_addresses())
                else:
                    unused = (self.get_unused_addresses() if ps_ks
                              else w.get_unused_addresses())
                if unused:
                    addr = unused[0]
                else:
                    addr = (self.create_new_address(for_change) if ps_ks
                            else w.create_new_address(for_change))
                if tmp:
                    self.set_tmp_reserved_address(addr)
                else:
                    self.add_ps_reserved(addr, data)
                result.append(addr)
        return result

    def first_unused_index(self, for_change=False, force_main_ks=False):
        w = self.wallet
        ps_ks = self.ps_keystore and not force_main_ks
        with w.lock:
            if for_change:
                unused = (self.get_unused_addresses(for_change) if ps_ks
                          else w.calc_unused_change_addresses())
            else:
                unused = (self.get_unused_addresses() if ps_ks
                          else w.get_unused_addresses())
            if unused:
                return (self.get_address_index(unused[0])[1] if ps_ks
                        else w.get_address_index(unused[0])[1])
            # no unused, return first index beyond last address in db
            if for_change:
                return w.db.num_change_addresses(ps_ks=ps_ks)
            else:
                return w.db.num_receiving_addresses(ps_ks=ps_ks)

    def add_spent_addrs(self, addrs):
        w = self.wallet
        unspent = w.db.get_unspent_ps_addresses()
        for addr in addrs:
            if addr in unspent:
                continue
            self.spent_addrs.add(addr)

    def restore_spent_addrs(self, addrs):
        for addr in addrs:
            self.spent_addrs.remove(addr)
            self.subscribe_spent_addr(addr)

    def subscribe_spent_addr(self, addr):
        w = self.wallet
        if addr in self.unsubscribed_addrs:
            self.unsubscribed_addrs.remove(addr)
            if w.synchronizer:
                self.logger.debug(f'Add {addr} to synchronizer')
                w.synchronizer.add(addr)

    def unsubscribe_spent_addr(self, addr, hist):
        if (self.subscribe_spent
                or addr not in self.spent_addrs
                or addr in self.unsubscribed_addrs
                or not hist):
            return
        w = self.wallet
        local_height = w.get_local_height()
        for hist_item in hist:
            txid = hist_item[0]
            verified_tx = w.db.verified_tx.get(txid)
            if not verified_tx:
                return
            height = verified_tx[0]
            conf = local_height - height + 1
            if conf < 6:
                return
        self.unsubscribed_addrs.add(addr)
        if w.synchronizer:
            self.logger.debug(f'Remove {addr} from synchronizer')
            w.synchronizer.remove_addr(addr)

    def calc_need_denoms_amounts(self, coins=None, use_cache=False,
                                 on_keep_amount=False):
        w = self.wallet
        fee_per_kb = self.config.fee_per_kb()
        if fee_per_kb is None:
            raise NoDynamicFeeEstimates()

        if coins is not None:  # calc on coins selected from GUI
            return self._calc_denoms_amounts_from_coins(coins, fee_per_kb)

        if use_cache:
            old_denoms_val = self._ps_denoms_amount_cache
        else:
            old_denoms_val = sum(self.wallet.get_balance(include_ps=False,
                                                         min_rounds=0))

        need_val = to_haks(self.keep_amount) + CREATE_COLLATERAL_VAL
        if need_val < old_denoms_val:  # already have need value of denoms
            return []

        # calc spendable coins val
        coins = w.get_utxos(None, excluded_addresses=w.frozen_addresses,
                            mature_only=True)
        coins = [c for c in coins if not w.is_frozen_coin(c)]
        coins_val = sum([c['value'] for c in coins])
        if coins_val < MIN_DENOM_VAL and not on_keep_amount:
            return []  # no coins to create denoms

        in_cnt = len(coins)
        approx_val = need_val - old_denoms_val
        outputs_amounts = self.find_denoms_approx(approx_val)
        total_need_val, outputs_amounts = \
            self._calc_total_need_val(in_cnt, outputs_amounts, fee_per_kb)
        if on_keep_amount or coins_val >= total_need_val:
            return outputs_amounts

        # not enough funds to mix keep amount, approx amount that can be mixed
        approx_val = coins_val
        while True:
            if approx_val < CREATE_COLLATERAL_VAL:
                return []
            outputs_amounts = self.find_denoms_approx(approx_val)
            total_need_val, outputs_amounts = \
                self._calc_total_need_val(in_cnt, outputs_amounts, fee_per_kb)
            if coins_val >= total_need_val:
                return outputs_amounts
            else:
                approx_val -= MIN_DENOM_VAL

    def _calc_total_need_val(self, txin_cnt, outputs_amounts, fee_per_kb):
        res_outputs_amounts = copy.deepcopy(outputs_amounts)
        new_denoms_val = sum([sum(a) for a in res_outputs_amounts])
        new_denoms_cnt = sum([len(a) for a in res_outputs_amounts])

        # calc future new collaterals count and value
        new_collateral_cnt = self.calc_need_sign_cnt(new_denoms_cnt)[2]
        if not self.ps_collateral_cnt and res_outputs_amounts:
            new_collateral_cnt -= 1
            res_outputs_amounts[0].insert(0, CREATE_COLLATERAL_VAL)
        new_collaterals_val = CREATE_COLLATERAL_VAL * new_collateral_cnt

        # calc new denoms fee
        new_denoms_fee = 0
        for i, amounts in enumerate(res_outputs_amounts):
            if i == 0:  # use all coins as inputs, add change output
                new_denoms_fee += calc_tx_fee(txin_cnt, len(amounts) + 1,
                                              fee_per_kb, max_size=True)
            else:  # use change from prev txs as input
                new_denoms_fee += calc_tx_fee(1, len(amounts) + 1,
                                              fee_per_kb, max_size=True)

        # calc future new collaterals fee
        new_collateral_fee = calc_tx_fee(1, 2, fee_per_kb, max_size=True)
        new_collaterals_fee = new_collateral_cnt * new_collateral_fee

        # have coins enough to create new denoms and future new collaterals
        total_need_val = (new_denoms_val + new_denoms_fee +
                          new_collaterals_val + new_collaterals_fee)
        return total_need_val, res_outputs_amounts

    def _calc_denoms_amounts_fee(self, coins_cnt, denoms_amounts, fee_per_kb):
        txs_fee = 0
        tx_cnt = len(denoms_amounts)
        for i in range(tx_cnt):
            amounts = denoms_amounts[i]
            if i == 0:
                # inputs: coins
                # outputs: denoms + new denom + collateral + change
                out_cnt = len(amounts) + 3
                txs_fee += calc_tx_fee(coins_cnt, out_cnt,
                                       fee_per_kb, max_size=True)
            elif i == tx_cnt - 1:
                # inputs: one change amount
                # outputs: denoms + new denom
                out_cnt = len(amounts) + 1
                txs_fee += calc_tx_fee(1, out_cnt,
                                       fee_per_kb, max_size=True)
            else:
                # inputs: one change amount
                # outputs: is denoms + denom + change
                out_cnt = len(amounts) + 2
                txs_fee += calc_tx_fee(1, out_cnt,
                                       fee_per_kb, max_size=True)

        return txs_fee

    def _calc_denoms_amounts_from_coins(self, coins, fee_per_kb):
        coins_val = sum([c['value'] for c in coins])
        coins_cnt = len(coins)
        denoms_amounts = []
        denoms_val = 0
        denoms_cnt = 0
        approx_found = False

        while not approx_found:
            cur_approx_amounts = []

            for dval in PS_DENOMS_VALS:
                for dn in range(11):  # max 11 values of same denom
                    all_denoms_amounts = denoms_amounts + [cur_approx_amounts]
                    txs_fee = self._calc_denoms_amounts_fee(coins_cnt,
                                                            all_denoms_amounts,
                                                            fee_per_kb)
                    min_total = denoms_val + dval + COLLATERAL_VAL + txs_fee
                    max_total = min_total - COLLATERAL_VAL + MAX_COLLATERAL_VAL
                    if min_total < coins_val:
                        denoms_val += dval
                        denoms_cnt += 1
                        cur_approx_amounts.append(dval)
                        if max_total > coins_val:
                            approx_found = True
                            break
                    else:
                        if dval == MIN_DENOM_VAL:
                            approx_found = True
                        break
                if approx_found:
                    break
            if cur_approx_amounts:
                denoms_amounts.append(cur_approx_amounts)
        if denoms_amounts:
            for collateral_val in CREATE_COLLATERAL_VALS[::-1]:
                if coins_val - denoms_val - collateral_val > txs_fee:
                    denoms_amounts[0].insert(0, collateral_val)
                    break
            real_fee = coins_val - denoms_val - collateral_val
            assert real_fee - txs_fee < COLLATERAL_VAL, 'too high fee'
        return denoms_amounts

    def find_denoms_approx(self, need_amount):
        if need_amount < COLLATERAL_VAL:
            return []

        denoms_amounts = []
        denoms_total = 0
        approx_found = False

        while not approx_found:
            cur_approx_amounts = []

            for dval in PS_DENOMS_VALS:
                for dn in range(11):  # max 11 values of same denom
                    if denoms_total + dval > need_amount:
                        if dval == MIN_DENOM_VAL:
                            approx_found = True
                            denoms_total += dval
                            cur_approx_amounts.append(dval)
                        break
                    else:
                        denoms_total += dval
                        cur_approx_amounts.append(dval)
                if approx_found:
                    break

            denoms_amounts.append(cur_approx_amounts)
        return denoms_amounts

    def denoms_to_mix(self, mix_rounds=None, denom_value=None):
        res = {}
        w = self.wallet
        if mix_rounds is not None:
            denoms = w.db.get_ps_denoms(min_rounds=mix_rounds,
                                        max_rounds=mix_rounds)
        else:
            denoms = w.db.get_ps_denoms(max_rounds=self.mix_rounds-1)
        for outpoint, denom in denoms.items():
            if denom_value is not None and denom_value != denom[1]:
                continue
            if not w.db.get_ps_spending_denom(outpoint):
                res.update({outpoint: denom})
        return res

    @property
    def min_new_denoms_from_coins_val(self):
        if not self.config:
            raise Exception('self.config is not set')
        fee_per_kb = self.config.fee_per_kb()
        # no change, one coin input, one 100001 out and 10000 collateral out
        new_denoms_fee = calc_tx_fee(1, 2, fee_per_kb, max_size=True)
        return new_denoms_fee + MIN_DENOM_VAL + COLLATERAL_VAL

    @property
    def min_new_collateral_from_coins_val(self):
        if not self.config:
            raise Exception('self.config is not set')
        fee_per_kb = self.config.fee_per_kb()
        # no change, one coin input, one 10000 output
        new_collateral_fee = calc_tx_fee(1, 1, fee_per_kb, max_size=True)
        return new_collateral_fee + COLLATERAL_VAL

    # Methods related to mixing on hw wallets
    def prepare_funds_from_hw_wallet(self):
        try:
            w = self.wallet
            fee_per_kb = self.config.fee_per_kb()
            # calc amount need to be sent to ps_keystore
            coins = w.get_utxos(None, excluded_addresses=w.frozen_addresses,
                                mature_only=True)
            coins = [c for c in coins if not w.is_frozen_coin(c)]
            coins_val = sum([c['value'] for c in coins])
            main_ks_coins = [c for c in coins if not c['is_ps_ks']]
            main_ks_coins_val = sum([c['value'] for c in main_ks_coins])
            ps_ks_coins_val = sum([c['value'] for c in coins if c['is_ps_ks']])

            outputs_amounts = self.calc_need_denoms_amounts()
            in_cnt = len(coins)
            total_need_val, outputs_amounts = \
                self._calc_total_need_val(in_cnt, outputs_amounts, fee_per_kb)
            transfer_tx_fee = calc_tx_fee(len(main_ks_coins), 1,
                                          fee_per_kb, max_size=True)
            if coins_val < total_need_val + transfer_tx_fee:  # transfer all
                need_transfer_val = main_ks_coins_val - transfer_tx_fee
            else:
                need_transfer_val = total_need_val - ps_ks_coins_val
            if need_transfer_val < PS_DENOMS_VALS[0]:
                return
            # prepare and send transaction to ps_keystore unused address
            unused = self.reserve_addresses(1, tmp=True)
            ps_ks_oaddr = unused[0]
            outputs = [TxOutput(TYPE_ADDRESS, ps_ks_oaddr, need_transfer_val)]
            tx = w.make_unsigned_transaction(main_ks_coins, outputs,
                                             self.config)
            tx = self.wallet.sign_transaction(tx, None)
            if tx and tx.is_complete():
                return tx
        except BaseException as e:
            self.logger.wfl_err(f'prepare_funds_from_hw_wallet: {str(e)}')

    async def _prepare_funds_from_hw_wallet(self):
        while True:
            tx = self.prepare_funds_from_hw_wallet()
            if tx:
                await self.broadcast_transaction(tx)
                self.logger.info(f'Broadcasted PS Keystore'
                                 f' fund tx {tx.txid()}')
            await asyncio.sleep(30)

    def prepare_funds_from_ps_keystore(self, password):
        w = self.wallet
        coins_ps = w.get_utxos(None, mature_only=True,
                               min_rounds=PSCoinRounds.MINUSINF)
        ps_ks_coins_ps = [c for c in coins_ps if c['is_ps_ks']]
        coins_regular = w.get_utxos(None, mature_only=True)
        ps_ks_coins_regular = [c for c in coins_regular if c['is_ps_ks']]
        if not ps_ks_coins_ps and not ps_ks_coins_regular:
            raise NotEnoughFunds('No funds found on PS Keystore')
        unused = w.get_unused_addresses()
        if not unused:
            raise NotEnoughFunds('No unused addresses to prepare transaction')
        res = []
        outputs_ps = [TxOutput(TYPE_ADDRESS, unused[0], '!')]
        outputs_regular = [TxOutput(TYPE_ADDRESS, unused[1], '!')]
        if ps_ks_coins_ps:
            tx = w.make_unsigned_transaction(ps_ks_coins_ps, outputs_ps,
                                             self.config)
            tx = self.wallet.sign_transaction(tx, password)
            if tx and tx.is_complete():
                res.append(tx)
            else:
                raise Exception('Sign transaction failed')
        if ps_ks_coins_regular:
            tx = w.make_unsigned_transaction(ps_ks_coins_regular,
                                             outputs_regular, self.config)
            tx = self.wallet.sign_transaction(tx, password)
            if tx and tx.is_complete():
                res.append(tx)
            else:
                raise Exception('Sign transaction failed')
        return res

    def check_funds_on_ps_keystore(self):
        w = self.wallet
        coins = w.get_utxos(None, excluded_addresses=w.frozen_addresses,
                            mature_only=True, include_ps=True)
        coins = [c for c in coins if not w.is_frozen_coin(c)]
        ps_ks_coins = [c for c in coins if c['is_ps_ks']]
        if ps_ks_coins:
            return True
        else:
            return False

    # Workflow methods for pay collateral transaction
    def get_confirmed_ps_collateral_data(self):
        w = self.wallet
        for outpoint, ps_collateral in w.db.get_ps_collaterals().items():
            addr, value = ps_collateral
            utxos = w.get_utxos([addr], min_rounds=PSCoinRounds.COLLATERAL,
                                confirmed_only=True, consider_islocks=True)
            inputs = []
            for utxo in utxos:
                prev_h = utxo['prevout_hash']
                prev_n = utxo['prevout_n']
                if f'{prev_h}:{prev_n}' != outpoint:
                    continue
                self.add_input_info(utxo)
                inputs.append(utxo)
            if inputs:
                return outpoint, value, inputs
            else:
                self.logger.wfl_err(f'ps_collateral outpoint {outpoint}'
                                    f' is not confirmed')

    async def prepare_pay_collateral_wfl(self):
        try:
            _prepare = self._prepare_pay_collateral_tx
            res = await self.loop.run_in_executor(None, _prepare)
            if res:
                txid, wfl = res
                self.logger.wfl_ok(f'Completed pay collateral workflow with'
                                   f' tx: {txid}, workflow: {wfl.lid}')
                self.wallet.storage.write()
        except Exception as e:
            wfl = self.pay_collateral_wfl
            if wfl:
                self.logger.wfl_err(f'Error creating pay collateral tx:'
                                    f' {str(e)}, workflow: {wfl.lid}')
                await self.cleanup_pay_collateral_wfl(force=True)
            else:
                self.logger.wfl_err(f'Error during creation of pay collateral'
                                    f' worfklow: {str(e)}')
            type_e = type(e)
            msg = None
            if type_e == NoDynamicFeeEstimates:
                msg = self.NO_DYNAMIC_FEE_MSG.format(str(e))
            elif type_e == NotFoundInKeypairs:
                msg = self.NOT_FOUND_KEYS_MSG
            elif type_e == SignWithKeypairsFailed:
                msg = self.SIGN_WIHT_KP_FAILED_MSG
            if msg:
                await self.stop_mixing_from_async_thread(msg)

    def _prepare_pay_collateral_tx(self):
        with self.pay_collateral_wfl_lock:
            if self.pay_collateral_wfl:
                return
            uuid = str(uuid4())
            wfl = PSTxWorkflow(uuid=uuid)
            self.set_pay_collateral_wfl(wfl)
            self.logger.info(f'Started up pay collateral workflow: {wfl.lid}')

        res = self.get_confirmed_ps_collateral_data()
        if not res:
            raise Exception('No confirmed ps_collateral found')
        outpoint, value, inputs = res

        # check input addresses is in keypairs if keypairs cache available
        if self._keypairs_cache:
            input_addrs = [utxo['address'] for utxo in inputs]
            not_found_addrs = self._find_addrs_not_in_keypairs(input_addrs)
            if not_found_addrs:
                not_found_addrs = ', '.join(list(not_found_addrs))
                raise NotFoundInKeypairs(f'Input addresses is not found'
                                         f' in the keypairs cache:'
                                         f' {not_found_addrs}')

        self.add_ps_spending_collateral(outpoint, wfl.uuid)
        if value >= COLLATERAL_VAL*2:
            ovalue = value - COLLATERAL_VAL
            output_addr = None
            for addr, data in self.wallet.db.get_ps_reserved().items():
                if data == outpoint:
                    output_addr = addr
                    break
            if not output_addr:
                reserved = self.reserve_addresses(1, for_change=True,
                                                  data=outpoint)
                output_addr = reserved[0]
            outputs = [TxOutput(TYPE_ADDRESS, output_addr, ovalue)]
        else:
            # OP_RETURN as ouptut script
            outputs = [TxOutput(TYPE_SCRIPT, '6a', 0)]

        tx = Transaction.from_io(inputs[:], outputs[:], locktime=0)
        tx.inputs()[0]['sequence'] = 0xffffffff
        tx = self.sign_transaction(tx, None)
        txid = tx.txid()
        raw_tx = tx.serialize_to_network()
        tx_type = PSTxTypes.PAY_COLLATERAL
        wfl.add_tx(txid=txid, raw_tx=raw_tx, tx_type=tx_type)
        wfl.completed = True
        with self.pay_collateral_wfl_lock:
            saved = self.pay_collateral_wfl
            if not saved:
                raise Exception('pay_collateral_wfl not found')
            if saved.uuid != wfl.uuid:
                raise Exception('pay_collateral_wfl differs from original')
            self.set_pay_collateral_wfl(wfl)
        return txid, wfl

    async def cleanup_pay_collateral_wfl(self, force=False):
        _cleanup = self._cleanup_pay_collateral_wfl
        changed = await self.loop.run_in_executor(None, _cleanup, force)
        if changed:
            self.wallet.storage.write()

    def _cleanup_pay_collateral_wfl(self, force=False):
        with self.pay_collateral_wfl_lock:
            wfl = self.pay_collateral_wfl
            if not wfl or wfl.completed and wfl.tx_order and not force:
                return
        w = self.wallet
        if wfl.tx_order:
            for txid in wfl.tx_order[::-1]:  # use reversed tx_order
                if w.db.get_transaction(txid):
                    w.remove_transaction(txid)
                else:
                    self._cleanup_pay_collateral_wfl_tx_data(txid)
        else:
            self._cleanup_pay_collateral_wfl_tx_data()
        return True

    def _cleanup_pay_collateral_wfl_tx_data(self, txid=None):
        with self.pay_collateral_wfl_lock:
            wfl = self.pay_collateral_wfl
            if not wfl:
                return
            if txid:
                tx_data = wfl.pop_tx(txid)
                if tx_data:
                    self.set_pay_collateral_wfl(wfl)
                    self.logger.info(f'Cleaned up pay collateral tx:'
                                     f' {txid}, workflow: {wfl.lid}')
        if wfl.tx_order:
            return

        w = self.wallet
        for outpoint, uuid in list(w.db.get_ps_spending_collaterals().items()):
            if uuid != wfl.uuid:
                continue
            with self.collateral_lock:
                self.pop_ps_spending_collateral(outpoint)

        with self.pay_collateral_wfl_lock:
            saved = self.pay_collateral_wfl
            if saved and saved.uuid == wfl.uuid:
                self.clear_pay_collateral_wfl()
        self.logger.info(f'Cleaned up pay collateral workflow: {wfl.lid}')

    def _search_pay_collateral_wfl(self, txid, tx):
        err = self._check_pay_collateral_tx_err(txid, tx, full_check=False)
        if not err:
            wfl = self.pay_collateral_wfl
            if wfl and wfl.tx_order and txid in wfl.tx_order:
                return wfl

    def _check_on_pay_collateral_wfl(self, txid, tx):
        wfl = self._search_pay_collateral_wfl(txid, tx)
        err = self._check_pay_collateral_tx_err(txid, tx)
        if not err:
            return True
        if wfl:
            raise AddPSDataError(f'{err}')
        else:
            return False

    def _process_by_pay_collateral_wfl(self, txid, tx):
        wfl = self._search_pay_collateral_wfl(txid, tx)
        if not wfl:
            return

        with self.pay_collateral_wfl_lock:
            saved = self.pay_collateral_wfl
            if not saved or saved.uuid != wfl.uuid:
                return
            tx_data = wfl.pop_tx(txid)
            if tx_data:
                self.set_pay_collateral_wfl(wfl)
                self.logger.wfl_done(f'Processed tx: {txid} from pay'
                                     f' collateral workflow: {wfl.lid}')
        if wfl.tx_order:
            return

        w = self.wallet
        for outpoint, uuid in list(w.db.get_ps_spending_collaterals().items()):
            if uuid != wfl.uuid:
                continue
            with self.collateral_lock:
                self.pop_ps_spending_collateral(outpoint)

        with self.pay_collateral_wfl_lock:
            saved = self.pay_collateral_wfl
            if saved and saved.uuid == wfl.uuid:
                self.clear_pay_collateral_wfl()
        self.logger.wfl_done(f'Finished processing of pay collateral'
                             f' workflow: {wfl.lid}')

    def get_pay_collateral_tx(self):
        wfl = self.pay_collateral_wfl
        if not wfl or not wfl.tx_order:
            return
        txid = wfl.tx_order[0]
        tx_data = wfl.tx_data.get(txid)
        if not tx_data:
            return
        return tx_data.raw_tx

    # Workflow methods for new collateral transaction
    def new_collateral_from_coins_info(self, coins):
        if not coins or len(coins) > 1:
            return
        coins_val = sum([c['value'] for c in coins])
        if (coins_val >= self.min_new_denoms_from_coins_val
                or coins_val < self.min_new_collateral_from_coins_val):
            return
        fee_per_kb = self.config.fee_per_kb()
        for collateral_val in CREATE_COLLATERAL_VALS[::-1]:
            new_collateral_fee = calc_tx_fee(1, 1, fee_per_kb, max_size=True)
            if coins_val - new_collateral_fee >= collateral_val:
                tx_type = SPEC_TX_NAMES[PSTxTypes.NEW_COLLATERAL]
                info = _('Transactions type: {}').format(tx_type)
                info += '\n'
                info += _('Count of transactions: {}').format(1)
                info += '\n'
                info += _('Total sent amount: {}').format(coins_val)
                info += '\n'
                info += _('Total output amount: {}').format(collateral_val)
                info += '\n'
                info += _('Total fee: {}').format(coins_val - collateral_val)
                return info

    def create_new_collateral_wfl_from_gui(self, coins, password):
        if self.state in self.mixing_running_states:
            return None, ('Can not create new collateral as mixing'
                          ' process is currently run.')
        wfl = self._start_new_collateral_wfl()
        if not wfl:
            return None, ('Can not create new collateral as other new'
                          ' collateral creation process is in progress')
        try:
            w = self.wallet
            txid, tx = self._make_new_collateral_tx(wfl, coins, password)
            if not w.add_transaction(txid, tx):
                raise Exception(f'Transaction with txid: {txid}'
                                f' conflicts with current history')
            if not w.db.get_ps_tx(txid)[0] == PSTxTypes.NEW_COLLATERAL:
                self._add_ps_data(txid, tx, PSTxTypes.NEW_COLLATERAL)
            with self.new_collateral_wfl_lock:
                saved = self.new_collateral_wfl
                if not saved:
                    raise Exception('new_collateral_wfl not found')
                if saved.uuid != wfl.uuid:
                    raise Exception('new_collateral_wfl differs from original')
                wfl.completed = True
                self.set_new_collateral_wfl(wfl)
                self.logger.wfl_ok(f'Completed new collateral workflow'
                                   f' with tx: {txid},'
                                   f' workflow: {wfl.lid}')
            return wfl, None
        except Exception as e:
            err = str(e)
            self.logger.wfl_err(f'Error creating new collateral tx:'
                                f' {err}, workflow: {wfl.lid}')
            self._cleanup_new_collateral_wfl(force=True)
            self.logger.info(f'Cleaned up new collateral workflow:'
                             f' {wfl.lid}')
            return None, err

    async def create_new_collateral_wfl(self, coins=None):
        _start = self._start_new_collateral_wfl
        wfl = await self.loop.run_in_executor(None, _start)
        if not wfl:
            return
        try:
            _make_tx = self._make_new_collateral_tx
            txid, tx = await self.loop.run_in_executor(None, _make_tx,
                                                       wfl, coins)
            w = self.wallet
            # add_transaction need run in network therad
            if not w.add_transaction(txid, tx):
                raise Exception(f'Transaction with txid: {txid}'
                                f' conflicts with current history')

            def _after_create_tx():
                with self.new_collateral_wfl_lock:
                    saved = self.new_collateral_wfl
                    if not saved:
                        raise Exception('new_collateral_wfl not found')
                    if saved.uuid != wfl.uuid:
                        raise Exception('new_collateral_wfl differs'
                                        ' from original')
                    wfl.completed = True
                    self.set_new_collateral_wfl(wfl)
                    self.logger.wfl_ok(f'Completed new collateral workflow'
                                       f' with tx: {txid},'
                                       f' workflow: {wfl.lid}')
            await self.loop.run_in_executor(None, _after_create_tx)
            w.storage.write()
        except Exception as e:
            self.logger.wfl_err(f'Error creating new collateral tx:'
                                f' {str(e)}, workflow: {wfl.lid}')
            await self.cleanup_new_collateral_wfl(force=True)
            type_e = type(e)
            msg = None
            if type_e == NoDynamicFeeEstimates:
                msg = self.NO_DYNAMIC_FEE_MSG.format(str(e))
            elif type_e == AddPSDataError:
                msg = self.ADD_PS_DATA_ERR_MSG
                type_name = SPEC_TX_NAMES[PSTxTypes.NEW_COLLATERAL]
                msg = f'{msg} {type_name} {txid}:\n{str(e)}'
            elif type_e == NotFoundInKeypairs:
                msg = self.NOT_FOUND_KEYS_MSG
            elif type_e == SignWithKeypairsFailed:
                msg = self.SIGN_WIHT_KP_FAILED_MSG
            elif type_e == NotEnoughFunds:
                self._not_enough_funds = True
            if msg:
                await self.stop_mixing_from_async_thread(msg)

    def _start_new_collateral_wfl(self):
        with self.new_collateral_wfl_lock:
            if self.new_collateral_wfl:
                return

            uuid = str(uuid4())
            wfl = PSTxWorkflow(uuid=uuid)
            self.set_new_collateral_wfl(wfl)
            self.logger.info(f'Started up new collateral workflow: {wfl.lid}')
            return self.new_collateral_wfl

    def _make_new_collateral_tx(self, wfl, coins=None, password=None):
        with self.new_collateral_wfl_lock:
            if self.config is None:
                raise Exception('self.config is not set')
            saved = self.new_collateral_wfl
            if not saved:
                raise Exception('new_collateral_wfl not found')
            if saved.uuid != wfl.uuid:
                raise Exception('new_collateral_wfl differs from original')

        # try to create new collateral tx with change outupt at first
        w = self.wallet
        fee_per_kb = self.config.fee_per_kb()
        uuid = wfl.uuid
        oaddr = self.reserve_addresses(1, data=uuid)[0]
        if coins is None:
            utxos = w.get_utxos(None,
                                excluded_addresses=w.frozen_addresses,
                                mature_only=True, confirmed_only=True,
                                consider_islocks=True)
            utxos = [utxo for utxo in utxos if not w.is_frozen_coin(utxo)]
            if self.w_ks_type != 'bip32':  # filter coins from ps_keystore
                utxos = [utxo for utxo in utxos if utxo['is_ps_ks']]
            utxos_val = sum([utxo['value'] for utxo in utxos])
            # try calc fee with change output
            new_collateral_fee = calc_tx_fee(len(utxos), 2, fee_per_kb,
                                             max_size=True)
            if utxos_val - new_collateral_fee < CREATE_COLLATERAL_VAL:
                # try calc fee without change output
                new_collateral_fee = calc_tx_fee(len(utxos), 1, fee_per_kb,
                                                 max_size=True)
                if utxos_val - new_collateral_fee < CREATE_COLLATERAL_VAL:
                    # try select minimal denom utxo with mimial rounds
                    coins = w.get_utxos(None,
                                        mature_only=True,
                                        confirmed_only=True,
                                        consider_islocks=True,
                                        min_rounds=0)
                    coins = [c for c in coins
                             if c['value'] == MIN_DENOM_VAL]
                    if not coins:
                        raise NotEnoughFunds()
                    coins = sorted(coins, key=lambda x: x['ps_rounds'])
                    coins = coins[0:1]

        if coins is not None:
            if len(coins) > 1:
                raise TooManyUtxos('Not allowed multiple utxos')
            utxos_val = coins[0]['value']
            if utxos_val >= self.min_new_denoms_from_coins_val:
                raise TooLargeUtxoVal('To large utxo selected')
            outputs = None
            for collateral_val in CREATE_COLLATERAL_VALS[::-1]:
                new_collateral_fee = calc_tx_fee(1, 1, fee_per_kb,
                                                 max_size=True)
                if utxos_val - new_collateral_fee >= collateral_val:
                    outputs = [TxOutput(TYPE_ADDRESS, oaddr, collateral_val)]
                    utxos = coins
                    break
            if outputs is None:
                raise NotEnoughFunds()
        else:
            outputs = [TxOutput(TYPE_ADDRESS, oaddr, CREATE_COLLATERAL_VAL)]

        tx = w.make_unsigned_transaction(utxos, outputs, self.config)
        inputs = tx.inputs()
        # check input addresses is in keypairs if keypairs cache available
        if self._keypairs_cache:
            input_addrs = [utxo['address'] for utxo in inputs]
            not_found_addrs = self._find_addrs_not_in_keypairs(input_addrs)
            if not_found_addrs:
                not_found_addrs = ', '.join(list(not_found_addrs))
                raise NotFoundInKeypairs(f'Input addresses is not found'
                                         f' in the keypairs cache:'
                                         f' {not_found_addrs}')

        if coins is not None:  # no change output
            tx = Transaction.from_io(inputs[:], outputs[:], locktime=0)
            for txin in tx.inputs():
                txin['sequence'] = 0xffffffff
        else:  # use first input address as a change, use selected inputs
            change_addr = inputs[0]['address']
            tx = w.make_unsigned_transaction(inputs, outputs, self.config,
                                             change_addr=change_addr)
        tx = self.sign_transaction(tx, password)
        txid = tx.txid()
        raw_tx = tx.serialize_to_network()
        tx_type = PSTxTypes.NEW_COLLATERAL
        wfl.add_tx(txid=txid, raw_tx=raw_tx, tx_type=tx_type)
        with self.new_collateral_wfl_lock:
            saved = self.new_collateral_wfl
            if not saved:
                raise Exception('new_collateral_wfl not found')
            if saved.uuid != wfl.uuid:
                raise Exception('new_collateral_wfl differs from original')
            self.set_new_collateral_wfl(wfl)
        return txid, tx

    async def cleanup_new_collateral_wfl(self, force=False):
        _cleanup = self._cleanup_new_collateral_wfl
        changed = await self.loop.run_in_executor(None, _cleanup, force)
        if changed:
            self.wallet.storage.write()

    def _cleanup_new_collateral_wfl(self, force=False):
        with self.new_collateral_wfl_lock:
            wfl = self.new_collateral_wfl
            if not wfl or wfl.completed and wfl.tx_order and not force:
                return
        w = self.wallet
        if wfl.tx_order:
            for txid in wfl.tx_order[::-1]:  # use reversed tx_order
                if w.db.get_transaction(txid):
                    w.remove_transaction(txid)
                else:
                    self._cleanup_new_collateral_wfl_tx_data(txid)
        else:
            self._cleanup_new_collateral_wfl_tx_data()
        return True

    def _cleanup_new_collateral_wfl_tx_data(self, txid=None):
        with self.new_collateral_wfl_lock:
            wfl = self.new_collateral_wfl
            if not wfl:
                return
            if txid:
                tx_data = wfl.pop_tx(txid)
                if tx_data:
                    self.set_new_collateral_wfl(wfl)
                    self.logger.info(f'Cleaned up new collateral tx:'
                                     f' {txid}, workflow: {wfl.lid}')
        if wfl.tx_order:
            return

        w = self.wallet
        for addr in w.db.select_ps_reserved(data=wfl.uuid):
            self.pop_ps_reserved(addr)

        with self.new_collateral_wfl_lock:
            saved = self.new_collateral_wfl
            if saved and saved.uuid == wfl.uuid:
                self.clear_new_collateral_wfl()
        self.logger.info(f'Cleaned up new collateral workflow: {wfl.lid}')

    async def broadcast_new_collateral_wfl(self):
        def _check_wfl():
            with self.new_collateral_wfl_lock:
                wfl = self.new_collateral_wfl
                if not wfl:
                    return
                if not wfl.completed:
                    return
            return wfl
        wfl = await self.loop.run_in_executor(None, _check_wfl)
        if not wfl:
            return
        w = self.wallet
        tx_data = wfl.next_to_send(w)
        if not tx_data:
            return
        txid = tx_data.txid
        sent, err = await tx_data.send(self)
        if err:
            def _on_fail():
                with self.new_collateral_wfl_lock:
                    saved = self.new_collateral_wfl
                    if not saved:
                        raise Exception('new_collateral_wfl not found')
                    if saved.uuid != wfl.uuid:
                        raise Exception('new_collateral_wfl differs'
                                        ' from original')
                    self.set_new_collateral_wfl(wfl)
                self.logger.wfl_err(f'Failed broadcast of new collateral tx'
                                    f' {txid}: {err}, workflow {wfl.lid}')
            await self.loop.run_in_executor(None, _on_fail)
        if sent:
            def _on_success():
                with self.new_collateral_wfl_lock:
                    saved = self.new_collateral_wfl
                    if not saved:
                        raise Exception('new_collateral_wfl not found')
                    if saved.uuid != wfl.uuid:
                        raise Exception('new_collateral_wfl differs'
                                        ' from original')
                    self.set_new_collateral_wfl(wfl)
                self.logger.wfl_done(f'Broadcasted transaction {txid} from new'
                                     f' collateral workflow: {wfl.lid}')
                tx = Transaction(wfl.tx_data[txid].raw_tx)
                self._process_by_new_collateral_wfl(txid, tx)
                if not wfl.next_to_send(w):
                    self.logger.wfl_done(f'Broadcast completed for new'
                                         f' collateral workflow: {wfl.lid}')
            await self.loop.run_in_executor(None, _on_success)

    def _search_new_collateral_wfl(self, txid, tx):
        err = self._check_new_collateral_tx_err(txid, tx, full_check=False)
        if not err:
            wfl = self.new_collateral_wfl
            if wfl and wfl.tx_order and txid in wfl.tx_order:
                return wfl

    def _check_on_new_collateral_wfl(self, txid, tx):
        wfl = self._search_new_collateral_wfl(txid, tx)
        err = self._check_new_collateral_tx_err(txid, tx)
        if not err:
            return True
        if wfl:
            raise AddPSDataError(f'{err}')
        else:
            return False

    def _process_by_new_collateral_wfl(self, txid, tx):
        wfl = self._search_new_collateral_wfl(txid, tx)
        if not wfl:
            return

        with self.new_collateral_wfl_lock:
            saved = self.new_collateral_wfl
            if not saved or saved.uuid != wfl.uuid:
                return
            tx_data = wfl.pop_tx(txid)
            if tx_data:
                self.set_new_collateral_wfl(wfl)
                self.logger.wfl_done(f'Processed tx: {txid} from new'
                                     f' collateral workflow: {wfl.lid}')
        if wfl.tx_order:
            return

        w = self.wallet
        for addr in w.db.select_ps_reserved(data=wfl.uuid):
            self.pop_ps_reserved(addr)

        with self.new_collateral_wfl_lock:
            saved = self.new_collateral_wfl
            if saved and saved.uuid == wfl.uuid:
                self.clear_new_collateral_wfl()
        self.logger.wfl_done(f'Finished processing of new collateral'
                             f' workflow: {wfl.lid}')

    # Workflow methods for new denoms transaction
    def new_denoms_from_coins_info(self, coins):
        if not coins or len(coins) > 1:
            return
        coins_val = sum([c['value'] for c in coins])
        if coins_val < self.min_new_denoms_from_coins_val:
            return
        fee_per_kb = self.config.fee_per_kb()
        denoms_amounts = self._calc_denoms_amounts_from_coins(coins,
                                                              fee_per_kb)
        if denoms_amounts:
            tx_cnt = len(denoms_amounts)
            outputs_val = sum([sum(amounts) for amounts in denoms_amounts])
            tx_type = SPEC_TX_NAMES[PSTxTypes.NEW_DENOMS]
            info = _('Transactions type: {}').format(tx_type)
            info += '\n'
            info += _('Count of transactions: {}').format(tx_cnt)
            info += '\n'
            info += _('Total sent amount: {}').format(coins_val)
            info += '\n'
            info += _('Total output amount: {}').format(outputs_val)
            info += '\n'
            info += _('Total fee: {}').format(coins_val - outputs_val)
            return info

    def create_new_denoms_wfl_from_gui(self, coins, password):
        if self.state in self.mixing_running_states:
            return None, ('Can not create new denoms as mixing process'
                          ' is currently run.')
        if len(coins) > 1:
            return None, ('Can not create new denoms,'
                          ' too many coins selected')
        wfl, outputs_amounts = self._start_new_denoms_wfl(coins)
        if not outputs_amounts:
            return None, ('Can not create new denoms,'
                          ' not enough coins selected')
        if not wfl:
            return None, ('Can not create new denoms as other new'
                          ' denoms creation process is in progress')
        last_tx_idx = len(outputs_amounts) - 1
        w = self.wallet
        for i, tx_amounts in enumerate(outputs_amounts):
            try:
                txid, tx = self._make_new_denoms_tx(wfl, tx_amounts,
                                                    last_tx_idx, i,
                                                    coins, password)
                if not w.add_transaction(txid, tx):
                    raise Exception(f'Transaction with txid: {txid}'
                                    f' conflicts with current history')
                if not w.db.get_ps_tx(txid)[0] == PSTxTypes.NEW_DENOMS:
                    self._add_ps_data(txid, tx, PSTxTypes.NEW_DENOMS)
                self.logger.info(f'Created new denoms tx: {txid},'
                                 f' workflow: {wfl.lid}')
                if i == last_tx_idx:
                    with self.new_denoms_wfl_lock:
                        saved = self.new_denoms_wfl
                        if not saved:
                            raise Exception('new_denoms_wfl not found')
                        if saved.uuid != wfl.uuid:
                            raise Exception('new_denoms_wfl differs'
                                            ' from original')
                        wfl.completed = True
                        self.set_new_denoms_wfl(wfl)
                        self.logger.wfl_ok(f'Completed new denoms'
                                           f' workflow: {wfl.lid}')
                    return wfl, None
                else:
                    txin0 = copy.deepcopy(tx.inputs()[0])
                    self.add_input_info(txin0)
                    txin0_addr = txin0['address']
                    utxos = w.get_utxos([txin0_addr],
                                        min_rounds=PSCoinRounds.OTHER)
                    change_outpoint = None
                    for change_idx, o in enumerate(tx.outputs()):
                        if o.address == txin0_addr:
                            change_outpoint = f'{txid}:{change_idx}'
                            break
                    coins = []
                    for utxo in utxos:
                        prev_h = utxo['prevout_hash']
                        prev_n = utxo['prevout_n']
                        if f'{prev_h}:{prev_n}' != change_outpoint:
                            continue
                        coins.append(utxo)
            except Exception as e:
                err = str(e)
                self.logger.wfl_err(f'Error creating new denoms tx:'
                                    f' {err}, workflow: {wfl.lid}')
                self._cleanup_new_denoms_wfl(force=True)
                self.logger.info(f'Cleaned up new denoms workflow:'
                                 f' {wfl.lid}')
                return None, err

    async def create_new_denoms_wfl(self):
        _start = self._start_new_denoms_wfl
        wfl, outputs_amounts = await self.loop.run_in_executor(None, _start)
        if not wfl:
            return
        last_tx_idx = len(outputs_amounts) - 1
        for i, tx_amounts in enumerate(outputs_amounts):
            try:
                w = self.wallet
                _make_tx = self._make_new_denoms_tx
                txid, tx = await self.loop.run_in_executor(None, _make_tx,
                                                           wfl, tx_amounts,
                                                           last_tx_idx, i)
                # add_transaction need run in network therad
                if not w.add_transaction(txid, tx):
                    raise Exception(f'Transaction with txid: {txid}'
                                    f' conflicts with current history')

                def _after_create_tx():
                    with self.new_denoms_wfl_lock:
                        self.logger.info(f'Created new denoms tx: {txid},'
                                         f' workflow: {wfl.lid}')
                        if i == last_tx_idx:
                            saved = self.new_denoms_wfl
                            if not saved:
                                raise Exception('new_denoms_wfl not found')
                            if saved.uuid != wfl.uuid:
                                raise Exception('new_denoms_wfl differs'
                                                ' from original')
                            wfl.completed = True
                            self.set_new_denoms_wfl(wfl)
                            self.logger.wfl_ok(f'Completed new denoms'
                                               f' workflow: {wfl.lid}')
                await self.loop.run_in_executor(None, _after_create_tx)
                w.storage.write()
            except Exception as e:
                self.logger.wfl_err(f'Error creating new denoms tx:'
                                    f' {str(e)}, workflow: {wfl.lid}')
                await self.cleanup_new_denoms_wfl(force=True)
                type_e = type(e)
                msg = None
                if type_e == NoDynamicFeeEstimates:
                    msg = self.NO_DYNAMIC_FEE_MSG.format(str(e))
                elif type_e == AddPSDataError:
                    msg = self.ADD_PS_DATA_ERR_MSG
                    type_name = SPEC_TX_NAMES[PSTxTypes.NEW_DENOMS]
                    msg = f'{msg} {type_name} {txid}:\n{str(e)}'
                elif type_e == NotFoundInKeypairs:
                    msg = self.NOT_FOUND_KEYS_MSG
                elif type_e == SignWithKeypairsFailed:
                    msg = self.SIGN_WIHT_KP_FAILED_MSG
                elif type_e == NotEnoughFunds:
                    self._not_enough_funds = True
                if msg:
                    await self.stop_mixing_from_async_thread(msg)
                break

    def _start_new_denoms_wfl(self, coins=None):
        outputs_amounts = self.calc_need_denoms_amounts(coins=coins)
        if not outputs_amounts:
            return None, None
        with self.new_denoms_wfl_lock, \
                self.pay_collateral_wfl_lock, \
                self.new_collateral_wfl_lock:
            if self.new_denoms_wfl:
                return None, None

            uuid = str(uuid4())
            wfl = PSTxWorkflow(uuid=uuid)
            self.set_new_denoms_wfl(wfl)
            self.logger.info(f'Started up new denoms workflow: {wfl.lid}')
            return wfl, outputs_amounts

    def _make_new_denoms_tx(self, wfl, tx_amounts, last_tx_idx, i,
                            coins=None, password=None):
        if self.config is None:
            raise Exception('self.config is not set')

        w = self.wallet
        # try to create new denoms tx with change outupt at first
        use_confirmed = (i == 0)  # for first tx use confirmed coins
        addrs_cnt = len(tx_amounts)
        oaddrs = self.reserve_addresses(addrs_cnt, data=wfl.uuid)
        outputs = [TxOutput(TYPE_ADDRESS, addr, a)
                   for addr, a in zip(oaddrs, tx_amounts)]
        if coins is None:
            utxos = w.get_utxos(None,
                                excluded_addresses=w.frozen_addresses,
                                mature_only=True,
                                confirmed_only=use_confirmed,
                                consider_islocks=True)
            utxos = [utxo for utxo in utxos if not w.is_frozen_coin(utxo)]
            if self.w_ks_type != 'bip32':  # filter coins from ps_keystore
                utxos = [utxo for utxo in utxos if utxo['is_ps_ks']]
        else:
            utxos = coins
        tx = w.make_unsigned_transaction(utxos, outputs, self.config)
        inputs = tx.inputs()
        # check input addresses is in keypairs if keypairs cache available
        if self._keypairs_cache:
            input_addrs = [utxo['address'] for utxo in inputs]
            not_found_addrs = self._find_addrs_not_in_keypairs(input_addrs)
            if not_found_addrs:
                not_found_addrs = ', '.join(list(not_found_addrs))
                raise NotFoundInKeypairs(f'Input addresses is not found'
                                         f' in the keypairs cache:'
                                         f' {not_found_addrs}')

        if coins and i == last_tx_idx:
            tx = Transaction.from_io(inputs[:], outputs[:], locktime=0)
            for txin in tx.inputs():
                txin['sequence'] = 0xffffffff
        else:
            # use first input address as a change, use selected inputs
            in0 = inputs[0]['address']
            tx = w.make_unsigned_transaction(inputs, outputs,
                                             self.config, change_addr=in0)
        tx = self.sign_transaction(tx, password)
        txid = tx.txid()
        raw_tx = tx.serialize_to_network()
        tx_type = PSTxTypes.NEW_DENOMS
        wfl.add_tx(txid=txid, raw_tx=raw_tx, tx_type=tx_type)
        with self.new_denoms_wfl_lock:
            saved = self.new_denoms_wfl
            if not saved:
                raise Exception('new_denoms_wfl not found')
            if saved.uuid != wfl.uuid:
                raise Exception('new_denoms_wfl differs from original')
            self.set_new_denoms_wfl(wfl)
        return txid, tx

    async def cleanup_new_denoms_wfl(self, force=False):
        _cleanup = self._cleanup_new_denoms_wfl
        changed = await self.loop.run_in_executor(None, _cleanup, force)
        if changed:
            self.wallet.storage.write()

    def _cleanup_new_denoms_wfl(self, force=False):
        with self.new_denoms_wfl_lock:
            wfl = self.new_denoms_wfl
            if not wfl or wfl.completed and wfl.tx_order and not force:
                return
        w = self.wallet
        if wfl.tx_order:
            for txid in wfl.tx_order[::-1]:  # use reversed tx_order
                if w.db.get_transaction(txid):
                    w.remove_transaction(txid)
                else:
                    self._cleanup_new_denoms_wfl_tx_data(txid)
        else:
            self._cleanup_new_denoms_wfl_tx_data()
        return True

    def _cleanup_new_denoms_wfl_tx_data(self, txid=None):
        with self.new_denoms_wfl_lock:
            wfl = self.new_denoms_wfl
            if not wfl:
                return
            if txid:
                tx_data = wfl.pop_tx(txid)
                if tx_data:
                    self.set_new_denoms_wfl(wfl)
                    self.logger.info(f'Cleaned up new denoms tx:'
                                     f' {txid}, workflow: {wfl.lid}')
        if wfl.tx_order:
            return

        w = self.wallet
        for addr in w.db.select_ps_reserved(data=wfl.uuid):
            self.pop_ps_reserved(addr)

        with self.new_denoms_wfl_lock:
            saved = self.new_denoms_wfl
            if saved and saved.uuid == wfl.uuid:
                self.clear_new_denoms_wfl()
        self.logger.info(f'Cleaned up new denoms workflow: {wfl.lid}')

    async def broadcast_new_denoms_wfl(self):
        def _check_wfl():
            with self.new_denoms_wfl_lock:
                wfl = self.new_denoms_wfl
                if not wfl:
                    return
                if not wfl.completed:
                    return
            return wfl
        wfl = await self.loop.run_in_executor(None, _check_wfl)
        if not wfl:
            return
        w = self.wallet
        tx_data = wfl.next_to_send(w)
        if not tx_data:
            return
        txid = tx_data.txid
        sent, err = await tx_data.send(self)
        if err:
            def _on_fail():
                with self.new_denoms_wfl_lock:
                    saved = self.new_denoms_wfl
                    if not saved:
                        raise Exception('new_denoms_wfl not found')
                    if saved.uuid != wfl.uuid:
                        raise Exception('new_denoms_wfl differs from original')
                    self.set_new_denoms_wfl(wfl)
                self.logger.wfl_err(f'Failed broadcast of new denoms tx'
                                    f' {txid}: {err}, workflow {wfl.lid}')
            await self.loop.run_in_executor(None, _on_fail)
        if sent:
            def _on_success():
                with self.new_denoms_wfl_lock:
                    saved = self.new_denoms_wfl
                    if not saved:
                        raise Exception('new_denoms_wfl not found')
                    if saved.uuid != wfl.uuid:
                        raise Exception('new_denoms_wfl differs from original')
                    self.set_new_denoms_wfl(wfl)
                self.logger.wfl_done(f'Broadcasted transaction {txid} from new'
                                     f' denoms workflow: {wfl.lid}')
                tx = Transaction(wfl.tx_data[txid].raw_tx)
                self._process_by_new_denoms_wfl(txid, tx)
                if not wfl.next_to_send(w):
                    self.logger.wfl_done(f'Broadcast completed for new denoms'
                                         f' workflow: {wfl.lid}')
            await self.loop.run_in_executor(None, _on_success)

    def _search_new_denoms_wfl(self, txid, tx):
        err = self._check_new_denoms_tx_err(txid, tx, full_check=False)
        if not err:
            wfl = self.new_denoms_wfl
            if wfl and wfl.tx_order and txid in wfl.tx_order:
                return wfl

    def _check_on_new_denoms_wfl(self, txid, tx):
        wfl = self._search_new_denoms_wfl(txid, tx)
        err = self._check_new_denoms_tx_err(txid, tx)
        if not err:
            return True
        if wfl:
            raise AddPSDataError(f'{err}')
        else:
            return False

    def _process_by_new_denoms_wfl(self, txid, tx):
        wfl = self._search_new_denoms_wfl(txid, tx)
        if not wfl:
            return

        with self.new_denoms_wfl_lock:
            saved = self.new_denoms_wfl
            if not saved or saved.uuid != wfl.uuid:
                return
            tx_data = wfl.pop_tx(txid)
            if tx_data:
                self.set_new_denoms_wfl(wfl)
                self.logger.wfl_done(f'Processed tx: {txid} from new denoms'
                                     f' workflow: {wfl.lid}')
        if wfl.tx_order:
            return

        w = self.wallet
        for addr in w.db.select_ps_reserved(data=wfl.uuid):
            self.pop_ps_reserved(addr)

        with self.new_denoms_wfl_lock:
            saved = self.new_denoms_wfl
            if saved and saved.uuid == wfl.uuid:
                self.clear_new_denoms_wfl()
        self.logger.wfl_done(f'Finished processing of new denoms'
                             f' workflow: {wfl.lid}')

    # Workflow methods for denominate transaction
    async def cleanup_staled_denominate_wfls(self):
        def _cleanup_staled():
            changed = False
            for uuid in self.denominate_wfl_list:
                wfl = self.get_denominate_wfl(uuid)
                if not wfl or not wfl.completed:
                    continue
                now = time.time()
                if now - wfl.completed > WAIT_FOR_MN_TXS_TIME_SEC:
                    self.logger.info(f'Cleaning staled denominate'
                                     f' workflow: {wfl.lid}')
                    self._cleanup_denominate_wfl(wfl)
                    changed = True
            return changed
        while True:
            if self.enabled:
                done = await self.loop.run_in_executor(None, _cleanup_staled)
                if done:
                    self.wallet.storage.write()
            await asyncio.sleep(WAIT_FOR_MN_TXS_TIME_SEC/12)

    async def start_denominate_wfl(self):
        wfl = None
        try:
            _start = self._start_denominate_wfl
            dsq = None
            session = None
            if random.random() > 0.33:
                self.logger.debug(f'try to get masternode from recent dsq')
                recent_mns = self.recent_mixes_mns
                while self.state == PSStates.Mixing:
                    dsq = self.axe_net.get_recent_dsq(recent_mns)
                    if dsq is not None:
                        self.logger.debug(f'get dsq from recent dsq queue'
                                          f' {dsq.masternodeOutPoint}')
                        dval = PS_DENOM_REVERSE_DICT[dsq.nDenom]
                        wfl = await self.loop.run_in_executor(None,
                                                              _start, dval)
                        break
                    await asyncio.sleep(0.5)
            else:
                self.logger.debug(f'try to create new queue'
                                  f' on random masternode')
                wfl = await self.loop.run_in_executor(None, _start)
            if not wfl:
                return

            if self.state != PSStates.Mixing:
                raise Exception('Mixing is finished')
            else:
                session = await self.start_mix_session(wfl.denom, dsq, wfl.lid)

            pay_collateral_tx = self.get_pay_collateral_tx()
            if not pay_collateral_tx:
                raise Exception('Absent suitable pay collateral tx')
            await session.send_dsa(pay_collateral_tx)
            while True:
                cmd, res = await session.read_next_msg(wfl)
                if cmd == 'dssu':
                    continue
                elif cmd == 'dsq' and session.fReady:
                    break
                else:
                    raise Exception(f'Unsolisited cmd: {cmd} after dsa sent')

            pay_collateral_tx = self.get_pay_collateral_tx()
            if not pay_collateral_tx:
                raise Exception('Absent suitable pay collateral tx')

            final_tx = None
            await session.send_dsi(wfl.inputs, pay_collateral_tx, wfl.outputs)
            while True:
                cmd, res = await session.read_next_msg(wfl)
                if cmd == 'dssu':
                    continue
                elif cmd == 'dsf':
                    final_tx = res
                    break
                else:
                    raise Exception(f'Unsolisited cmd: {cmd} after dsi sent')

            signed_inputs = self._sign_inputs(final_tx, wfl.inputs)
            await session.send_dss(signed_inputs)
            while True:
                cmd, res = await session.read_next_msg(wfl)
                if cmd == 'dssu':
                    continue
                elif cmd == 'dsc':
                    def _on_dsc():
                        with self.denominate_wfl_lock:
                            saved = self.get_denominate_wfl(wfl.uuid)
                            if saved:
                                saved.completed = time.time()
                                self.set_denominate_wfl(saved)
                                return saved
                            else:  # already processed from _add_ps_data
                                self.logger.debug(f'denominate workflow:'
                                                  f' {wfl.lid} not found')
                    saved = await self.loop.run_in_executor(None, _on_dsc)
                    if saved:
                        wfl = saved
                        self.wallet.storage.write()
                    break
                else:
                    raise Exception(f'Unsolisited cmd: {cmd} after dss sent')
            self.logger.wfl_ok(f'Completed denominate workflow: {wfl.lid}')
        except Exception as e:
            type_e = type(e)
            if type_e != asyncio.CancelledError:
                if wfl:
                    self.logger.wfl_err(f'Error in denominate worfklow:'
                                        f' {str(e)}, workflow: {wfl.lid}')
                else:
                    self.logger.wfl_err(f'Error during creation of denominate'
                                        f' worfklow: {str(e)}')
                msg = None
                if type_e == NoDynamicFeeEstimates:
                    msg = self.NO_DYNAMIC_FEE_MSG.format(str(e))
                elif type_e == NotFoundInKeypairs:
                    msg = self.NOT_FOUND_KEYS_MSG
                elif type_e == SignWithKeypairsFailed:
                    msg = self.SIGN_WIHT_KP_FAILED_MSG
                if msg:
                    await self.stop_mixing_from_async_thread(msg)
        finally:
            if session:
                await self.stop_mix_session(session.peer_str)
            if wfl:
                await self.cleanup_denominate_wfl(wfl)

    def _select_denoms_to_mix(self, denom_value=None):
        if not self._denoms_to_mix_cache:
            self.logger.debug(f'No suitable denoms to mix,'
                              f' _denoms_to_mix_cache is empty')
            return None, None

        if denom_value is not None:
            denoms = self.denoms_to_mix(denom_value=denom_value)
        else:
            denoms = self.denoms_to_mix()
        outpoints = list(denoms.keys())

        w = self.wallet
        icnt = 0
        txids = []
        inputs = []
        while icnt < random.randint(1, PRIVATESEND_ENTRY_MAX_SIZE):
            if not outpoints:
                break

            outpoint = outpoints.pop(random.randint(0, len(outpoints)-1))
            if not w.db.get_ps_denom(outpoint):  # already spent
                continue

            if w.db.get_ps_spending_denom(outpoint):  # reserved to spend
                continue

            txid = outpoint.split(':')[0]
            if txid in txids:  # skip outputs from same tx
                continue

            height = w.get_tx_height(txid).height
            islock = w.db.get_islock(txid)
            if not islock and height <= 0:  # skip not islocked/confirmed
                continue

            denom = denoms.pop(outpoint)
            if denom[2] >= self.mix_rounds:
                continue

            if not self.is_ps_ks(denom[0]) and self.is_hw_ks:
                continue  # skip denoms on hw keystore

            if denom_value is None:
                denom_value = denom[1]
            elif denom[1] != denom_value:  # skip other denom values
                continue

            inputs.append(outpoint)
            txids.append(txid)
            icnt += 1

        if not inputs:
            self.logger.debug(f'No suitable denoms to mix:'
                              f' denom_value={denom_value}')
            return None, None
        else:
            return inputs, denom_value

    def _start_denominate_wfl(self, denom_value=None):
        if self.active_denominate_wfl_cnt >= self.max_sessions:
            return
        selected_inputs, denom_value = self._select_denoms_to_mix(denom_value)
        if not selected_inputs:
            return

        with self.denominate_wfl_lock, self.denoms_lock:
            if self.active_denominate_wfl_cnt >= self.max_sessions:
                return
            icnt = 0
            inputs = []
            input_addrs = []
            w = self.wallet
            for outpoint in selected_inputs:
                denom = w.db.get_ps_denom(outpoint)
                if not denom:
                    continue  # already spent
                if w.db.get_ps_spending_denom(outpoint):
                    continue  # already used by other wfl
                if self.is_hw_ks and not self.is_ps_ks(denom[0]):
                    continue  # skip denoms from hardware keystore
                inputs.append(outpoint)
                input_addrs.append(denom[0])
                icnt += 1

            if icnt < 1:
                self.logger.debug(f'No suitable denoms to mix after'
                                  f' denoms_lock: denom_value={denom_value}')
                return

            uuid = str(uuid4())
            wfl = PSDenominateWorkflow(uuid=uuid)
            wfl.inputs = inputs
            wfl.denom = denom_value
            self.set_denominate_wfl(wfl)
            for outpoint in inputs:
                self.add_ps_spending_denom(outpoint, wfl.uuid)

        # check input addresses is in keypairs if keypairs cache available
        if self._keypairs_cache:
            not_found_addrs = self._find_addrs_not_in_keypairs(input_addrs)
            if not_found_addrs:
                not_found_addrs = ', '.join(list(not_found_addrs))
                raise NotFoundInKeypairs(f'Input addresses is not found'
                                         f' in the keypairs cache:'
                                         f' {not_found_addrs}')

        output_addrs = []
        found_outpoints = []
        for addr, data in w.db.get_ps_reserved().items():
            if data in inputs:
                output_addrs.append(addr)
                found_outpoints.append(data)
        for outpoint in inputs:
            if outpoint not in found_outpoints:
                force_main_ks = False
                if self.is_hw_ks:
                    denom = w.db.get_ps_denom(outpoint)
                    if denom[2] == self.mix_rounds - 1:
                        force_main_ks = True
                reserved = self.reserve_addresses(1, data=outpoint,
                                                  force_main_ks=force_main_ks)
                output_addrs.append(reserved[0])

        with self.denominate_wfl_lock:
            saved = self.get_denominate_wfl(wfl.uuid)
            if not saved:
                raise Exception(f'denominate_wfl {wfl.lid} not found')
            wfl = saved
            wfl.outputs = output_addrs
            self.set_denominate_wfl(saved)

        self.logger.info(f'Created denominate workflow: {wfl.lid}, with inputs'
                         f' value {wfl.denom}, count {len(wfl.inputs)}')
        return wfl

    def _sign_inputs(self, tx, inputs):
        signed_inputs = []
        tx = self._sign_denominate_tx(tx)
        for i in tx.inputs():
            prev_h = i['prevout_hash']
            prev_n = i['prevout_n']
            if f'{prev_h}:{prev_n}' not in inputs:
                continue
            prev_h = bfh(prev_h)[::-1]
            prev_n = int(prev_n)
            scriptSig = bfh(i['scriptSig'])
            sequence = i['sequence']
            signed_inputs.append(CTxIn(prev_h, prev_n, scriptSig, sequence))
        return signed_inputs

    def _sign_denominate_tx(self, tx):
        mine_txins_cnt = 0
        for txin in tx.inputs():
            self.add_input_info(txin)
            if txin['address'] is None:
                del txin['num_sig']
                txin['x_pubkeys'] = []
                txin['pubkeys'] = []
                txin['signatures'] = []
                continue
            mine_txins_cnt += 1
        self.sign_transaction(tx, None, mine_txins_cnt)
        raw_tx = tx.serialize()
        return Transaction(raw_tx)

    async def cleanup_denominate_wfl(self, wfl):
        _cleanup = self._cleanup_denominate_wfl
        changed = await self.loop.run_in_executor(None, _cleanup, wfl)
        if changed:
            self.wallet.storage.write()

    def _cleanup_denominate_wfl(self, wfl):
        with self.denominate_wfl_lock:
            saved = self.get_denominate_wfl(wfl.uuid)
            if not saved:  # already processed from _add_ps_data
                return
            else:
                wfl = saved

            completed = wfl.completed
            if completed:
                now = time.time()
                if now - wfl.completed <= WAIT_FOR_MN_TXS_TIME_SEC:
                    return

        w = self.wallet
        for outpoint, uuid in list(w.db.get_ps_spending_denoms().items()):
            if uuid != wfl.uuid:
                continue
            with self.denoms_lock:
                self.pop_ps_spending_denom(outpoint)

        with self.denominate_wfl_lock:
            self.clear_denominate_wfl(wfl.uuid)
        self.logger.info(f'Cleaned up denominate workflow: {wfl.lid}')
        return True

    def _search_denominate_wfl(self, txid, tx):
        err = self._check_denominate_tx_err(txid, tx, full_check=False)
        if not err:
            for uuid in self.denominate_wfl_list:
                wfl = self.get_denominate_wfl(uuid)
                if not wfl or not wfl.completed:
                    continue
                if self._check_denominate_tx_io_on_wfl(txid, tx, wfl):
                    return wfl

    def _check_on_denominate_wfl(self, txid, tx):
        wfl = self._search_denominate_wfl(txid, tx)
        err = self._check_denominate_tx_err(txid, tx)
        if not err:
            return True
        if wfl:
            raise AddPSDataError(f'{err}')
        else:
            return False

    def _process_by_denominate_wfl(self, txid, tx):
        wfl = self._search_denominate_wfl(txid, tx)
        if not wfl:
            return

        w = self.wallet
        for outpoint, uuid in list(w.db.get_ps_spending_denoms().items()):
            if uuid != wfl.uuid:
                continue
            with self.denoms_lock:
                self.pop_ps_spending_denom(outpoint)

        with self.denominate_wfl_lock:
            self.clear_denominate_wfl(wfl.uuid)
        self.logger.wfl_done(f'Finished processing of denominate'
                             f' workflow: {wfl.lid} with tx: {txid}')

    def get_workflow_tx_info(self, wfl):
        w = self.wallet
        tx_cnt = len(wfl.tx_order)
        tx_type = None if not tx_cnt else wfl.tx_data[wfl.tx_order[0]].tx_type
        total = 0
        total_fee = 0
        for txid in wfl.tx_order:
            tx = Transaction(wfl.tx_data[txid].raw_tx)
            tx_info = w.get_tx_info(tx)
            total += tx_info.amount
            total_fee += tx_info.fee
        return tx_type, tx_cnt, total, total_fee

    # Methods to check different tx types, add/rm ps data on these types
    def unpack_io_values(func):
        '''Decorator to prepare tx inputs/outputs info'''
        def func_wrapper(self, txid, tx, full_check=True):
            w = self.wallet
            inputs = []
            outputs = []
            icnt = mine_icnt = others_icnt = 0
            ocnt = op_return_ocnt = 0
            for i in tx.inputs():
                icnt += 1
                prev_h = i['prevout_hash']
                prev_n = i['prevout_n']
                prev_tx = w.db.get_transaction(prev_h)
                tx_type = w.db.get_ps_tx(prev_h)[0]
                if prev_tx:
                    o = prev_tx.outputs()[prev_n]
                    if w.is_mine(o.address):  # mine
                        inputs.append((o, prev_h, prev_n, True, tx_type))
                        mine_icnt += 1
                    else:  # others
                        inputs.append((o, prev_h, prev_n, False, tx_type))
                        others_icnt += 1
                else:  # possible others
                    inputs.append((None, prev_h, prev_n, False, tx_type))
                    others_icnt += 1
            for idx, o in enumerate(tx.outputs()):
                ocnt += 1
                if o.address.lower() == '6a':
                    op_return_ocnt += 1
                outputs.append((o, txid, idx))
            io_values = (inputs, outputs,
                         icnt, mine_icnt, others_icnt, ocnt, op_return_ocnt)
            return func(self, txid, io_values, full_check)
        return func_wrapper

    def _add_spent_ps_outpoints_ps_data(self, txid, tx):
        w = self.wallet
        spent_ps_addrs = set()
        spent_outpoints = []
        for txin in tx.inputs():
            spent_prev_h = txin['prevout_hash']
            spent_prev_n = txin['prevout_n']
            spent_outpoint = f'{spent_prev_h}:{spent_prev_n}'
            spent_outpoints.append(spent_outpoint)

            with self.denoms_lock:
                spent_denom = w.db.get_ps_spent_denom(spent_outpoint)
                if not spent_denom:
                    spent_denom = w.db.get_ps_denom(spent_outpoint)
                    if spent_denom:
                        w.db.add_ps_spent_denom(spent_outpoint, spent_denom)
                        spent_ps_addrs.add(spent_denom[0])
                self.pop_ps_denom(spent_outpoint)
            # cleanup of denominate wfl will be done on timeout

            with self.collateral_lock:
                spent_collateral = w.db.get_ps_spent_collateral(spent_outpoint)
                if not spent_collateral:
                    spent_collateral = w.db.get_ps_collateral(spent_outpoint)
                    if spent_collateral:
                        w.db.add_ps_spent_collateral(spent_outpoint,
                                                     spent_collateral)
                        spent_ps_addrs.add(spent_collateral[0])
                w.db.pop_ps_collateral(spent_outpoint)
            # cleanup of pay collateral wfl
            uuid = w.db.get_ps_spending_collateral(spent_outpoint)
            if uuid:
                self._cleanup_pay_collateral_wfl(force=True)

            with self.others_lock:
                spent_other = w.db.get_ps_spent_other(spent_outpoint)
                if not spent_other:
                    spent_other = w.db.get_ps_other(spent_outpoint)
                    if spent_other:
                        w.db.add_ps_spent_other(spent_outpoint, spent_other)
                        spent_ps_addrs.add(spent_other[0])
                w.db.pop_ps_other(spent_outpoint)

        self.add_spent_addrs(spent_ps_addrs)
        for addr, data in list(w.db.get_ps_reserved().items()):
            if data in spent_outpoints:
                self.pop_ps_reserved(addr)

    def _rm_spent_ps_outpoints_ps_data(self, txid, tx):
        w = self.wallet
        restored_ps_addrs = set()
        for txin in tx.inputs():
            restore_prev_h = txin['prevout_hash']
            restore_prev_n = txin['prevout_n']
            restore_outpoint = f'{restore_prev_h}:{restore_prev_n}'
            tx_type, completed = w.db.get_ps_tx_removed(restore_prev_h)
            with self.denoms_lock:
                if not tx_type:
                    restore_denom = w.db.get_ps_denom(restore_outpoint)
                    if not restore_denom:
                        restore_denom = \
                            w.db.get_ps_spent_denom(restore_outpoint)
                        if restore_denom:
                            self.add_ps_denom(restore_outpoint, restore_denom)
                            restored_ps_addrs.add(restore_denom[0])
                w.db.pop_ps_spent_denom(restore_outpoint)

            with self.collateral_lock:
                if not tx_type:
                    restore_collateral = \
                        w.db.get_ps_collateral(restore_outpoint)
                    if not restore_collateral:
                        restore_collateral = \
                            w.db.get_ps_spent_collateral(restore_outpoint)
                        if restore_collateral:
                            w.db.add_ps_collateral(restore_outpoint,
                                                   restore_collateral)
                            restored_ps_addrs.add(restore_collateral[0])
                w.db.pop_ps_spent_collateral(restore_outpoint)

            with self.others_lock:
                if not tx_type:
                    restore_other = w.db.get_ps_other(restore_outpoint)
                    if not restore_other:
                        restore_other = \
                            w.db.get_ps_spent_other(restore_outpoint)
                        if restore_other:
                            w.db.add_ps_other(restore_outpoint, restore_other)
                            restored_ps_addrs.add(restore_other[0])
                w.db.pop_ps_spent_other(restore_outpoint)
        self.restore_spent_addrs(restored_ps_addrs)

    @unpack_io_values
    def _check_new_denoms_tx_err(self, txid, io_values, full_check):
        (inputs, outputs,
         icnt, mine_icnt, others_icnt, ocnt, op_return_ocnt) = io_values
        if others_icnt > 0:
            return 'Transaction has not mine inputs'
        if op_return_ocnt > 0:
            return 'Transaction has OP_RETURN outputs'
        if mine_icnt == 0:
            return 'Transaction has not enough inputs count'

        if not full_check:
            return

        dval_cnt = 0
        collateral_cnt = 0
        denoms_cnt = 0
        last_denom_val = MIN_DENOM_VAL  # must start with minimal denom

        txin0_addr = inputs[0][0].address
        txin0_tx_type = inputs[0][4]
        change_cnt = sum([1 if o.address == txin0_addr else 0
                          for o, prev_h, prev_n in outputs])
        change_cnt2 = sum([1 if o.value not in PS_VALS else 0
                           for o, prev_h, prev_n in outputs])
        change_cnt = max(change_cnt, change_cnt2)
        if change_cnt > 1:
            return f'Excess change outputs'

        for i, (o, prev_h, prev_n) in enumerate(outputs):
            if o.address == txin0_addr:
                continue
            val = o.value
            if val in CREATE_COLLATERAL_VALS:
                if collateral_cnt > 0:
                    return f'Excess collateral output i={i}'
                else:
                    if val == CREATE_COLLATERAL_VAL:
                        collateral_cnt += 1
                    elif change_cnt > 0:
                        return f'This type of tx must have no change'
                    elif icnt > 1:
                        return f'This type of tx must have one input'
                    elif txin0_tx_type not in [PSTxTypes.OTHER_PS_COINS,
                                               PSTxTypes.NEW_DENOMS,
                                               PSTxTypes.DENOMINATE]:
                        return (f'This type of tx must have input from'
                                f' ps other coins/new denoms/denominate txs')
                    else:
                        collateral_cnt += 1
            elif val in PS_DENOMS_VALS:
                if val < last_denom_val:  # must increase or be the same
                    return (f'Unsuitable denom value={val}, must be'
                            f' {last_denom_val} or greater')
                elif val == last_denom_val:
                    dval_cnt += 1
                    if dval_cnt > 11:  # max 11 times of same denom val
                        return f'To many denoms of value={val}'
                else:
                    dval_cnt = 1
                    last_denom_val = val
                denoms_cnt += 1
            else:
                return f'Unsuitable output value={val}'
        if denoms_cnt < 1:
            return 'Transaction has no denom outputs'

    def _add_new_denoms_ps_data(self, txid, tx):
        w = self.wallet
        self._add_spent_ps_outpoints_ps_data(txid, tx)
        outputs = tx.outputs()
        new_outpoints = []
        new_others_outpoints = []
        txin0 = copy.deepcopy(tx.inputs()[0])
        self.add_input_info(txin0)
        txin0_addr = txin0['address']
        for i, o in enumerate(outputs):
            addr = o.address
            val = o.value
            new_outpoint = f'{txid}:{i}'
            if addr == txin0_addr:
                txin0_prev_h = txin0['prevout_hash']
                txin0_prev_n = txin0['prevout_n']
                txin0_outpoint = f'{txin0_prev_h}:{txin0_prev_n}'
                if (w.db.get_ps_spent_denom(txin0_outpoint)
                        or w.db.get_ps_spent_collateral(txin0_outpoint)
                        or w.db.get_ps_spent_other(txin0_outpoint)):
                    new_others_outpoints.append((new_outpoint, addr, val))
            elif val in PS_VALS:
                new_outpoints.append((new_outpoint, addr, val))
            else:
                raise AddPSDataError(f'Illegal value: {val}'
                                     f' in new denoms tx')
        with self.denoms_lock, self.collateral_lock:
            for new_outpoint, addr, val in new_outpoints:
                if val in CREATE_COLLATERAL_VALS:  # collaterral
                    new_collateral = (addr, val)
                    w.db.add_ps_collateral(new_outpoint, new_collateral)
                else:  # denom round 0
                    new_denom = (addr, val, 0)
                    self.add_ps_denom(new_outpoint, new_denom)
        with self.others_lock:
            for new_outpoint, addr, val in new_others_outpoints:
                w.db.add_ps_other(new_outpoint, (addr, val))

    def _rm_new_denoms_ps_data(self, txid, tx):
        w = self.wallet
        self._rm_spent_ps_outpoints_ps_data(txid, tx)
        outputs = tx.outputs()
        rm_outpoints = []
        rm_others_outpoints = []
        txin0 = copy.deepcopy(tx.inputs()[0])
        self.add_input_info(txin0)
        txin0_addr = txin0['address']
        for i, o in enumerate(outputs):
            addr = o.address
            val = o.value
            rm_outpoint = f'{txid}:{i}'
            if addr == txin0_addr:
                txin0_prev_h = txin0['prevout_hash']
                txin0_prev_n = txin0['prevout_n']
                txin0_outpoint = f'{txin0_prev_h}:{txin0_prev_n}'
                if (w.db.get_ps_spent_denom(txin0_outpoint)
                        or w.db.get_ps_spent_collateral(txin0_outpoint)
                        or w.db.get_ps_spent_other(txin0_outpoint)):
                    rm_others_outpoints.append(rm_outpoint)
            elif val in PS_VALS:
                rm_outpoints.append((rm_outpoint, val))
        with self.denoms_lock, self.collateral_lock:
            for rm_outpoint, val in rm_outpoints:
                if val in CREATE_COLLATERAL_VALS:  # collaterral
                    w.db.pop_ps_collateral(rm_outpoint)
                else:  # denom round 0
                    self.pop_ps_denom(rm_outpoint)
        with self.others_lock:
            for rm_outpoint in rm_others_outpoints:
                w.db.pop_ps_other(rm_outpoint)

    @unpack_io_values
    def _check_new_collateral_tx_err(self, txid, io_values, full_check):
        (inputs, outputs,
         icnt, mine_icnt, others_icnt, ocnt, op_return_ocnt) = io_values
        if others_icnt > 0:
            return 'Transaction has not mine inputs'
        if op_return_ocnt > 0:
            return 'Transaction has OP_RETURN outputs'
        if mine_icnt == 0:
            return 'Transaction has not enough inputs count'
        if ocnt > 2:
            return 'Transaction has wrong outputs count'

        collateral_cnt = 0

        txin0_addr = inputs[0][0].address
        txin0_tx_type = inputs[0][4]
        change_cnt = sum([1 if o.address == txin0_addr else 0
                          for o, prev_h, prev_n in outputs])
        change_cnt2 = sum([1 if o.value not in CREATE_COLLATERAL_VALS else 0
                           for o, prev_h, prev_n in outputs])
        change_cnt = max(change_cnt, change_cnt2)
        if change_cnt > 1:
            return f'Excess change outputs'

        for i, (o, prev_h, prev_n) in enumerate(outputs):
            if o.address == txin0_addr:
                continue
            val = o.value
            if val in CREATE_COLLATERAL_VALS:
                if collateral_cnt > 0:
                    return f'Excess collateral output i={i}'
                else:
                    if val == CREATE_COLLATERAL_VAL:
                        collateral_cnt += 1
                    elif change_cnt > 0:
                        return f'This type of tx must have no change'
                    elif icnt > 1:
                        return f'This type of tx must have one input'
                    elif txin0_tx_type not in [PSTxTypes.OTHER_PS_COINS,
                                               PSTxTypes.NEW_DENOMS,
                                               PSTxTypes.DENOMINATE]:
                        return (f'This type of tx must have input from'
                                f' ps other coins/new denoms/denominate txs')
                    else:
                        collateral_cnt += 1
            else:
                return f'Unsuitable output value={val}'
        if collateral_cnt < 1:
            return 'Transaction has no collateral outputs'

    def _add_new_collateral_ps_data(self, txid, tx):
        w = self.wallet
        self._add_spent_ps_outpoints_ps_data(txid, tx)
        outputs = tx.outputs()
        new_outpoints = []
        new_others_outpoints = []
        txin0 = copy.deepcopy(tx.inputs()[0])
        self.add_input_info(txin0)
        txin0_addr = txin0['address']
        for i, o in enumerate(outputs):
            addr = o.address
            val = o.value
            new_outpoint = f'{txid}:{i}'
            if addr == txin0_addr:
                txin0_prev_h = txin0['prevout_hash']
                txin0_prev_n = txin0['prevout_n']
                txin0_outpoint = f'{txin0_prev_h}:{txin0_prev_n}'
                if (w.db.get_ps_spent_denom(txin0_outpoint)
                        or w.db.get_ps_spent_collateral(txin0_outpoint)
                        or w.db.get_ps_spent_other(txin0_outpoint)):
                    new_others_outpoints.append((new_outpoint, addr, val))
            elif val in CREATE_COLLATERAL_VALS:
                new_outpoints.append((new_outpoint, addr, val))
            else:
                raise AddPSDataError(f'Illegal value: {val}'
                                     f' in new collateral tx')
        with self.collateral_lock:
            for new_outpoint, addr, val in new_outpoints:
                new_collateral = (addr, val)
                w.db.add_ps_collateral(new_outpoint, new_collateral)
        with self.others_lock:
            for new_outpoint, addr, val in new_others_outpoints:
                w.db.add_ps_other(new_outpoint, (addr, val))

    def _rm_new_collateral_ps_data(self, txid, tx):
        w = self.wallet
        self._rm_spent_ps_outpoints_ps_data(txid, tx)
        outputs = tx.outputs()
        rm_outpoints = []
        rm_others_outpoints = []
        txin0 = copy.deepcopy(tx.inputs()[0])
        self.add_input_info(txin0)
        txin0_addr = txin0['address']
        for i, o in enumerate(outputs):
            addr = o.address
            val = o.value
            rm_outpoint = f'{txid}:{i}'
            if addr == txin0_addr:
                txin0_prev_h = txin0['prevout_hash']
                txin0_prev_n = txin0['prevout_n']
                txin0_outpoint = f'{txin0_prev_h}:{txin0_prev_n}'
                if (w.db.get_ps_spent_denom(txin0_outpoint)
                        or w.db.get_ps_spent_collateral(txin0_outpoint)
                        or w.db.get_ps_spent_other(txin0_outpoint)):
                    rm_others_outpoints.append(rm_outpoint)
            elif val in CREATE_COLLATERAL_VALS:
                rm_outpoints.append(rm_outpoint)
        with self.collateral_lock:
            for rm_outpoint in rm_outpoints:
                w.db.pop_ps_collateral(rm_outpoint)
        with self.others_lock:
            for rm_outpoint in rm_others_outpoints:
                w.db.pop_ps_other(rm_outpoint)

    @unpack_io_values
    def _check_pay_collateral_tx_err(self, txid, io_values, full_check):
        (inputs, outputs,
         icnt, mine_icnt, others_icnt, ocnt, op_return_ocnt) = io_values
        if others_icnt > 0:
            return 'Transaction has not mine inputs'
        if mine_icnt != 1:
            return 'Transaction has wrong inputs count'
        if ocnt != 1:
            return 'Transaction has wrong outputs count'

        i, i_prev_h, i_prev_n, is_mine, tx_type = inputs[0]
        if i.value not in CREATE_COLLATERAL_VALS:
            return 'Wrong collateral amount'

        o, o_prev_h, o_prev_n = outputs[0]
        if o.address.lower() == '6a':
            if o.value != 0:
                return 'Wrong output collateral amount'
        else:
            if o.value not in CREATE_COLLATERAL_VALS[:-1]:
                return 'Wrong output collateral amount'
        if o.value != i.value - COLLATERAL_VAL:
            return 'Wrong output collateral amount'

        if not full_check:
            return

        w = self.wallet
        if not self.ps_collateral_cnt:
            return 'Collateral amount not ready'
        outpoint = f'{i_prev_h}:{i_prev_n}'
        ps_collateral = w.db.get_ps_collateral(outpoint)
        if not ps_collateral:
            return 'Collateral amount not found'

    def _add_pay_collateral_ps_data(self, txid, tx):
        w = self.wallet
        in0 = tx.inputs()[0]
        spent_prev_h = in0['prevout_hash']
        spent_prev_n = in0['prevout_n']
        spent_outpoint = f'{spent_prev_h}:{spent_prev_n}'
        spent_ps_addrs = set()
        with self.collateral_lock:
            spent_collateral = w.db.get_ps_spent_collateral(spent_outpoint)
            if not spent_collateral:
                spent_collateral = w.db.get_ps_collateral(spent_outpoint)
                if not spent_collateral:
                    raise AddPSDataError(f'ps_collateral {spent_outpoint}'
                                         f' not found')
            w.db.add_ps_spent_collateral(spent_outpoint, spent_collateral)
            spent_ps_addrs.add(spent_collateral[0])
            w.db.pop_ps_collateral(spent_outpoint)
            self.add_spent_addrs(spent_ps_addrs)

            out0 = tx.outputs()[0]
            addr = out0.address
            if addr.lower() != '6a':
                new_outpoint = f'{txid}:{0}'
                new_collateral = (addr, out0.value)
                w.db.add_ps_collateral(new_outpoint, new_collateral)
                self.pop_ps_reserved(addr)
                # add change address to not wait on wallet.synchronize_sequence
                if self.ps_keystore:
                    limit = self.gap_limit_for_change
                    addrs = self.get_change_addresses()
                    last_few_addrs = addrs[-limit:]
                    found_hist = False
                    for ch_addr in last_few_addrs:
                        if w.db.get_addr_history(ch_addr):
                            found_hist = True
                            break
                    if found_hist:
                        self.create_new_address(for_change=True)
                elif hasattr(w, '_unused_change_addresses'):
                    # _unused_change_addresses absent on wallet startup and
                    # wallet.create_new_address fails in that case
                    limit = w.gap_limit_for_change
                    addrs = w.get_change_addresses()
                    last_few_addrs = addrs[-limit:]
                    if any(map(w.db.get_addr_history, last_few_addrs)):
                        w.create_new_address(for_change=True)

    def _rm_pay_collateral_ps_data(self, txid, tx):
        w = self.wallet
        in0 = tx.inputs()[0]
        restore_prev_h = in0['prevout_hash']
        restore_prev_n = in0['prevout_n']
        restore_outpoint = f'{restore_prev_h}:{restore_prev_n}'
        restored_ps_addrs = set()
        with self.collateral_lock:
            tx_type, completed = w.db.get_ps_tx_removed(restore_prev_h)
            if not tx_type:
                restore_collateral = w.db.get_ps_collateral(restore_outpoint)
                if not restore_collateral:
                    restore_collateral = \
                        w.db.get_ps_spent_collateral(restore_outpoint)
                    if not restore_collateral:
                        raise RmPSDataError(f'ps_spent_collateral'
                                            f' {restore_outpoint} not found')
                w.db.add_ps_collateral(restore_outpoint, restore_collateral)
                restored_ps_addrs.add(restore_collateral[0])
            w.db.pop_ps_spent_collateral(restore_outpoint)
            self.restore_spent_addrs(restored_ps_addrs)

            out0 = tx.outputs()[0]
            addr = out0.address
            if addr.lower() != '6a':
                rm_outpoint = f'{txid}:{0}'
                self.add_ps_reserved(addr, restore_outpoint)
                w.db.pop_ps_collateral(rm_outpoint)

    @unpack_io_values
    def _check_denominate_tx_err(self, txid, io_values, full_check):
        (inputs, outputs,
         icnt, mine_icnt, others_icnt, ocnt, op_return_ocnt) = io_values
        if icnt != ocnt:
            return 'Transaction has different count of inputs/outputs'
        if icnt < POOL_MIN_PARTICIPANTS:
            return 'Transaction has too small count of inputs/outputs'
        if icnt > POOL_MAX_PARTICIPANTS * PRIVATESEND_ENTRY_MAX_SIZE:
            return 'Transaction has too many count of inputs/outputs'
        if mine_icnt < 1:
            return 'Transaction has too small count of mine inputs'
        if op_return_ocnt > 0:
            return 'Transaction has OP_RETURN outputs'

        denom_val = None
        for i, prev_h, prev_n, is_mine, tx_type in inputs:
            if not is_mine:
                continue
            if denom_val is None:
                denom_val = i.value
                if denom_val not in PS_DENOMS_VALS:
                    return f'Unsuitable input value={denom_val}'
            elif i.value != denom_val:
                return f'Unsuitable input value={i.value}'
        for o, prev_h, prev_n in outputs:
            if o.value != denom_val:
                return f'Unsuitable output value={o.value}'

        if not full_check:
            return

        w = self.wallet
        for i, prev_h, prev_n, is_mine, tx_type in inputs:
            if not is_mine:
                continue
            denom = w.db.get_ps_denom(f'{prev_h}:{prev_n}')
            if not denom:
                return f'Transaction input not found in ps_denoms'

    def _check_denominate_tx_io_on_wfl(self, txid, tx, wfl):
        w = self.wallet
        icnt = 0
        ocnt = 0
        for i, txin in enumerate(tx.inputs()):
            txin = copy.deepcopy(txin)
            self.add_input_info(txin)
            addr = txin['address']
            if not w.is_mine(addr):
                continue
            prev_h = txin['prevout_hash']
            prev_n = txin['prevout_n']
            outpoint = f'{prev_h}:{prev_n}'
            if outpoint in wfl.inputs:
                icnt += 1
        for i, o in enumerate(tx.outputs()):
            if o.value != wfl.denom:
                return False
            if o.address in wfl.outputs:
                ocnt += 1
        if icnt > 0 and ocnt == icnt:
            return True
        else:
            return False

    def _is_mine_lookahead(self, addr, for_change=False, look_ahead_cnt=100,
                           ps_ks=False):
        # need look_ahead_cnt is max 16 sessions * avg 5 addresses is ~ 80
        w = self.wallet
        if w.is_mine(addr):
            return True
        if self.state in self.mixing_running_states:
            return False

        imported_addrs = getattr(w.db, 'imported_addresses', {})
        if not ps_ks and imported_addrs:
            return False

        if for_change:
            last_wallet_addr = w.db.get_change_addresses(slice_start=-1,
                                                         ps_ks=ps_ks)[0]
            if ps_ks:
                last_wallet_index = self.get_address_index(last_wallet_addr)[1]
            else:
                last_wallet_index = w.get_address_index(last_wallet_addr)[1]
        else:
            last_wallet_addr = w.db.get_receiving_addresses(slice_start=-1,
                                                            ps_ks=ps_ks)[0]
            if ps_ks:
                last_wallet_index = self.get_address_index(last_wallet_addr)[1]
            else:
                last_wallet_index = w.get_address_index(last_wallet_addr)[1]

        # prepare cache
        if ps_ks:
            cache = getattr(self, '_is_mine_lookahead_cache_ps_ks', {})
        else:
            cache = getattr(self, '_is_mine_lookahead_cache', {})
        if not cache:
            cache['change'] = {}
            cache['recv'] = {}
        if ps_ks:
            self._is_mine_lookahead_cache_ps_ks = cache
        else:
            self._is_mine_lookahead_cache = cache

        cache_type = 'change' if for_change else 'recv'
        cache = cache[cache_type]
        if 'first_idx' not in cache:
            cache['addrs'] = addrs = list()
            cache['first_idx'] = first_idx = last_wallet_index + 1
        else:
            addrs = cache['addrs']
            first_idx = cache['first_idx']
            if addr in addrs:
                return True
            elif first_idx < last_wallet_index + 1:
                difference = last_wallet_index + 1 - first_idx
                cache['addrs'] = addrs = addrs[difference:]
                cache['first_idx'] = first_idx = last_wallet_index + 1

        # generate new addrs and check match
        idx = first_idx + len(addrs)
        while len(addrs) < look_ahead_cnt:
            sequence = [1, idx] if for_change else [0, idx]
            if ps_ks:
                x_pubkey = self.ps_keystore.get_xpubkey(*sequence)
            else:
                x_pubkey = w.keystore.get_xpubkey(*sequence)
            _, generated_addr = xpubkey_to_address(x_pubkey)
            if generated_addr not in addrs:
                addrs.append(generated_addr)
            if addr in addrs:
                return True
            idx += 1
        return False

    def _calc_rounds_for_denominate_tx(self, new_outpoints, input_rounds):
        output_rounds = list(map(lambda x: x+1, input_rounds[:]))
        if self.is_hw_ks:
            max_round = max(output_rounds)
            min_round = min(output_rounds)
            if min_round < max_round:
                hw_addrs_idxs = []
                for i, (new_outpoint, addr, value) in enumerate(new_outpoints):
                    if not self.is_ps_ks(addr):
                        hw_addrs_idxs.append(i)
                if hw_addrs_idxs:
                    max_round_idxs = []
                    for i, r in enumerate(output_rounds):
                        if r == max_round:
                            max_round_idxs.append(i)
                    res_rounds = [r for r in output_rounds if r < max_round]
                    while max_round_idxs:
                        r = output_rounds[max_round_idxs.pop(0)]
                        if hw_addrs_idxs:
                            i = hw_addrs_idxs.pop(0)
                            res_rounds.insert(i, r)
                        else:
                            res_rounds.append(r)
                    output_rounds = res_rounds[:]
        return output_rounds

    def _add_denominate_ps_data(self, txid, tx):
        w = self.wallet
        spent_outpoints = []
        for txin in tx.inputs():
            txin = copy.deepcopy(txin)
            self.add_input_info(txin)
            addr = txin['address']
            if not w.is_mine(addr):
                continue
            spent_prev_h = txin['prevout_hash']
            spent_prev_n = txin['prevout_n']
            spent_outpoint = f'{spent_prev_h}:{spent_prev_n}'
            spent_outpoints.append(spent_outpoint)

        new_outpoints = []
        for i, o in enumerate(tx.outputs()):
            addr = o.address
            if self.ps_keystore:
                if (not self._is_mine_lookahead(addr, ps_ks=True)
                        and not self._is_mine_lookahead(addr)):
                    continue
            else:
                if not self._is_mine_lookahead(addr):
                    continue
            new_outpoints.append((f'{txid}:{i}', addr, o.value))

        input_rounds = []
        spent_ps_addrs = set()
        with self.denoms_lock:
            for spent_outpoint in spent_outpoints:
                spent_denom = w.db.get_ps_spent_denom(spent_outpoint)
                if not spent_denom:
                    spent_denom = w.db.get_ps_denom(spent_outpoint)
                    if not spent_denom:
                        raise AddPSDataError(f'ps_denom {spent_outpoint}'
                                             f' not found')
                w.db.add_ps_spent_denom(spent_outpoint, spent_denom)
                spent_ps_addrs.add(spent_denom[0])
                self.pop_ps_denom(spent_outpoint)
                input_rounds.append(spent_denom[2])
            self.add_spent_addrs(spent_ps_addrs)

            output_rounds = self._calc_rounds_for_denominate_tx(new_outpoints,
                                                                input_rounds)
            for i, (new_outpoint, addr, value) in enumerate(new_outpoints):
                new_denom = (addr, value, output_rounds[i])
                self.add_ps_denom(new_outpoint, new_denom)
                self.pop_ps_reserved(addr)

    def _rm_denominate_ps_data(self, txid, tx):
        w = self.wallet
        restore_outpoints = []
        for txin in tx.inputs():
            txin = copy.deepcopy(txin)
            self.add_input_info(txin)
            addr = txin['address']
            if not w.is_mine(addr):
                continue
            restore_prev_h = txin['prevout_hash']
            restore_prev_n = txin['prevout_n']
            restore_outpoint = f'{restore_prev_h}:{restore_prev_n}'
            restore_outpoints.append((restore_outpoint, restore_prev_h))

        rm_outpoints = []
        for i, o in enumerate(tx.outputs()):
            addr = o.address
            if self.ps_keystore:
                if (not self._is_mine_lookahead(addr, ps_ks=True)
                        and not self._is_mine_lookahead(addr)):
                    continue
            else:
                if not self._is_mine_lookahead(addr):
                    continue
            rm_outpoints.append((f'{txid}:{i}', addr))

        restored_ps_addrs = set()
        with self.denoms_lock:
            for restore_outpoint, restore_prev_h in restore_outpoints:
                tx_type, completed = w.db.get_ps_tx_removed(restore_prev_h)
                if not tx_type:
                    restore_denom = w.db.get_ps_denom(restore_outpoint)
                    if not restore_denom:
                        restore_denom = \
                            w.db.get_ps_spent_denom(restore_outpoint)
                        if not restore_denom:
                            raise RmPSDataError(f'ps_denom {restore_outpoint}'
                                                f' not found')
                    self.add_ps_denom(restore_outpoint, restore_denom)
                    restored_ps_addrs.add(restore_denom[0])
                w.db.pop_ps_spent_denom(restore_outpoint)
            self.restore_spent_addrs(restored_ps_addrs)

            for i, (rm_outpoint, addr) in enumerate(rm_outpoints):
                self.add_ps_reserved(addr, restore_outpoints[i][0])
                self.pop_ps_denom(rm_outpoint)

    @unpack_io_values
    def _check_other_ps_coins_tx_err(self, txid, io_values, full_check):
        (inputs, outputs,
         icnt, mine_icnt, others_icnt, ocnt, op_return_ocnt) = io_values

        w = self.wallet
        for o, prev_h, prev_n in outputs:
            addr = o.address
            if addr in w.db.get_ps_addresses():
                return
        return 'Transaction has no outputs with ps denoms/collateral addresses'

    @unpack_io_values
    def _check_privatesend_tx_err(self, txid, io_values, full_check):
        (inputs, outputs,
         icnt, mine_icnt, others_icnt, ocnt, op_return_ocnt) = io_values
        if others_icnt > 0:
            return 'Transaction has not mine inputs'
        if mine_icnt < 1:
            return 'Transaction has too small count of mine inputs'
        if op_return_ocnt > 0:
            return 'Transaction has OP_RETURN outputs'
        if ocnt != 1:
            return 'Transaction has wrong count of outputs'

        w = self.wallet
        for i, prev_h, prev_n, is_mine, tx_type in inputs:
            if i.value not in PS_DENOMS_VALS:
                return f'Unsuitable input value={i.value}'
            denom = w.db.get_ps_denom(f'{prev_h}:{prev_n}')
            if not denom:
                return f'Transaction input not found in ps_denoms'
            if denom[2] < self.min_mix_rounds:
                return f'Transaction input mix_rounds too small'

    @unpack_io_values
    def _check_spend_ps_coins_tx_err(self, txid, io_values, full_check):
        (inputs, outputs,
         icnt, mine_icnt, others_icnt, ocnt, op_return_ocnt) = io_values
        if others_icnt > 0:
            return 'Transaction has not mine inputs'
        if mine_icnt == 0:
            return 'Transaction has not enough inputs count'

        w = self.wallet
        for i, prev_h, prev_n, is_mine, tx_type in inputs:
            spent_outpoint = f'{prev_h}:{prev_n}'
            if w.db.get_ps_denom(spent_outpoint):
                return
            if w.db.get_ps_collateral(spent_outpoint):
                return
            if w.db.get_ps_other(spent_outpoint):
                return
        return 'Transaction has no inputs from ps denoms/collaterals/others'

    def _add_spend_ps_coins_ps_data(self, txid, tx):
        w = self.wallet
        self._add_spent_ps_outpoints_ps_data(txid, tx)
        ps_addrs = w.db.get_ps_addresses()
        new_others = []
        for i, o in enumerate(tx.outputs()):  # check to add ps_others
            addr = o.address
            if addr in ps_addrs:
                new_others.append((f'{txid}:{i}', addr, o.value))
        with self.others_lock:
            for new_outpoint, addr, value in new_others:
                new_other = (addr, value)
                w.db.add_ps_other(new_outpoint, new_other)

    def _rm_spend_ps_coins_ps_data(self, txid, tx):
        w = self.wallet
        self._rm_spent_ps_outpoints_ps_data(txid, tx)
        ps_addrs = w.db.get_ps_addresses()
        rm_others = []
        for i, o in enumerate(tx.outputs()):  # check to rm ps_others
            addr = o.address
            if addr in ps_addrs:
                rm_others.append(f'{txid}:{i}')
        with self.others_lock:
            for rm_outpoint in rm_others:
                w.db.pop_ps_other(rm_outpoint)

    # Methods to add ps data, using preceding methods for different tx types
    def _check_ps_tx_type(self, txid, tx,
                          find_untracked=False, last_iteration=False):
        if find_untracked and last_iteration:
            err = self._check_other_ps_coins_tx_err(txid, tx)
            if not err:
                return PSTxTypes.OTHER_PS_COINS
            else:
                return STANDARD_TX

        if self._check_on_denominate_wfl(txid, tx):
            return PSTxTypes.DENOMINATE
        if self._check_on_pay_collateral_wfl(txid, tx):
            return PSTxTypes.PAY_COLLATERAL
        if self._check_on_new_collateral_wfl(txid, tx):
            return PSTxTypes.NEW_COLLATERAL
        if self._check_on_new_denoms_wfl(txid, tx):
            return PSTxTypes.NEW_DENOMS

        # OTHER_PS_COINS before PRIVATESEND and SPEND_PS_COINS
        # to prevent spending ps coins to ps addresses
        # Do not must happen if blocked in PSManager.broadcast_transaction
        err = self._check_other_ps_coins_tx_err(txid, tx)
        if not err:
            return PSTxTypes.OTHER_PS_COINS
        # PRIVATESEND before SPEND_PS_COINS as second pattern more relaxed
        err = self._check_privatesend_tx_err(txid, tx)
        if not err:
            return PSTxTypes.PRIVATESEND
        # SPEND_PS_COINS will be allowed when mixing is stopped
        err = self._check_spend_ps_coins_tx_err(txid, tx)
        if not err:
            return PSTxTypes.SPEND_PS_COINS

        return STANDARD_TX

    def _add_ps_data(self, txid, tx, tx_type):
        w = self.wallet
        w.db.add_ps_tx(txid, tx_type, completed=False)
        if tx_type == PSTxTypes.NEW_DENOMS:
            self._add_new_denoms_ps_data(txid, tx)
            if self._keypairs_cache:
                self._cleanup_spendable_keypairs(txid, tx, tx_type)
        elif tx_type == PSTxTypes.NEW_COLLATERAL:
            self._add_new_collateral_ps_data(txid, tx)
            if self._keypairs_cache:
                self._cleanup_spendable_keypairs(txid, tx, tx_type)
        elif tx_type == PSTxTypes.PAY_COLLATERAL:
            self._add_pay_collateral_ps_data(txid, tx)
            self._process_by_pay_collateral_wfl(txid, tx)
            if self._keypairs_cache:
                self._cleanup_ps_keypairs(txid, tx, tx_type)
        elif tx_type == PSTxTypes.DENOMINATE:
            self._add_denominate_ps_data(txid, tx)
            self._process_by_denominate_wfl(txid, tx)
            if self._keypairs_cache:
                self._cleanup_ps_keypairs(txid, tx, tx_type)
        elif tx_type == PSTxTypes.PRIVATESEND:
            self._add_spend_ps_coins_ps_data(txid, tx)
            if self._keypairs_cache:
                self._cleanup_ps_keypairs(txid, tx, tx_type)
        elif tx_type == PSTxTypes.SPEND_PS_COINS:
            self._add_spend_ps_coins_ps_data(txid, tx)
            if self._keypairs_cache:
                self._cleanup_ps_keypairs(txid, tx, tx_type)
        elif tx_type == PSTxTypes.OTHER_PS_COINS:
            self._add_spend_ps_coins_ps_data(txid, tx)
            if self._keypairs_cache:
                self._cleanup_ps_keypairs(txid, tx, tx_type)
            # notify ui on ps other coins arrived
            self.postpone_notification('ps-other-coins-arrived', w, txid)
        else:
            raise AddPSDataError(f'{txid} unknow type {tx_type}')
        w.db.pop_ps_tx_removed(txid)
        w.db.add_ps_tx(txid, tx_type, completed=True)

        # check if not enough small denoms
        check_denoms_by_vals = False
        if tx_type == PSTxTypes.NEW_DENOMS:
            txin0 = copy.deepcopy(tx.inputs()[0])
            self.add_input_info(txin0)
            txin0_addr = txin0['address']
            if txin0_addr not in [o.address for o in tx.outputs()]:
                check_denoms_by_vals = True
        elif tx_type in [PSTxTypes.SPEND_PS_COINS, PSTxTypes.PRIVATESEND]:
            check_denoms_by_vals = True
        if check_denoms_by_vals:
            denoms_by_vals = self.calc_denoms_by_values()
            if denoms_by_vals:
                if not self.check_enough_sm_denoms(denoms_by_vals):
                    self.postpone_notification('ps-not-enough-sm-denoms',
                                               w, denoms_by_vals)

    def _add_tx_ps_data(self, txid, tx):
        '''Used from AddressSynchronizer.add_transaction'''
        if self.state not in [PSStates.Mixing, PSStates.StopMixing]:
            return
        w = self.wallet
        tx_type, completed = w.db.get_ps_tx(txid)
        if tx_type and completed:  # ps data already exists
            return
        if not tx_type:  # try to find type in removed ps txs
            tx_type, completed = w.db.get_ps_tx_removed(txid)
            if tx_type:
                self.logger.info(f'_add_tx_ps_data: matched removed tx {txid}')
        if not tx_type:  # check possible types from workflows and patterns
            tx_type = self._check_ps_tx_type(txid, tx)
        if not tx_type:
            return
        self._add_tx_type_ps_data(txid, tx, tx_type)

    def _add_tx_type_ps_data(self, txid, tx, tx_type):
        w = self.wallet
        if tx_type in PS_SAVED_TX_TYPES:
            try:
                type_name = SPEC_TX_NAMES[tx_type]
                self._add_ps_data(txid, tx, tx_type)
                self.last_mixed_tx_time = time.time()
                self.logger.debug(f'_add_tx_type_ps_data {txid}, {type_name}')
                self.postpone_notification('ps-data-changes', w)
            except Exception as e:
                self.logger.info(f'_add_ps_data {txid} failed: {str(e)}')
                if tx_type in [PSTxTypes.NEW_COLLATERAL, PSTxTypes.NEW_DENOMS]:
                    # this two tx types added during wfl creation process
                    raise
                if tx_type in [PSTxTypes.PAY_COLLATERAL, PSTxTypes.DENOMINATE]:
                    # this two tx types added from network
                    msg = self.ADD_PS_DATA_ERR_MSG
                    msg = f'{msg} {type_name} {txid}:\n{str(e)}'
                    self.stop_mixing(msg)
        else:
            self.logger.info(f'_add_tx_type_ps_data: {txid}'
                             f' unknonw type {tx_type}')

    # Methods to rm ps data, using preceding methods for different tx types
    def _rm_ps_data(self, txid, tx, tx_type):
        w = self.wallet
        w.db.add_ps_tx_removed(txid, tx_type, completed=False)
        if tx_type == PSTxTypes.NEW_DENOMS:
            self._rm_new_denoms_ps_data(txid, tx)
            self._cleanup_new_denoms_wfl_tx_data(txid)
        elif tx_type == PSTxTypes.NEW_COLLATERAL:
            self._rm_new_collateral_ps_data(txid, tx)
            self._cleanup_new_collateral_wfl_tx_data(txid)
        elif tx_type == PSTxTypes.PAY_COLLATERAL:
            self._rm_pay_collateral_ps_data(txid, tx)
            self._cleanup_pay_collateral_wfl_tx_data(txid)
        elif tx_type == PSTxTypes.DENOMINATE:
            self._rm_denominate_ps_data(txid, tx)
        elif tx_type == PSTxTypes.PRIVATESEND:
            self._rm_spend_ps_coins_ps_data(txid, tx)
        elif tx_type == PSTxTypes.SPEND_PS_COINS:
            self._rm_spend_ps_coins_ps_data(txid, tx)
        elif tx_type == PSTxTypes.OTHER_PS_COINS:
            self._rm_spend_ps_coins_ps_data(txid, tx)
        else:
            raise RmPSDataError(f'{txid} unknow type {tx_type}')
        w.db.pop_ps_tx(txid)
        w.db.add_ps_tx_removed(txid, tx_type, completed=True)

    def _rm_tx_ps_data(self, txid):
        '''Used from AddressSynchronizer.remove_transaction'''
        w = self.wallet
        tx = w.db.get_transaction(txid)
        if not tx:
            self.logger.info(f'_rm_tx_ps_data: {txid} not found')
            return

        tx_type, completed = w.db.get_ps_tx(txid)
        if not tx_type:
            return
        if tx_type in PS_SAVED_TX_TYPES:
            try:
                self._rm_ps_data(txid, tx, tx_type)
                self.postpone_notification('ps-data-changes', w)
            except Exception as e:
                self.logger.info(f'_rm_ps_data {txid} failed: {str(e)}')
        else:
            self.logger.info(f'_rm_tx_ps_data: {txid} unknonw type {tx_type}')

    # Auxiliary methods
    def clear_ps_data(self):
        if self.loop:
            coro = self._clear_ps_data()
            asyncio.run_coroutine_threadsafe(coro, self.loop)

    async def _clear_ps_data(self):
        w = self.wallet

        def _do_clear_ps_data():
            msg = None
            with self.state_lock:
                if self.state in self.mixing_running_states:
                    msg = _('To clear PrivateSend data'
                            ' stop PrivateSend mixing')
                elif self.state == PSStates.FindingUntracked:
                    msg = _('Can not clear PrivateSend data. Process'
                            ' of finding untracked PS transactions'
                            ' is currently run')
                elif self.state == PSStates.Cleaning:
                    return
                else:
                    self.state = PSStates.Cleaning
                    self.trigger_callback('ps-state-changes', w, None, None)
                    self.logger.info(f'Clearing PrivateSend wallet data')
                    w.db.clear_ps_data()
                    self.state = PSStates.Ready
                    self.logger.info(f'All PrivateSend wallet data cleared')
            return msg
        msg = await self.loop.run_in_executor(None, _do_clear_ps_data)
        if msg:
            self.trigger_callback('ps-state-changes', w, msg, None)
        else:
            self.trigger_callback('ps-state-changes', w, None, None)
            self.postpone_notification('ps-data-changes', w)
            w.storage.write()

    def find_untracked_ps_txs_from_gui(self):
        if self.loop:
            coro = self.find_untracked_ps_txs()
            asyncio.run_coroutine_threadsafe(coro, self.loop)

    async def find_untracked_ps_txs(self, log=True):
        w = self.wallet
        found = 0
        with self.state_lock:
            if self.state in [PSStates.Ready, PSStates.Initializing]:
                self.state = PSStates.FindingUntracked
        if not self.state == PSStates.FindingUntracked:
            return found
        else:
            self.trigger_callback('ps-state-changes', w, None, None)
        try:
            _find = self._find_untracked_ps_txs
            found = await self.loop.run_in_executor(None, _find, log)
            if found:
                w.storage.write()
                self.postpone_notification('ps-data-changes', w)
        except Exception as e:
            with self.state_lock:
                self.state = PSStates.Errored
            self.logger.info(f'Error during loading of untracked'
                             f' PS transactions: {str(e)}')
        finally:
            _find_uncompleted = self._fix_uncompleted_ps_txs
            await self.loop.run_in_executor(None, _find_uncompleted)
            with self.state_lock:
                if self.state != PSStates.Errored:
                    self.state = PSStates.Ready
            self.trigger_callback('ps-state-changes', w, None, None)
        return found

    def _fix_uncompleted_ps_txs(self):
        w = self.wallet
        ps_txs = w.db.get_ps_txs()
        ps_txs_removed = w.db.get_ps_txs_removed()
        found = 0
        failed = 0
        for txid, (tx_type, completed) in ps_txs.items():
            if completed:
                continue
            tx = w.db.get_transaction(txid)
            if tx:
                try:
                    self.logger.info(f'_fix_uncompleted_ps_txs:'
                                     f' add {txid} ps data')
                    self._add_ps_data(txid, tx, tx_type)
                    found += 1
                except Exception as e:
                    str_err = f'_add_ps_data {txid} failed: {str(e)}'
                    failed += 1
                    self.logger.info(str_err)
        for txid, (tx_type, completed) in ps_txs_removed.items():
            if completed:
                continue
            tx = w.db.get_transaction(txid)
            if tx:
                try:
                    self.logger.info(f'_fix_uncompleted_ps_txs:'
                                     f' rm {txid} ps data')
                    self._rm_ps_data(txid, tx, tx_type)
                    found += 1
                except Exception as e:
                    str_err = f'_rm_ps_data {txid} failed: {str(e)}'
                    failed += 1
                    self.logger.info(str_err)
        if failed != 0:
            with self.state_lock:
                self.state = PSStates.Errored
        if found:
            self.postpone_notification('ps-data-changes', w)

    def _get_simplified_history(self):
        w = self.wallet
        history = []
        for txid in w.db.list_transactions():
            tx = w.db.get_transaction(txid)
            tx_type, completed = w.db.get_ps_tx(txid)
            islock = w.db.get_islock(txid)
            if islock:
                tx_mined_status = w.get_tx_height(txid)
                islock_sort = txid if not tx_mined_status.conf else ''
            else:
                islock_sort = ''
            history.append((txid, tx, tx_type, islock, islock_sort))
        history.sort(key=lambda x: (w.get_txpos(x[0], x[3]), x[4]))
        return history

    @profiler
    def _find_untracked_ps_txs(self, log):
        if log:
            self.logger.info(f'Finding untracked PrivateSend transactions')
        history = self._get_simplified_history()
        all_detected_txs = set()
        found = 0
        while True:
            detected_txs = set()
            not_detected_parents = set()
            for txid, tx, tx_type, islock, islock_sort in history:
                if tx_type or txid in all_detected_txs:  # already found
                    continue
                tx_type = self._check_ps_tx_type(txid, tx, find_untracked=True)
                if tx_type:
                    self._add_ps_data(txid, tx, tx_type)
                    type_name = SPEC_TX_NAMES[tx_type]
                    if log:
                        self.logger.info(f'Found {type_name} {txid}')
                    found += 1
                    detected_txs.add(txid)
                else:
                    parents = set([i['prevout_hash'] for i in tx.inputs()])
                    not_detected_parents |= parents
            all_detected_txs |= detected_txs
            if not detected_txs & not_detected_parents:
                break
        # last iteration to detect PS Other Coins not found before other ps txs
        for txid, tx, tx_type, islock, islock_sort in history:
            if tx_type or txid in all_detected_txs:  # already found
                continue
            tx_type = self._check_ps_tx_type(txid, tx, find_untracked=True,
                                             last_iteration=True)
            if tx_type:
                self._add_ps_data(txid, tx, tx_type)
                type_name = SPEC_TX_NAMES[tx_type]
                if log:
                    self.logger.info(f'Found {type_name} {txid}')
                found += 1
        if not found and log:
            self.logger.info(f'No untracked PrivateSend'
                             f' transactions found')
        return found

    def prob_denominate_tx_coin(self, c, check_inputs_vals=False):
        w = self.wallet
        val = c['value']
        if val not in PS_DENOMS_VALS:
            return

        prev_txid = c['prevout_hash']
        prev_tx = w.db.get_transaction(prev_txid)
        if not prev_tx:
            return

        inputs = prev_tx.inputs()
        outputs = prev_tx.outputs()
        inputs_cnt = len(inputs)
        outputs_cnt = len(outputs)
        if inputs_cnt != outputs_cnt:
            return

        dval_outputs_cnt = 0
        mine_outputs_cnt = 0
        for o in outputs:
            if o.value != val:
                break
            dval_outputs_cnt += 1
            mine_outputs_cnt += 1 if w.is_mine(o.address) else 0
        if dval_outputs_cnt != outputs_cnt:
            return
        if mine_outputs_cnt == outputs_cnt:
            return

        if not check_inputs_vals:
            return True

        dval_inputs_cnt = 0
        for prev_txin in prev_tx.inputs():
            is_denominate_input = False
            try:
                prev_txin_txid = prev_txin['prevout_hash']
                prev_txin_tx = w.get_input_tx(prev_txin_txid)
                if not prev_txin_tx:
                    return
                prev_txin_tx_outputs = prev_txin_tx.outputs()
                prev_txin_tx_outputs_cnt = len(prev_txin_tx_outputs)
                prev_txin_tx_dval_out_cnt = 0
                for o in prev_txin_tx_outputs:
                    if o.value == val:
                        prev_txin_tx_dval_out_cnt +=1
                if (prev_txin_tx_outputs_cnt == prev_txin_tx_dval_out_cnt):
                    is_denominate_input = True
            except:
                continue
            if is_denominate_input:
                dval_inputs_cnt += 1
        if dval_inputs_cnt != inputs_cnt:
            return
        return True

    def find_common_ancestor(self, utxo_a, utxo_b, search_depth=5):
        w = self.wallet
        min_common_depth = 1e9
        cur_depth = 0
        cur_utxos_a = [(utxo_a, ())]
        cur_utxos_b = [(utxo_b, ())]
        txids_a = {}
        txids_b = {}
        while cur_depth <= search_depth:
            next_utxos_a = []
            for utxo, path in cur_utxos_a:
                txid = utxo['prevout_hash']
                txid_path = path + (txid, )
                txids_a[txid] = txid_path
                tx = w.db.get_transaction(txid)
                if tx:
                    for txin in tx.inputs():
                        txin = copy.deepcopy(txin)
                        self.add_input_info(txin)
                        addr = txin['address']
                        if addr and w.is_mine(addr):
                            next_utxos_a.append((txin, txid_path))
            cur_utxos_a = next_utxos_a[:]

            next_utxos_b = []
            for utxo, path in cur_utxos_b:
                txid = utxo['prevout_hash']
                txid_path = path + (txid, )
                txids_b[txid] = txid_path
                tx = w.db.get_transaction(txid)
                if tx:
                    for txin in tx.inputs():
                        txin = copy.deepcopy(txin)
                        self.add_input_info(txin)
                        addr = txin['address']
                        if addr and w.is_mine(addr):
                            next_utxos_b.append((txin, txid_path))
            cur_utxos_b = next_utxos_b[:]

            common_txids = set(txids_a).intersection(txids_b)
            if common_txids:
                res = {'paths_a': [], 'paths_b': []}
                for txid in common_txids:
                    path_a = txids_a[txid]
                    path_b = txids_b[txid]
                    min_common_depth = min(min_common_depth, len(path_a) - 1)
                    min_common_depth = min(min_common_depth, len(path_b) - 1)
                    res['paths_a'].append(path_a)
                    res['paths_b'].append(path_b)
                res['min_common_depth'] = min_common_depth
                return res

            cur_utxos_a = next_utxos_a[:]
            cur_depth += 1
