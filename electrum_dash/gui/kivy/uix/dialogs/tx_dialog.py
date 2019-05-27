from datetime import datetime
from typing import NamedTuple, Callable

from kivy.app import App
from kivy.factory import Factory
from kivy.properties import ObjectProperty
from kivy.lang import Builder
from kivy.clock import Clock
from kivy.uix.label import Label
from kivy.uix.dropdown import DropDown
from kivy.uix.button import Button

from .question import Question
from electrum_dash.gui.kivy.i18n import _

from electrum_dash.util import InvalidPassword
from electrum_dash.address_synchronizer import TX_HEIGHT_LOCAL


Builder.load_string('''

<TxDialog>
    id: popup
    title: _('Transaction')
    is_mine: True
    can_sign: False
    can_broadcast: False
    fee_str: ''
    date_str: ''
    date_label:''
    amount_str: ''
    tx_hash: ''
    status_str: ''
    description: ''
    outputs_str: ''
    BoxLayout:
        orientation: 'vertical'
        ScrollView:
            scroll_type: ['bars', 'content']
            bar_width: '25dp'
            GridLayout:
                height: self.minimum_height
                size_hint_y: None
                cols: 1
                spacing: '10dp'
                padding: '10dp'
                GridLayout:
                    height: self.minimum_height
                    size_hint_y: None
                    cols: 1
                    spacing: '10dp'
                    BoxLabel:
                        text: _('Status')
                        value: root.status_str
                    BoxLabel:
                        text: _('Description') if root.description else ''
                        value: root.description
                    BoxLabel:
                        text: root.date_label
                        value: root.date_str
                    BoxLabel:
                        text: _('Amount sent') if root.is_mine else _('Amount received')
                        value: root.amount_str
                    BoxLabel:
                        text: _('Transaction fee') if root.fee_str else ''
                        value: root.fee_str
                TopLabel:
                    text: _('Transaction ID') + ':' if root.tx_hash else ''
                TxHashLabel:
                    data: root.tx_hash
                    name: _('Transaction ID')
                TopLabel:
                    text: _('Outputs') + ':'
                OutputList:
                    id: output_list
        Widget:
            size_hint: 1, 0.1

        BoxLayout:
            size_hint: 1, None
            height: '48dp'
            Button:
                id: action_button
                size_hint: 0.5, None
                height: '48dp'
                text: ''
                disabled: True
                opacity: 0
                on_release: root.on_action_button_clicked()
            IconButton:
                size_hint: 0.5, None
                height: '48dp'
                icon: 'atlas://electrum_dash/gui/kivy/theming/light/qrcode'
                on_release: root.show_qr()
            Button:
                size_hint: 0.5, None
                height: '48dp'
                text: _('Close')
                on_release: root.dismiss()
''')


class ActionButtonOption(NamedTuple):
    text: str
    func: Callable
    enabled: bool


class TxDialog(Factory.Popup):

    def __init__(self, app, tx):
        Factory.Popup.__init__(self)
        self.app = app
        self.wallet = self.app.wallet
        self.tx = tx
        self._action_button_fn = lambda btn: None

    def on_open(self):
        self.update()

    def update(self):
        format_amount = self.app.format_amount_and_units
        tx_details = self.wallet.get_tx_info(self.tx)
        tx_mined_status = tx_details.tx_mined_status
        exp_n = tx_details.mempool_depth_bytes
        amount, fee = tx_details.amount, tx_details.fee
        self.status_str = tx_details.status
        self.description = tx_details.label
        self.can_broadcast = tx_details.can_broadcast
        self.tx_hash = tx_details.txid or ''
        if tx_mined_status.timestamp:
            self.date_label = _('Date')
            self.date_str = datetime.fromtimestamp(tx_mined_status.timestamp).isoformat(' ')[:-3]
        elif exp_n:
            self.date_label = _('Mempool depth')
            self.date_str = _('{} from tip').format('%.2f MB'%(exp_n/1000000))
        else:
            self.date_label = ''
            self.date_str = ''

        if amount is None:
            self.amount_str = _("Transaction unrelated to your wallet")
        elif amount > 0:
            self.is_mine = False
            self.amount_str = format_amount(amount)
        else:
            self.is_mine = True
            self.amount_str = format_amount(-amount)
        self.fee_str = format_amount(fee) if fee is not None else _('unknown')
        self.can_sign = self.wallet.can_sign(self.tx)
        self.ids.output_list.update(self.tx.get_outputs_for_UI())
        self.is_local_tx = tx_mined_status.height == TX_HEIGHT_LOCAL
        self.update_action_button()

    def update_action_button(self):
        action_button = self.ids.action_button
        options = (
            ActionButtonOption(text=_('Sign'), func=lambda btn: self.do_sign(), enabled=self.can_sign),
            ActionButtonOption(text=_('Broadcast'), func=lambda btn: self.do_broadcast(), enabled=self.can_broadcast),
            ActionButtonOption(text=_('Remove'), func=lambda btn: self.remove_local_tx(), enabled=self.is_local_tx),
        )
        num_options = sum(map(lambda o: bool(o.enabled), options))
        # if no options available, hide button
        if num_options == 0:
            action_button.disabled = True
            action_button.opacity = 0
            return
        action_button.disabled = False
        action_button.opacity = 1

        if num_options == 1:
            # only one option, button will correspond to that
            for option in options:
                if option.enabled:
                    action_button.text = option.text
                    self._action_button_fn = option.func
        else:
            # multiple options. button opens dropdown which has one sub-button for each
            dropdown = DropDown()
            action_button.text = _('Options')
            self._action_button_fn = dropdown.open
            for option in options:
                if option.enabled:
                    btn = Button(text=option.text, size_hint_y=None, height=48)
                    btn.bind(on_release=option.func)
                    dropdown.add_widget(btn)

    def on_action_button_clicked(self):
        action_button = self.ids.action_button
        self._action_button_fn(action_button)

    def do_sign(self):
        self.app.protected(_("Enter your PIN code in order to sign this transaction"), self._do_sign, ())

    def _do_sign(self, password):
        self.status_str = _('Signing') + '...'
        Clock.schedule_once(lambda dt: self.__do_sign(password), 0.1)

    def __do_sign(self, password):
        try:
            self.app.wallet.sign_transaction(self.tx, password)
        except InvalidPassword:
            self.app.show_error(_("Invalid PIN"))
        self.update()

    def do_broadcast(self):
        self.app.broadcast(self.tx)

    def show_qr(self):
        from electrum_dash.bitcoin import base_encode, bfh
        raw_tx = str(self.tx)
        text = bfh(raw_tx)
        text = base_encode(text, base=43)
        self.app.qr_dialog(_("Raw Transaction"), text, text_for_clipboard=raw_tx)

    def remove_local_tx(self):
        txid = self.tx.txid()
        to_delete = {txid}
        to_delete |= self.wallet.get_depending_transactions(txid)
        question = _("Are you sure you want to remove this transaction?")
        if len(to_delete) > 1:
            question = (_("Are you sure you want to remove this transaction and {} child transactions?")
                        .format(len(to_delete) - 1))

        def on_prompt(b):
            if b:
                for tx in to_delete:
                    self.wallet.remove_transaction(tx)
                self.wallet.storage.write()
                self.app._trigger_update_wallet()  # FIXME private...
                self.dismiss()
        d = Question(question, on_prompt)
        d.open()
