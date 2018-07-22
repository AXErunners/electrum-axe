import time
import string

from . import bitcoin
from . import ecc
from .transaction import BCDataStream, Transaction
from . import util
from .util import bfh
from .i18n import _
from . import constants

BUDGET_PAYMENTS_CYCLE_BLOCKS = 50 if constants.net.TESTNET else 16616
SUBSIDY_HALVING_INTERVAL = 210240

safe_characters = string.ascii_letters + " .,;-_/:?@()"
def is_safe(s):
    return all(i in safe_characters for i in s)

class BudgetProposal(object):
    """A budget proposal.

    Attributes:
        - proposal_name (str): Name of the proposal.
        - proposal_url (str): URL where the proposal can be reached.
        - start_block (int): Starting block of payments.
        - end_block (int): Ending block of payments.
        - payment_amount (int): Monthly payment amount in satoshis.
        - address (str): Payment recipient.
        - fee_txid (str): Collateral transaction ID.
        - submitted (bool): Whether the proposal has been submitted.
        - rejected (bool): Whether the proposal was rejected as invalid.

    Optional attributes used when displaying proposals from the network:
        - yes_count (int): Number of votes in favor of the proposal.
        - no_count (int): Number of votes against the proposal.

    """
    @classmethod
    def from_dict(cls, d):
        return cls(**util.utfify(d))

    def __init__(self, proposal_name='', proposal_url='', start_block=0, end_block=0,
                payment_amount=0, address='', fee_txid='', submitted=False, rejected=False,
                yes_count=0, no_count=0):
        self.proposal_name = proposal_name
        self.proposal_url = proposal_url
        self.start_block = start_block
        self.end_block = end_block
        self.payment_amount = payment_amount
        self.address = address
        self.fee_txid = fee_txid
        self.submitted = submitted
        self.rejected = rejected

        self.yes_count = yes_count
        self.no_count = no_count

    def get_hash(self):
        vds = BCDataStream()
        vds.write_string(self.proposal_name)
        vds.write_string(self.proposal_url)
        vds.write_int32(self.start_block)
        vds.write_int32(self.end_block)
        vds.write_int64(self.payment_amount)
        vds.write_string(bfh(Transaction.pay_script(bitcoin.TYPE_ADDRESS, self.address)))
        return bitcoin.hash_encode(bitcoin.Hash(vds.input))

    def dump(self):
        kwargs = {}
        for i in ['proposal_name', 'proposal_url', 'start_block',
                'end_block', 'payment_amount', 'address', 'fee_txid', 'submitted', 'rejected']:
            kwargs[i] = getattr(self, i)
        return kwargs

    def get_payments_count(self):
        """Get the number of payments that this proposal entails."""
        return (self.end_block - self.start_block) / BUDGET_PAYMENTS_CYCLE_BLOCKS

    def set_payments_count(self, count):
        """Set end_block according to a number of payments."""
        payments_start = self.start_block - self.start_block % BUDGET_PAYMENTS_CYCLE_BLOCKS
        self.end_block = payments_start + BUDGET_PAYMENTS_CYCLE_BLOCKS * count
        return True

    def check_valid(self):
        """Evaluate whether this proposal is valid."""
        if not self.proposal_name:
            raise ValueError(_('A proposal name is required.'))
        elif len(self.proposal_name) > 20:
            raise ValueError(_('Proposal names have a limit of 20 characters.'))
        if not is_safe(self.proposal_name):
            raise ValueError(_('Unsafe characters in proposal name.'))

        if not self.proposal_url:
            raise ValueError(_('A proposal URL is required.'))
        elif len(self.proposal_url) > 64:
            raise ValueError(_('Proposal URLs have a limit of 64 characters.'))
        if not is_safe(self.proposal_url):
            raise ValueError(_('Unsafe characters in proposal URL.'))

        if self.end_block < self.start_block:
            raise ValueError(_('End block must be after start block.'))

        if not bitcoin.is_address(self.address):
            raise ValueError(_('Invalid address:') + ' %s' % self.address)
        addrtype, h160 = bitcoin.b58_address_to_hash160(self.address)
        if addrtype != constants.net.ADDRTYPE_P2PKH:
            raise ValueError(_('Only P2PKH addresses are currently supported.'))

        if self.payment_amount < bitcoin.COIN:
            raise ValueError(_('Payments must be at least 1 DASH.'))

        # Calculate max budget.
        subsidy = 5 * bitcoin.COIN
        if constants.net.TESTNET:
            for i in range(46200, self.start_block + 1, SUBSIDY_HALVING_INTERVAL):
                subsidy -= subsidy/14
        else:
            for i in range(SUBSIDY_HALVING_INTERVAL, self.start_block + 1, SUBSIDY_HALVING_INTERVAL):
                subsidy -= subsidy/14

        # 10%
        total_budget = ((subsidy/100)*10) * BUDGET_PAYMENTS_CYCLE_BLOCKS
        if self.payment_amount > total_budget:
            raise ValueError(_('Payment is more than max') + ' (%s).' % util.format_satoshis_plain(total_budget))


class BudgetVote(object):
    """A vote on a budget proposal."""
    @classmethod
    def from_dict(cls, d):
        return cls(**util.utfify(d))

    def __init__(self, vin=None, proposal_hash='', vote='ABSTAIN', timestamp=0):
        if vin is None:
            vin = {'prevout_hash':'', 'prevout_n': 0, 'scriptSig': '', 'sequence':0xffffffff}
        self.vin = vin
        self.proposal_hash = proposal_hash
        self.vote = vote
        self.timestamp = timestamp

    def serialize_for_sig(self, update_time=True):
        """Serialize the vote for signing."""
        if update_time:
            self.timestamp = int(time.time())

        s = self.get_vin_short()
        s += self.proposal_hash
        vote = '1' if self.vote.upper() == 'YES' else '0'
        s += vote

        s += str(self.timestamp)
        return s

    def sign(self, wif, current_time=None):
        """Sign the vote."""
        update_time = True
        if current_time is not None:
            self.timestamp = current_time
            update_time = False

        txin_type, key, is_compressed = bitcoin.deserialize_privkey(wif)
        delegate_pubkey = bfh(ecc.ECPrivkey(key)
            .get_public_key_hex(compressed=is_compressed))
        eckey = ecc.ECPrivkey(key)
        serialized = self.serialize_for_sig(update_time=update_time)
        return eckey.sign_message(serialized, is_compressed)

    def get_vin_short(self):
        return '%s-%d' % (self.vin['prevout_hash'], self.vin['prevout_n'])

    def dump(self):
        kwargs = {}
        for i in ['vin', 'proposal_hash', 'vote', 'timestamp']:
            kwargs[i] = getattr(self, i)
        return kwargs
