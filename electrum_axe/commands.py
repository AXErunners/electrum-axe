#!/usr/bin/env python
#
# Electrum - lightweight Bitcoin client
# Copyright (C) 2011 thomasv@gitorious
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

import os
import sys
import datetime
import copy
import argparse
import json
import ast
import base64
from functools import wraps
from decimal import Decimal
from typing import Optional, TYPE_CHECKING

from .import util, ecc
from .util import bfh, bh2u, format_satoshis, json_decode, json_encode, is_hash256_str, is_hex_str, to_bytes
from . import bitcoin
from .bitcoin import is_address,  hash_160, COIN, TYPE_ADDRESS
from .bip32 import BIP32Node
from .i18n import _
from .transaction import Transaction, multisig_script, TxOutput
from .paymentrequest import PR_PAID, PR_UNPAID, PR_UNKNOWN, PR_EXPIRED
from .synchronizer import Notifier
from .wallet import Abstract_Wallet, create_new_wallet, restore_wallet_from_text
from .address_synchronizer import TX_HEIGHT_LOCAL
from .masternode import MasternodeAnnounce
from .masternode_budget import BudgetProposal
from .masternode_manager import MasternodeManager, parse_masternode_conf, BUDGET_FEE_CONFIRMATIONS

if TYPE_CHECKING:
    from .network import Network
    from .simple_config import SimpleConfig


known_commands = {}


def satoshis(amount):
    # satoshi conversion must not be performed by the parser
    return int(COIN*Decimal(amount)) if amount not in ['!', None] else amount


class Command:
    def __init__(self, func, s):
        self.name = func.__name__
        self.requires_network = 'n' in s
        self.requires_wallet = 'w' in s
        self.requires_password = 'p' in s
        self.description = func.__doc__
        self.help = self.description.split('.')[0] if self.description else None
        varnames = func.__code__.co_varnames[1:func.__code__.co_argcount]
        self.defaults = func.__defaults__
        if self.defaults:
            n = len(self.defaults)
            self.params = list(varnames[:-n])
            self.options = list(varnames[-n:])
        else:
            self.params = list(varnames)
            self.options = []
            self.defaults = []


def command(s):
    def decorator(func):
        global known_commands
        name = func.__name__
        known_commands[name] = Command(func, s)
        @wraps(func)
        def func_wrapper(*args, **kwargs):
            c = known_commands[func.__name__]
            wallet = args[0].wallet
            password = kwargs.get('password')
            if c.requires_wallet and wallet is None:
                raise Exception("wallet not loaded. Use 'electrum-axe daemon load_wallet'")
            if c.requires_password and password is None and wallet.has_password():
                return {'error': 'Password required' }
            return func(*args, **kwargs)
        return func_wrapper
    return decorator


class Commands:

    def __init__(self, config: 'SimpleConfig', wallet: Abstract_Wallet,
                 network: Optional['Network'], callback=None):
        self.config = config
        self.wallet = wallet
        self.network = network
        self.masternode_manager = None
        if self.wallet:
            self.masternode_manager = MasternodeManager(self.wallet,
                                                        self.config)
        self._callback = callback

    def _run(self, method, args, password_getter):
        # this wrapper is called from the python console
        cmd = known_commands[method]
        if cmd.requires_password and self.wallet.has_password():
            password = password_getter()
            if password is None:
                return
        else:
            password = None

        f = getattr(self, method)
        if cmd.requires_password:
            result = f(*args, **{'password':password})
        else:
            result = f(*args)

        if self._callback:
            self._callback()
        return result

    @command('')
    def commands(self):
        """List of commands"""
        return ' '.join(sorted(known_commands.keys()))

    @command('')
    def create(self, passphrase=None, password=None, encrypt_file=True):
        """Create a new wallet.
        If you want to be prompted for an argument, type '?' or ':' (concealed)
        """
        d = create_new_wallet(path=self.config.get_wallet_path(),
                              passphrase=passphrase,
                              password=password,
                              encrypt_file=encrypt_file)
        return {
            'seed': d['seed'],
            'path': d['wallet'].storage.path,
            'msg': d['msg'],
        }

    @command('')
    def restore(self, text, passphrase=None, password=None, encrypt_file=True):
        """Restore a wallet from text. Text can be a seed phrase, a master
        public key, a master private key, a list of Axe addresses
        or Axe private keys.
        If you want to be prompted for an argument, type '?' or ':' (concealed)
        """
        d = restore_wallet_from_text(text,
                                     path=self.config.get_wallet_path(),
                                     passphrase=passphrase,
                                     password=password,
                                     encrypt_file=encrypt_file,
                                     network=self.network)
        return {
            'path': d['wallet'].storage.path,
            'msg': d['msg'],
        }

    @command('wp')
    def password(self, password=None, new_password=None):
        """Change wallet password. """
        if self.wallet.storage.is_encrypted_with_hw_device() and new_password:
            raise Exception("Can't change the password of a wallet encrypted with a hw device.")
        b = self.wallet.storage.is_encrypted()
        self.wallet.update_password(password, new_password, b)
        self.wallet.storage.write()
        return {'password':self.wallet.has_password()}

    @command('w')
    def get(self, key):
        """Return item from wallet storage"""
        return self.wallet.storage.get(key)

    @command('')
    def getconfig(self, key):
        """Return a configuration variable. """
        return self.config.get(key)

    @classmethod
    def _setconfig_normalize_value(cls, key, value):
        if key not in ('rpcuser', 'rpcpassword'):
            value = json_decode(value)
            try:
                value = ast.literal_eval(value)
            except:
                pass
        return value

    @command('')
    def setconfig(self, key, value):
        """Set a configuration variable. 'value' may be a string or a Python expression."""
        value = self._setconfig_normalize_value(key, value)
        self.config.set_key(key, value)
        return True

    @command('')
    def make_seed(self, nbits=132, language=None):
        """Create a seed"""
        from .mnemonic import Mnemonic
        t = 'standard'
        s = Mnemonic(language).make_seed(t, nbits)
        return s

    @command('n')
    def getaddresshistory(self, address):
        """Return the transaction history of any address. Note: This is a
        walletless server query, results are not checked by SPV.
        """
        sh = bitcoin.address_to_scripthash(address)
        return self.network.run_from_another_thread(self.network.get_history_for_scripthash(sh))

    @command('w')
    def listunspent(self):
        """List unspent outputs. Returns the list of unspent transaction
        outputs in your wallet."""
        l = copy.deepcopy(self.wallet.get_utxos())
        for i in l:
            v = i["value"]
            i["value"] = str(Decimal(v)/COIN) if v is not None else None
        return l

    @command('n')
    def getaddressunspent(self, address):
        """Returns the UTXO list of any address. Note: This
        is a walletless server query, results are not checked by SPV.
        """
        sh = bitcoin.address_to_scripthash(address)
        return self.network.run_from_another_thread(self.network.listunspent_for_scripthash(sh))

    @command('')
    def serialize(self, jsontx):
        """Create a transaction from json inputs.
        Inputs must have a redeemPubkey.
        Outputs must be a list of {'address':address, 'value':satoshi_amount}.
        """
        keypairs = {}
        if jsontx.get('extra_payload'):
            return {'error': 'Transactions with extra payload can not'
                             ' be created from serialize command'}
        inputs = jsontx.get('inputs')
        outputs = jsontx.get('outputs')
        locktime = jsontx.get('lockTime', 0)
        for txin in inputs:
            if txin.get('output'):
                prevout_hash, prevout_n = txin['output'].split(':')
                txin['prevout_n'] = int(prevout_n)
                txin['prevout_hash'] = prevout_hash
            sec = txin.get('privkey')
            if sec:
                txin_type, privkey, compressed = bitcoin.deserialize_privkey(sec)
                pubkey = ecc.ECPrivkey(privkey).get_public_key_hex(compressed=compressed)
                keypairs[pubkey] = privkey, compressed
                txin['type'] = txin_type
                txin['x_pubkeys'] = [pubkey]
                txin['signatures'] = [None]
                txin['num_sig'] = 1

        outputs = [TxOutput(TYPE_ADDRESS, x['address'], int(x['value'])) for x in outputs]
        tx = Transaction.from_io(inputs, outputs, locktime=locktime)
        tx.sign(keypairs)
        return tx.as_dict()

    @command('wp')
    def signtransaction(self, tx, privkey=None, password=None):
        """Sign a transaction. The wallet keys will be used unless a private key is provided."""
        tx = Transaction(tx)
        if privkey:
            txin_type, privkey2, compressed = bitcoin.deserialize_privkey(privkey)
            pubkey_bytes = ecc.ECPrivkey(privkey2).get_public_key_bytes(compressed=compressed)
            h160 = bitcoin.hash_160(pubkey_bytes)
            x_pubkey = 'fd' + bh2u(b'\x00' + h160)
            tx.sign({x_pubkey:(privkey2, compressed)})
        else:
            self.wallet.sign_transaction(tx, password)
        return tx.as_dict()

    @command('')
    def deserialize(self, tx):
        """Deserialize a serialized transaction"""
        tx = Transaction(tx)
        return tx.deserialize(force_full_parse=True,
                              extra_payload_for_json=True)

    @command('n')
    def broadcast(self, tx):
        """Broadcast a transaction to the network. """
        tx = Transaction(tx)
        self.network.run_from_another_thread(self.network.broadcast_transaction(tx))
        return tx.txid()

    @command('')
    def createmultisig(self, num, pubkeys):
        """Create multisig address"""
        assert isinstance(pubkeys, list), (type(num), type(pubkeys))
        redeem_script = multisig_script(pubkeys, num)
        address = bitcoin.hash160_to_p2sh(hash_160(bfh(redeem_script)))
        return {'address':address, 'redeemScript':redeem_script}

    @command('w')
    def freeze(self, address):
        """Freeze address. Freeze the funds at one of your wallet\'s addresses"""
        return self.wallet.set_frozen_state_of_addresses([address], True)

    @command('w')
    def unfreeze(self, address):
        """Unfreeze address. Unfreeze the funds at one of your wallet\'s address"""
        return self.wallet.set_frozen_state_of_addresses([address], False)

    @command('wp')
    def getprivatekeys(self, address, password=None):
        """Get private keys of addresses. You may pass a single wallet address, or a list of wallet addresses."""
        if isinstance(address, str):
            address = address.strip()
        if is_address(address):
            return self.wallet.export_private_key(address, password)[0]
        domain = address
        return [self.wallet.export_private_key(address, password)[0] for address in domain]

    @command('w')
    def ismine(self, address):
        """Check if address is in wallet. Return true if and only address is in wallet"""
        return self.wallet.is_mine(address)

    @command('')
    def dumpprivkeys(self):
        """Deprecated."""
        return "This command is deprecated. Use a pipe instead: 'electrum-axe listaddresses | electrum-axe getprivatekeys - '"

    @command('')
    def validateaddress(self, address):
        """Check that an address is valid. """
        return is_address(address)

    @command('w')
    def getpubkeys(self, address):
        """Return the public keys for a wallet address. """
        return self.wallet.get_public_keys(address)

    @command('w')
    def getbalance(self):
        """Return the balance of your wallet. """
        c, u, x = self.wallet.get_balance()
        out = {"confirmed": str(Decimal(c)/COIN)}
        if u:
            out["unconfirmed"] = str(Decimal(u)/COIN)
        if x:
            out["unmatured"] = str(Decimal(x)/COIN)
        return out

    @command('n')
    def getaddressbalance(self, address):
        """Return the balance of any address. Note: This is a walletless
        server query, results are not checked by SPV.
        """
        sh = bitcoin.address_to_scripthash(address)
        out = self.network.run_from_another_thread(self.network.get_balance_for_scripthash(sh))
        out["confirmed"] =  str(Decimal(out["confirmed"])/COIN)
        out["unconfirmed"] =  str(Decimal(out["unconfirmed"])/COIN)
        return out

    @command('n')
    def getmerkle(self, txid, height):
        """Get Merkle branch of a transaction included in a block. Axe Electrum
        uses this to verify transactions (Simple Payment Verification)."""
        return self.network.run_from_another_thread(self.network.get_merkle_for_transaction(txid, int(height)))

    @command('n')
    def getservers(self):
        """Return the list of available servers"""
        return self.network.get_servers()

    @command('')
    def version(self):
        """Return the version of Axe Electrum."""
        from .version import ELECTRUM_VERSION
        return ELECTRUM_VERSION

    @command('w')
    def getmpk(self):
        """Get master public key. Return your wallet\'s master public key"""
        return self.wallet.get_master_public_key()

    @command('wp')
    def getmasterprivate(self, password=None):
        """Get master private key. Return your wallet\'s master private key"""
        return str(self.wallet.keystore.get_master_private_key(password))

    @command('')
    def convert_xkey(self, xkey, xtype):
        """Convert xtype of a master key. e.g. xpub -> ypub"""
        try:
            node = BIP32Node.from_xkey(xkey)
        except:
            raise Exception('xkey should be a master public/private key')
        return node._replace(xtype=xtype).to_xkey()

    @command('wp')
    def getseed(self, password=None):
        """Get seed phrase. Print the generation seed of your wallet."""
        s = self.wallet.get_seed(password)
        return s

    @command('wp')
    def importprivkey(self, privkey, password=None):
        """Import a private key."""
        if not self.wallet.can_import_privkey():
            return "Error: This type of wallet cannot import private keys. Try to create a new wallet with that key."
        try:
            addr = self.wallet.import_private_key(privkey, password)
            out = "Keypair imported: " + addr
        except Exception as e:
            out = "Error: " + str(e)
        return out

    def _resolver(self, x):
        if x is None:
            return None
        out = self.wallet.contacts.resolve(x)
        if out.get('type') == 'openalias' and self.nocheck is False and out.get('validated') is False:
            raise Exception('cannot verify alias', x)
        return out['address']

    @command('n')
    def sweep(self, privkey, destination, fee=None, nocheck=False, imax=100):
        """Sweep private keys. Returns a transaction that spends UTXOs from
        privkey to a destination address. The transaction is not
        broadcasted."""
        from .wallet import sweep
        tx_fee = satoshis(fee)
        privkeys = privkey.split()
        self.nocheck = nocheck
        #dest = self._resolver(destination)
        tx = sweep(privkeys, self.network, self.config, destination, tx_fee, imax)
        return tx.as_dict() if tx else None

    @command('wp')
    def signmessage(self, address, message, password=None):
        """Sign a message with a key. Use quotes if your message contains
        whitespaces"""
        sig = self.wallet.sign_message(address, message, password)
        return base64.b64encode(sig).decode('ascii')

    @command('')
    def verifymessage(self, address, signature, message):
        """Verify a signature."""
        sig = base64.b64decode(signature)
        message = util.to_bytes(message)
        return ecc.verify_message_with_address(address, sig, message)

    def _mktx(self, outputs, fee, change_addr, domain, nocheck, unsigned, password, locktime=None):
        self.nocheck = nocheck
        change_addr = self._resolver(change_addr)
        domain = None if domain is None else map(self._resolver, domain)
        final_outputs = []
        for address, amount in outputs:
            address = self._resolver(address)
            amount = satoshis(amount)
            final_outputs.append(TxOutput(TYPE_ADDRESS, address, amount))

        coins = self.wallet.get_spendable_coins(domain, self.config)
        tx = self.wallet.make_unsigned_transaction(coins, final_outputs, self.config, fee, change_addr)
        if locktime != None:
            tx.locktime = locktime
        if not unsigned:
            self.wallet.sign_transaction(tx, password)
        return tx

    @command('wp')
    def payto(self, destination, amount, fee=None, from_addr=None, change_addr=None, nocheck=False, unsigned=False, password=None, locktime=None):
        """Create a transaction. """
        tx_fee = satoshis(fee)
        domain = from_addr.split(',') if from_addr else None
        tx = self._mktx([(destination, amount)], tx_fee, change_addr, domain, nocheck, unsigned, password, locktime)
        return tx.as_dict()

    @command('wp')
    def paytomany(self, outputs, fee=None, from_addr=None, change_addr=None, nocheck=False, unsigned=False, password=None, locktime=None):
        """Create a multi-output transaction. """
        tx_fee = satoshis(fee)
        domain = from_addr.split(',') if from_addr else None
        tx = self._mktx(outputs, tx_fee, change_addr, domain, nocheck, unsigned, password, locktime)
        return tx.as_dict()

    @command('w')
    def history(self, year=None, show_addresses=False, show_fiat=False, show_fees=False,
                from_height=None, to_height=None):
        """Wallet history. Returns the transaction history of your wallet."""
        kwargs = {
            'show_addresses': show_addresses,
            'show_fees': show_fees,
            'from_height': from_height,
            'to_height': to_height,
            'config': self.config,
        }
        if year:
            import time
            start_date = datetime.datetime(year, 1, 1)
            end_date = datetime.datetime(year+1, 1, 1)
            kwargs['from_timestamp'] = time.mktime(start_date.timetuple())
            kwargs['to_timestamp'] = time.mktime(end_date.timetuple())
        if show_fiat:
            from .exchange_rate import FxThread
            fx = FxThread(self.config, None)
            kwargs['fx'] = fx
        return json_encode(self.wallet.get_full_history(**kwargs))

    @command('w')
    def setlabel(self, key, label):
        """Assign a label to an item. Item may be a Axe address or a
        transaction ID"""
        self.wallet.set_label(key, label)

    @command('w')
    def listcontacts(self):
        """Show your list of contacts"""
        return self.wallet.contacts

    @command('w')
    def getalias(self, key):
        """Retrieve alias. Lookup in your list of contacts, and for an OpenAlias DNS record."""
        return self.wallet.contacts.resolve(key)

    @command('w')
    def searchcontacts(self, query):
        """Search through contacts, return matching entries. """
        results = {}
        for key, value in self.wallet.contacts.items():
            if query.lower() in key.lower():
                results[key] = value
        return results

    @command('w')
    def listaddresses(self, receiving=False, change=False, labels=False, frozen=False, unused=False, funded=False, balance=False):
        """List wallet addresses. Returns the list of all addresses in your wallet. Use optional arguments to filter the results."""
        out = []
        for addr in self.wallet.get_addresses():
            if frozen and not self.wallet.is_frozen_address(addr):
                continue
            if receiving and self.wallet.is_change(addr):
                continue
            if change and not self.wallet.is_change(addr):
                continue
            if unused and self.wallet.is_used(addr):
                continue
            if funded and self.wallet.is_empty(addr):
                continue
            item = addr
            if labels or balance:
                item = (item,)
            if balance:
                item += (format_satoshis(sum(self.wallet.get_addr_balance(addr))),)
            if labels:
                item += (repr(self.wallet.labels.get(addr, '')),)
            out.append(item)
        return out

    @command('n')
    def gettransaction(self, txid):
        """Retrieve a transaction. """
        tx = None
        if self.wallet:
            tx = self.wallet.db.get_transaction(txid)
        if tx is None:
            raw = self.network.run_from_another_thread(self.network.get_transaction(txid))
            if raw:
                tx = Transaction(raw)
            else:
                raise Exception("Unknown transaction")
        return tx.as_dict()

    @command('')
    def encrypt(self, pubkey, message) -> str:
        """Encrypt a message with a public key. Use quotes if the message contains whitespaces."""
        if not is_hex_str(pubkey):
            raise Exception(f"pubkey must be a hex string instead of {repr(pubkey)}")
        try:
            message = to_bytes(message)
        except TypeError:
            raise Exception(f"message must be a string-like object instead of {repr(message)}")
        public_key = ecc.ECPubkey(bfh(pubkey))
        encrypted = public_key.encrypt_message(message)
        return encrypted.decode('utf-8')

    @command('wp')
    def decrypt(self, pubkey, encrypted, password=None) -> str:
        """Decrypt a message encrypted with a public key."""
        if not is_hex_str(pubkey):
            raise Exception(f"pubkey must be a hex string instead of {repr(pubkey)}")
        if not isinstance(encrypted, (str, bytes, bytearray)):
            raise Exception(f"encrypted must be a string-like object instead of {repr(encrypted)}")
        decrypted = self.wallet.decrypt_message(pubkey, encrypted, password)
        return decrypted.decode('utf-8')

    def _format_request(self, out):
        pr_str = {
            PR_UNKNOWN: 'Unknown',
            PR_UNPAID: 'Pending',
            PR_PAID: 'Paid',
            PR_EXPIRED: 'Expired',
        }
        out['amount (AXE)'] = format_satoshis(out.get('amount'))
        out['status'] = pr_str[out.get('status', PR_UNKNOWN)]
        return out

    @command('w')
    def getrequest(self, key):
        """Return a payment request"""
        r = self.wallet.get_payment_request(key, self.config)
        if not r:
            raise Exception("Request not found")
        return self._format_request(r)

    #@command('w')
    #def ackrequest(self, serialized):
    #    """<Not implemented>"""
    #    pass

    @command('w')
    def listrequests(self, pending=False, expired=False, paid=False):
        """List the payment requests you made."""
        out = self.wallet.get_sorted_requests(self.config)
        if pending:
            f = PR_UNPAID
        elif expired:
            f = PR_EXPIRED
        elif paid:
            f = PR_PAID
        else:
            f = None
        if f is not None:
            out = list(filter(lambda x: x.get('status')==f, out))
        return list(map(self._format_request, out))

    @command('w')
    def createnewaddress(self):
        """Create a new receiving address, beyond the gap limit of the wallet"""
        return self.wallet.create_new_address(False)

    @command('w')
    def getunusedaddress(self):
        """Returns the first unused address of the wallet, or None if all addresses are used.
        An address is considered as used if it has received a transaction, or if it is used in a payment request."""
        return self.wallet.get_unused_address()

    @command('w')
    def addrequest(self, amount, memo='', expiration=None, force=False):
        """Create a payment request, using the first unused address of the wallet.
        The address will be considered as used after this operation.
        If no payment is received, the address will be considered as unused if the payment request is deleted from the wallet."""
        addr = self.wallet.get_unused_address()
        if addr is None:
            if force:
                addr = self.wallet.create_new_address(False)
            else:
                return False
        amount = satoshis(amount)
        expiration = int(expiration) if expiration else None
        req = self.wallet.make_payment_request(addr, amount, memo, expiration)
        self.wallet.add_payment_request(req, self.config)
        out = self.wallet.get_payment_request(addr, self.config)
        return self._format_request(out)

    @command('w')
    def addtransaction(self, tx):
        """ Add a transaction to the wallet history """
        tx = Transaction(tx)
        if not self.wallet.add_transaction(tx.txid(), tx):
            return False
        self.wallet.storage.write()
        return tx.txid()

    @command('wp')
    def signrequest(self, address, password=None):
        "Sign payment request with an OpenAlias"
        alias = self.config.get('alias')
        if not alias:
            raise Exception('No alias in your configuration')
        alias_addr = self.wallet.contacts.resolve(alias)['address']
        self.wallet.sign_payment_request(address, alias, alias_addr, password)

    @command('w')
    def rmrequest(self, address):
        """Remove a payment request"""
        return self.wallet.remove_payment_request(address, self.config)

    @command('w')
    def clearrequests(self):
        """Remove all payment requests"""
        for k in list(self.wallet.receive_requests.keys()):
            self.wallet.remove_payment_request(k, self.config)

    # Masternode commands.
    @command('wnp')
    def importmasternodeconf(self, conf_file):
        """Import a masternode.conf file."""
        if not os.path.exists(conf_file):
            return 'File does not exist.'
        with open(conf_file, 'r') as f:
            lines = f.readlines()

        try:
            conf_lines = parse_masternode_conf(lines)
        except Exception as e:
            return 'Error parsing: ' + str(e)

        mn_man = self.masternode_manager
        num = mn_man.import_masternode_conf_lines(conf_lines, self.password)
        if not num:
            return 'Could not import any configurations. Please ensure that they are not already imported.'
        return '%d configuration%s imported.' % (num, 's' if num == 1 else '')

    @command('w')
    def newmasternode(self, alias):
        """Create a new masternode."""
        try:
            self.masternode_manager.add_masternode(MasternodeAnnounce(alias=alias))
            return 'Added new masternode "%s".' % alias
        except Exception as e:
            return 'Error: %s' % str(e)

    @command('w')
    def rmmasternode(self, alias):
        """Remove an existing masternode."""
        try:
            self.masternode_manager.remove_masternode(alias)
            return 'Removed masternode "%s".' % alias
        except Exception as e:
            return 'Error: %s' % str(e)

    @command('w')
    def listmasternodes(self):
        """List wallet masternodes."""
        return sorted([i.alias for i in self.masternode_manager.masternodes])

    @command('w')
    def showmasternode(self, alias):
        """Show details about a masternode."""
        mn = self.masternode_manager.get_masternode(alias)
        if not mn:
            return 'No masternode exists for alias "%s".' % alias
        return mn.dump()

    @command('w')
    def listmasternodepayments(self):
        """List unused masternode-compatible payments."""
        return self.masternode_manager.get_masternode_outputs(exclude_frozen=False)

    @command('wnp')
    def activatemasternode(self, alias):
        """Activate a masternode."""
        self.masternode_manager.populate_masternode_output(alias)
        try:
            self.masternode_manager.sign_announce(alias, self.password)
        except Exception as e:
            return 'Error signing: ' + str(e)

        try:
            self.masternode_manager.send_announce(alias)
        except Exception as e:
            return 'Error sending: ' + str(e)

        return 'Masternode "%s" activated successfully.' % alias

    # Budget-related commands.
    @command('wp')
    def prepareproposal(self, proposal_name, proposal_url, payments_count, block_start, address, amount, broadcast=False):
        """Create a budget proposal transaction."""
        proposal = self.masternode_manager.get_proposal(proposal_name)
        amount = int(amount*COIN)
        if not proposal:
            proposal = BudgetProposal(proposal_name=proposal_name, proposal_url=proposal_url, start_block=block_start,
                        payment_amount=amount, address=address)
            proposal.set_payments_count(payments_count)
            self.masternode_manager.add_proposal(proposal)

        tx = self.masternode_manager.create_proposal_tx(proposal_name, self.password)

        if broadcast:
            r, h = self.wallet.sendtx(tx)
            return h
        return str(tx)

    @command('wn')
    def sendproposal(self, proposal_name):
        """Send a budget proposal."""
        try:
            errmsg, submitted = self.masternode_manager.submit_proposal(proposal_name)
        except Exception as e:
            return 'Error: %s' % str(e)

        if errmsg:
            return 'Error: %s' % errmsg
        return submitted

    @command('wn')
    def sendreadyproposals(self):
        """Send all budget proposals that are ready to be sent."""
        results = {}
        proposals = filter(lambda p: p.fee_txid and not p.submitted and not p.rejected, self.masternode_manager.proposals)
        for p in proposals:
            tx_height = self.wallet.get_tx_height(p.fee_txid)
            if tx_height.conf < BUDGET_FEE_CONFIRMATIONS:
                continue

            errmsg, success = self.masternode_manager.submit_proposal(p.proposal_name)
            if not success:
                results[p.proposal_name] = errmsg
            else:
                results[p.proposal_name] = 'Successfully submitted'

        return results

    @command('w')
    def listproposals(self):
        """List proposals created with this wallet."""
        return {p.proposal_name: p.dump() for p in self.masternode_manager.proposals}

    @command('w')
    def listreadyproposals(self):
        """List the proposals created with this wallet that are ready to be submitted."""
        results = {}
        proposals = filter(lambda p: p.fee_txid and not p.submitted and not p.rejected, self.masternode_manager.proposals)
        for p in proposals:
            tx_height = self.wallet.get_tx_height(p.fee_txid)
            if tx_height.conf < BUDGET_FEE_CONFIRMATIONS:
                continue
            results[p.proposal_name] = p.dump()

        return results

    @command('n')
    def mnbudget(self, budget_command):
        """Get information on masternode budget proposals."""
        valid_commands = ('list', 'nextblock', 'nextsuperblocksize', 'projection')
        if budget_command not in valid_commands:
            return 'Budget command must be one of %s' % valid_commands
        method = 'masternode.budget.%s' % budget_command
        return self.network.synchronous_get([(method, [])])[0]

    @command('n')
    def getvotes(self, proposal_hash):
        """Get the votes for a budget proposal."""
        req = ('masternode.budget.getvotes', [proposal_hash])
        return self.network.synchronous_get([req])[0]

    @command('n')
    def getproposalhash(self, proposal_name):
        """Get the hash of a budget proposal by its name."""
        req = ('masternode.budget.getproposalhash', [proposal_name])
        return self.network.synchronous_get([req])[0]

    @command('n')
    def getproposal(self, proposal_hash):
        """Get information on a budget proposal."""
        req = ('masternode.budget.getproposal', [proposal_hash])
        return self.network.synchronous_get([req])[0]

    @command('wn')
    def vote(self, alias, proposal_name, vote_choice):
        """Vote on a proposal."""
        valid_choices = ('yes', 'no')
        if vote_choice.lower() not in valid_choices:
            return 'Invalid vote choice: "%s"' % vote_choice

        errmsg, success = self.masternode_manager.vote(alias, proposal_name, vote_choice)
        if errmsg:
            return 'Error: %s' % errmsg
        return success

    @command('n')
    def notify(self, address: str, URL: str):
        """Watch an address. Every time the address changes, a http POST is sent to the URL."""
        if not hasattr(self, "_notifier"):
            self._notifier = Notifier(self.network)
        self.network.run_from_another_thread(self._notifier.start_watching_queue.put((address, URL)))
        return True

    @command('wn')
    def is_synchronized(self):
        """ return wallet synchronization status """
        return self.wallet.is_up_to_date()

    @command('n')
    def getfeerate(self, fee_method=None, fee_level=None):
        """Return current suggested fee rate (in sat/kvByte), according to config
        settings or supplied parameters.
        """
        if fee_method is None:
            dyn, mempool = None, None
        elif fee_method.lower() == 'static':
            dyn, mempool = False, False
        elif fee_method.lower() == 'eta':
            dyn, mempool = True, False
        else:
            raise Exception('Invalid fee estimation method: {}'.format(fee_method))
        if fee_level is not None:
            fee_level = Decimal(fee_level)
        return self.config.fee_per_kb(dyn=dyn, mempool=mempool, fee_level=fee_level)

    @command('w')
    def removelocaltx(self, txid):
        """Remove a 'local' transaction from the wallet, and its dependent
        transactions.
        """
        if not is_hash256_str(txid):
            raise Exception(f"{repr(txid)} is not a txid")
        height = self.wallet.get_tx_height(txid).height
        to_delete = {txid}
        if height != TX_HEIGHT_LOCAL:
            raise Exception(f'Only local transactions can be removed. '
                            f'This tx has height: {height} != {TX_HEIGHT_LOCAL}')
        to_delete |= self.wallet.get_depending_transactions(txid)
        for tx_hash in to_delete:
            self.wallet.remove_transaction(tx_hash)
        self.wallet.storage.write()

    @command('wn')
    def get_tx_status(self, txid):
        """Returns some information regarding the tx. For now, only confirmations.
        The transaction must be related to the wallet.
        """
        if not is_hash256_str(txid):
            raise Exception(f"{repr(txid)} is not a txid")
        if not self.wallet.db.get_transaction(txid):
            raise Exception("Transaction not in wallet.")
        res = {
            "confirmations": self.wallet.get_tx_height(txid).conf,
        }
        if txid in self.wallet.db.islocks:
            res['instantsend_locked'] = True
        return res

    @command('n')
    def exportcp(self, cpfile):
        """Export checkpoints to file"""
        try:
            self.network.export_checkpoints(cpfile)
            return 'Exporting checkpoints done'
        except Exception as e:
            return 'Error exporting checkpoints: ' + str(e)

    @command('')
    def help(self):
        # for the python console
        return sorted(known_commands.keys())


def eval_bool(x: str) -> bool:
    if x == 'false': return False
    if x == 'true': return True
    try:
        return bool(ast.literal_eval(x))
    except:
        return bool(x)


param_descriptions = {
    'privkey': 'Private key. Type \'?\' to get a prompt.',
    'destination': 'Axe address, contact or alias',
    'address': 'Axe address',
    'seed': 'Seed phrase',
    'txid': 'Transaction ID',
    'pos': 'Position',
    'height': 'Block height',
    'tx': 'Serialized transaction (hexadecimal)',
    'key': 'Variable name',
    'pubkey': 'Public key',
    'message': 'Clear text message. Use quotes if it contains spaces.',
    'encrypted': 'Encrypted message',
    'amount': 'Amount to be sent (in AXE). Type \'!\' to send the maximum available.',
    'requested_amount': 'Requested amount (in AXE).',
    'outputs': 'list of ["address", amount]',
    'redeem_script': 'redeem script (hexadecimal)',
    'conf_file': 'Masternode.conf file from Axe.',
    'alias': 'Masternode alias.',
    'cpfile': 'Checkpoints file',
}

command_options = {
    'broadcast':   (None, "Broadcast the transaction to the Axe network"),
    'password':    ("-W", "Password"),
    'new_password':(None, "New Password"),
    'encrypt_file':(None, "Whether the file on disk should be encrypted with the provided password"),
    'receiving':   (None, "Show only receiving addresses"),
    'change':      (None, "Show only change addresses"),
    'frozen':      (None, "Show only frozen addresses"),
    'unused':      (None, "Show only unused addresses"),
    'funded':      (None, "Show only funded addresses"),
    'balance':     ("-b", "Show the balances of listed addresses"),
    'labels':      ("-l", "Show the labels of listed addresses"),
    'nocheck':     (None, "Do not verify aliases"),
    'imax':        (None, "Maximum number of inputs"),
    'fee':         ("-f", "Transaction fee (in Axe)"),
    'from_addr':   ("-F", "Source address (must be a wallet address; use sweep to spend from non-wallet address)."),
    'change_addr': ("-c", "Change address. Default is a spare address, or the source address if it's not in the wallet"),
    'nbits':       (None, "Number of bits of entropy"),
    'language':    ("-L", "Default language for wordlist"),
    'passphrase':  (None, "Seed extension"),
    'privkey':     (None, "Private key. Set to '?' to get a prompt."),
    'unsigned':    ("-u", "Do not sign transaction"),
    'locktime':    (None, "Set locktime block number"),
    'domain':      ("-D", "List of addresses"),
    'memo':        ("-m", "Description of the request"),
    'expiration':  (None, "Time in seconds"),
    'timeout':     (None, "Timeout in seconds"),
    'force':       (None, "Create new address beyond gap limit, if no more addresses are available."),
    'pending':     (None, "Show only pending requests."),
    'expired':     (None, "Show only expired requests."),
    'paid':        (None, "Show only paid requests."),
    'show_addresses': (None, "Show input and output addresses"),
    'show_fiat':   (None, "Show fiat value of transactions"),
    'show_fees':   (None, "Show miner fees paid by transactions"),
    'year':        (None, "Show history for a given year"),
    'fee_method':  (None, "Fee estimation method to use"),
    'fee_level':   (None, "Float between 0.0 and 1.0, representing fee slider position"),
    'from_height': (None, "Only show transactions that confirmed after given block height"),
    'to_height':   (None, "Only show transactions that confirmed before given block height"),
}


# don't use floats because of rounding errors
from .transaction import tx_from_str
json_loads = lambda x: json.loads(x, parse_float=lambda x: str(Decimal(x)))
arg_types = {
    'block_start': int,
    'num': int,
    'nbits': int,
    'payments_count': int,
    'imax': int,
    'year': int,
    'from_height': int,
    'to_height': int,
    'tx': tx_from_str,
    'pubkeys': json_loads,
    'jsontx': json_loads,
    'inputs': json_loads,
    'outputs': json_loads,
    'fee': lambda x: str(Decimal(x)) if x is not None else None,
    'amount': lambda x: str(Decimal(x)) if x != '!' else '!',
    'locktime': int,
    'fee_method': str,
    'fee_level': json_loads,
    'encrypt_file': eval_bool,
}

config_variables = {

    'addrequest': {
        'requests_dir': 'directory where a bip70 file will be written.',
        'ssl_privkey': 'Path to your SSL private key, needed to sign the request.',
        'ssl_chain': 'Chain of SSL certificates, needed for signed requests. Put your certificate at the top and the root CA at the end',
        'url_rewrite': 'Parameters passed to str.replace(), in order to create the r= part of axe: URIs. Example: \"(\'file:///var/www/\',\'https://electrum.axe.org/\')\"',
    },
    'listrequests':{
        'url_rewrite': 'Parameters passed to str.replace(), in order to create the r= part of axe: URIs. Example: \"(\'file:///var/www/\',\'https://electrum.axe.org/\')\"',
    }
}

def set_default_subparser(self, name, args=None):
    """see http://stackoverflow.com/questions/5176691/argparse-how-to-specify-a-default-subcommand"""
    subparser_found = False
    for arg in sys.argv[1:]:
        if arg in ['-h', '--help']:  # global help if no subparser
            break
    else:
        for x in self._subparsers._actions:
            if not isinstance(x, argparse._SubParsersAction):
                continue
            for sp_name in x._name_parser_map.keys():
                if sp_name in sys.argv[1:]:
                    subparser_found = True
        if not subparser_found:
            # insert default in first position, this implies no
            # global options without a sub_parsers specified
            if args is None:
                sys.argv.insert(1, name)
            else:
                args.insert(0, name)

argparse.ArgumentParser.set_default_subparser = set_default_subparser


# workaround https://bugs.python.org/issue23058
# see https://github.com/nickstenning/honcho/pull/121

def subparser_call(self, parser, namespace, values, option_string=None):
    from argparse import ArgumentError, SUPPRESS, _UNRECOGNIZED_ARGS_ATTR
    parser_name = values[0]
    arg_strings = values[1:]
    # set the parser name if requested
    if self.dest is not SUPPRESS:
        setattr(namespace, self.dest, parser_name)
    # select the parser
    try:
        parser = self._name_parser_map[parser_name]
    except KeyError:
        tup = parser_name, ', '.join(self._name_parser_map)
        msg = _('unknown parser {!r} (choices: {})').format(*tup)
        raise ArgumentError(self, msg)
    # parse all the remaining options into the namespace
    # store any unrecognized options on the object, so that the top
    # level parser can decide what to do with them
    namespace, arg_strings = parser.parse_known_args(arg_strings, namespace)
    if arg_strings:
        vars(namespace).setdefault(_UNRECOGNIZED_ARGS_ATTR, [])
        getattr(namespace, _UNRECOGNIZED_ARGS_ATTR).extend(arg_strings)

argparse._SubParsersAction.__call__ = subparser_call


def add_network_options(parser):
    parser.add_argument("-1", "--oneserver", action="store_true", dest="oneserver", default=None, help="connect to one server only")
    parser.add_argument("-s", "--server", dest="server", default=None, help="set server host:port:protocol, where protocol is either t (tcp) or s (ssl)")
    parser.add_argument("-p", "--proxy", dest="proxy", default=None, help="set proxy [type:]host[:port], where type is socks4,socks5 or http")
    parser.add_argument("--noonion", action="store_true", dest="noonion", default=None, help="do not try to connect to onion servers")
    parser.add_argument("--skipmerklecheck", action="store_true", dest="skipmerklecheck", default=False, help="Tolerate invalid merkle proofs from server")
    parser.add_argument("--axe-peer", action="append", dest="axe_peers", default=None, help="add axe network peer host[:port]")
    parser.add_argument("--no-axe-net", action="store_false", default=None, dest="run_axe_net", help="do not run axe network")
    parser.add_argument("--no-load-mns", action="store_false", default=None, dest="protx_load_mns", help="do not load protx Masternodes")

def add_global_options(parser):
    group = parser.add_argument_group('global options')
    group.add_argument("-v", dest="verbosity", help="Set verbosity (log levels)", default='')
    group.add_argument("-V", dest="verbosity_shortcuts", help="Set verbosity (shortcut-filter list)", default='')
    group.add_argument("-D", "--dir", dest="electrum_path", help="electrum-axe directory")
    group.add_argument("-P", "--portable", action="store_true", dest="portable", default=False, help="Use local 'electrum_data' directory")
    group.add_argument("-w", "--wallet", dest="wallet_path", help="wallet path")
    group.add_argument("--testnet", action="store_true", dest="testnet", default=False, help="Use Testnet")
    group.add_argument("--regtest", action="store_true", dest="regtest", default=False, help="Use Regtest")

def get_parser():
    # create main parser
    parser = argparse.ArgumentParser(
        epilog="Run 'electrum-axe help <command>' to see the help for a command")
    add_global_options(parser)
    subparsers = parser.add_subparsers(dest='cmd', metavar='<command>')
    # gui
    parser_gui = subparsers.add_parser('gui', description="Run Axe Electrum Graphical User Interface.", help="Run GUI (default)")
    parser_gui.add_argument("url", nargs='?', default=None, help="axe URI (or bip70 file)")
    parser_gui.add_argument("-g", "--gui", dest="gui", help="select graphical user interface", choices=['qt', 'kivy', 'text', 'stdio'])
    parser_gui.add_argument("-o", "--offline", action="store_true", dest="offline", default=False, help="Run offline")
    parser_gui.add_argument("-m", action="store_true", dest="hide_gui", default=False, help="hide GUI on startup")
    parser_gui.add_argument("-L", "--lang", dest="language", default=None, help="default language used in GUI")
    parser_gui.add_argument("--daemon", action="store_true", dest="daemon", default=False, help="keep daemon running after GUI is closed")
    add_network_options(parser_gui)
    add_global_options(parser_gui)
    # daemon
    parser_daemon = subparsers.add_parser('daemon', help="Run Daemon")
    parser_daemon.add_argument("subcommand", choices=['start', 'status', 'stop', 'load_wallet', 'close_wallet'], nargs='?')
    #parser_daemon.set_defaults(func=run_daemon)
    add_network_options(parser_daemon)
    add_global_options(parser_daemon)
    # commands
    for cmdname in sorted(known_commands.keys()):
        cmd = known_commands[cmdname]
        p = subparsers.add_parser(cmdname, help=cmd.help, description=cmd.description)
        add_global_options(p)
        for optname, default in zip(cmd.options, cmd.defaults):
            a, help = command_options[optname]
            b = '--' + optname
            action = "store_true" if default is False else 'store'
            args = (a, b) if a else (b,)
            if action == 'store':
                _type = arg_types.get(optname, str)
                p.add_argument(*args, dest=optname, action=action, default=default, help=help, type=_type)
            else:
                p.add_argument(*args, dest=optname, action=action, default=default, help=help)

        for param in cmd.params:
            h = param_descriptions.get(param, '')
            _type = arg_types.get(param, str)
            p.add_argument(param, help=h, type=_type)

        cvh = config_variables.get(cmdname)
        if cvh:
            group = p.add_argument_group('configuration variables', '(set with setconfig/getconfig)')
            for k, v in cvh.items():
                group.add_argument(k, nargs='?', help=v)

    # 'gui' is the default command
    parser.set_default_subparser('gui')
    return parser
