import time
from kivy.clock import Clock
from kivy.factory import Factory
from kivy.properties import (NumericProperty, StringProperty, BooleanProperty,
                             ObjectProperty, ListProperty)
from kivy.lang import Builder
from kivy.logger import Logger

from electrum_axe.gui.kivy.i18n import _


Builder.load_string('''
#:import _ electrum_axe.gui.kivy.i18n._
#:import MIN_PEERS_LIMIT electrum_axe.axe_net.MIN_PEERS_LIMIT
#:import MAX_PEERS_LIMIT electrum_axe.axe_net.MAX_PEERS_LIMIT


<AxeNetStatItem@SettingsItem>
    total: 0
    received: 0
    sent: 0
    _total: _('Total') + ': %s KiB' % self.total
    _received: _('Received') + ': %s KiB' % self.received
    _sent: _('Sent') + ': %s KiB' % self.sent
    title: ', '.join([self._total, self._received, self._sent])
    description: _('Data flow over Axe network')


<AxeNetDataFlowDialog@Popup>
    title: _('Data flow over Axe network')
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


<ProTxListStatItem@SettingsItem>
    protx_ready: ''
    protx_info_completeness: '0%'
    llmq_ready: ''
    _protx: _('ProTx') + ': %s' % self.protx_ready
    _protx_info: _('ProTx Info') + ': %s' % self.protx_info_completeness
    _llmq: _('LLMQ') + ': %s' % self.llmq_ready
    title: ', '.join([self._protx, self._protx_info, self._llmq])
    description: _('ProTx, ProTx Info, LLMQ readiness')


<ProTxStatsDialog@Popup>
    title: _('ProTx, ProTx Info, LLMQ stats')
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


<ListColLabel@Label>
    is_title: False
    height: self.texture_size[1]
    text_size: self.width, None
    padding: 10, 10
    bold: True if self.is_title else False
    halign: 'left'


<AxePeerCard@BoxLayout>
    peer: ''
    ua: ''
    is_title: False
    orientation: 'vertical'
    size_hint: 1, None
    height: self.minimum_height
    BoxLayout:
        size_hint: 1, None
        height: max(l1.height, l2.height)
        orientation: 'horizontal'
        ListColLabel:
            id: l1
            text: root.peer
            is_title: root.is_title
        ListColLabel:
            id: l2
            text: root.ua
            is_title: root.is_title
    CardSeparator:
        color: [0.192, .498, 0.745, 1] if root.is_title else [.9, .9, .9, 1]


<ConnectedPeersPopup@Popup>
    title: _('Connected Peers')
    vbox: vbox
    BoxLayout:
        orientation: 'vertical'
        ScrollView:
            BoxLayout:
                id: vbox
                orientation: 'vertical'
                size_hint: 1, None
                height: self.minimum_height
                padding: '10dp'
        Button:
            size_hint: 1, 0.1
            text: _('Close')
            on_release: root.dismiss()


<MaxPeersPopup@Popup>
    title: _('Max Peers')
    size_hint: 0.8, 0.5
    slider: slider
    BoxLayout:
        orientation: 'vertical'
        Label:
            text: root.title +  ': %s' % slider.value
        BoxLayout:
            orientation: 'horizontal'
            Label:
                size_hint: 0.1, 1
                text: str(slider.min)
            Slider:
                id: slider
                size_hint: 0.8, 1
                value: MIN_PEERS_LIMIT
                min: MIN_PEERS_LIMIT
                max: MAX_PEERS_LIMIT
                step: 1
            Label:
                size_hint: 0.1, 1
                text: str(slider.max)
        Button:
            text: _('Set')
            on_release: root.dismiss(slider.value)


<StaticPeersPopup@Popup>
    title: _('Static Peers')
    size_hint: 0.8, 0.5
    edit: edit
    err_label: err_label
    BoxLayout:
        orientation: 'vertical'
        TextInput:
            id: edit
            size_hint: 1, 0.6
            cursor_blink: False
        Label:
            id: err_label
            size_hint: 1, 0.2
            color: [1, 0, 0, 1]
        Button:
            size_hint: 1, 0.2
            text: _('Set')
            on_release: root.dismiss(edit.text)


<SporkCard@BoxLayout>
    name: ''
    active: ''
    value: ''
    is_title: False
    orientation: 'vertical'
    size_hint: 1, None
    height: self.minimum_height
    BoxLayout:
        size_hint: 1, None
        height: max(l1.height, l2.height, l3.height)
        orientation: 'horizontal'
        ListColLabel:
            id: l1
            size_hint: 0.6, None
            text: root.name
            is_title: root.is_title
        ListColLabel:
            id: l2
            size_hint: 0.2, None
            text: root.active
            is_title: root.is_title
        ListColLabel:
            id: l3
            size_hint: 0.2, None
            text: root.value
            is_title: root.is_title
    CardSeparator:
        color: [0.192, .498, 0.745, 1] if root.is_title else [.9, .9, .9, 1]


<SporksPopup@Popup>
    title: _('Axe Sporks Values')
    vbox: vbox
    BoxLayout:
        orientation: 'vertical'
        ScrollView:
            BoxLayout:
                id: vbox
                orientation: 'vertical'
                size_hint: 1, None
                height: self.minimum_height
                padding: '10dp'
        Button:
            size_hint: 1, 0.1
            text: _('Close')
            on_release: root.dismiss()


<BanlistCard@BoxLayout>
    peer: ''
    ua: ''
    is_title: False
    btn: btn
    orientation: 'vertical'
    size_hint: 1, None
    height: self.minimum_height
    BoxLayout:
        size_hint: 1, None
        height: max(l1.height, l2.height, btn.height)
        orientation: 'horizontal'
        ListColLabel:
            id: l1
            size_hint: 0.4, None
            text: root.peer
            is_title: root.is_title
        ListColLabel:
            id: l2
            size_hint: 0.4, None
            text: root.ua
            is_title: root.is_title
        Button:
            id: btn
            size_hint: 0.2, None
            height: l2.height
            text: _('Remove')
            on_release: root.on_remove(root.peer if not root.is_title else '')
    CardSeparator:
        color: [0.192, .498, 0.745, 1] if root.is_title else [.9, .9, .9, 1]


<BanlistPopup@Popup>
    title: _('Banned Axe Peers')
    vbox: vbox
    BoxLayout:
        orientation: 'vertical'
        ScrollView:
            BoxLayout:
                id: vbox
                orientation: 'vertical'
                size_hint: 1, None
                height: self.minimum_height
                padding: '10dp'
        Button:
            size_hint: 1, 0.1
            text: _('Close')
            on_release: root.dismiss()


<BlsSpeedPopup@Popup>
    title: _('Show bls_py verify signature speed')
    BoxLayout:
        orientation: 'vertical'
        Label:
            text: _('Min time') + ': %s' % root.min_t
        Label:
            text: _('Max time') + ': %s' % root.max_t
        Button:
            size_hint: 1, 0.1
            text: _('Close')
            on_release: root.dismiss()


<AxeNetDialog@Popup>
    title: _('Axe Network')
    id: dlg
    BoxLayout:
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
                    value: ': ON' if root.run_axe_net else ': OFF'
                    title: _('Enable Axe Network') + self.value
                    description: _('Enable or Disable Axe network')
                    action: root.toggle_axe_net
                CardSeparator
                AxeNetStatItem
                    total: root.total
                    received: root.received
                    sent: root.sent
                    action: dlg.show_data_flow
                CardSeparator
                ProTxListStatItem
                    protx_ready: root.protx_ready
                    protx_info_completeness: root.protx_info_completeness
                    llmq_ready: root.llmq_ready
                    action: dlg.show_protx_stats
                CardSeparator
                SettingsItem:
                    title: _('Connected Peers') + ': %s' % len(root.peers)
                    description: _('Number of currently connected Axe peers')
                    action: root.show_peers
                CardSeparator
                SettingsItem:
                    title: _('Max Peers') + ': %s' % root.max_peers
                    description: _('Maximally allowed Axe peers count')
                    action: root.change_max_peers
                CardSeparator
                SettingsItem:
                    value: ': ON' if root.use_static_peers else ': OFF'
                    title: _('Use Static Peers') + self.value
                    description: _('Use static peers list instead random one')
                    action: root.toggle_use_static_peers
                CardSeparator
                SettingsItem:
                    title: _('Static Peers') + ': ' + root.static_peers
                    description: _('List of static peers to use')
                    action: root.change_static_peers
                CardSeparator
                SettingsItem:
                    title: _('Sporks') + ': %s' % len(root.sporks)
                    description: _('Axe Sporks Values')
                    action: root.show_sporks
                CardSeparator
                SettingsItem:
                    title: _('Banlist') + ': %s' % len(root.banlist)
                    description: _('Banned Axe Peers')
                    action: root.show_banlist
                CardSeparator
                SettingsItem:
                    id: bls_speed_item
                    title: _('BLS Speed')
                    description: _('Show bls_py verify signature speed')
                    action: root.show_bls_speed
''')


class AxeNetDataFlowDialog(Factory.Popup):

    def __init__(self, dn_dlg):
        Factory.Popup.__init__(self)
        self.dn_dlg = dn_dlg
        self.update()

    def open(self, *args, **kwargs):
        super(AxeNetDataFlowDialog, self).open(*args, **kwargs)
        self.dn_dlg.axe_net.register_callback(self.update_cb,
                                               ['axe-net-activity',
                                                'axe-peers-updated'])

    def dismiss(self, *args, **kwargs):
        super(AxeNetDataFlowDialog, self).dismiss(*args, **kwargs)
        self.dn_dlg.axe_net.unregister_callback(self.update_cb)

    def update_cb(self, event, *args):
        Clock.schedule_once(lambda dt: self.update())

    def update(self):
        res = ''
        peers = self.dn_dlg.axe_net.peers
        for peer, axe_peer in sorted(list(peers.items())):
            ping_time = str(axe_peer.ping_time)
            read_kbytes = str(round(axe_peer.read_bytes/1024, 1))
            write_kbytes = str(round(axe_peer.write_bytes/1024, 1))
            res += f'{peer}:\n\n'
            res += f'Ping time (ms): {ping_time}\n'
            res += f'Received KiB: {read_kbytes}\n'
            res += f'Sent KiB: {write_kbytes}\n\n'
        self.data.text = res


class ProTxStatsDialog(Factory.Popup):

    def __init__(self, dn_dlg):
        Factory.Popup.__init__(self)
        self.dn_dlg = dn_dlg
        self.update()
        self.trigger_update = Clock.create_trigger(self.update, 1)

    def open(self, *args, **kwargs):
        super(ProTxStatsDialog, self).open(*args, **kwargs)
        net = self.dn_dlg.net
        mn_list = net.mn_list
        mn_list.register_callback(self.update_cb, ['mn-list-diff-updated',
                                                   'mn-list-info-updated'])
        net.register_callback(self.update_cb, ['network_updated'])

    def dismiss(self, *args, **kwargs):
        super(ProTxStatsDialog, self).dismiss(*args, **kwargs)
        net = self.dn_dlg.net
        mn_list = net.mn_list
        mn_list.unregister_callback(self.update_cb)
        net.unregister_callback(self.update_cb)

    def update_cb(self, event, *args):
        self.trigger_update()

    def update(self, dt=None):
        dn_dlg = self.dn_dlg
        res = 'Actual Heights:\n'
        res += f'Local: {dn_dlg.local_height}\n'
        res += f'ProTx: {dn_dlg.protx_height}\n'
        res += f'LLMQ: {dn_dlg.llmq_height}\n'
        res += '\nReadiness:\n'
        res += f'ProTx: {dn_dlg.protx_ready}\n'
        res += f'LLMQ: {dn_dlg.llmq_ready}\n'
        res += '\nCompleteness:\n'
        res += f'ProTx Info: {dn_dlg.protx_info_completeness}\n'
        self.data.text = res


class AxePeerCard(Factory.BoxLayout):

    peer = StringProperty()
    us = StringProperty()
    is_title = BooleanProperty()

    def __init__(self, peer, ua, is_title=False):
        Factory.BoxLayout.__init__(self)
        self.peer = peer
        self.ua = ua
        self.is_title = is_title


class ConnectedPeersPopup(Factory.Popup):

    vbox = ObjectProperty(None)

    def __init__(self, dn_dlg):
        self.dn_dlg = dn_dlg
        self.dn_dlg.bind(peers=self.on_peers)
        Factory.Popup.__init__(self)

    def dismiss(self, *args, **kwargs):
        super(ConnectedPeersPopup, self).dismiss(*args, **kwargs)
        self.dn_dlg.unbind(peers=self.on_peers)

    def update(self, *args, **kwargs):
        self.vbox.clear_widgets()
        self.vbox.add_widget(AxePeerCard(_('Peer'),
                                          _('User Agent'),
                                          is_title=True))
        for peer, ua in self.dn_dlg.peers:
            self.vbox.add_widget(AxePeerCard(peer, ua))

    def on_peers(self, *args):
        self.update()

    def on_vbox(self, *args):
        self.update()


class MaxPeersPopup(Factory.Popup):

    slider = ObjectProperty(None)

    def __init__(self, dn_dlg):
        Factory.Popup.__init__(self)
        self.dn_dlg = dn_dlg
        self.slider.value = dn_dlg.axe_net.max_peers

    def dismiss(self, value=None):
        super(MaxPeersPopup, self).dismiss()
        if value is not None:
            self.dn_dlg.axe_net.max_peers = value
            self.dn_dlg.max_peers = value


class StaticPeersPopup(Factory.Popup):

    edit = ObjectProperty(None)
    err_label = ObjectProperty(None)

    def __init__(self, dn_dlg):
        Factory.Popup.__init__(self)
        self.dn_dlg = dn_dlg
        self.edit.text = dn_dlg.axe_net.axe_peers_as_str()

    def dismiss(self, axe_peers=None):
        if axe_peers is None:
            super(StaticPeersPopup, self).dismiss()
            return

        net = self.dn_dlg.net
        axe_net = net.axe_net
        res = axe_net.axe_peers_from_str(axe_peers)
        if type(res) == str:
            self.err_label.text = f'Error: {res}'
        else:
            super(StaticPeersPopup, self).dismiss()
            self.dn_dlg.config.set_key('axe_peers', res, True)
            net.run_from_another_thread(axe_net.set_parameters())
            self.dn_dlg.static_peers = axe_net.axe_peers_as_str()


class SporkCard(Factory.BoxLayout):

    name = StringProperty()
    active = StringProperty()
    value = StringProperty()
    is_title = BooleanProperty()

    def __init__(self, name, active, value, is_title=False):
        Factory.BoxLayout.__init__(self)
        self.name = name
        self.active = active
        self.value = value
        self.is_title = is_title


class SporksPopup(Factory.Popup):

    vbox = ObjectProperty(None)

    def __init__(self, dn_dlg):
        self.dn_dlg = dn_dlg
        self.dn_dlg.bind(sporks=self.on_sporks)
        Factory.Popup.__init__(self)

    def dismiss(self, *args, **kwargs):
        self.dn_dlg.unbind(sporks=self.on_sporks)
        super(SporksPopup, self).dismiss(*args, **kwargs)

    def update(self, *args, **kwargs):
        self.vbox.clear_widgets()
        self.vbox.add_widget(SporkCard(_('Name'), _('Active'), _('Value'),
                                       is_title=True))
        for name, active, value in self.dn_dlg.sporks:
            self.vbox.add_widget(SporkCard(name, active, value))

    def on_sporks(self, *args):
        self.update()

    def on_vbox(self, *args):
        self.update()


class BanlistCard(Factory.BoxLayout):

    peer = StringProperty()
    us = StringProperty()
    is_title = BooleanProperty()

    def __init__(self, peer, ua, is_title, dn_dlg):
        self.dn_dlg = dn_dlg
        Factory.BoxLayout.__init__(self)
        self.peer = peer
        self.ua = ua
        self.is_title = is_title
        if is_title:
            self.btn.opacity = 0

    def on_remove(self, peer):
        if not peer:
            return
        axe_net = self.dn_dlg.axe_net
        axe_net._remove_banned_peer(peer)


class BanlistPopup(Factory.Popup):

    vbox = ObjectProperty(None)

    def __init__(self, dn_dlg):
        self.dn_dlg = dn_dlg
        self.dn_dlg.bind(banlist=self.on_banlist)
        Factory.Popup.__init__(self)

    def dismiss(self, *args, **kwargs):
        self.dn_dlg.unbind(banlist=self.on_banlist)
        super(BanlistPopup, self).dismiss(*args, **kwargs)

    def update(self, *args, **kwargs):
        self.vbox.clear_widgets()
        self.vbox.add_widget(BanlistCard(_('Peer'), _('User Agent'),
                                         True, self.dn_dlg))
        for peer, ua in self.dn_dlg.banlist:
            self.vbox.add_widget(BanlistCard(peer, ua, False, self.dn_dlg))

    def on_banlist(self, *args):
        self.update()

    def on_vbox(self, *args):
        self.update()


class BlsSpeedPopup(Factory.Popup):

    min_t = NumericProperty(1000)
    max_t = NumericProperty(0)

    def __init__(self, dn_dlg):
        Factory.Popup.__init__(self)
        self.axe_net = dn_dlg.axe_net
        self.clock_e = Clock.schedule_once(self.update, 0.5)

    def update(self, *args, **kwargs):
        start_t = time.time()
        res = self.axe_net.test_bls_speed()
        res_t = time.time() - start_t
        Logger.info(f'Test BLS Speed: res={res}, time={res_t}')
        self.min_t = min(self.min_t, res_t)
        self.max_t = max(self.max_t, res_t)
        self.clock_e = Clock.schedule_once(self.update, 0.5)

    def dismiss(self, *args, **kwargs):
        Clock.unschedule(self.clock_e)
        super(BlsSpeedPopup, self).dismiss(*args, **kwargs)


class AxeNetDialog(Factory.Popup):

    total = NumericProperty()
    received = NumericProperty()
    sent = NumericProperty()
    run_axe_net = BooleanProperty()
    peers = ListProperty()
    max_peers = NumericProperty()
    use_static_peers = BooleanProperty()
    static_peers = StringProperty()
    sporks = ListProperty()
    banlist = ListProperty()
    local_height = StringProperty()
    protx_height = StringProperty()
    llmq_height = StringProperty()
    protx_ready = StringProperty()
    protx_info_completeness = StringProperty()
    llmq_ready = StringProperty()

    def __init__(self, app):
        self.app = app
        self.config = self.app.electrum_config
        self.net = app.network
        self.mn_list = self.net.mn_list
        self.axe_net = self.net.axe_net
        Factory.Popup.__init__(self)
        layout = self.ids.scrollviewlayout
        layout.bind(minimum_height=layout.setter('height'))
        if not self.app.testnet:
            layout.remove_widget(self.ids.bls_speed_item)
        self.trigger_mn_list_info_updated = \
            Clock.create_trigger(self.on_mn_list_info_updated, 1)

    def update(self):
        self.on_axe_net_activity()
        self.on_sporks_activity()
        self.on_axe_peers_updated()
        self.on_axe_banlist_updated()
        self.on_mn_list_diff_updated()
        self.on_network_updated()
        self.run_axe_net = self.config.get('run_axe_net', True)
        self.max_peers = self.axe_net.max_peers
        self.use_static_peers = self.config.get('axe_use_static_peers', False)
        self.static_peers = self.axe_net.axe_peers_as_str()

    def open(self, *args, **kwargs):
        super(AxeNetDialog, self).open(*args, **kwargs)
        self.axe_net.register_callback(self.on_axe_net_activity_cb,
                                        ['axe-net-activity'])
        self.axe_net.register_callback(self.on_sporks_activity_cb,
                                        ['sporks-activity'])
        self.axe_net.register_callback(self.on_axe_peers_updated_cb,
                                        ['axe-peers-updated'])
        self.axe_net.register_callback(self.on_axe_banlist_updated_cb,
                                        ['axe-banlist-updated'])
        self.mn_list.register_callback(self.on_mn_list_diff_updated_cb,
                                       ['mn-list-diff-updated'])
        self.mn_list.register_callback(self.on_mn_list_info_updated_cb,
                                       ['mn-list-info-updated'])
        self.net.register_callback(self.on_network_updated_cb,
                                   ['network_updated'])

    def dismiss(self, *args, **kwargs):
        super(AxeNetDialog, self).dismiss(*args, **kwargs)
        self.axe_net.unregister_callback(self.on_axe_net_activity_cb)
        self.axe_net.unregister_callback(self.on_sporks_activity_cb)
        self.axe_net.unregister_callback(self.on_axe_peers_updated_cb)
        self.axe_net.unregister_callback(self.on_axe_banlist_updated_cb)
        self.mn_list.unregister_callback(self.on_mn_list_diff_updated_cb)
        self.mn_list.unregister_callback(self.on_mn_list_info_updated_cb)
        self.net.unregister_callback(self.on_network_updated_cb)

    def on_axe_net_activity_cb(self, event, *args):
        Clock.schedule_once(lambda dt: self.on_axe_net_activity())

    def on_axe_net_activity(self):
        read_bytes = self.axe_net.read_bytes
        write_bytes = self.axe_net.write_bytes
        self.total = round((write_bytes + read_bytes)/1024, 1)
        self.received = round(read_bytes/1024, 1)
        self.sent = round(write_bytes/1024, 1)

    def on_sporks_activity_cb(self, event, *args):
        Clock.schedule_once(lambda dt: self.on_sporks_activity())

    def on_sporks_activity(self):
        sporks_dict = self.axe_net.sporks.as_dict()
        self.sporks = []
        for k in sorted(list(sporks_dict.keys())):
            name = sporks_dict[k]['name']
            name = name[6:].replace('_', ' ')
            active = str(sporks_dict[k]['active'])
            value = str(sporks_dict[k]['value'])
            default = sporks_dict[k]['default']
            value = value + ' %s' % _('Default') if default else value
            spork_item = [name, active, value]
            self.sporks.append(spork_item)

    def on_axe_peers_updated_cb(self, event, *args):
        Clock.schedule_once(lambda dt: self.on_axe_peers_updated())

    def on_axe_peers_updated(self):
        self.peers = []
        for peer, axe_peer in self.axe_net.peers.items():
            ua = axe_peer.version.user_agent.decode('utf-8')
            self.peers.append((peer, ua))

    def on_axe_banlist_updated_cb(self, event, *args):
        Clock.schedule_once(lambda dt: self.on_axe_banlist_updated())

    def on_axe_banlist_updated(self):
        banlist = self.axe_net.banlist
        self.banlist = []
        for peer, banned in sorted(list(banlist.items())):
            self.banlist.append((peer, banned['ua']))

    def on_mn_list_diff_updated_cb(self, event, *args):
        Clock.schedule_once(lambda dt: self.on_mn_list_diff_updated())

    def on_mn_list_diff_updated(self):
        mn_list = self.mn_list
        self.protx_height = str(mn_list.protx_height)
        self.protx_ready = 'Yes' if mn_list.protx_ready else 'No'
        completeness = mn_list.protx_info_completeness
        self.protx_info_completeness = '%s%%' % round(completeness*100)
        self.llmq_height = str(mn_list.llmq_human_height)
        self.llmq_ready = 'Yes' if mn_list.llmq_ready else 'No'

    def on_mn_list_info_updated_cb(self, event, *args):
        self.trigger_mn_list_info_updated()

    def on_mn_list_info_updated(self, dt=None):
        completeness = self.mn_list.protx_info_completeness
        self.protx_info_completeness = '%s%%' % round(completeness*100)

    def on_network_updated_cb(self, event, *args):
        Clock.schedule_once(lambda dt: self.on_network_updated())

    def on_network_updated(self):
        self.local_height = str(self.net.get_local_height())

    def toggle_axe_net(self, *args):
        self.run_axe_net = not self.config.get('run_axe_net', True)
        self.config.set_key('run_axe_net', self.run_axe_net, True)
        self.net.run_from_another_thread(self.net.axe_net.set_parameters())

    def show_peers(self, *args):
        ConnectedPeersPopup(self).open()

    def change_max_peers(self, *args):
        MaxPeersPopup(self).open()

    def toggle_use_static_peers(self, *args):
        use_static_peers = not self.config.get('axe_use_static_peers', False)
        self.use_static_peers = use_static_peers
        self.config.set_key('axe_use_static_peers', use_static_peers, True)
        net = self.net
        net.run_from_another_thread(net.axe_net.set_parameters())

    def change_static_peers(self, *args):
        StaticPeersPopup(self).open()

    def show_sporks(self, *args):
        SporksPopup(self).open()

    def show_banlist(self, *args):
        BanlistPopup(self).open()

    def show_bls_speed(self, *args):
        BlsSpeedPopup(self).open()

    def show_data_flow(self, *args):
        AxeNetDataFlowDialog(self).open()

    def show_protx_stats(self, *args):
        ProTxStatsDialog(self).open()
