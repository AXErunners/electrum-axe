#!/usr/bin/env python
#
# Electrum - lightweight Bitcoin client
# Copyright (C) 2015 Thomas Voegtlin
#
# Permission is hereby granted, free of charge, to any person
# obtaining a copy of this software and associated documentation files
# (the "Software"), to deal in the Software without restriction,
# including without limitation the rights to use, copy, modify, merge,
# publish, distribute, sublicense, and/or sell copies of the Software,
# and to permit persons to whom the Software is furnished to do so,
# subject to the following conditions:
#
# The above copyright notice and this permission notice shall be
# included in all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
# EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
# MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
# NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS
# BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN
# ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN
# CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

from enum import IntEnum

from PyQt5.QtCore import (pyqtSignal, Qt, QPersistentModelIndex,
                          QModelIndex, QAbstractItemModel, QVariant,
                          QItemSelectionModel)
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (QAbstractItemView, QHeaderView, QComboBox,
                             QLabel, QMenu)

from electrum_axe.i18n import _
from electrum_axe.logging import Logger
from electrum_axe.util import block_explorer_URL, profiler
from electrum_axe.plugin import run_hook
from electrum_axe.bitcoin import is_address
from electrum_axe.wallet import InternalAddressCorruption

from .util import (MyTreeView, MONOSPACE_FONT, ColorScheme, webopen,
                   GetDataThread)


class AddrColumns(IntEnum):
    TYPE = 0
    ADDRESS = 1
    LABEL = 2
    COIN_BALANCE = 3
    FIAT_BALANCE = 4
    NUM_TXS = 5
    PS_TYPE = 6


class AddressModel(QAbstractItemModel, Logger):

    data_ready = pyqtSignal()

    SELECT_ROWS = QItemSelectionModel.Rows | QItemSelectionModel.Select

    SORT_KEYS = {
        AddrColumns.TYPE: lambda x: (x['addr_type'], x['ix']),
        AddrColumns.ADDRESS: lambda x: x['addr'],
        AddrColumns.LABEL: lambda x: x['label'],
        AddrColumns.COIN_BALANCE: lambda x: x['balance'],
        AddrColumns.FIAT_BALANCE: lambda x: x['fiat_balance'],
        AddrColumns.NUM_TXS: lambda x: x['num_txs'],
        AddrColumns.PS_TYPE: lambda x: x['is_ps'],
    }

    def __init__(self, parent):
        super(AddressModel, self).__init__(parent)
        Logger.__init__(self)
        self.parent = parent
        self.wallet = self.parent.wallet
        self.addr_items = list()
        # setup bg thread to get updated data
        self.data_ready.connect(self.on_get_data, Qt.BlockingQueuedConnection)
        self.get_data_thread = GetDataThread(self, self.get_addresses,
                                             self.data_ready, self)
        self.get_data_thread.start()

    def set_view(self, address_list):
        self.view = address_list
        self.view.refresh_headers()

    def headerData(self, section, orientation, role):
        if role != Qt.DisplayRole:
            return
        fx = self.parent.fx
        if fx and fx.get_fiat_address_config():
            ccy = fx.get_currency()
        else:
            ccy = _('Fiat')
        return {
            AddrColumns.TYPE: _('Type'),
            AddrColumns.ADDRESS: _('Address'),
            AddrColumns.LABEL: _('Label'),
            AddrColumns.COIN_BALANCE: _('Balance'),
            AddrColumns.FIAT_BALANCE: ccy + ' ' + _('Balance'),
            AddrColumns.NUM_TXS: _('Tx'),
            AddrColumns.PS_TYPE: _('PS Type'),
        }[section]

    def flags(self, idx):
        extra_flags = Qt.NoItemFlags
        if idx.column() in self.view.editable_columns:
            extra_flags |= Qt.ItemIsEditable
        return super().flags(idx) | extra_flags

    def columnCount(self, parent: QModelIndex):
        return len(AddrColumns)

    def rowCount(self, parent: QModelIndex):
        return len(self.addr_items)

    def index(self, row: int, column: int, parent: QModelIndex):
        if not parent.isValid():  # parent is root
            if len(self.addr_items) > row:
                return self.createIndex(row, column, self.addr_items[row])
        return QModelIndex()

    def parent(self, index: QModelIndex):
        return QModelIndex()

    def hasChildren(self, index: QModelIndex):
        return not index.isValid()

    def sort(self, col, order):
        if self.addr_items:
            self.process_changes(self.sorted(self.addr_items, col, order))

    def sorted(self, addr_items, col, order):
        return sorted(addr_items, key=self.SORT_KEYS[col], reverse=order)

    def data(self, index: QModelIndex, role: Qt.ItemDataRole) -> QVariant:
        assert index.isValid()
        col = index.column()
        addr_item = index.internalPointer()
        addr_type = addr_item['addr_type']
        addr = addr_item['addr']
        is_frozen = addr_item['is_frozen']
        is_beyond_limit = addr_item['is_beyond_limit']
        is_ps = addr_item['is_ps']
        label = addr_item['label']
        balance = addr_item['balance']
        fiat_balance = addr_item['fiat_balance']
        num_txs = addr_item['num_txs']
        if role not in (Qt.DisplayRole, Qt.EditRole):
            if role == Qt.TextAlignmentRole:
                if col != AddrColumns.FIAT_BALANCE:
                    return QVariant(Qt.AlignVCenter)
                else:
                    return QVariant(Qt.AlignRight|Qt.AlignVCenter)
            elif role == Qt.FontRole:
                if col not in (AddrColumns.TYPE, AddrColumns.LABEL,
                               AddrColumns.PS_TYPE):
                    return QVariant(QFont(MONOSPACE_FONT))
            elif role == Qt.BackgroundRole:
                if col == AddrColumns.TYPE:
                    if addr_type == 0:
                        return QVariant(ColorScheme.GREEN.as_color(True))
                    else:
                        return QVariant(ColorScheme.YELLOW.as_color(True))
                elif col == AddrColumns.ADDRESS:
                    if is_frozen:
                        return QVariant(ColorScheme.BLUE.as_color(True))
                    elif is_beyond_limit:
                        return QVariant(ColorScheme.RED.as_color(True))
        elif col == AddrColumns.TYPE:
            return QVariant(_('receiving') if addr_type == 0 else _('change'))
        elif col == AddrColumns.ADDRESS:
            return QVariant(addr)
        elif col == AddrColumns.LABEL:
            return QVariant(label)
        elif col == AddrColumns.COIN_BALANCE:
            return QVariant(balance)
        elif col == AddrColumns.FIAT_BALANCE:
            return QVariant(fiat_balance)
        elif col == AddrColumns.NUM_TXS:
            return QVariant(num_txs)
        elif col == AddrColumns.PS_TYPE:
            return QVariant(_('PrivateSend') if is_ps else _('Regular'))
        else:
            return QVariant()

    @profiler
    def get_addresses(self):
        addr_items = []

        ps_addrs = self.wallet.db.get_ps_addresses()
        show_change = self.view.show_change
        show_used = self.view.show_used
        show_ps = self.view.show_ps
        w = self.wallet
        if show_change == 1:
            all_addrs = w.get_receiving_addresses()
        elif show_change == 2:
            all_addrs = w.get_change_addresses()
        else:
            all_addrs = w.get_addresses()
        if show_ps == 0:  # All
            addr_list = all_addrs
        elif show_ps == 1:  # PrivateSend
            addr_list = [addr for addr in all_addrs if addr in ps_addrs]
        else:  # Regular
            addr_list = [addr for addr in all_addrs if addr not in ps_addrs]

        fx = self.parent.fx
        for i, addr in enumerate(addr_list):
            balance = sum(w.get_addr_balance(addr))
            is_used_and_empty = w.is_used(addr) and balance == 0
            if show_used == 1 and (balance or is_used_and_empty):
                continue
            if show_used == 2 and balance == 0:
                continue
            if show_used == 3 and not is_used_and_empty:
                continue

            balance_text = self.parent.format_amount(balance, whitespaces=True)
            if fx and fx.get_fiat_address_config():
                rate = fx.exchange_rate()
                fiat_balance = fx.value_str(balance, rate)
            else:
                fiat_balance = ''

            addr_items.append({
                'ix': i,
                'addr_type': 1 if w.is_change(addr) else 0,
                'addr': addr,
                'is_frozen': w.is_frozen_address(addr),
                'is_beyond_limit': w.is_beyond_limit(addr),
                'label': w.labels.get(addr, ''),
                'balance': balance_text,
                'fiat_balance': fiat_balance,
                'num_txs': w.get_address_history_len(addr),
                'is_ps': True if addr in ps_addrs else False,
            })
        return addr_items

    @profiler
    def process_changes(self, addr_items):
        selected = self.view.selectionModel().selectedRows()
        selected_addrs = []
        for idx in selected:
            selected_addrs.append(idx.internalPointer()['addr'])

        if self.addr_items:
            self.beginRemoveRows(QModelIndex(), 0, len(self.addr_items)-1)
            self.addr_items.clear()
            self.endRemoveRows()

        if addr_items:
            self.beginInsertRows(QModelIndex(), 0, len(addr_items)-1)
            self.addr_items = addr_items[:]
            self.endInsertRows()

        selected_rows = []
        if selected_addrs:
            for i, addr_item in enumerate(addr_items):
                addr = addr_item['addr']
                if addr in selected_addrs:
                    selected_rows.append(i)
                    selected_addrs.remove(addr)
                    if not selected_addrs:
                        break
        if selected_rows:
            for i in selected_rows:
                idx = self.index(i, 0, QModelIndex())
                self.view.selectionModel().select(idx, self.SELECT_ROWS)

    def on_get_data(self):
        self.refresh(self.get_data_thread.res)

    @profiler
    def refresh(self, addr_items):
        self.view.refresh_headers()
        if addr_items == self.addr_items:
            return
        col = self.view.header().sortIndicatorSection()
        order = self.view.header().sortIndicatorOrder()
        self.process_changes(self.sorted(addr_items, col, order))
        self.view.filter()


class AddressList(MyTreeView):

    filter_columns = [AddrColumns.TYPE, AddrColumns.ADDRESS,
                      AddrColumns.LABEL, AddrColumns.COIN_BALANCE,
                      AddrColumns.PS_TYPE]

    def __init__(self, parent, model):
        stretch_column = AddrColumns.LABEL
        super(AddressList, self).__init__(parent, self.create_menu,
                                          stretch_column=stretch_column)
        self.am = model
        self.setModel(model)
        self.wallet = self.parent.wallet
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)

        header = self.header()
        header.setDefaultAlignment(Qt.AlignCenter)
        header.setStretchLastSection(False)
        header.setSortIndicator(AddrColumns.TYPE, Qt.AscendingOrder)
        self.setSortingEnabled(True)
        for col in AddrColumns:
            if col == stretch_column:
                header.setSectionResizeMode(col, QHeaderView.Stretch)
            elif col in [AddrColumns.TYPE, AddrColumns.PS_TYPE]:
                header.setSectionResizeMode(col, QHeaderView.Fixed)
            else:
                header.setSectionResizeMode(col, QHeaderView.ResizeToContents)

        self.show_change = 0
        self.show_used = 0
        self.show_ps = 0
        self.change_button = QComboBox(self)
        self.change_button.currentIndexChanged.connect(self.toggle_change)
        for t in [_('All'), _('Receiving'), _('Change')]:
            self.change_button.addItem(t)
        self.used_button = QComboBox(self)
        self.used_button.currentIndexChanged.connect(self.toggle_used)
        for t in [_('All'), _('Unused'), _('Funded'), _('Used')]:
            self.used_button.addItem(t)
        self.ps_button = QComboBox(self)
        self.ps_button.currentIndexChanged.connect(self.toggle_ps)
        for t in [_('All'), _('PrivateSend'), _('Regular')]:
            self.ps_button.addItem(t)

    def refresh_headers(self):
        fx = self.parent.fx
        if fx and fx.get_fiat_address_config():
            self.showColumn(AddrColumns.FIAT_BALANCE)
        else:
            self.hideColumn(AddrColumns.FIAT_BALANCE)

    def get_toolbar_buttons(self):
        return (QLabel(_("Filter:")),
                self.change_button, self.used_button, self.ps_button)

    def on_hide_toolbar(self):
        self.show_change = 0
        self.show_used = 0
        self.show_ps = 0
        self.update()

    def save_toolbar_state(self, state, config):
        config.set_key('show_toolbar_addresses', state)

    def toggle_change(self, state):
        if state == self.show_change:
            return
        self.show_change = state
        self.update()

    def toggle_used(self, state):
        if state == self.show_used:
            return
        self.show_used = state
        self.update()

    def toggle_ps(self, state):
        if state == self.show_ps:
            return
        self.show_ps = state
        self.update()

    def update(self):
        self.am.get_data_thread.need_update.set()

    def create_menu(self, position):
        from electrum_axe.wallet import Multisig_Wallet
        is_multisig = isinstance(self.wallet, Multisig_Wallet)
        can_delete = self.wallet.can_delete_address()
        selected = self.selectionModel().selectedRows()
        if not selected:
            return
        multi_select = len(selected) > 1
        addr_items = []
        for idx in selected:
            if not idx.isValid():
                return
            addr_items.append(idx.internalPointer())
        addrs = [addr_item['addr'] for addr_item in addr_items]
        menu = QMenu()
        if not multi_select:
            idx = self.indexAt(position)
            if not idx.isValid():
                return
            col = idx.column()
            item = addr_items[0]
            if not item:
                return
            addr = item['addr']
            is_ps = item['is_ps']

            hd = self.am.headerData
            addr_title = hd(AddrColumns.LABEL, None, Qt.DisplayRole)
            column_title = hd(col, None, Qt.DisplayRole)
            label_idx = idx.sibling(idx.row(), AddrColumns.LABEL)

            copy_text = str(self.am.data(idx, Qt.DisplayRole).value())
            if col in [AddrColumns.COIN_BALANCE, AddrColumns.FIAT_BALANCE]:
                copy_text = copy_text.strip()
            menu.addAction(_("Copy {}").format(column_title),
                           lambda: self.place_text_on_clipboard(copy_text))
            menu.addAction(_('Details'),
                           lambda: self.parent.show_address(addr))

            persistent = QPersistentModelIndex(label_idx)
            menu.addAction(_("Edit {}").format(addr_title),
                           lambda p=persistent: self.edit(QModelIndex(p)))

            if not is_ps:
                menu.addAction(_("Request payment"),
                               lambda: self.parent.receive_at(addr))
            if self.wallet.can_export():
                menu.addAction(_("Private key"),
                               lambda: self.parent.show_private_key(addr))
            if not is_multisig and not self.wallet.is_watching_only():
                menu.addAction(_("Sign/verify message"),
                               lambda: self.parent.sign_verify_message(addr))
                menu.addAction(_("Encrypt/decrypt message"),
                               lambda: self.parent.encrypt_message(addr))
            if can_delete:
                menu.addAction(_("Remove from wallet"),
                               lambda: self.parent.remove_address(addr))
            addr_URL = block_explorer_URL(self.config, 'addr', addr)
            if addr_URL:
                menu.addAction(_("View on block explorer"),
                               lambda: webopen(addr_URL))

            if not is_ps:
                def set_frozen_state(addrs, state):
                    self.parent.set_frozen_state_of_addresses(addrs, state)
                if not self.wallet.is_frozen_address(addr):
                    menu.addAction(_("Freeze"),
                                   lambda: set_frozen_state([addr], True))
                else:
                    menu.addAction(_("Unfreeze"),
                                   lambda: set_frozen_state([addr], False))

        coins = self.wallet.get_spendable_coins(addrs, config=self.config)
        if coins:
            menu.addAction(_("Spend from"),
                           lambda: self.parent.spend_coins(coins))

        run_hook('receive_menu', menu, addrs, self.wallet)
        menu.exec_(self.viewport().mapToGlobal(position))

    def place_text_on_clipboard(self, text):
        if is_address(text):
            try:
                self.wallet.check_address(text)
            except InternalAddressCorruption as e:
                self.parent.show_error(str(e))
                raise
        self.parent.app.clipboard().setText(text)

    def hide_rows(self):
        for row in range(len(self.am.addr_items)):
            if self.current_filter:
                self.hide_row(row)
            else:
                self.setRowHidden(row, QModelIndex(), False)

    def hide_row(self, row):
        model = self.am
        for column in self.filter_columns:
            idx = model.index(row, column, QModelIndex())
            if idx.isValid():
                txt = model.data(idx, Qt.DisplayRole).value().lower()
                if self.current_filter in txt:
                    self.setRowHidden(row, QModelIndex(), False)
                    return
        self.setRowHidden(row, QModelIndex(), True)

    def on_edited(self, idx, user_role, text):
        if idx.isValid() and user_role:
            self.wallet.set_label(user_role, text)
            addr_item = idx.internalPointer()
            addr_item['label'] = text
            self.am.dataChanged.emit(idx, idx, [Qt.DisplayRole])
            self.parent.update_completions()

    def text_txid_from_coordinate(self, row, col, idx):
        if not idx.isValid():
            return None, None
        addr_item = idx.internalPointer()
        if not addr_item:
            return None, None
        return self.am.data(idx, Qt.DisplayRole).value(), addr_item['addr']
