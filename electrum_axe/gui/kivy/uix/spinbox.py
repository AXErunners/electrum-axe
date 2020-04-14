# -*- coding: utf-8 -*-

from kivy.lang import Builder
from kivy.properties import NumericProperty
from kivy.uix.boxlayout import BoxLayout

from electrum_axe.gui.kivy.i18n import _


Builder.load_string('''
<SpinBox>
    id: sb
    input: input
    err: err
    orientation: 'vertical'
    BoxLayout:
        orientation: 'horizontal'
        size_hint_y: None
        height: input.minimum_height
        Button
            id: dec_btn
            text: '-'
            on_press: sb.on_dec_val()
        Label:
            text: str(sb.min_val)
        TextInput:
            id: input
            sb: sb
            multiline: False
            input_filter: 'int'
            halign: 'center'
            text: str(sb.value)
            size_hint_y: None
            height: self.minimum_height
            on_text: root.on_text(self.text)
        Label:
            text: str(sb.max_val)
        Button:
            id: inc_btn
            text: '+'
            padding: 0, 0
            on_press: sb.on_inc_val()
    Label:
        id: err
        text: ''
        color: 1, 0, 0, 1
''')


class SpinBox(BoxLayout):
    min_val = NumericProperty(0)
    max_val = NumericProperty(100)
    step = NumericProperty(1)
    value = NumericProperty(0)

    def on_inc_val(self, *args):
        if self.err.text:
            self.on_text(str(self.err.subs_val))
        if self.value + self.step <= self.max_val:
            self.value += self.step

    def on_dec_val(self, *args):
        if self.err.text:
            self.on_text(str(self.err.subs_val))
        if self.value - self.step >= self.min_val:
            self.value -= self.step

    def on_text(self, new_val):
        if not new_val:
            self.err.text = _('Missing value')
            self.err.subs_val = self.min_val
            return
        new_val = int(new_val)
        if new_val < self.min_val:
            self.err.text = _('Value too small')
            self.err.subs_val = self.min_val
        elif new_val > self.max_val:
            self.err.text = _('Value too large')
            self.err.subs_val = self.max_val
        else:
            self.err.text = ''
            self.value = new_val
