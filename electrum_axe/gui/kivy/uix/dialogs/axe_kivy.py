import os

from kivy.clock import Clock
from kivy.factory import Factory
from kivy.lang import Builder

from electrum_axe.gui.kivy.i18n import _
from electrum_axe.network import deserialize_proxy

from kivy.properties import BooleanProperty
from kivy.uix.button import Button


Builder.load_string('''


<TorWarnDialog@Popup>
    title: ''
    auto_dismiss: False
    BoxLayout:
        id: vbox
        orientation: 'vertical'
        padding: '10dp'
        BoxLayout:
            size_hint: 1, None
            spacing: '10dp'
            orientation: 'horizontal'
            Image:
                id: warn_img
                source: 'atlas://electrum_axe/gui/kivy/theming/light/error'
                size_hint: None, None
                width: 64
                height: 64
                allow_stretch: True
            Label:
                id: warn_lbl
                text_size: self.width, None
                height: self.texture_size[1]
                markup: True
                on_ref_press:
                    import webbrowser
                    webbrowser.open(args[1])
        Widget:
            id: w_spacer
            size_hint: 1, 0.4
        BoxLayout:
            id: tor_auto_on_hbox
            size_hint: 1, None
            orientation: 'horizontal'
            CheckBox:
                size_hint: None, None
                active: root.tor_auto_on_bp
                on_active: root.toggle_tor_auto_on()
            Label:
                text: app.network.TOR_AUTO_ON_MSG
                text_size: self.width, None
                height: self.texture_size[1]
        BoxLayout:
            id: btns_vbox
            spacing: '10dp'
            orientation: 'vertical'
            Button:
                size_hint: 1, 0.1
                text: _('Continue without Tor')
                on_release: root.continue_without_tor()
            Button:
                size_hint: 1, 0.1
                text: _('Open Orbot app')
                on_release: root.open_orbot_app()
            Button:
                size_hint: 1, 0.1
                text: _('Detect Tor again')
                on_release: root.detect_tor_again()
            Button:
                size_hint: 1, 0.1
                text: _('Close wallet')
                on_release: root.close_wallet()
''')


class TorWarnDialog(Factory.Popup):

    tor_auto_on_bp = BooleanProperty()

    def __init__(self, app, w_path, continue_load):
        self.app = app
        self.continue_load = continue_load
        self.can_hide = False
        self.config = app.electrum_config
        self.net = net = app.network
        self.tor_detected = False

        Factory.Popup.__init__(self)
        app_name = 'Axe Electrum'
        w_basename = os.path.basename(w_path)
        self.title = f'{app_name}  -  {w_basename}'

        warn_lbl = self.ids.warn_lbl
        warn_lbl.text = net.TOR_WARN_MSG_KIVY
        self.tor_auto_on_bp = self.config.get('tor_auto_on', True)

    def on_dismiss(self):
        if not self.can_hide:
            return True

    def toggle_tor_auto_on(self):
        self.tor_auto_on_bp = not self.config.get('tor_auto_on', True)
        self.config.set_key('tor_auto_on', self.tor_auto_on_bp, True)

    def continue_without_tor(self):
        net = self.net
        net_params = net.get_parameters()
        if net_params.proxy:
            host = net_params.proxy['host']
            port = net_params.proxy['port']
            if host == '127.0.0.1' and port in ['9050', '9150']:
                net_params = net_params._replace(proxy=None)
                coro = net.set_parameters(net_params)
                net.run_from_another_thread(coro)
        self.continue_load()
        self.can_hide = True
        self.dismiss()

    def open_orbot_app(self):
        err = self.app.run_app('org.torproject.android')
        if err:
            self.app.show_error(err)

    def detect_tor_again(self):
        net = self.net
        self.tor_detected = net.detect_tor_proxy()
        if self.tor_detected:
            net_params = net.get_parameters()
            proxy = deserialize_proxy(self.tor_detected)
            net_params = net_params._replace(proxy=proxy)
            coro = net.set_parameters(net_params)
            net.run_from_another_thread(coro)

            self.title = _('Information')
            self.ids.warn_lbl.text = _('Tor proxy detected')
            w_img = self.ids.warn_img
            w_img.source = 'atlas://electrum_axe/gui/kivy/theming/light/info'
            vbox = self.ids.vbox
            vbox.remove_widget(self.ids.tor_auto_on_hbox)
            vbox.remove_widget(self.ids.btns_vbox)
            self.ids.w_spacer.size_hint = (1, 0.7)
            ok_btn = Button(text=_('OK'), size_hint=(1, 0.1))
            ok_btn.bind(on_press=self.on_ok)
            vbox.add_widget(ok_btn)

    def on_ok(self):
        self.continue_load()
        self.can_hide = True
        self.dismiss()

    def close_wallet(self):
        if not self.app.wallet:
            from kivy.base import stopTouchApp
            stopTouchApp()
        else:
            self.can_hide = True
            self.dismiss()
