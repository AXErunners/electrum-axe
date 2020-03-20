from kivy.app import App
from kivy.factory import Factory
from kivy.properties import StringProperty
from kivy.lang import Builder
from decimal import Decimal

from electrum_axe.bitcoin import COIN


Builder.load_string('''

<AmountDialog@Popup>
    id: popup
    available_amount: ''
    title: _('Amount')
    ScrollView:
        do_scroll_y: True
        AnchorLayout:
            anchor_x: 'center'
            size_hint_min_y: 520
            BoxLayout:
                id: main_box
                orientation: 'vertical'
                size_hint: 0.9, 1
                BoxLayout:
                    id: available_amount_box
                    orientation: 'horizontal'
                    size_hint: 1, 0.2
                    Label:
                        text: _('Available amount') + ':'
                        text_size: btc.width, None
                        size: self.texture_size
                    Label:
                        text: root.available_amount
                        text_size: btc.width, None
                        size: self.texture_size
                        halign: 'center'
                BoxLayout:
                    size_hint: 1, None
                    height: '80dp'
                    Button:
                        background_color: 0, 0, 0, 0
                        id: btc
                        text: kb.amount + ' ' + app.base_unit
                        color: (0.7, 0.7, 1, 1) if kb.is_fiat else (1, 1, 1, 1)
                        halign: 'right'
                        size_hint: 1, None
                        font_size: '20dp'
                        height: '48dp'
                        on_release: root.on_fiat(False)
                    Button:
                        background_color: 0, 0, 0, 0
                        id: fiat
                        text: kb.fiat_amount + ' ' + app.fiat_unit
                        color: (1, 1, 1, 1) if kb.is_fiat else (0.7, 0.7, 1, 1)
                        halign: 'right'
                        size_hint: 1, None
                        font_size: '20dp'
                        height: '48dp'
                        disabled: not app.fx.is_enabled()
                        on_release: root.on_fiat(True)
                Widget:
                    size_hint: 1, 0.1
                GridLayout:
                    id: kb
                    amount: ''
                    fiat_amount: ''
                    is_fiat: False
                    on_fiat_amount: if self.is_fiat: self.amount = app.fiat_to_btc(self.fiat_amount)
                    on_amount: if not self.is_fiat: self.fiat_amount = app.btc_to_fiat(self.amount)
                    size_hint: 1, None
                    update_amount: popup.update_amount
                    height: '300dp'
                    cols: 3
                    KButton:
                        text: '1'
                    KButton:
                        text: '2'
                    KButton:
                        text: '3'
                    KButton:
                        text: '4'
                    KButton:
                        text: '5'
                    KButton:
                        text: '6'
                    KButton:
                        text: '7'
                    KButton:
                        text: '8'
                    KButton:
                        text: '9'
                    KButton:
                        text: '.'
                    KButton:
                        text: '0'
                    KButton:
                        text: '<'
                    Widget:
                        size_hint: 1, None
                        height: '48dp'
                    Button:
                        id: but_max
                        opacity: 1 if root.show_max else 0
                        disabled: not root.show_max
                        size_hint: 1, None
                        height: '48dp'
                        text: 'Max'
                        on_release:
                            kb.is_fiat = False
                            kb.amount = app.get_max_amount(is_ps=root.is_ps)
                            root.recalc_available_amount()
                    Button:
                        size_hint: 1, None
                        height: '48dp'
                        text: 'Clear'
                        on_release:
                            kb.amount = ''
                            kb.fiat_amount = ''
                Widget:
                    size_hint: 1, 0.1
                BoxLayout:
                    size_hint: 1, None
                    height: '48dp'
                    Widget:
                        size_hint: 1, None
                        height: '48dp'
                    Button:
                        size_hint: 1, None
                        height: '48dp'
                        text: _('OK')
                        on_release: root.on_finish()
''')

from kivy.properties import BooleanProperty

class AmountDialog(Factory.Popup):
    show_max = BooleanProperty(False)
    app = App.get_running_app()
    available_amount = StringProperty()
    is_ps = BooleanProperty(False)

    def __init__(self, show_max, amount, is_ps=None, cb=None):
        Factory.Popup.__init__(self)
        self.show_max = show_max
        self.callback = cb
        if amount:
            self.ids.kb.amount = amount

        if is_ps is not None:  # is amount dialog in send screen
            self.is_spend = True
            self.is_ps = is_ps
        else:  # is amount dialog in receive screen
            self.is_spend = False

        main_box = self.ids.main_box
        available_amount_box = self.ids.available_amount_box
        if not self.is_spend:
            main_box.remove_widget(available_amount_box)
        else:
            self.recalc_available_amount()

    def update_amount(self, c):
        kb = self.ids.kb
        amount = kb.fiat_amount if kb.is_fiat else kb.amount
        if c == '<':
            amount = amount[:-1]
        elif c == '.' and amount in ['0', '']:
            amount = '0.'
        elif amount == '0':
            amount = c
        else:
            try:
                Decimal(amount+c)
                amount += c
            except:
                pass
        if kb.is_fiat:
            kb.fiat_amount = amount
        else:
            kb.amount = amount

    def on_finish(self):
        btc = self.ids.btc
        kb = self.ids.kb
        amount = btc.text if kb.amount else ''
        if self.is_spend:
            self.callback(amount)
        else:
            self.callback(amount)
        self.dismiss()

    def on_fiat(self, is_fiat):
        kb = self.ids.kb
        kb.is_fiat = is_fiat
        self.recalc_available_amount()

    def recalc_available_amount(self):
        app = self.app
        kb = self.ids.kb
        max_amount = app.get_max_amount(is_ps=self.is_ps)
        if not max_amount:
            max_amount = 0
        max_amount = COIN * Decimal(max_amount)
        if kb.is_fiat:
            max_amount = app.fx.format_amount(max_amount)
            ccy = app.fx.ccy
            max_amount = f'{max_amount} {ccy}'
        else:
            max_amount = app.format_amount_and_units(max_amount)
        self.available_amount = max_amount
