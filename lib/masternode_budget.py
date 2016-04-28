import time

import bitcoin
from transaction import BCDataStream, Transaction
import util

BUDGET_PAYMENTS_CYCLE_BLOCKS = 50 if bitcoin.TESTNET else 16616

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

    """
    @classmethod
    def from_dict(cls, d):
        return cls(**util.utfify(d))

    def __init__(self, proposal_name='', proposal_url='', start_block=0, end_block=0,
                payment_amount=0, address='', fee_txid='', submitted=False):
        self.proposal_name = proposal_name
        self.proposal_url = proposal_url
        self.start_block = start_block
        self.end_block = end_block
        self.payment_amount = payment_amount
        self.address = address
        self.fee_txid = fee_txid
        self.submitted = submitted

    def get_hash(self):
        vds = BCDataStream()
        vds.write_string(self.proposal_name)
        vds.write_string(self.proposal_url)
        vds.write_int32(self.start_block)
        vds.write_int32(self.end_block)
        vds.write_int64(self.payment_amount)
        vds.write_string(Transaction.pay_script('address', self.address).decode('hex'))
        return bitcoin.hash_encode(bitcoin.Hash(vds.input))

    def dump(self):
        kwargs = {}
        for i in ['proposal_name', 'proposal_url', 'start_block',
                'end_block', 'payment_amount', 'address', 'fee_txid', 'submitted']:
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
        s += self.vote

        s += str(self.timestamp)
        return s

    def sign(self, wif, current_time=None):
        """Sign the vote."""
        update_time = True
        if current_time is not None:
            self.timestamp = current_time
            update_time = False

        delegate_pubkey = bitcoin.public_key_from_private_key(wif).decode('hex')
        eckey = bitcoin.regenerate_key(wif)
        serialized = unicode(self.serialize_for_sig(update_time=update_time)).encode('utf-8')
        return eckey.sign_message(serialized, bitcoin.is_compressed(wif),
                bitcoin.public_key_to_bc_address(delegate_pubkey))

    def get_vin_short(self):
        return '%s-%d' % (self.vin['prevout_hash'], self.vin['prevout_n'])

    def dump(self):
        kwargs = {}
        for i in ['vin', 'proposal_hash', 'vote', 'timestamp']:
            kwargs[i] = getattr(self, i)
        return kwargs
