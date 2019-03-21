# -*- coding: utf-8 -*-

from PyQt5.QtWidgets import QTextEdit

from electrum_dash.dash_tx import SPEC_TX_NAMES


class ExtraPayloadWidget(QTextEdit):
    def __init__(self, parent=None):
        super(ExtraPayloadWidget, self).__init__(parent)
        self.setReadOnly(True)
        self.tx_type = 0
        self.extra_payload = b''

    def clear(self):
        super(ExtraPayloadWidget, self).clear()
        self.tx_type = 0
        self.extra_payload = b''
        self.setText('')

    def get_extra_data(self):
        return self.tx_type, self.extra_payload

    def set_extra_data(self, tx_type, extra_payload):
        self.tx_type, self.extra_payload = tx_type, extra_payload
        tx_type_name = SPEC_TX_NAMES.get(tx_type, str(tx_type))
        self.setText('Tx Type: %s\n\n%s' % (tx_type_name, extra_payload))
