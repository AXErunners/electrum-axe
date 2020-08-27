from kivy.factory import Factory
from kivy.lang import Builder
from kivy.properties import BooleanProperty, StringProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.recycleview.layout import LayoutSelectionBehavior
from kivy.uix.recycleview.views import RecycleDataViewBehavior
from kivy.uix.recycleboxlayout import RecycleBoxLayout
from kivy.uix.behaviors import FocusBehavior

from electrum_axe.axe_ps import sort_utxos_by_ps_rounds
from electrum_axe.axe_tx import PSCoinRounds, SPEC_TX_NAMES
from electrum_axe.gui.kivy.i18n import _
from electrum_axe.gui.kivy.uix.context_menu import ContextMenu
from electrum_axe.gui.kivy.uix.dialogs.question import Question


Builder.load_string('''
<CoinLabel@Label>
    text_size: self.width, None
    halign: 'left'
    valign: 'top'
    shorten: True


<CoinItem>
    outpoint: ''
    address: ''
    block_height: ''
    amount: ''
    ps_rounds: ''
    size_hint: 1, None
    height: '65dp'
    padding: dp(12)
    spacing: dp(5)
    canvas.before:
        Color:
            rgba: (0.192, .498, 0.745, 1) if self.selected  \
                else (0.15, 0.15, 0.17, 1)
        Rectangle:
            size: self.size
            pos: self.pos
    BoxLayout:
        spacing: '8dp'
        height: '32dp'
        orientation: 'vertical'
        Widget
        CoinLabel:
            text: root.outpoint
        Widget
        CoinLabel:
            text: '%s    Height: %s' % (root.address, root.block_height)
            color: .699, .699, .699, 1
            font_size: '13sp'
        Widget
        CoinLabel:
            text: '%s    PS Rounds: %s' % (root.amount, root.ps_rounds)
            color: .699, .899, .699, 1
            font_size: '13sp'
        Widget


<CoinsDialog@Popup>
    id: dlg
    title: _('Coins')
    show_ps_ks: 0
    show_ps: 0
    cmbox: cmbox
    padding: 0
    spacing: 0
    BoxLayout:
        id: box
        padding: '12dp', '12dp', '12dp', '12dp'
        spacing: '12dp'
        orientation: 'vertical'
        size_hint: 1, 1
        BoxLayout:
            spacing: '6dp'
            size_hint: 1, None
            height: self.minimum_height
            orientation: 'horizontal'
            AddressFilter:
                opacity: 1
                size_hint: 1, None
                height: self.minimum_height
                spacing: '5dp'
                AddressButton:
                    text: {0: _('Main'), \
                           1: _('PS Keystore'), \
                           2: _('All')}[root.show_ps_ks]
                    on_release:
                        root.show_ps_ks = (root.show_ps_ks + 1) % 3
                        Clock.schedule_once(lambda dt: root.update())
            AddressFilter:
                opacity: 1
                size_hint: 1, None
                height: self.minimum_height
                spacing: '5dp'
                AddressButton:
                    text: {0: _('PrivateSend'), \
                           1: _('PS Other coins'), \
                           2: _('Regular'), \
                           3: _('All')}[root.show_ps]
                    on_release:
                        root.show_ps = (root.show_ps + 1) % 4
                        Clock.schedule_once(lambda dt: root.update())
            AddressFilter:
                opacity: 1
                size_hint: 1, None
                height: self.minimum_height
                spacing: '5dp'
                AddressButton:
                    id: clear_btn
                    disabled: True
                    disabled_color: 0.5, 0.5, 0.5, 1
                    text: _('Clear Selection') + root.selected_str
                    on_release:
                        Clock.schedule_once(lambda dt: root.clear_selection())
        RecycleView:
            scroll_type: ['bars', 'content']
            bar_width: '15dp'
            viewclass: 'CoinItem'
            id: scroll_container
            CoinsRecycleBoxLayout:
                dlg: dlg
                orientation: 'vertical'
                default_size: None, dp(72)
                default_size_hint: 1, None
                size_hint_y: None
                height: self.minimum_height
                multiselect: False
                touch_multiselect: False
        BoxLayout:
            id: cmbox
            height: '48dp'
            size_hint: 1, None
            orientation: 'vertical'
            canvas.before:
                Color:
                    rgba: .1, .1, .1, 1
                Rectangle:
                    pos: self.pos
                    size: self.size
''')


class CoinItem(RecycleDataViewBehavior, BoxLayout):
    index = None
    selected = BooleanProperty(False)

    def refresh_view_attrs(self, rv, index, data):
        self.index = index
        return super(CoinItem, self).refresh_view_attrs(rv, index, data)

    def on_touch_down(self, touch):
        if super(CoinItem, self).on_touch_down(touch):
            return True
        if self.collide_point(*touch.pos):
            return self.parent.select_with_touch(self.index, touch)

    def apply_selection(self, rv, index, is_selected):
        self.selected = is_selected


class CoinsRecycleBoxLayout(FocusBehavior, LayoutSelectionBehavior,
                            RecycleBoxLayout):
    def select_node(self, node):
        super(CoinsRecycleBoxLayout, self).select_node(node)
        self.dlg.selection_changed(self.selected_nodes)

    def deselect_node(self, node):
        super(CoinsRecycleBoxLayout, self).deselect_node(node)
        self.dlg.selection_changed(self.selected_nodes)


class CoinsDialog(Factory.Popup):

    selected_str = StringProperty('')

    def __init__(self, app, filter_val=0):
        Factory.Popup.__init__(self)
        self.app = app
        self.context_menu = None
        self.coins_selected = []
        self.utxos = []
        self.show_ps = filter_val

    def get_card(self, prev_h, prev_n, addr, amount, height, ps_rounds):
        ci = {}
        ci['outpoint'] = f'{prev_h[:32]}...:{prev_n}'
        ci['address'] = addr
        ci['amount'] = self.app.format_amount_and_units(amount)
        ci['block_height'] = str(height)
        if ps_rounds is None:
            ci['ps_rounds'] = 'N/A'
        elif ps_rounds == PSCoinRounds.OTHER:
            ci['ps_rounds'] = 'Other'
        elif ps_rounds == PSCoinRounds.COLLATERAL:
            ci['ps_rounds'] = 'Collateral'
        else:
            ci['ps_rounds'] = str(ps_rounds)
        ci['ps_rounds_orig'] = ps_rounds
        ci['prev_h'] = prev_h
        ci['prev_n'] = prev_n
        return ci

    def update(self):
        w = self.app.wallet
        if self.show_ps == 1:  # PS Other coins
            utxos = w.get_utxos(min_rounds=PSCoinRounds.MINUSINF)
            utxos = [c for c in utxos if c['ps_rounds'] <= PSCoinRounds.OTHER]
        elif self.show_ps == 2:  # Regular
            utxos = w.get_utxos()
        elif self.show_ps == 3:  # All
            utxos = w.get_utxos(include_ps=True)
        else:  # PrivateSend
            utxos = w.get_utxos(min_rounds=PSCoinRounds.COLLATERAL)
        if self.show_ps_ks == 0:    # Main
            utxos = [c for c in utxos if not c['is_ps_ks']]
        elif self.show_ps_ks == 1:  # PS Keystore
            utxos = [c for c in utxos if c['is_ps_ks']]
        utxos.sort(key=sort_utxos_by_ps_rounds)
        container = self.ids.scroll_container
        container.layout_manager.clear_selection()
        container.scroll_y = 1
        cards = []
        self.utxos = utxos
        for utxo in utxos:
            prev_h = utxo['prevout_hash']
            prev_n = utxo['prevout_n']
            addr = utxo['address']
            amount = utxo['value']
            height = utxo['height']
            ps_rounds = utxo['ps_rounds']
            card = self.get_card(prev_h, prev_n, addr,
                                 amount, height, ps_rounds)
            cards.append(card)
        container.data = cards

    def hide_menu(self):
        if self.context_menu is not None:
            self.cmbox.remove_widget(self.context_menu)
            self.context_menu = None

    def clear_selection(self):
        container = self.ids.scroll_container
        container.layout_manager.clear_selection()

    def selection_changed(self, nodes):
        w = self.app.wallet
        psman = w.psman
        self.hide_menu()
        self.coins_selected = [self.utxos[i] for i in nodes]
        if not self.coins_selected:
            self.selected_str = ''
            self.ids.clear_btn.disabled = True
            return
        else:
            self.selected_str = f' ({len(self.coins_selected)})'
            self.ids.clear_btn.disabled = False

        coins = self.coins_selected
        if len(coins) != 1:
            return
        r = coins[0]['ps_rounds']
        if r is None:
            return
        if r == PSCoinRounds.OTHER or r >= 0:
            coin_value = coins[0]['value']
            if coin_value >= psman.min_new_denoms_from_coins_val:
                cmenu = [(_('Create New Denoms'), self.create_new_denoms)]
            elif coin_value >= psman.min_new_collateral_from_coins_val:
                cmenu = [(_('Create New Collateral'),
                         self.create_new_collateral)]
            self.context_menu = ContextMenu(None, cmenu)
            self.cmbox.add_widget(self.context_menu)

    def create_new_denoms(self, obj):
        coins = self.coins_selected[:]
        self.hide_menu()
        self.clear_selection()
        self.app.create_new_denoms(coins)

    def create_new_collateral(self, obj):
        coins = self.coins_selected[:]
        self.hide_menu()
        self.clear_selection()
        self.app.create_new_collateral(coins)
