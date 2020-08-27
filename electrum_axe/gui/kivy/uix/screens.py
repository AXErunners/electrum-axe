from weakref import ref
from decimal import Decimal
import re
import datetime
import threading
import traceback, sys

from kivy.app import App
from kivy.cache import Cache
from kivy.clock import Clock
from kivy.compat import string_types
from kivy.logger import Logger
from kivy.properties import (ObjectProperty, DictProperty, NumericProperty,
                             ListProperty, StringProperty, BooleanProperty)

from kivy.uix.behaviors import FocusBehavior
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.recycleview.layout import LayoutSelectionBehavior
from kivy.uix.recycleview.views import RecycleDataViewBehavior
from kivy.uix.recycleboxlayout import RecycleBoxLayout
from kivy.uix.label import Label

from kivy.lang import Builder
from kivy.factory import Factory
from kivy.utils import platform

from electrum_axe.util import profiler, parse_URI, format_time, InvalidPassword, NotEnoughFunds, Fiat
from electrum_axe import bitcoin
from electrum_axe.axe_tx import PSTxTypes, SPEC_TX_NAMES
from electrum_axe.transaction import TxOutput, Transaction, tx_from_str
from electrum_axe.util import send_exception_to_crash_reporter, parse_URI, InvalidBitcoinURI
from electrum_axe.paymentrequest import PR_UNPAID, PR_PAID, PR_UNKNOWN, PR_EXPIRED
from electrum_axe.plugin import run_hook
from electrum_axe.wallet import InternalAddressCorruption
from electrum_axe import simple_config

from .context_menu import ContextMenu


from electrum_axe.gui.kivy.i18n import _


class HistoryItem(RecycleDataViewBehavior, BoxLayout):
    index = None
    selected = BooleanProperty(False)

    def refresh_view_attrs(self, rv, index, data):
        self.index = index
        return super(HistoryItem, self).refresh_view_attrs(rv, index, data)

    def on_touch_down(self, touch):
        if super(HistoryItem, self).on_touch_down(touch):
            return True
        if self.collide_point(*touch.pos):
            return self.parent.select_with_touch(self.index, touch)

    def apply_selection(self, rv, index, is_selected):
        self.selected = is_selected


class HistBoxLayout(FocusBehavior, LayoutSelectionBehavior, RecycleBoxLayout):
    def select_node(self, node):
        super(HistBoxLayout, self).select_node(node)
        rv = self.recycleview
        data = rv.data[node]
        rv.hist_screen.on_select_node(node, data)

    def deselect_node(self, node):
        super(HistBoxLayout, self).deselect_node(node)
        rv = self.recycleview
        rv.hist_screen.on_deselect_node()


class CScreen(Factory.Screen):
    __events__ = ('on_activate', 'on_deactivate', 'on_enter', 'on_leave')
    action_view = ObjectProperty(None)
    loaded = False
    kvname = None
    context_menu = None
    menu_actions = []
    app = App.get_running_app()

    def _change_action_view(self):
        app = App.get_running_app()
        action_bar = app.root.manager.current_screen.ids.action_bar
        _action_view = self.action_view

        if (not _action_view) or _action_view.parent:
            return
        action_bar.clear_widgets()
        action_bar.add_widget(_action_view)

    def on_enter(self):
        # FIXME: use a proper event don't use animation time of screen
        Clock.schedule_once(lambda dt: self.dispatch('on_activate'), .25)
        pass

    def update(self):
        pass

    @profiler
    def load_screen(self):
        self.screen = Builder.load_file('electrum_axe/gui/kivy/uix/ui_screens/' + self.kvname + '.kv')
        self.add_widget(self.screen)
        self.loaded = True
        self.update()
        setattr(self.app, self.kvname + '_screen', self)

    def on_activate(self):
        if self.kvname and not self.loaded:
            self.load_screen()
        #Clock.schedule_once(lambda dt: self._change_action_view())

    def on_leave(self):
        self.dispatch('on_deactivate')

    def on_deactivate(self):
        self.hide_menu()

    def hide_menu(self):
        if self.context_menu is not None:
            self.screen.cmbox.remove_widget(self.context_menu)
            self.context_menu = None


# note: this list needs to be kept in sync with another in qt
TX_ICONS = [
    "unconfirmed",
    "close",
    "unconfirmed",
    "close",
    "clock1",
    "clock2",
    "clock3",
    "clock4",
    "clock5",
    "instantsend_locked",
    "confirmed",
]


class GetHistoryDataThread(threading.Thread):

    def __init__(self, screen):
        super(GetHistoryDataThread, self).__init__()
        self.screen = screen
        self.need_update = threading.Event()
        self.res = []
        self._stopped = False

    def run(self):
        app = self.screen.app
        while True:
            try:
                self.need_update.wait()
                self.need_update.clear()
                if self._stopped:
                    return
                config = app.electrum_config
                group_ps = app.wallet.psman.group_history
                res = app.wallet.get_history(config=config, group_ps=group_ps)
                Clock.schedule_once(lambda dt: self.screen.update_data(res))
            except Exception as e:
                Logger.info(f'GetHistoryDataThread error: {str(e)}')

    def stop(self):
        self._stopped = True
        self.need_update.set()


class HistoryScreen(CScreen):

    tab = ObjectProperty(None)
    kvname = 'history'
    cards = {}

    def __init__(self, **kwargs):
        self.ra_dialog = None
        super(HistoryScreen, self).__init__(**kwargs)
        atlas_path = 'atlas://electrum_axe/gui/kivy/theming/light/'
        self.atlas_path = atlas_path
        self.group_icn_empty = atlas_path + 'kv_tx_group_empty'
        self.group_icn_head = atlas_path + 'kv_tx_group_head'
        self.group_icn_tail = atlas_path + 'kv_tx_group_tail'
        self.group_icn_mid = atlas_path + 'kv_tx_group_mid'
        self.group_icn_all = atlas_path + 'kv_tx_group_all'
        self.expanded_groups = set()
        self.history = []
        self.selected_txid = ''
        self.get_data_thread = None

    def stop_get_data_thread(self):
        if self.get_data_thread is not None:
            self.get_data_thread.stop()

    def show_tx(self, data):
        tx_hash = data['tx_hash']
        tx = self.app.wallet.db.get_transaction(tx_hash)
        if not tx:
            return
        self.app.tx_dialog(tx)

    def label_dialog(self, data):
        from .dialogs.label_dialog import LabelDialog
        key = data['tx_hash']
        text = self.app.wallet.get_label(key)
        def callback(text):
            self.app.wallet.set_label(key, text)
            self.update()
        d = LabelDialog(_('Enter Transaction Label'), text, callback)
        d.open()

    def expand_tx_group(self, data):
        group_txid = data['group_txid']
        if group_txid and group_txid not in self.expanded_groups:
            self.expanded_groups.add(group_txid)
            self.update(reload_history=False)

    def collapse_tx_group(self, data):
        group_txid = data['group_txid']
        if group_txid and group_txid in self.expanded_groups:
            self.expanded_groups.remove(group_txid)
            self.update(reload_history=False)

    def on_deselect_node(self):
        self.hide_menu()
        self.selected_txid = ''

    def clear_selection(self):
        self.hide_menu()
        container = self.screen.ids.history_container
        container.layout_manager.clear_selection()

    def on_select_node(self, node, data):
        menu_actions = []
        self.selected_txid = data['tx_hash']
        group_txid = data['group_txid']
        if group_txid and group_txid not in self.expanded_groups:
            menu_actions.append(('Expand Tx Group', self.expand_tx_group))
        elif group_txid and group_txid in self.expanded_groups:
            menu_actions.append(('Collapse Tx Group', self.collapse_tx_group))
        if not group_txid or group_txid in self.expanded_groups:
            menu_actions.append(('Label', self.label_dialog))
        menu_actions.append(('Details', self.show_tx))
        self.hide_menu()
        self.context_menu = ContextMenu(data, menu_actions)
        self.screen.cmbox.add_widget(self.context_menu)

    def get_card(self, tx_hash, tx_type, tx_mined_status,
                 value, balance, islock, label, group_txid, group_icn):
        status, status_str = self.app.wallet.get_tx_status(tx_hash,
                                                           tx_mined_status,
                                                           islock)
        if label is None:
            label = (self.app.wallet.get_label(tx_hash) if tx_hash
                     else _('Pruned transaction outputs'))
        ri = {}
        ri['screen'] = self
        ri['tx_hash'] = tx_hash
        ri['tx_type'] = SPEC_TX_NAMES.get(tx_type, str(tx_type))
        ri['icon'] = self.atlas_path + TX_ICONS[status]
        ri['group_icn'] = group_icn
        ri['group_txid'] = group_txid
        ri['date'] = status_str
        ri['message'] = label
        ri['confirmations'] = tx_mined_status.conf
        if value is not None:
            ri['is_mine'] = value < 0
            if value < 0: value = - value
            ri['amount'] = self.app.format_amount_and_units(value)
            if self.app.fiat_unit:
                fx = self.app.fx
                fiat_value = value / Decimal(bitcoin.COIN) * self.app.wallet.price_at_timestamp(tx_hash, fx.timestamp_rate)
                fiat_value = Fiat(fiat_value, fx.ccy)
                ri['quote_text'] = fiat_value.to_ui_string()
        return ri

    def process_tx_groups(self, history):
        txs = []
        group_txs = []
        expanded_groups = set()
        selected_node = None
        selected_txid = self.selected_txid
        for (txid, tx_type, tx_mined_status, value, balance,
             islock, group_txid, group_data) in history:
            label = None
            if group_txid is None and not group_data:
                txs.append((txid, tx_type, tx_mined_status,
                            value, balance, islock, None,
                            group_txid, self.group_icn_empty))
                if selected_txid and selected_txid == txid:
                    selected_node = len(txs) - 1
            elif group_txid:
                if not group_txs:
                    tx = (txid, tx_type, tx_mined_status,
                          value, balance, islock, None,
                          group_txid, self.group_icn_tail)
                else:
                    tx = (txid, tx_type, tx_mined_status,
                          value, balance, islock, None,
                          group_txid, self.group_icn_mid)
                group_txs.append(tx)
            else:
                value, balance, group_txids = group_data
                for expanded_txid in self.expanded_groups:
                    if expanded_txid in group_txids:
                        expanded_groups.add(txid)
                if txid in expanded_groups:
                    txs.extend(group_txs)
                    txs.append((txid, tx_type, tx_mined_status,
                                value, balance, islock, None,
                                txid, self.group_icn_head))
                    if selected_txid and selected_txid in group_txids:
                        idx = group_txids.index(selected_txid)
                        selected_node = len(txs) - 1 - idx
                else:
                    tx_type = PSTxTypes.PS_MIXING_TXS
                    label = _('Group of {} Txs').format(len(group_txids))
                    txs.append((txid, tx_type, tx_mined_status,
                                value, balance, islock, label,
                                txid, self.group_icn_all))
                    if selected_txid and selected_txid in group_txids:
                        selected_node = len(txs) - 1
                        self.selected_txid = selected_txid = txid
                group_txs = []
        if selected_node is None:
            self.selected_txid = ''
        self.expanded_groups = expanded_groups
        return selected_node, txs

    @profiler
    def update(self, reload_history=True):
        if self.app.wallet is None:
            return
        if self.get_data_thread is None:
            self.get_data_thread = GetHistoryDataThread(self)
            self.get_data_thread.start()
        if reload_history:
            self.get_data_thread.need_update.set()
        else:
            self.update_data(self.history)

    @profiler
    def update_data(self, history):
        self.history = history
        selected_txid = self.selected_txid
        self.clear_selection()
        self.selected_txid = selected_txid
        selected_node, history = self.process_tx_groups(self.history)
        if selected_node is not None:
            selected_node = len(history) - 1 - selected_node
        history = reversed(history)
        history_card = self.screen.ids.history_container
        history_card.data = [self.get_card(*item) for item in history]
        if selected_node is not None:
            history_card.layout_manager.select_node(selected_node)


class SendScreen(CScreen):

    kvname = 'send'
    payment_request = None
    payment_request_queued = None
    is_ps = False

    def set_URI(self, text):
        if not self.app.wallet:
            self.payment_request_queued = text
            return
        try:
            uri = parse_URI(text, self.app.on_pr, loop=self.app.asyncio_loop)
        except InvalidBitcoinURI as e:
            self.app.show_info(_("Error parsing URI") + f":\n{e}")
            return
        amount = uri.get('amount')
        self.screen.address = uri.get('address', '')
        self.screen.message = uri.get('message', '')
        self.screen.amount = self.app.format_amount_and_units(amount) if amount else ''
        self.screen.ps_txt = self.privatesend_txt()
        self.payment_request = None
        self.screen.is_pr = False

    def update(self):
        if self.app.wallet and self.payment_request_queued:
            self.set_URI(self.payment_request_queued)
            self.payment_request_queued = None

    def do_clear(self):
        self.screen.amount = ''
        self.is_ps = False
        self.screen.ps_txt = self.privatesend_txt()
        self.screen.message = ''
        self.screen.address = ''
        self.payment_request = None
        self.screen.is_pr = False

    def set_request(self, pr):
        self.screen.address = pr.get_requestor()
        amount = pr.get_amount()
        self.screen.amount = self.app.format_amount_and_units(amount) if amount else ''
        self.screen.message = pr.get_memo()
        if pr.is_pr():
            self.screen.is_pr = True
            self.payment_request = pr
        else:
            self.screen.is_pr = False
            self.payment_request = None

    def do_save(self):
        if not self.screen.address:
            return
        if self.screen.is_pr:
            # it should be already saved
            return
        # save address as invoice
        from electrum_axe.paymentrequest import make_unsigned_request, PaymentRequest
        req = {'address':self.screen.address, 'memo':self.screen.message}
        amount = self.app.get_amount(self.screen.amount) if self.screen.amount else 0
        req['amount'] = amount
        pr = make_unsigned_request(req).SerializeToString()
        pr = PaymentRequest(pr)
        self.app.wallet.invoices.add(pr)
        self.app.show_info(_("Invoice saved"))
        if pr.is_pr():
            self.screen.is_pr = True
            self.payment_request = pr
        else:
            self.screen.is_pr = False
            self.payment_request = None

    def do_paste(self):
        data = self.app._clipboard.paste()
        if not data:
            self.app.show_info(_("Clipboard is empty"))
            return
        # try to decode as transaction
        try:
            raw_tx = tx_from_str(data)
            tx = Transaction(raw_tx)
            tx.deserialize()
        except:
            tx = None
        if tx:
            self.app.tx_dialog(tx)
            return
        # try to decode as URI/address
        self.set_URI(data)

    def do_send(self):
        if self.screen.is_pr:
            if self.payment_request.has_expired():
                self.app.show_error(_('Payment request has expired'))
                return
            outputs = self.payment_request.get_outputs()
        else:
            address = str(self.screen.address)
            if not address:
                self.app.show_error(_('Recipient not specified.') + ' ' + _('Please scan a Axe address or a payment request'))
                return
            if not bitcoin.is_address(address):
                self.app.show_error(_('Invalid Axe Address') + ':\n' + address)
                return
            try:
                amount = self.app.get_amount(self.screen.amount)
            except:
                self.app.show_error(_('Invalid amount') + ':\n' + self.screen.amount)
                return
            outputs = [TxOutput(bitcoin.TYPE_ADDRESS, address, amount)]
        message = self.screen.message
        amount = sum(map(lambda x:x[2], outputs))
        self._do_send(amount, message, outputs, self.is_ps)

    def _do_send(self, amount, message, outputs, is_ps=False):
        # make unsigned transaction
        config = self.app.electrum_config
        wallet = self.app.wallet
        mix_rounds = None if not is_ps else wallet.psman.mix_rounds
        include_ps = (mix_rounds is None)
        coins = wallet.get_spendable_coins(None, config, include_ps=include_ps,
                                           min_rounds=mix_rounds)
        try:
            tx = wallet.make_unsigned_transaction(coins, outputs, config, None,
                                                  min_rounds=mix_rounds)
        except NotEnoughFunds:
            self.app.show_error(_("Not enough funds"))
            return
        except Exception as e:
            traceback.print_exc(file=sys.stdout)
            self.app.show_error(str(e))
            return
        fee = tx.get_fee()
        msg = [
            _("Amount to be sent") + ": " + self.app.format_amount_and_units(amount),
            _("Mining fee") + ": " + self.app.format_amount_and_units(fee),
        ]
        x_fee = run_hook('get_tx_extra_fee', self.app.wallet, tx)
        if x_fee:
            x_fee_address, x_fee_amount = x_fee
            msg.append(_("Additional fees") + ": " + self.app.format_amount_and_units(x_fee_amount))

        feerate_warning = simple_config.FEERATE_WARNING_HIGH_FEE
        if fee > feerate_warning * tx.estimated_size() / 1000:
            msg.append(_('Warning') + ': ' + _("The fee for this transaction seems unusually high."))
        msg.append(_("Enter your PIN code to proceed"))
        self.app.protected('\n'.join(msg), self.send_tx, (tx, message))

    def send_tx(self, tx, message, password):
        if self.app.wallet.has_password() and password is None:
            return
        def on_success(tx):
            if tx.is_complete():
                self.app.broadcast(tx, self.payment_request)
                self.app.wallet.set_label(tx.txid(), message)
            else:
                self.app.tx_dialog(tx)
        def on_failure(error):
            self.app.show_error(error)
        if self.app.wallet.can_sign(tx):
            self.app.show_info("Signing...")
            self.app.sign_tx(tx, password, on_success, on_failure)
        else:
            self.app.tx_dialog(tx)

    def privatesend_txt(self, is_ps=None):
        if is_ps is None:
            is_ps = self.is_ps
        if is_ps:
            return _('PrivateSend')
        else:
            return _('Regular Transaction')

    def ps_dialog(self):
        from .dialogs.checkbox_dialog import CheckBoxDialog

        def ps_dialog_cb(key):
            self.is_ps = key
            if self.is_ps:
                w = self.app.wallet
                psman = w.psman
                denoms_by_vals = psman.calc_denoms_by_values()
                if denoms_by_vals:
                    if not psman.check_enough_sm_denoms(denoms_by_vals):
                        psman.postpone_notification('ps-not-enough-sm-denoms',
                                                     w, denoms_by_vals)
            self.screen.ps_txt = self.privatesend_txt()

        d = CheckBoxDialog(_('PrivateSend'),
                           _('Send coins as a PrivateSend transaction'),
                           self.is_ps, ps_dialog_cb)
        d.open()


class ReceiveScreen(CScreen):

    kvname = 'receive'

    def update(self):
        if not self.screen.address:
            self.get_new_address()
        else:
            addr = self.screen.address
            req = self.app.wallet.get_payment_request(addr,
                                                      self.app.electrum_config)
            if req:
                if req.get('status', PR_UNKNOWN) == PR_PAID:
                    self.screen.status = _('Payment received')
                else:
                    self.screen.status = ''
            else:
                self.set_address_status(addr)

    def clear(self):
        self.screen.address = ''
        self.screen.amount = ''
        self.screen.message = ''

    def get_new_address(self) -> bool:
        """Sets the address field, and returns whether the set address
        is unused."""
        if not self.app.wallet:
            return False
        self.clear()
        unused = True
        try:
            addr = self.app.wallet.get_unused_address()
            if addr is None:
                addr = self.app.wallet.get_receiving_address() or ''
                unused = False
        except InternalAddressCorruption as e:
            addr = ''
            self.app.show_error(str(e))
            send_exception_to_crash_reporter(e)
        self.screen.address = addr
        return unused

    def set_address_status(self, addr):
        if self.app.wallet.is_used(addr):
            self.screen.status = _('This address has already been used.'
                                   ' For better privacy, do not reuse it'
                                   ' for new payments.')
        elif addr in self.app.wallet.db.get_ps_reserved():
            self.screen.status = _('This address has been reserved for'
                                   ' PrivateSend use. For better privacy,'
                                   ' do not use it for new payments.')
        else:
            self.screen.status = ''

    def on_address(self, addr):
        req = self.app.wallet.get_payment_request(addr, self.app.electrum_config)
        if req:
            self.screen.message = req.get('memo', '')
            amount = req.get('amount')
            self.screen.amount = self.app.format_amount_and_units(amount) if amount else ''
            status = req.get('status', PR_UNKNOWN)
            self.screen.status = _('Payment received') if status == PR_PAID else ''
        else:
            self.set_address_status(addr)
        Clock.schedule_once(lambda dt: self.update_qr())

    def get_URI(self):
        from electrum_axe.util import create_bip21_uri
        amount = self.screen.amount
        addr = self.screen.address
        if (self.app.wallet.is_used(addr)
                or addr in self.app.wallet.db.get_ps_reserved()):
            return ''
        if amount:
            a, u = self.screen.amount.split()
            assert u == self.app.base_unit
            amount = Decimal(a) * pow(10, self.app.decimal_point())
        return create_bip21_uri(self.screen.address, amount, self.screen.message)

    @profiler
    def update_qr(self):
        qr = self.screen.ids.qr
        uri = self.get_URI()
        if self.screen.amount == '' and uri:
            qr.set_data(self.screen.address)
        else:
            qr.set_data(uri)

    def do_share(self):
        uri = self.get_URI()
        if uri:
            self.app.do_share(uri, _("Share Axe Request"))

    def do_copy(self):
        uri = self.get_URI()
        if not uri:
            return
        if self.screen.amount == '':
            self.app._clipboard.copy(self.screen.address)
            self.app.show_info(_('Address copied to clipboard'))
        else:
            self.app._clipboard.copy(uri)
            self.app.show_info(_('Request copied to clipboard'))

    def save_request(self):
        addr = self.screen.address
        if not addr:
            return False
        amount = self.screen.amount
        message = self.screen.message
        amount = self.app.get_amount(amount) if amount else 0
        req = self.app.wallet.make_payment_request(addr, amount, message, None)
        try:
            self.app.wallet.add_payment_request(req, self.app.electrum_config)
            added_request = True
        except Exception as e:
            self.app.show_error(_('Error adding payment request') + ':\n' + str(e))
            added_request = False
        finally:
            self.app.update_tab('requests')
        return added_request

    def on_amount_or_message(self):
        Clock.schedule_once(lambda dt: self.update_qr())

    def do_new(self):
        is_unused = self.get_new_address()
        if not is_unused:
            from electrum_axe.gui.kivy.uix.dialogs.question import Question
            q = _('Warning: The next address will not be recovered'
                  ' automatically if you restore your wallet from seed;'
                  ' you may need to add it manually.\n\nThis occurs because'
                  ' you have too many unused addresses in your wallet.'
                  ' To avoid this situation, use the existing addresses'
                  ' first.\n\nCreate anyway?')
            d = Question(q, self._create_new_address)
            d.open()

    def _create_new_address(self, create):
        if create:
            self.app.wallet.create_new_address(False)
            self.screen.address = ''
            self.update()

    def do_save(self):
        if self.save_request():
            self.app.show_info(_('Request was saved.'))


class TabbedCarousel(Factory.TabbedPanel):
    '''Custom TabbedPanel using a carousel used in the Main Screen
    '''

    carousel = ObjectProperty(None)

    def animate_tab_to_center(self, value):
        scrlv = self._tab_strip.parent
        if not scrlv:
            return
        idx = self.tab_list.index(value)
        n = len(self.tab_list)
        if idx in [0, 1]:
            scroll_x = 1
        elif idx in [n-1, n-2]:
            scroll_x = 0
        else:
            scroll_x = 1. * (n - idx - 1) / (n - 1)
        mation = Factory.Animation(scroll_x=scroll_x, d=.25)
        mation.cancel_all(scrlv)
        mation.start(scrlv)

    def on_current_tab(self, instance, value):
        self.animate_tab_to_center(value)

    def on_index(self, instance, value):
        current_slide = instance.current_slide
        if not hasattr(current_slide, 'tab'):
            return
        tab = current_slide.tab
        ct = self.current_tab
        try:
            if ct.text != tab.text:
                carousel = self.carousel
                carousel.slides[ct.slide].dispatch('on_leave')
                self.switch_to(tab)
                carousel.slides[tab.slide].dispatch('on_enter')
        except AttributeError:
            current_slide.dispatch('on_enter')

    def switch_to(self, header):
        # we have to replace the functionality of the original switch_to
        if not header:
            return
        if not hasattr(header, 'slide'):
            header.content = self.carousel
            super(TabbedCarousel, self).switch_to(header)
            try:
                tab = self.tab_list[-1]
            except IndexError:
                return
            self._current_tab = tab
            tab.state = 'down'
            return

        carousel = self.carousel
        self.current_tab.state = "normal"
        header.state = 'down'
        self._current_tab = header
        # set the carousel to load the appropriate slide
        # saved in the screen attribute of the tab head
        slide = carousel.slides[header.slide]
        if carousel.current_slide != slide:
            carousel.current_slide.dispatch('on_leave')
            carousel.load_slide(slide)
            slide.dispatch('on_enter')

    def add_widget(self, widget, index=0):
        if isinstance(widget, Factory.CScreen):
            self.carousel.add_widget(widget)
            return
        super(TabbedCarousel, self).add_widget(widget, index=index)
