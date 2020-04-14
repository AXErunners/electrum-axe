from kivy.factory import Factory
from kivy.lang import Builder

Builder.load_string('''
#:import _ electrum_axe.gui.kivy.i18n._

<WarnDialog@Popup>
    id: popup
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
            id: warn_msg
            halign: 'left'
            text_size: self.width, None
            size: self.texture_size
        Button:
            text: 'OK'
            size_hint_y: 0.15
            height: '48dp'
            on_release:
                popup.dismiss()
''')


class WarnDialog(Factory.Popup):
    def __init__(self, warn_msg, title=''):
        Factory.Popup.__init__(self)
        self.ids.warn_msg.text = warn_msg
        if title:
            self.title = title
