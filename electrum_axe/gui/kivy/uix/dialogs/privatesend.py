import time

from electrum_axe.axe_ps import filter_log_line, PSLogSubCat, PSStates

from kivy.clock import Clock
from kivy.properties import (NumericProperty, StringProperty, BooleanProperty,
                             ObjectProperty)
from kivy.lang import Builder
from kivy.uix.behaviors import FocusBehavior
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.popup import Popup
from kivy.uix.recycleview.layout import LayoutSelectionBehavior
from kivy.uix.recycleview.views import RecycleDataViewBehavior
from kivy.uix.recycleboxlayout import RecycleBoxLayout

from electrum_axe.gui.kivy.i18n import _
from electrum_axe.gui.kivy.uix.dialogs.question import Question


Builder.load_string('''
#:import _ electrum_axe.gui.kivy.i18n._
#:import SpinBox electrum_axe.gui.kivy.uix.spinbox.SpinBox


<LineItem>
    text: ''
    lb: lb
    size_hint: 1, None
    height: lb.height
    markup: True
    canvas.before:
        Color:
            rgba: (0.192, .498, 0.745, 1) if self.selected  \
                else (0.15, 0.15, 0.17, 1)
        Rectangle:
            size: self.size
            pos: self.pos
    Label:
        id: lb
        text: root.text
        halign: 'left'
        valign: 'top'
        size_hint_y: None
        text_size: self.width, None
        height: self.texture_size[1]
        padding: dp(5), dp(5)
        font_size: '13sp'


<RecycledLinesView@RecycleView>
    btns: None
    app: None
    scroll_type: ['bars', 'content']
    bar_width: '15dp'
    viewclass: 'LineItem'
    LinesRecycleBoxLayout:
        btns: root.btns
        orientation: 'vertical'
        size_hint_y: None
        padding: '5dp', '5dp'
        spacing: '5dp'
        height: self.minimum_height
        default_size: None, None
        default_size_hint: 1, None
        multiselect: True
        touch_multiselect: True


<SelectionButtons@BoxLayout>
    rv: None
    clear_sel: clear_sel
    copy_sel: copy_sel
    copy_filtered: copy_filtered.__self__
    orientation: 'horizontal'
    size_hint: 1, None
    height: self.minimum_height
    Button:
        id: sel_all
        text: _('Select All')
        size_hint: 1, None
        height: '48dp'
        on_release: root.rv.layout_manager.select_all()
    Button:
        id: clear_sel
        text: _('Clear Selection')
        size_hint: 1, None
        height: '48dp'
        disabled: True
        on_release: root.rv.layout_manager.clear_selection()
    Button:
        id: copy_sel
        text: _('Copy')
        size_hint: 1, None
        height: '48dp'
        disabled: True
        on_release: root.rv.layout_manager.copy_selected()
    Button:
        id: copy_filtered
        text: _('Copy filtered')
        size_hint: 1, None
        height: '48dp'
        disabled: True
        on_release: root.rv.layout_manager.copy_filtered()


<EXWarnPopup@Popup>
    id: popup
    cb: cb
    title: _('Warning')
    title_align: 'center'
    size_hint: 0.8, 0.8
    pos_hint: {'top':0.9}
    BoxLayout:
        padding: 10
        spacing: 10
        orientation: 'vertical'
        Image:
            source:'atlas://electrum_axe/gui/kivy/theming/light/error'
            size_hint_y: 0.1
        Label:
            size_hint_y: 0.4
            id: warn_msg
            halign: 'left'
            text_size: self.width, None
            size: self.texture_size
        BoxLayout:
            orientation: 'horizontal'
            size_hint_y: 0.3
            Label:
                size_hint_x: 0.7
                text: _('Do not show this on PrivateSend popup open.')
                text_size: self.width, None
                size: self.texture_size
            CheckBox:
                id:cb
                size_hint_x: 0.3
        Button:
            text: 'OK'
            size_hint_y: 0.2
            height: '48dp'
            on_release:
                popup.dismiss()


<KeepAmountPopup@Popup>
    title: root.title
    size_hint: 0.8, 0.5
    spinbox: spinbox
    BoxLayout:
        orientation: 'vertical'
        padding: dp(10), dp(10)
        spacing: dp(10)
        SpinBox:
            id: spinbox
            size_hint: 1, 0.7
        Button:
            text: _('Set')
            size_hint: 1, 0.3
            on_release: root.dismiss(spinbox.value)


<MixRoundsPopup@Popup>
    title: root.title
    size_hint: 0.8, 0.5
    spinbox: spinbox
    BoxLayout:
        padding: dp(10), dp(10)
        spacing: dp(10)
        orientation: 'vertical'
        SpinBox:
            id: spinbox
            size_hint: 1, 0.7
        Button:
            text: _('Set')
            size_hint: 1, 0.3
            on_release: root.dismiss(spinbox.value)


<MaxSessionsPopup@Popup>
    title: root.title
    size_hint: 0.8, 0.5
    spinbox: spinbox
    BoxLayout:
        padding: dp(10), dp(10)
        spacing: dp(10)
        orientation: 'vertical'
        SpinBox:
            id: spinbox
            size_hint: 1, 0.7
        Button:
            text: _('Set')
            size_hint: 1, 0.3
            on_release: root.dismiss(spinbox.value)


<KPTimeoutPopup@Popup>
    title: root.title
    size_hint: 0.8, 0.5
    spinbox: spinbox
    BoxLayout:
        padding: dp(10), dp(10)
        spacing: dp(10)
        orientation: 'vertical'
        SpinBox:
            id: spinbox
            size_hint: 1, 0.7
        Button:
            text: _('Set')
            size_hint: 1, 0.3
            on_release: root.dismiss(spinbox.value)


<SettingsProgress@ButtonBehavior+BoxLayout>
    orientation: 'vertical'
    title: ''
    prog_val: 0
    size_hint: 1, None
    height: self.minimum_height
    padding: 0, '10dp', 0, '10dp'
    spacing: '10dp'
    canvas.before:
        Color:
            rgba: (.2, .5, .75, 1) if self.state == 'down' else (.3, .3, .3, 0)
        Rectangle:
            size: self.size
            pos: self.pos
    on_release:
        Clock.schedule_once(self.action)
    TopLabel:
        id: title
        text: self.parent.title + ': %s%%' % self.parent.prog_val
        bold: True
        halign: 'left'
    ProgressBar:
        height: '20dp'
        size_hint: 1, None
        max: 100
        value: self.parent.prog_val


<MixingProgressPopup@Popup>
    title: root.title
    data: data
    ScrollView:
        Label:
            id: data
            text: ''
            halign: 'left'
            valign: 'top'
            size_hint_y: None
            text_size: self.width, None
            height: self.texture_size[1]
            padding: dp(5), dp(5)


<PSMixingTab@BoxLayout>
    orientation: 'vertical'
    ScrollView:
        GridLayout:
            id: scrollviewlayout
            cols:1
            size_hint: 1, None
            height: self.minimum_height
            padding: '10dp'
            CardSeparator
            SettingsItem:
                title: root.warn_electrumx_text
                description: root.warn_electrumx_help
                action: root.show_warn_electrumx
            CardSeparator
            SettingsItem:
                title: root.keep_amount_text + ': %s Axe' % root.keep_amount
                description: root.keep_amount_help
                action: root.show_keep_amount_popup
            CardSeparator
            SettingsItem:
                title: root.mix_rounds_text + ': %s' % root.mix_rounds
                description: root.mix_rounds_help
                action: root.show_mix_rounds_popup
            CardSeparator
            SettingsItem:
                title: root.mixing_control_text
                description: root.mixing_control_help
                action: root.on_mixing_control
            CardSeparator
            SettingsProgress:
                title: root.mix_prog_text
                prog_val: root.mix_prog
                action: root.show_mixing_progress_by_rounds
            CardSeparator
            SettingsItem:
                title: root.ps_balance_text + ': ' + root.ps_balance
                description: root.ps_balance_help
                action: root.toggle_fiat_ps_balance
            CardSeparator
            SettingsItem:
                title: root.dn_balance_text + ': ' + root.dn_balance
                description: root.dn_balance_help
                action: root.toggle_fiat_dn_balance
            CardSeparator
            SettingsItem:
                title: root.create_sm_denoms_text
                description: root.create_sm_denoms_help
                action: root.create_sm_denoms
            CardSeparator
            SettingsItem:
                title: _('PrivateSend Coins')
                description: _('Show and use PrivateSend/Standard coins')
                action: root.show_coins_dialog
            CardSeparator
            SettingsItem:
                title: root.max_sessions_text + ': %s' % root.max_sessions
                description: root.max_sessions_help
                action: root.show_max_sessions_popup
            CardSeparator
            SettingsItem:
                title: root.kp_timeout_text + ': %s' % root.kp_timeout
                description: root.kp_timeout_help
                action: root.show_kp_timeout_popup
            CardSeparator
            SettingsItem:
                value: ': ON' if root.group_history else ': OFF'
                title: root.group_history_text + self.value
                description: root.group_history_help
                action: root.toggle_group_history
            CardSeparator
            SettingsItem:
                value: ': ON' if root.subscribe_spent else ': OFF'
                title: root.subscribe_spent_text + self.value
                description: root.subscribe_spent_help
                action: root.toggle_sub_spent
            CardSeparator
            SettingsItem:
                value: ': ON' if root.allow_others else ': OFF'
                title: root.allow_others_text + self.value
                description: root.allow_others_help
                action: root.toggle_allow_others


<PSInfoTab@BoxLayout>
    orientation: 'vertical'
    rv: rv
    app: None
    clear_ps_data_btn: clear_ps_data_btn
    find_untracked_btn: find_untracked_btn
    RecycledLinesView:
        id: rv
        app: root.app
        btns: btns
    SelectionButtons:
        id: btns
        rv: rv
    BoxLayout:
        orientation: 'horizontal'
        size_hint: 1, None
        padding: dp(0), dp(5)
        height: self.minimum_height
        Button:
            id: clear_ps_data_btn
            text: _('Clear PS data')
            size_hint: 0.5, None
            height: '48dp'
            on_release: root.clear_ps_data()
        Button:
            id: find_untracked_btn
            text: _('Find untracked PS txs')
            size_hint: 0.5, None
            height: '48dp'
            on_release: root.find_untracked_ps_txs()


<PSLogTab@BoxLayout>
    orientation: 'vertical'
    rv: rv
    app: None
    RecycledLinesView:
        id: rv
        app: root.app
        btns: btns
        scroll_y: 0
        effect_cls: 'ScrollEffect'
    SelectionButtons:
        id: btns
        rv: rv
    BoxLayout:
        orientation: 'horizontal'
        size_hint: 1, None
        padding: dp(0), dp(5)
        height: self.minimum_height
        Button:
            text: _('Clear Log')
            size_hint: 1, None
            height: '48dp'
            on_release: root.clear_log()


<PSDialogUnsupportedPS@Popup>
    title: _('PrivateSend')
    data: data
    Label:
        id: data
        text: ''
        halign: 'left'
        valign: 'top'
        text_size: self.width, None
        height: self.texture_size[1]
        padding: dp(5), dp(5)



<PSDialog@Popup>
    title: _('PrivateSend')
    tabs: tabs
    mixing_tab_header: mixing_tab_header
    mixing_tab: mixing_tab_header.content
    info_tab_header: info_tab_header
    info_tab: info_tab_header.content
    log_tab_header: log_tab_header
    log_tab: log_tab_header.content
    TabbedPanel:
        id: tabs
        do_default_tab: False
        TabbedPanelHeader:
            id: mixing_tab_header
            text: _('Mixing')
        TabbedPanelHeader:
            id: info_tab_header
            text: _('Info')
        TabbedPanelHeader:
            id: log_tab_header
            text: _('Log')
''')


class LineItem(RecycleDataViewBehavior, BoxLayout):
    index = None
    selected = BooleanProperty(False)

    def refresh_view_attrs(self, rv, index, data):
        self.index = index
        return super(LineItem, self).refresh_view_attrs(rv, index, data)

    def on_touch_down(self, touch):
        if super(LineItem, self).on_touch_down(touch):
            return True
        if self.collide_point(*touch.pos):
            return self.parent.select_with_touch(self.index, touch)

    def apply_selection(self, rv, index, is_selected):
        self.selected = is_selected


class LinesRecycleBoxLayout(FocusBehavior, LayoutSelectionBehavior,
                            RecycleBoxLayout):
    def __init__(self, *args, **kwargs):
        super(LinesRecycleBoxLayout, self).__init__(*args, **kwargs)

    def select_node(self, node):
        super(LinesRecycleBoxLayout, self).select_node(node)
        if self.selected_nodes:
            self.btns.clear_sel.disabled = False
            self.btns.copy_sel.disabled = False
            if self.btns.copy_filtered:
                self.btns.copy_filtered.disabled = False

    def deselect_node(self, node):
        super(LinesRecycleBoxLayout, self).deselect_node(node)
        if not self.selected_nodes:
            self.btns.clear_sel.disabled = True
            self.btns.copy_sel.disabled = True
            if self.btns.copy_filtered:
                self.btns.copy_filtered.disabled = True

    def select_all(self):
        for i in range(len(self.recycleview.data)):
            self.select_node(i)

    def copy_selected(self):
        res = []
        for i in sorted(self.selected_nodes):
            line = self.recycleview.data[i]['text']
            res.append(line)
        self.recycleview.app._clipboard.copy('\n'.join(res))

    def copy_filtered(self):
        res = []
        for i in sorted(self.selected_nodes):
            line = filter_log_line(self.recycleview.data[i]['text'])
            res.append(line)
        self.recycleview.app._clipboard.copy('\n'.join(res))


class EXWarnPopup(Popup):

    def __init__(self, psman):
        super(EXWarnPopup, self).__init__()
        self.psman = psman
        self.ids.warn_msg.text = psman.warn_electrumx_data(full_txt=True)
        self.ids.cb.active = not psman.show_warn_electrumx

    def dismiss(self):
        super(EXWarnPopup, self).dismiss()
        self.psman.show_warn_electrumx = not self.ids.cb.active


class KeepAmountPopup(Popup):

    spinbox = ObjectProperty(None)

    def __init__(self, psdlg):
        super(KeepAmountPopup, self).__init__()
        self.psdlg = psdlg
        self.psman = psman = psdlg.psman
        self.title = self.psdlg.keep_amount_text
        self.spinbox.min_val = psman.min_keep_amount
        self.spinbox.max_val = psman.max_keep_amount
        self.spinbox.value = self.psdlg.keep_amount

    def dismiss(self, value=None):
        if self.spinbox.err.text:
            return
        super(KeepAmountPopup, self).dismiss()
        if value is not None and value != self.psman.keep_amount:
            self.psman.keep_amount = value
            self.psdlg.keep_amount = value


class MixRoundsPopup(Popup):

    spinbox = ObjectProperty(None)

    def __init__(self, psdlg):
        super(MixRoundsPopup, self).__init__()
        self.psdlg = psdlg
        self.psman = psman = psdlg.psman
        self.title = self.psdlg.mix_rounds_text
        self.spinbox.min_val = psman.min_mix_rounds
        self.spinbox.max_val = psman.max_mix_rounds
        self.spinbox.value = self.psdlg.mix_rounds

    def dismiss(self, value=None):
        if self.spinbox.err.text:
            return
        super(MixRoundsPopup, self).dismiss()
        if value is not None and value != self.psman.mix_rounds:
            self.psman.mix_rounds = value
            self.psdlg.mix_rounds = value
            self.psdlg.update()


class MaxSessionsPopup(Popup):

    spinbox = ObjectProperty(None)

    def __init__(self, psdlg):
        super(MaxSessionsPopup, self).__init__()
        self.psdlg = psdlg
        self.psman = psman = psdlg.psman
        self.title = self.psdlg.max_sessions_text
        self.spinbox.min_val = psman.min_max_sessions
        self.spinbox.max_val = psman.max_max_sessions
        self.spinbox.value = self.psdlg.max_sessions

    def dismiss(self, value=None):
        if self.spinbox.err.text:
            return
        super(MaxSessionsPopup, self).dismiss()
        if value is not None and value != self.psman.max_sessions:
            self.psman.max_sessions = value
            self.psdlg.max_sessions = value


class KPTimeoutPopup(Popup):

    spinbox = ObjectProperty(None)

    def __init__(self, psdlg):
        super(KPTimeoutPopup, self).__init__()
        self.psdlg = psdlg
        self.psman = psman = psdlg.psman
        self.title = self.psdlg.kp_timeout_text
        self.spinbox.min_val = psman.min_kp_timeout
        self.spinbox.max_val = psman.max_kp_timeout
        self.spinbox.value = self.psdlg.kp_timeout

    def dismiss(self, value=None):
        if self.spinbox.err.text:
            return
        super(KPTimeoutPopup, self).dismiss()
        if value is not None and value != self.psman.kp_timeout:
            self.psman.kp_timeout = value
            self.psdlg.kp_timeout = value


class MixingProgressPopup(Popup):

    def __init__(self, psdlg):
        super(MixingProgressPopup, self).__init__()
        self.psdlg = psdlg
        self.psman = psman = psdlg.psman
        self.title = self.psdlg.mix_prog_text
        res = ''
        mix_rounds = psman.mix_rounds
        for i in range(1, mix_rounds+1):
            progress = psman.mixing_progress(i)
            res += f'Round: {i}\t Progress: {progress}%\n'
        self.data.text = res


class PSMixingTab(BoxLayout):

    keep_amount = NumericProperty()
    mix_rounds = NumericProperty()
    max_sessions = NumericProperty()
    kp_timeout = NumericProperty()
    mixing_control_text = StringProperty()
    mix_prog = NumericProperty()
    dn_balance = StringProperty()
    ps_balance = StringProperty()
    group_history = BooleanProperty()
    subscribe_spent = BooleanProperty()
    allow_others = BooleanProperty()
    is_fiat_dn_balance = False
    is_fiat_ps_balance = False

    def __init__(self, app):
        self.app = app
        self.wallet = wallet = app.wallet
        self.psman = psman = wallet.psman

        self.warn_electrumx_text = psman.warn_electrumx_data()
        self.warn_electrumx_help = psman.warn_electrumx_data(help_txt=True)

        self.keep_amount_text = psman.keep_amount_data()
        self.keep_amount_help = psman.keep_amount_data(full_txt=True)

        self.mix_rounds_text = psman.mix_rounds_data()
        self.mix_rounds_help = psman.mix_rounds_data(full_txt=True)

        self.max_sessions_text = psman.max_sessions_data()
        self.max_sessions_help = psman.max_sessions_data(full_txt=True)

        self.kp_timeout_text = psman.kp_timeout_data()
        self.kp_timeout_help = psman.kp_timeout_data(full_txt=True)

        self.mixing_control_help = psman.mixing_control_data(full_txt=True)

        self.mix_prog_text = psman.mixing_progress_data()
        self.mix_prog_help = psman.mixing_progress_data(full_txt=True)

        self.ps_balance_text = psman.ps_balance_data()
        self.ps_balance_help = psman.ps_balance_data(full_txt=True)

        self.dn_balance_text = psman.dn_balance_data()
        self.dn_balance_help = psman.dn_balance_data(full_txt=True)

        self.create_sm_denoms_text = psman.create_sm_denoms_data()
        self.create_sm_denoms_help = psman.create_sm_denoms_data(full_txt=True)

        self.group_history_text = psman.group_history_data()
        self.group_history_help = psman.group_history_data(full_txt=True)

        self.subscribe_spent_text = psman.subscribe_spent_data()
        self.subscribe_spent_help = psman.subscribe_spent_data(full_txt=True)

        self.allow_others_text = psman.allow_others_data()
        self.allow_others_help = psman.allow_others_data(full_txt=True)

        super(PSMixingTab, self).__init__()
        self.update()

    def update(self):
        app = self.app
        wallet = self.wallet
        psman = self.psman
        self.keep_amount = psman.keep_amount
        self.mix_rounds = psman.mix_rounds
        self.max_sessions = psman.max_sessions
        self.kp_timeout = psman.kp_timeout
        self.mixing_control_text = psman.mixing_control_data()
        self.mix_prog = psman.mixing_progress()
        r = psman.mix_rounds
        val = sum(wallet.get_balance(include_ps=False, min_rounds=r))
        self.ps_balance = app.format_amount_and_units(val)
        val = sum(wallet.get_balance(include_ps=False, min_rounds=0))
        self.dn_balance = app.format_amount_and_units(val)
        self.group_history = psman.group_history
        self.subscribe_spent = psman.subscribe_spent
        self.allow_others = psman.allow_others

    def show_warn_electrumx(self, *args):
        EXWarnPopup(self.psman).open()

    def show_keep_amount_popup(self, *args):
        psman = self.psman
        if psman.state in psman.mixing_running_states:
            self.app.show_info(_('To change value stop mixing process'))
            return
        KeepAmountPopup(self).open(self.psman)

    def show_mix_rounds_popup(self, *args):
        psman = self.psman
        if psman.state in psman.mixing_running_states:
            self.app.show_info(_('To change value stop mixing process'))
            return
        MixRoundsPopup(self).open(self.psman)

    def show_max_sessions_popup(self, *args):
        MaxSessionsPopup(self).open(self.psman)

    def show_kp_timeout_popup(self, *args):
        KPTimeoutPopup(self).open(self.psman)

    def on_mixing_control(self, *args):
        psman = self.psman
        if psman.state == PSStates.Ready:
            need_new_kp, prev_kp_state = psman.check_need_new_keypairs()
            if need_new_kp:
                self.start_mixing(prev_kp_state)
            else:
                self.psman.start_mixing(None)
        elif psman.state == PSStates.Mixing:
            psman.stop_mixing()
        elif psman.state == PSStates.Disabled:
            psman.enable_ps()

    def start_mixing(self, prev_kp_state):
        def on_success_pwd(password):
            self.psman.start_mixing(password)

        def on_fail_pwd():
            self.psman.keypairs_state = prev_kp_state

        w = self.app.wallet
        self.app.password_dialog(w, _('Enter your PIN code to start mixing'),
                                 on_success_pwd, on_fail_pwd)

    def toggle_fiat_dn_balance(self, *args):
        if not self.app.fx.is_enabled():
            return
        self.is_fiat_dn_balance = not self.is_fiat_dn_balance
        val = sum(self.wallet.get_balance(include_ps=False, min_rounds=0))
        app = self.app
        if self.is_fiat_dn_balance:
            fiat_balance = app.fx.format_amount(val)
            ccy = app.fx.ccy
            self.dn_balance = f'{fiat_balance} {ccy}'
        else:
            self.dn_balance = app.format_amount_and_units(val)

    def toggle_fiat_ps_balance(self, *args):
        if not self.app.fx.is_enabled():
            return
        self.is_fiat_ps_balance = not self.is_fiat_ps_balance
        val = sum(self.wallet.get_balance(include_ps=False,
                                          min_rounds=self.psman.mix_rounds))
        app = self.app
        if self.is_fiat_ps_balance:
            fiat_balance = app.fx.format_amount(val)
            ccy = app.fx.ccy
            self.ps_balance = f'{fiat_balance} {ccy}'
        else:
            self.ps_balance = app.format_amount_and_units(val)

    def show_mixing_progress_by_rounds(self, *args):
        d = MixingProgressPopup(self)
        d.open()

    def create_sm_denoms(self, *args):
        w = self.wallet
        psman = w.psman
        denoms_by_vals = psman.calc_denoms_by_values()
        if (not denoms_by_vals
                or not psman.check_big_denoms_presented(denoms_by_vals)):
            msg = psman.create_sm_denoms_data(no_denoms_txt=True)
            self.app.show_error(msg)
        else:
            do_create = False
            if psman.check_enough_sm_denoms(denoms_by_vals):
                q = psman.create_sm_denoms_data(enough_txt=True)
            else:
                q = psman.create_sm_denoms_data(confirm_txt=True)

            def on_q_answered(b):
                if b:
                    self.app.create_small_denoms(denoms_by_vals)
            d = Question(q, on_q_answered)
            d.open()

    def toggle_group_history(self, *args):
        self.psman.group_history = not self.psman.group_history
        self.group_history = self.psman.group_history
        self.app._trigger_update_history()

    def toggle_sub_spent(self, *args):
        self.psman.subscribe_spent = not self.psman.subscribe_spent
        self.subscribe_spent = self.psman.subscribe_spent

    def toggle_allow_others(self, *args):
        if self.psman.allow_others:
            self.psman.allow_others = False
            self.allow_others = False
        else:
            q = self.psman.allow_others_data(kv_question=True)

            def on_q_answered(b):
                if b:
                    self.psman.allow_others = True
                    self.allow_others = True

            d = Question(q, on_q_answered)
            d.size_hint = (0.9, 0.9)
            d.open()

    def show_coins_dialog(self, *args):
        self.app.coins_dialog()


class PSInfoTab(BoxLayout):

    def __init__(self, app):
        super(PSInfoTab, self).__init__()
        self.app = app
        self.wallet = wallet = app.wallet
        self.psman = wallet.psman
        self.update()
        self.data_buttons_update()
        self.rv.btns.remove_widget(self.rv.btns.copy_filtered)

    def update(self):
        lines = self.psman.get_ps_data_info()
        self.rv.data = [{'text': line} for line in lines]

    def data_buttons_update(self):
        psman = self.psman
        if psman.state in [PSStates.Ready, PSStates.Errored]:
            self.clear_ps_data_btn.disabled = False
        else:
            self.clear_ps_data_btn.disabled = True
        if psman.state == PSStates.Ready:
            self.find_untracked_btn.disabled = False
        else:
            self.find_untracked_btn.disabled = True

    def clear_ps_data(self):
        psman = self.psman

        def _clear_ps_data(b: bool):
            if b:
                psman.clear_ps_data()
        d = Question(psman.CLEAR_PS_DATA_MSG, _clear_ps_data)
        d.open()

    def find_untracked_ps_txs(self):
        psman = self.psman
        Clock.schedule_once(lambda dt: psman.find_untracked_ps_txs_from_gui())


class PSLogTab(BoxLayout):

    def __init__(self, app):
        super(PSLogTab, self).__init__()
        self.app = app
        self.wallet = wallet = app.wallet
        self.psman = psman = wallet.psman
        self.log_handler = psman.log_handler
        self.log_head = self.log_handler.head
        self.log_tail = self.log_head

    def append_log_tail(self):
        log_handler = self.log_handler
        log_tail = log_handler.tail
        for i in range(self.log_tail, log_tail):
            log_line = ''
            log_record = log_handler.log.get(i, None)
            if log_record:
                created = time.localtime(log_record.created)
                created = time.strftime('%x %X', created)
                log_line = f'{created} {log_record.msg}'
                if log_record.subcat == PSLogSubCat.WflDone:
                    log_line = f'[color=1c75bc]{log_line}[/color]'
                elif log_record.subcat == PSLogSubCat.WflOk:
                    log_line = f'[color=32b332]{log_line}[/color]'
                elif log_record.subcat == PSLogSubCat.WflErr:
                    log_line = f'[color=bc1e1e]{log_line}[/color]'
            self.rv.data.append({'text': log_line})
        self.log_tail = log_tail

    def clear_log_head(self):
        log_head = self.log_handler.head
        difference = log_head - self.log_head
        self.rv.data = self.rv.data[difference:]
        self.log_head = log_head

    def clear_log(self):
        def _clear_log():
            self.rv.data = []
            self.log_handler.clear_log()
        Clock.schedule_once(lambda dt: _clear_log())


class PSDialogUnsupportedPS(Popup):

    def __init__(self, app):
        super(PSDialogUnsupportedPS, self).__init__()
        psman = app.wallet.psman
        self.data.text = psman.unsupported_msg


class PSDialog(Popup):
    def __init__(self, app):
        super(PSDialog, self).__init__()
        self.app = app
        self.wallet = app.wallet
        self.psman = app.wallet.psman
        self.mixing_tab_header.content = PSMixingTab(self.app)
        self.info_tab_header.content = PSInfoTab(self.app)
        self.log_tab_header.content = PSLogTab(self.app)
        self.tabs.switch_to(self.mixing_tab_header)
        self.tabs.bind(current_tab=self.on_tabs_changed)

    def open(self):
        super(PSDialog, self).open()
        self.psman.register_callback(self.on_ps_callback,
                                     ['ps-log-changes',
                                      'ps-wfl-changes',
                                      'ps-keypairs-changes',
                                      'ps-reserved-changes',
                                      'ps-data-changes',
                                      'ps-state-changes'])
        if self.psman.show_warn_electrumx:
            mixing_tab = self.mixing_tab
            Clock.schedule_once(lambda dt: mixing_tab.show_warn_electrumx())

    def dismiss(self):
        super(PSDialog, self).dismiss()
        self.log_tab.log_handler.notify = False
        self.psman.unregister_callback(self.on_ps_callback)

    def on_ps_callback(self, event, *args):
        Clock.schedule_once(lambda dt: self.on_ps_event(event, *args))

    def on_ps_event(self, event, *args):
        if event == 'ps-log-changes':
            psman = args[0]
            if psman == self.psman:
                log_tab = self.log_tab
                if log_tab.log_handler.head > log_tab.log_head:
                    log_tab.clear_log_head()
                if log_tab.log_handler.tail > log_tab.log_tail:
                    log_tab.append_log_tail()
        elif event == 'ps-wfl-changes':
            wallet = args[0]
            if wallet == self.wallet:
                self.info_tab.update()
        elif event == 'ps-data-changes':
            wallet = args[0]
            psman = wallet.psman
            if wallet == self.wallet:
                val = sum(wallet.get_balance(include_ps=False,
                                             min_rounds=0))
                dn_balance = self.app.format_amount_and_units(val)
                self.mixing_tab.dn_balance = dn_balance
                val = sum(wallet.get_balance(include_ps=False,
                                             min_rounds=psman.mix_rounds))
                ps_balance = self.app.format_amount_and_units(val)
                self.ps_balance = ps_balance
                self.mix_prog = psman.mixing_progress()
                self.info_tab.update()
        elif event in ['ps-reserved-changes', 'ps-keypairs-changes']:
            wallet = args[0]
            if wallet == self.wallet:
                self.info_tab.update()
        elif event == 'ps-state-changes':
            wallet, msg, msg_type = args
            if wallet == self.wallet:
                self.mixing_tab.mixing_control_text = \
                    self.psman.mixing_control_data()
                self.info_tab.data_buttons_update()

    def on_tabs_changed(self, tabs, current_tab):
        if current_tab == self.log_tab_header:
            self.log_tab.append_log_tail()
            self.log_tab.log_handler.notify = True
        else:
            self.log_tab.log_handler.notify = False
