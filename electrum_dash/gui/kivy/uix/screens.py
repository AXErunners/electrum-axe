from weakref import ref
from decimal import Decimal
import re
import datetime
import traceback, sys

from kivy.app import App
from kivy.cache import Cache
from kivy.clock import Clock
from kivy.compat import string_types
from kivy.properties import (ObjectProperty, DictProperty, NumericProperty,
                             ListProperty, StringProperty)

from kivy.uix.recycleview import RecycleView
from kivy.uix.label import Label

from kivy.lang import Builder
from kivy.factory import Factory
from kivy.utils import platform

from electrum_dash.util import profiler, parse_URI, format_time, InvalidPassword, NotEnoughFunds, Fiat
from electrum_dash import bitcoin
from electrum_dash.transaction import TxOutput, Transaction, tx_from_str
from electrum_dash.util import send_exception_to_crash_reporter, parse_URI, InvalidBitcoinURI
from electrum_dash.paymentrequest import PR_UNPAID, PR_PAID, PR_UNKNOWN, PR_EXPIRED
from electrum_dash.plugin import run_hook
from electrum_dash.wallet import InternalAddressCorruption
from electrum_dash import simple_config

from .context_menu import ContextMenu


from electrum_dash.gui.kivy.i18n import _

class HistoryRecycleView(RecycleView):
    pass

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
        self.screen = Builder.load_file('electrum_dash/gui/kivy/uix/ui_screens/' + self.kvname + '.kv')
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
            self.remove_widget(self.context_menu)
            self.context_menu = None

    def show_menu(self, obj):
        self.hide_menu()
        self.context_menu = ContextMenu(obj, self.menu_actions)
        self.add_widget(self.context_menu)


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
    "confirmed",
]

class HistoryScreen(CScreen):

    tab = ObjectProperty(None)
    kvname = 'history'
    cards = {}

    def __init__(self, **kwargs):
        self.ra_dialog = None
        super(HistoryScreen, self).__init__(**kwargs)
        self.menu_actions = [ ('Label', self.label_dialog), ('Details', self.show_tx)]

    def show_tx(self, obj):
        tx_hash = obj.tx_hash
        tx = self.app.wallet.db.get_transaction(tx_hash)
        if not tx:
            return
        self.app.tx_dialog(tx)

    def label_dialog(self, obj):
        from .dialogs.label_dialog import LabelDialog
        key = obj.tx_hash
        text = self.app.wallet.get_label(key)
        def callback(text):
            self.app.wallet.set_label(key, text)
            self.update()
        d = LabelDialog(_('Enter Transaction Label'), text, callback)
        d.open()

    def get_card(self, tx_hash, tx_type, tx_mined_status, value, balance):
        status, status_str = self.app.wallet.get_tx_status(tx_hash, tx_mined_status)
        icon = "atlas://electrum_dash/gui/kivy/theming/light/" + TX_ICONS[status]
        label = self.app.wallet.get_label(tx_hash) if tx_hash else _('Pruned transaction outputs')
        ri = {}
        ri['screen'] = self
        ri['tx_hash'] = tx_hash
        ri['icon'] = icon
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

    def update(self, see_all=False):
        if self.app.wallet is None:
            return
        config = self.app.electrum_config
        history = reversed(self.app.wallet.get_history(config=config))
        history_card = self.screen.ids.history_container
        history_card.data = [self.get_card(*item) for item in history]


class SendScreen(CScreen):

    kvname = 'send'
    payment_request = None
    payment_request_queued = None

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
        self.payment_request = None
        self.screen.is_pr = False

    def update(self):
        if self.app.wallet and self.payment_request_queued:
            self.set_URI(self.payment_request_queued)
            self.payment_request_queued = None

    def do_clear(self):
        self.screen.amount = ''
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
        from electrum_dash.paymentrequest import make_unsigned_request, PaymentRequest
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
                self.app.show_error(_('Recipient not specified.') + ' ' + _('Please scan a Dash address or a payment request'))
                return
            if not bitcoin.is_address(address):
                self.app.show_error(_('Invalid Dash Address') + ':\n' + address)
                return
            try:
                amount = self.app.get_amount(self.screen.amount)
            except:
                self.app.show_error(_('Invalid amount') + ':\n' + self.screen.amount)
                return
            outputs = [TxOutput(bitcoin.TYPE_ADDRESS, address, amount)]
        message = self.screen.message
        amount = sum(map(lambda x:x[2], outputs))
        self._do_send(amount, message, outputs)

    def _do_send(self, amount, message, outputs):
        # make unsigned transaction
        config = self.app.electrum_config
        coins = self.app.wallet.get_spendable_coins(None, config)
        try:
            tx = self.app.wallet.make_unsigned_transaction(coins, outputs, config, None)
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


class ReceiveScreen(CScreen):

    kvname = 'receive'

    def update(self):
        if not self.screen.address:
            self.get_new_address()
        else:
            status = self.app.wallet.get_request_status(self.screen.address)
            self.screen.status = _('Payment received') if status == PR_PAID else ''

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

    def on_address(self, addr):
        req = self.app.wallet.get_payment_request(addr, self.app.electrum_config)
        self.screen.status = ''
        if req:
            self.screen.message = req.get('memo', '')
            amount = req.get('amount')
            self.screen.amount = self.app.format_amount_and_units(amount) if amount else ''
            status = req.get('status', PR_UNKNOWN)
            self.screen.status = _('Payment received') if status == PR_PAID else ''
        Clock.schedule_once(lambda dt: self.update_qr())

    def get_URI(self):
        from electrum_dash.util import create_bip21_uri
        amount = self.screen.amount
        if amount:
            a, u = self.screen.amount.split()
            assert u == self.app.base_unit
            amount = Decimal(a) * pow(10, self.app.decimal_point())
        return create_bip21_uri(self.screen.address, amount, self.screen.message)

    @profiler
    def update_qr(self):
        uri = self.get_URI()
        qr = self.screen.ids.qr
        qr.set_data(uri)

    def do_share(self):
        uri = self.get_URI()
        self.app.do_share(uri, _("Share Dash Request"))

    def do_copy(self):
        uri = self.get_URI()
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
            self.app.show_info(_('Please use the existing requests first.'))

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
