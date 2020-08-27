import colorama
import getpass
import logging
import time
from colorama import Fore, Style
from datetime import datetime
from decimal import Decimal

from electrum_axe import WalletStorage, Wallet
from electrum_axe.axe_ps import filter_log_line, PSLogSubCat
from electrum_axe.axe_tx import SPEC_TX_NAMES
from electrum_axe.util import format_satoshis
from electrum_axe.bitcoin import is_address, COIN, TYPE_ADDRESS
from electrum_axe.transaction import TxOutput
from electrum_axe.network import TxBroadcastError, BestEffortRequestFailed
from electrum_axe.logging import console_stderr_handler

_ = lambda x:x  # i18n

# minimal fdisk like gui for console usage
# written by rofl0r, with some bits stolen from the text gui (ncurses)


class ElectrumGui:

    def __init__(self, config, daemon, plugins):
        colorama.init()
        self.config = config
        self.network = network = daemon.network
        if config.get('tor_auto_on', True):
            if network:
                proxy_modifiable = config.is_modifiable('proxy')
                if not proxy_modifiable or not network.detect_tor_proxy():
                    print(network.TOR_WARN_MSG_TXT)
                    c = ''
                    while c != 'y':
                        c = input("Continue without Tor (y/n)?")
                        if c == 'n':
                            exit()
        storage = WalletStorage(config.get_wallet_path())
        if not storage.file_exists:
            print("Wallet not found. try 'electrum-axe create'")
            exit()
        if storage.is_encrypted():
            password = getpass.getpass('Password:', stream=None)
            storage.decrypt(password)

        if getattr(storage, 'backup_message', None):
            print(f'{storage.backup_message}\n')
            input('Press Enter to continue...')

        self.done = 0
        self.last_balance = ""

        console_stderr_handler.setLevel(logging.CRITICAL)

        self.str_recipient = ""
        self.str_description = ""
        self.str_amount = ""
        self.str_fee = ""

        self.wallet = Wallet(storage)
        self.wallet.start_network(self.network)
        self.wallet.psman.config = config
        self.contacts = self.wallet.contacts

        self.network.register_callback(self.on_network, ['wallet_updated', 'network_updated', 'banner'])
        self.commands = [_("[h] - displays this help text"), \
                         _("[i] - display transaction history"), \
                         _("[o] - enter payment order"), \
                         _("[p] - print stored payment order"), \
                         _("[s] - send stored payment order"), \
                         _("[r] - show own receipt addresses"), \
                         _("[c] - display contacts"), \
                         _("[b] - print server banner"), \
                         _("[M] - start PrivateSend mixing"),
                         _("[S] - stop PrivateSend mixing"),
                         _("[l][f][a] - print PrivateSend log (filtered/all)"),
                         _("[q] - quit") ]
        self.num_commands = len(self.commands)

    def on_network(self, event, *args):
        if event in ['wallet_updated', 'network_updated']:
            self.updated()
        elif event == 'banner':
            self.print_banner()

    def main_command(self):
        self.print_balance()
        c = input("enter command: ")
        if c == "h" : self.print_commands()
        elif c == "i" : self.print_history()
        elif c == "o" : self.enter_order()
        elif c == "p" : self.print_order()
        elif c == "s" : self.send_order()
        elif c == "r" : self.print_addresses()
        elif c == "c" : self.print_contacts()
        elif c == "b" : self.print_banner()
        elif c == "n" : self.network_dialog()
        elif c == "e" : self.settings_dialog()
        elif c == "M" : self.start_mixing()
        elif c == "S" : self.stop_mixing()
        elif c.startswith('l'): self.privatesend_log(c)
        elif c == "q" : self.done = 1
        else: self.print_commands()

    def updated(self):
        s = self.get_balance()
        if s != self.last_balance:
            print(s)
        self.last_balance = s
        return True

    def print_commands(self):
        self.print_list(self.commands, "Available commands")

    def print_history(self):
        messages = []

        hist_list = reversed(self.wallet.get_history(config=self.config))
        def_dip2 = not self.wallet.psman.unsupported
        show_dip2 = self.config.get('show_dip2_tx_type', def_dip2)
        if show_dip2:
            width = [20, 18, 22, 14, 14]
            wdelta = (80 - sum(width) - 5) // 3
            format_str = ("%" + "%d" % width[0] + "s" +
                          "%" + "%d" % width[1] + "s" +
                          "%" + "%d" % (width[2] + wdelta) + "s" +
                          "%" + "%d" % (width[3] + wdelta) + "s" +
                          "%" + "%d" % (width[4] + wdelta) + "s")
        else:
            width = [20, 40, 14, 14]
            wdelta = (80 - sum(width) - 4) // 3
            format_str = ("%" + "%d" % width[0] + "s" +
                          "%" + "%d" % (width[1] + wdelta) + "s" +
                          "%" + "%d" % (width[2] + wdelta) + "s" +
                          "%" + "%d" % (width[3] + wdelta) + "s")
        for (tx_hash, tx_type, tx_mined_status, delta, balance,
             islock, group_txid, group_data) in hist_list:
            if tx_mined_status.conf:
                timestamp = tx_mined_status.timestamp
                try:
                    dttm = datetime.fromtimestamp(timestamp)
                    time_str = dttm.isoformat(' ')[:-3]
                except Exception:
                    time_str = "unknown"
            elif islock:
                dttm = datetime.fromtimestamp(islock)
                time_str = dttm.isoformat(' ')[:-3]
            else:
                time_str = 'unconfirmed'

            label = self.wallet.get_label(tx_hash)
            if show_dip2:
                tx_type_name = SPEC_TX_NAMES.get(tx_type, str(tx_type))
                msg = format_str % (time_str, tx_type_name, label,
                                    format_satoshis(delta, whitespaces=True),
                                    format_satoshis(balance, whitespaces=True))
                messages.append(msg)
            else:
                msg = format_str % (time_str, label,
                                    format_satoshis(delta, whitespaces=True),
                                    format_satoshis(balance, whitespaces=True))
                messages.append(msg)
        if show_dip2:
            self.print_list(messages[::-1],
                            format_str % (_("Date"), 'Type',
                                          _("Description"), _("Amount"),
                                          _("Balance")))
        else:
            self.print_list(messages[::-1],
                            format_str % (_("Date"),
                                          _("Description"), _("Amount"),
                                          _("Balance")))

    def print_balance(self):
        print(self.get_balance())

    def get_balance(self):
        if self.wallet.network.is_connected():
            if not self.wallet.up_to_date:
                msg = _( "Synchronizing..." )
            else:
                c, u, x =  self.wallet.get_balance()
                msg = _("Balance")+": %f  "%(Decimal(c) / COIN)
                if u:
                    msg += "  [%f unconfirmed]"%(Decimal(u) / COIN)
                if x:
                    msg += "  [%f unmatured]"%(Decimal(x) / COIN)
        else:
                msg = _( "Not connected" )

        return(msg)


    def print_contacts(self):
        messages = map(lambda x: "%20s   %45s "%(x[0], x[1][1]), self.contacts.items())
        self.print_list(messages, "%19s  %25s "%("Key", "Value"))

    def print_addresses(self):
        w = self.wallet
        addrs = w.get_addresses() + w.psman.get_addresses()
        messages = map(lambda addr: "%30s    %30s       " %
                                    (addr, self.wallet.labels.get(addr,"")),
                       addrs)
        self.print_list(messages, "%19s  %25s "%("Address", "Label"))

    def print_order(self):
        print("send order to " + self.str_recipient + ", amount: " + self.str_amount \
              + "\nfee: " + self.str_fee + ", desc: " + self.str_description)

    def enter_order(self):
        self.str_recipient = input("Pay to: ")
        self.str_description = input("Description : ")
        self.str_amount = input("Amount: ")
        self.str_fee = input("Fee: ")

    def send_order(self):
        self.do_send()

    def print_banner(self):
        for i, x in enumerate( self.wallet.network.banner.split('\n') ):
            print( x )

    def print_list(self, lst, firstline):
        lst = list(lst)
        self.maxpos = len(lst)
        if not self.maxpos: return
        print(firstline)
        for i in range(self.maxpos):
            msg = lst[i] if i < len(lst) else ""
            print(msg)


    def main(self):
        while self.done == 0: self.main_command()

    def do_send(self):
        if not is_address(self.str_recipient):
            print(_('Invalid Axe address'))
            return
        try:
            amount = int(Decimal(self.str_amount) * COIN)
        except Exception:
            print(_('Invalid Amount'))
            return
        try:
            fee = int(Decimal(self.str_fee) * COIN)
        except Exception:
            print(_('Invalid Fee'))
            return

        if self.wallet.has_password():
            password = self.password_dialog()
            if not password:
                return
        else:
            password = None

        c = ""
        while c != "y":
            c = input("ok to send (y/n)?")
            if c == "n": return

        try:
            tx = self.wallet.mktx([TxOutput(TYPE_ADDRESS, self.str_recipient, amount)],
                                  password, self.config, fee)
        except Exception as e:
            print(str(e))
            return

        if self.str_description:
            self.wallet.labels[tx.txid()] = self.str_description

        print(_("Please wait..."))
        try:
            coro = self.wallet.psman.broadcast_transaction(tx)
            self.network.run_from_another_thread(coro)
        except TxBroadcastError as e:
            msg = e.get_message_for_gui()
            print(msg)
        except BestEffortRequestFailed as e:
            msg = repr(e)
            print(msg)
        else:
            print(_('Payment sent.'))
            #self.do_clear()
            #self.update_contacts_tab()

    def network_dialog(self):
        print("use 'electrum-axe setconfig server/proxy' to change your network settings")
        return True


    def settings_dialog(self):
        print("use 'electrum-axe setconfig' to change your settings")
        return True

    def start_mixing(self):
        if self.wallet.has_password():
            password = self.password_dialog()
            if not password:
                return
        else:
            password = None
        self.wallet.psman.start_mixing(password)
        return True

    def stop_mixing(self):
        self.wallet.psman.stop_mixing()

    def privatesend_log(self, cmd):
        try:
            cmd = cmd.lower()
            subcmds = cmd[1:].split()
            print_filtered = True if 'f' in subcmds else False
            print_tail = True if 'a' not in subcmds else False
            log_handler = self.wallet.psman.log_handler
            p_from = log_handler.tail - 20 if print_tail else log_handler.head
            p_from = max(p_from, log_handler.head)
            for i in range(p_from, log_handler.tail):
                log_line = ''
                log_record = log_handler.log.get(i, None)
                if log_record:
                    created = time.localtime(log_record.created)
                    created = time.strftime('%x %X', created)
                    log_line = f'{created} {log_record.msg}'
                    if print_filtered:
                        log_line = filter_log_line(log_line)
                    if log_record.subcat == PSLogSubCat.WflDone:
                        log_line = f'{Fore.BLUE}{log_line}{Style.RESET_ALL}'
                    elif log_record.subcat == PSLogSubCat.WflOk:
                        log_line = f'{Fore.GREEN}{log_line}{Style.RESET_ALL}'
                    elif log_record.subcat == PSLogSubCat.WflErr:
                        log_line = f'{Fore.RED}{log_line}{Style.RESET_ALL}'
                print(log_line)
        except:
            import traceback
            traceback.print_exc()

    def password_dialog(self):
        return getpass.getpass()


#   XXX unused

    def run_receive_tab(self, c):
        #if c == 10:
        #    out = self.run_popup('Address', ["Edit label", "Freeze", "Prioritize"])
        return

    def run_contacts_tab(self, c):
        pass
