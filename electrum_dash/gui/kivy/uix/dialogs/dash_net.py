from kivy.factory import Factory
from kivy.properties import (NumericProperty, StringProperty, BooleanProperty,
                             ObjectProperty, ListProperty)
from kivy.lang import Builder

from electrum_dash.gui.kivy.i18n import _


Builder.load_string('''
#:import _ electrum_dash.gui.kivy.i18n._
#:import MIN_PEERS_LIMIT electrum_dash.dash_net.MIN_PEERS_LIMIT
#:import MAX_PEERS_LIMIT electrum_dash.dash_net.MAX_PEERS_LIMIT


<DashNetStatItem@SettingsItem>
    total: 0
    received: 0
    sent: 0
    _total: _('Total') + ': %s KiB' % self.total
    _received: _('Received') + ': %s KiB' % self.received
    _sent: _('Sent') + ': %s KiB' % self.sent
    title: ', '.join([self._total, self._received, self._sent])
    description: _('Data flow over Dash network')
    action: lambda x: None


<ProTxListStatItem@SettingsItem>
    llmq_height: 0
    local_height: 0
    _llmq_height: _('LLMQ Height') + ': %s' % self.llmq_height
    _local_height: _('Local height') + ': %s' % self.local_height
    title: ', '.join([self._llmq_height, self._local_height])
    description: _('LLMQ list height and local blockchain height')
    action: lambda x: None


<ListColLabel@Label>
    is_title: False
    height: self.texture_size[1]
    text_size: self.width, None
    padding: 10, 10
    bold: True if self.is_title else False
    halign: 'left'


<DashPeerCard@BoxLayout>
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
    title: _('Dash Sporks Values')
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
    title: _('Banned Dash Peers')
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


<DashNetDialog@Popup>
    title: _('Dash Network')
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
                DashNetStatItem
                    total: root.total
                    received: root.received
                    sent: root.sent
                CardSeparator
                ProTxListStatItem
                    llmq_height: root.llmq_height
                    local_height: root.local_height
                CardSeparator
                SettingsItem:
                    value: ': ON' if root.run_dash_net else ': OFF'
                    title: _('Enable Dash Network') + self.value
                    description: _('Enable or Disable Dash network')
                    action: root.toggle_dash_net
                CardSeparator
                SettingsItem:
                    title: _('Connected Peers') + ': %s' % len(root.peers)
                    description: _('Number of currently connected Dash peers')
                    action: root.show_peers
                CardSeparator
                SettingsItem:
                    title: _('Max Peers') + ': %s' % root.max_peers
                    description: _('Maximally allowed Dash peers count')
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
                    description: _('Dash Sporks Values')
                    action: root.show_sporks
                CardSeparator
                SettingsItem:
                    title: _('Banlist') + ': %s' % len(root.banlist)
                    description: _('Banned Dash Peers')
                    action: root.show_banlist
''')


class DashPeerCard(Factory.BoxLayout):

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
        self.vbox.add_widget(DashPeerCard(_('Peer'),
                                          _('User Agent'),
                                          is_title=True))
        for peer, ua in self.dn_dlg.peers:
            self.vbox.add_widget(DashPeerCard(peer, ua))

    def on_peers(self, *args):
        self.update()

    def on_vbox(self, *args):
        self.update()


class MaxPeersPopup(Factory.Popup):

    slider = ObjectProperty(None)

    def __init__(self, dn_dlg):
        Factory.Popup.__init__(self)
        self.dn_dlg = dn_dlg
        self.slider.value = dn_dlg.dash_net.max_peers

    def dismiss(self, value=None):
        super(MaxPeersPopup, self).dismiss()
        if value is not None:
            self.dn_dlg.dash_net.max_peers = value
            self.dn_dlg.max_peers = value


class StaticPeersPopup(Factory.Popup):

    edit = ObjectProperty(None)
    err_label = ObjectProperty(None)

    def __init__(self, dn_dlg):
        Factory.Popup.__init__(self)
        self.dn_dlg = dn_dlg
        self.edit.text = dn_dlg.dash_net.dash_peers_as_str()

    def dismiss(self, dash_peers=None):
        if dash_peers is None:
            super(StaticPeersPopup, self).dismiss()
            return

        net = self.dn_dlg.net
        dash_net = net.dash_net
        res = dash_net.dash_peers_from_str(dash_peers)
        if type(res) == str:
            self.err_label.text = f'Error: {res}'
        else:
            super(StaticPeersPopup, self).dismiss()
            self.dn_dlg.config.set_key('dash_peers', res, True)
            self.dn_dlg.static_peers = dash_net.dash_peers_as_str()
            net.run_from_another_thread(dash_net.set_parameters())


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
        dash_net = self.dn_dlg.dash_net
        dash_net._remove_banned_peer(peer)


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


class DashNetDialog(Factory.Popup):

    total = NumericProperty()
    received = NumericProperty()
    sent = NumericProperty()
    run_dash_net = BooleanProperty()
    peers = ListProperty()
    max_peers = NumericProperty()
    use_static_peers = BooleanProperty()
    static_peers = StringProperty()
    sporks = ListProperty()
    banlist = ListProperty()
    local_height = NumericProperty()
    llmq_height = NumericProperty()

    def __init__(self, app):
        self.app = app
        self.config = self.app.electrum_config
        self.net = app.network
        self.mn_list = self.net.mn_list
        self.dash_net = self.net.dash_net
        Factory.Popup.__init__(self)
        layout = self.ids.scrollviewlayout
        layout.bind(minimum_height=layout.setter('height'))

    def update(self):
        self.on_dash_net_activity()
        self.on_sporks_activity()
        self.on_dash_peers_updated()
        self.on_dash_banlist_updated()
        self.on_mn_list_diff_updated()
        self.on_network_updated()
        self.run_dash_net = self.config.get('run_dash_net', True)
        self.max_peers = self.dash_net.max_peers
        self.use_static_peers = self.config.get('dash_use_static_peers', True)
        self.static_peers = self.dash_net.dash_peers_as_str()

    def open(self, *args, **kwargs):
        super(DashNetDialog, self).open(*args, **kwargs)
        self.dash_net.register_callback(self.on_dash_net_activity,
                                        ['dash-net-activity'])
        self.dash_net.register_callback(self.on_sporks_activity,
                                        ['sporks-activity'])
        self.dash_net.register_callback(self.on_dash_peers_updated,
                                        ['dash-peers-updated'])
        self.dash_net.register_callback(self.on_dash_banlist_updated,
                                        ['dash-banlist-updated'])
        self.mn_list.register_callback(self.on_mn_list_diff_updated,
                                       ['mn-list-diff-updated'])
        self.net.register_callback(self.on_network_updated,
                                   ['network_updated'])

    def dismiss(self, *args, **kwargs):
        super(DashNetDialog, self).dismiss(*args, **kwargs)
        self.dash_net.unregister_callback(self.on_dash_net_activity)
        self.dash_net.unregister_callback(self.on_sporks_activity)
        self.dash_net.unregister_callback(self.on_dash_peers_updated)
        self.dash_net.unregister_callback(self.on_dash_banlist_updated)
        self.mn_list.unregister_callback(self.on_mn_list_diff_updated)
        self.net.unregister_callback(self.on_network_updated)

    def on_dash_net_activity(self, *args, **kwargs):
        read_bytes = self.dash_net.read_bytes
        write_bytes = self.dash_net.write_bytes
        self.total = round((write_bytes + read_bytes)/1024, 1)
        self.received = round(read_bytes/1024, 1)
        self.sent = round(write_bytes/1024, 1)

    def on_sporks_activity(self, *args, **kwargs):
        sporks_dict = self.dash_net.sporks.as_dict()
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

    def on_dash_peers_updated(self, *args, **kwargs):
        self.peers = []
        for peer, dash_peer in self.dash_net.peers.items():
            ua = dash_peer.version.user_agent.decode('utf-8')
            self.peers.append((peer, ua))

    def on_dash_banlist_updated(self, *args, **kwargs):
        banlist = self.dash_net.banlist
        self.banlist = []
        for peer, banned in sorted(list(banlist.items())):
            self.banlist.append((peer, banned['ua']))

    def on_mn_list_diff_updated(self, *args, **kwargs):
        self.llmq_height = self.mn_list.llmq_human_height

    def on_network_updated(self, *args, **kwargs):
        self.local_height = self.net.get_local_height()

    def toggle_dash_net(self, *args):
        self.run_dash_net = not self.config.get('run_dash_net', True)
        self.config.set_key('run_dash_net', self.run_dash_net, True)
        self.net.run_from_another_thread(self.net.dash_net.set_parameters())

    def show_peers(self, *args):
        ConnectedPeersPopup(self).open()

    def change_max_peers(self, *args):
        MaxPeersPopup(self).open()

    def toggle_use_static_peers(self, *args):
        use_static_peers = not self.config.get('dash_use_static_peers', True)
        self.use_static_peers = use_static_peers
        self.config.set_key('dash_use_static_peers', use_static_peers, True)
        net = self.net
        net.run_from_another_thread(net.dash_net.set_parameters())

    def change_static_peers(self, *args):
        StaticPeersPopup(self).open()

    def show_sporks(self, *args):
        SporksPopup(self).open()

    def show_banlist(self, *args):
        BanlistPopup(self).open()
