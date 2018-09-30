from collections import namedtuple, OrderedDict
import base64
import threading
from decimal import Decimal

from . import bitcoin
from . import ecc
from .blockchain import hash_header
from .masternode import MasternodeAnnounce, NetworkAddress
from .masternode_budget import BudgetProposal, BudgetVote
from .util import AlreadyHaveAddress, print_error, bfh
from .util import format_satoshis_plain

BUDGET_FEE_CONFIRMATIONS = 6
BUDGET_FEE_TX = 5 * bitcoin.COIN
# From masternode.h
MASTERNODE_MIN_CONFIRMATIONS = 15

MasternodeConfLine = namedtuple('MasternodeConfLine', ('alias', 'addr',
        'wif', 'txid', 'output_index'))

def parse_masternode_conf(lines):
    """Construct MasternodeConfLine instances from lines of a masternode.conf file."""
    conf_lines = []
    for line in lines:
        # Comment.
        if line.startswith('#'):
            continue

        s = line.split(' ')
        if len(s) < 5:
            continue
        alias = s[0]
        addr_str = s[1]
        masternode_wif = s[2]
        collateral_txid = s[3]
        collateral_output_n = s[4]

        # Validate input.
        try:
            txin_type, key, is_compressed = bitcoin.deserialize_privkey(masternode_wif)
            assert key
        except Exception:
            raise ValueError('Invalid masternode private key of alias "%s"' % alias)

        if len(collateral_txid) != 64:
            raise ValueError('Transaction ID of alias "%s" must be 64 hex characters.' % alias)

        try:
            collateral_output_n = int(collateral_output_n)
        except ValueError:
            raise ValueError('Transaction output index of alias "%s" must be an integer.' % alias)

        conf_lines.append(MasternodeConfLine(alias, addr_str, masternode_wif, collateral_txid, collateral_output_n))
    return conf_lines

def parse_proposals_subscription_result(results):
    """Parse the proposals subscription response."""
    proposals = []
    for k, result in results.items():
        kwargs = {'proposal_name': result['Name'], 'proposal_url': result['URL'],
                'start_block': int(result['BlockStart']), 'end_block': int(result['BlockEnd']),
                'payment_amount': result['MonthlyPayment'], 'address': result['PaymentAddress']}

        fee_txid_key = 'FeeTXHash' if result.get('FeeTXHash') else 'FeeHash'
        kwargs['fee_txid'] = result[fee_txid_key]
        yes_count_key = 'YesCount' if result.get('YesCount') else 'Yeas'
        kwargs['yes_count'] = result[yes_count_key]
        no_count_key = 'NoCount' if result.get('NoCount') else 'Nays'
        kwargs['no_count'] = result[no_count_key]

        payment_amount = Decimal(str(kwargs['payment_amount']))
        kwargs['payment_amount'] = pow(10, 8) * payment_amount
        proposals.append(BudgetProposal.from_dict(kwargs))

    print_error('Received updated budget proposal information (%d proposals)' % len(proposals))
    return proposals

class MasternodeManager(object):
    """Masternode manager.

    Keeps track of masternodes and helps with signing broadcasts.
    """
    def __init__(self, wallet, config):
        self.network_event = threading.Event()
        self.wallet = wallet
        self.config = config
        # Subscribed masternode statuses.
        self.masternode_statuses = {}

        self.load()

    def load(self):
        """Load masternodes from wallet storage."""
        masternodes = self.wallet.storage.get('masternodes', {})
        self.masternodes = [MasternodeAnnounce.from_dict(d) for d in masternodes.values()]
        proposals = self.wallet.storage.get('budget_proposals', {})
        self.proposals = [BudgetProposal.from_dict(d) for d in proposals.values()]
        self.budget_votes = [BudgetVote.from_dict(d) for d in self.wallet.storage.get('budget_votes', [])]

    def send_subscriptions(self):
        if not self.wallet.network.is_connected():
            return
        self.subscribe_to_masternodes()

    def subscribe_to_masternodes(self):
        for mn in self.masternodes:
            if not mn.announced:
                continue
            collateral = mn.get_collateral_str()
            if self.masternode_statuses.get(collateral) is None:
                req = ('masternode.subscribe', [collateral])
                self.wallet.network.send([req], self.masternode_subscription_response)
                self.masternode_statuses[collateral] = ''

    def get_masternode(self, alias):
        """Get the masternode labelled as alias."""
        for mn in self.masternodes:
            if mn.alias == alias:
                return mn

    def get_masternode_by_hash(self, hash_):
        for mn in self.masternodes:
            if mn.get_hash() == hash_:
                return mn

    def add_masternode(self, mn, save = True):
        """Add a new masternode."""
        if any(i.alias == mn.alias for i in self.masternodes):
            raise Exception('A masternode with alias "%s" already exists' % mn.alias)
        self.masternodes.append(mn)
        if save:
            self.save()

    def remove_masternode(self, alias, save = True):
        """Remove the masternode labelled as alias."""
        mn = self.get_masternode(alias)
        if not mn:
            raise Exception('Nonexistent masternode')
        # Don't delete the delegate key if another masternode uses it too.
        if not any(i.alias != mn.alias and i.delegate_key == mn.delegate_key for i in self.masternodes):
            self.wallet.delete_masternode_delegate(mn.delegate_key)

        self.masternodes.remove(mn)
        if save:
            self.save()

    def populate_masternode_output(self, alias):
        """Attempt to populate the masternode's data using its output."""
        mn = self.get_masternode(alias)
        if not mn:
            return
        if mn.announced:
            return
        txid = mn.vin.get('prevout_hash')
        prevout_n = mn.vin.get('prevout_n')
        if not txid or prevout_n is None:
            return
        # Return if it already has the information.
        if mn.collateral_key and mn.vin.get('address') and mn.vin.get('value') == 1000 * bitcoin.COIN:
            return

        tx = self.wallet.transactions.get(txid)
        if not tx:
            return
        if len(tx.outputs()) <= prevout_n:
            return
        _, addr, value = tx.outputs()[prevout_n]
        mn.vin['address'] = addr
        mn.vin['value'] = value
        mn.vin['scriptSig'] = ''

        mn.collateral_key = self.wallet.get_public_keys(addr)[0]
        self.save()
        return True

    def get_masternode_outputs(self, domain = None, exclude_frozen = True):
        """Get spendable coins that can be used as masternode collateral."""
        excluded = self.wallet.frozen_addresses if exclude_frozen else None
        coins = self.wallet.get_utxos(domain, excluded,
                                      mature=True, confirmed_only=True)

        used_vins = map(lambda mn: '%s:%d' % (mn.vin.get('prevout_hash'), mn.vin.get('prevout_n', 0xffffffff)), self.masternodes)
        unused = lambda d: '%s:%d' % (d['prevout_hash'], d['prevout_n']) not in used_vins
        correct_amount = lambda d: d['value'] == 1000 * bitcoin.COIN

        # Valid outputs have a value of exactly 1000 DASH and
        # are not in use by an existing masternode.
        is_valid = lambda d: correct_amount(d) and unused(d)

        coins = filter(is_valid, coins)
        return coins

    def get_delegate_privkey(self, pubkey):
        """Return the private delegate key for pubkey (if we have it)."""
        return self.wallet.get_delegate_private_key(pubkey)

    def check_can_sign_masternode(self, alias):
        """Raise an exception if alias can't be signed and announced to the network."""
        mn = self.get_masternode(alias)
        if not mn:
            raise Exception('Nonexistent masternode')
        if not mn.vin.get('prevout_hash'):
            raise Exception('Collateral payment is not specified')
        if not mn.collateral_key:
            raise Exception('Collateral key is not specified')
        if not mn.delegate_key:
            raise Exception('Masternode delegate key is not specified')
        if not mn.addr.ip:
            raise Exception('Masternode has no IP address')

        # Ensure that the collateral payment has >= MASTERNODE_MIN_CONFIRMATIONS.
        tx_height = self.wallet.get_tx_height(mn.vin['prevout_hash'])
        if tx_height.conf < MASTERNODE_MIN_CONFIRMATIONS:
            raise Exception('Collateral payment must have at least %d confirmations (current: %d)' % (MASTERNODE_MIN_CONFIRMATIONS, conf))
        # Ensure that the masternode's vin is valid.
        if mn.vin.get('value', 0) != bitcoin.COIN * 1000:
            raise Exception('Masternode requires a collateral 1000 DASH output.')

        # If the masternode has been announced, it can be announced again if it has been disabled.
        if mn.announced:
            status = self.masternode_statuses.get(mn.get_collateral_str())
            if status in ['PRE_ENABLED', 'ENABLED']:
                raise Exception('Masternode has already been activated')

    def save(self):
        """Save masternodes."""
        masternodes = {}
        for mn in self.masternodes:
            masternodes[mn.alias] = mn.dump()
        proposals = {p.get_hash(): p.dump() for p in self.proposals}
        votes = [v.dump() for v in self.budget_votes]

        self.wallet.storage.put('masternodes', masternodes)
        self.wallet.storage.put('budget_proposals', proposals)
        self.wallet.storage.put('budget_votes', votes)

    def sign_announce(self, alias, password):
        """Sign a Masternode Announce message for alias."""
        self.check_can_sign_masternode(alias)
        mn = self.get_masternode(alias)
        # Ensure that the masternode's vin is valid.
        if mn.vin.get('scriptSig') is None:
            mn.vin['scriptSig'] = ''
        if mn.vin.get('sequence') is None:
            mn.vin['sequence'] = 0xffffffff
        # Ensure that the masternode's last_ping is current.
        height = self.wallet.get_local_height() - 12
        blockchain = self.wallet.network.blockchain()
        header = blockchain.read_header(height)
        mn.last_ping.block_hash = hash_header(header)
        mn.last_ping.vin = mn.vin

        # Sign ping with delegate key.
        self.wallet.sign_masternode_ping(mn.last_ping, mn.delegate_key)

        # After creating the Masternode Ping, sign the Masternode Announce.
        address = bitcoin.public_key_to_p2pkh(bfh(mn.collateral_key))
        mn.sig = self.wallet.sign_message(address, mn.serialize_for_sig(update_time=True), password)

        return mn

    def send_announce(self, alias):
        """Broadcast a Masternode Announce message for alias to the network.

        Returns a 2-tuple of (error_message, was_announced).
        """
        if not self.wallet.network.is_connected():
            raise Exception('Not connected')

        mn = self.get_masternode(alias)
        # Vector-serialize the masternode.
        serialized = '01' + mn.serialize()
        errmsg = []
        callback = lambda r: self.broadcast_announce_callback(alias, errmsg, r)
        self.network_event.clear()
        self.wallet.network.send([('masternode.announce.broadcast', [serialized])], callback)
        self.network_event.wait()
        self.subscribe_to_masternodes()
        if errmsg:
            errmsg = errmsg[0]
        return (errmsg, mn.announced)

    def broadcast_announce_callback(self, alias, errmsg, r):
        """Callback for when a Masternode Announce message is broadcasted."""
        try:
            self.on_broadcast_announce(alias, r)
        except Exception as e:
            errmsg.append(str(e))
        finally:
            self.save()
            self.network_event.set()

    def on_broadcast_announce(self, alias, r):
        """Validate the server response."""
        err = r.get('error')
        if err:
            raise Exception('Error response: %s' % str(err))

        result = r.get('result')

        mn = self.get_masternode(alias)
        mn_hash = mn.get_hash()
        mn_dict = result.get(mn_hash)
        if not mn_dict:
            raise Exception('No result for expected Masternode Hash. Got %s' % result)

        if mn_dict.get('errorMessage'):
            raise Exception('Announce was rejected: %s' % mn_dict['errorMessage'])
        if mn_dict.get(mn_hash) != 'successful':
            raise Exception('Announce was rejected (no error message specified)')

        mn.announced = True

    def import_masternode_delegate(self, sec):
        """Import a WIF delegate key.

        An exception will not be raised if the key is already imported.
        """
        try:
            pubkey = self.wallet.import_masternode_delegate(sec)
        except AlreadyHaveAddress:
            txin_type, key, is_compressed = bitcoin.deserialize_privkey(sec)
            pubkey = ecc.ECPrivkey(key)\
                .get_public_key_hex(compressed=is_compressed)
        return pubkey

    def import_masternode_conf_lines(self, conf_lines, password):
        """Import a list of MasternodeConfLine."""
        def already_have(line):
            for masternode in self.masternodes:
                # Don't let aliases collide.
                if masternode.alias == line.alias:
                    return True
                # Don't let outputs collide.
                if masternode.vin.get('prevout_hash') == line.txid and masternode.vin.get('prevout_n') == line.output_index:
                    return True
            return False

        num_imported = 0
        for conf_line in conf_lines:
            if already_have(conf_line):
                continue
            # Import delegate WIF key for signing last_ping.
            public_key = self.import_masternode_delegate(conf_line.wif)

            addr = conf_line.addr.split(':')
            addr = NetworkAddress(ip=addr[0], port=int(addr[1]))
            vin = {'prevout_hash': conf_line.txid, 'prevout_n': conf_line.output_index}
            mn = MasternodeAnnounce(alias=conf_line.alias, vin=vin,  
                    delegate_key = public_key, addr=addr)
            self.add_masternode(mn)
            try:
                self.populate_masternode_output(mn.alias)
            except Exception as e:
                print_error(str(e))
            num_imported += 1

        return num_imported



    def get_votes(self, alias):
        """Get budget votes that alias has cast."""
        mn = self.get_masternode(alias)
        if not mn:
            raise Exception('Nonexistent masternode')
        return filter(lambda v: v.vin == mn.vin, self.budget_votes)

    def check_can_vote(self, alias, proposal_name):
        """Raise an exception if alias can't vote for proposal name."""
        if not self.wallet.network.is_connected():
            raise Exception('Not connected')
        # Get the proposal that proposal_name identifies.
        proposal = None
        for p in self.wallet.network.all_proposals:
            if p.proposal_name == proposal_name:
                proposal = p
                break
        else:
            raise Exception('Unknown proposal')

        # Make sure the masternode hasn't already voted.
        proposal_hash = proposal.get_hash()
        previous_votes = self.get_votes(alias)
        if any(v.proposal_hash == proposal_hash for v in previous_votes):
            raise Exception('Masternode has already voted on this proposal')

        mn = self.get_masternode(alias)
        if not mn.announced:
            raise Exception('Masternode has not been activated')
        else:
            status = self.masternode_statuses.get(mn.get_collateral_str())
            if status not in ['PRE_ENABLED', 'ENABLED']:
                raise Exception('Masternode is not currently enabled')

    def vote(self, alias, proposal_name, vote_choice):
        """Vote on a budget proposal."""
        self.check_can_vote(alias, proposal_name)
        # Validate vote choice.
        if vote_choice.upper() not in ('YES', 'NO'):
            raise ValueError('Invalid vote choice: "%s"' % vote_choice)

        # Create the vote.
        mn = self.get_masternode(alias)
        vote = BudgetVote(vin=mn.vin, proposal_hash=proposal_hash, vote=vote_choice)

        # Sign the vote with delegate key.
        sig = self.wallet.sign_budget_vote(vote, mn.delegate_key)

        return self.send_vote(vote, base64.b64encode(sig))

    def send_vote(self, vote, sig):
        """Broadcast vote to the network.

        Returns a 2-tuple of (error_message, success).
        """
        errmsg = []
        callback = lambda r: self.broadcast_vote_callback(vote, errmsg, r)
        params = [vote.vin['prevout_hash'], vote.vin['prevout_n'], vote.proposal_hash, vote.vote.lower(),
                vote.timestamp, sig]
        self.network_event.clear()
        self.wallet.network.send([('masternode.budget.submitvote', params)], callback)
        self.network_event.wait()
        if errmsg:
            return (errmsg[0], False)
        return (errmsg, True)

    def broadcast_vote_callback(self, vote, errmsg, r):
        """Callback for when a vote is broadcast."""
        if r.get('error'):
            errmsg.append(r['error'])
        else:
            self.budget_votes.append(vote)
            self.save()

        self.network_event.set()



    def get_proposal(self, name):
        for proposal in self.proposals:
            if proposal.proposal_name == name:
                return proposal

    def add_proposal(self, proposal, save = True):
        """Add a new proposal."""
        if proposal in self.proposals:
            raise Exception('Proposal already exists')
        self.proposals.append(proposal)
        if save:
            self.save()

    def remove_proposal(self, proposal_name, save = True):
        """Remove the proposal named proposal_name."""
        proposal = self.get_proposal(proposal_name)
        if not proposal:
            raise Exception('Proposal does not exist')
        self.proposals.remove(proposal)
        if save:
            self.save()

    def create_proposal_tx(self, proposal_name, password, save = True):
        """Create a fee transaction for proposal_name."""
        proposal = self.get_proposal(proposal_name)
        if proposal.fee_txid:
            print_error('Warning: Proposal "%s" already has a fee tx: %s' % (proposal_name, proposal.fee_txid))
        if proposal.submitted:
            raise Exception('Proposal has already been submitted')

        h = bfh(bitcoin.hash_decode(proposal.get_hash()))
        script = '6a20' + h # OP_RETURN hash
        outputs = [(bitcoin.TYPE_SCRIPT, bfh(script), BUDGET_FEE_TX)]
        tx = self.wallet.mktx(outputs, password, self.config)
        proposal.fee_txid = tx.hash()
        if save:
            self.save()
        return tx

    def submit_proposal(self, proposal_name, save = True):
        """Submit the proposal for proposal_name."""
        proposal = self.get_proposal(proposal_name)
        if not proposal.fee_txid:
            raise Exception('Proposal has no fee transaction')
        if proposal.submitted:
            raise Exception('Proposal has already been submitted')

        if not self.wallet.network.is_connected():
            raise Exception('Not connected')

        tx_height = self.wallet.get_tx_height(proposal.fee_txid)
        if tx_height.conf < BUDGET_FEE_CONFIRMATIONS:
            raise Exception('Collateral requires at least %d confirmations' % BUDGET_FEE_CONFIRMATIONS)

        payments_count = proposal.get_payments_count()
        payment_amount = format_satoshis_plain(proposal.payment_amount)
        params = [proposal.proposal_name, proposal.proposal_url, payments_count, proposal.start_block, proposal.address, payment_amount, proposal.fee_txid]

        errmsg = []
        callback = lambda r: self.submit_proposal_callback(proposal.proposal_name, errmsg, r, save)
        self.network_event.clear()
        self.wallet.network.send([('masternode.budget.submit', params)], callback)
        self.network_event.wait()
        if errmsg:
            errmsg = errmsg[0]
        return (errmsg, proposal.submitted)

    def submit_proposal_callback(self, proposal_name, errmsg, r, save = True):
        """Callback for when a proposal has been submitted."""
        try:
            self.on_proposal_submitted(proposal_name, r)
        except Exception as e:
            errmsg.append(str(e))
        finally:
            if save:
                self.save()
            self.network_event.set()

    def on_proposal_submitted(self, proposal_name, r):
        """Validate the server response."""
        proposal = self.get_proposal(proposal_name)
        err = r.get('error')
        if err:
            proposal.rejected = True
            raise Exception('Error response: %s' % str(err))

        result = r.get('result')

        if proposal.get_hash() != result:
            raise Exception('Invalid proposal hash from server: %s' % result)

        proposal.submitted = True

    def masternode_subscription_response(self, response):
        """Callback for when a masternode's status changes."""
        collateral = response['params'][0]
        mn = None
        for masternode in self.masternodes:
            if masternode.get_collateral_str() == collateral:
                mn = masternode
                break

        if not mn:
            return

        if not 'result' in response:
            return

        status = response['result']
        if status is None:
            status = False
        print_error('Received updated status for masternode %s: "%s"' % (mn.alias, status))
        self.masternode_statuses[collateral] = status
