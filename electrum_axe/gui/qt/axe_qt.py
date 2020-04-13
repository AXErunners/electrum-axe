# -*- coding: utf-8 -*-

from PyQt5.QtCore import QRect, QPoint, QSize
from PyQt5.QtWidgets import (QTabBar, QTextEdit, QStylePainter,
                             QStyleOptionTab, QStyle)

from electrum_axe.axe_tx import SPEC_TX_NAMES


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


class VTabBar(QTabBar):

    def tabSizeHint(self, index):
        s = QTabBar.tabSizeHint(self, index)
        s.transpose()
        return QSize(s.width(), s.height())

    def paintEvent(self, event):
        painter = QStylePainter(self)
        opt = QStyleOptionTab()

        for i in range(self.count()):
            self.initStyleOption(opt, i)
            painter.drawControl(QStyle.CE_TabBarTabShape, opt)
            painter.save()

            s = opt.rect.size()
            s.transpose()
            r = QRect(QPoint(), s)
            r.moveCenter(opt.rect.center())
            opt.rect = r

            c = self.tabRect(i).center()
            painter.translate(c)
            painter.rotate(270)
            painter.translate(-c)
            painter.drawControl(QStyle.CE_TabBarTabLabel, opt)
            painter.restore()
