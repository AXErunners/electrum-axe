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

from PyQt5.QtCore import (pyqtSignal, Qt, QModelIndex, QVariant,
                          QAbstractItemModel, QItemSelectionModel)
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (QAbstractItemView, QHeaderView, QComboBox,
                             QLabel, QMenu)

from electrum_axe.i18n import _
from electrum_axe.axe_ps import sort_utxos_by_ps_rounds
from electrum_axe.axe_tx import PSCoinRounds
from electrum_axe.logging import Logger
from electrum_axe.util import profiler

from .util import MyTreeView, ColorScheme, MONOSPACE_FONT, GetDataThread


class UTXOColumns(IntEnum):
    OUTPOINT = 0
    ADDRESS = 1
    LABEL = 2
    AMOUNT = 3
    HEIGHT = 4
    PS_ROUNDS = 5
    KEYSTORE_TYPE = 6


class UTXOModel(QAbstractItemModel, Logger):

    data_ready = pyqtSignal()

    SELECT_ROWS = QItemSelectionModel.Rows | QItemSelectionModel.Select

    SORT_KEYS = {
        UTXOColumns.ADDRESS: lambda x: x['address'],
        UTXOColumns.LABEL: lambda x: x['label'],
        UTXOColumns.PS_ROUNDS: lambda x: x['ix'],
        UTXOColumns.KEYSTORE_TYPE: lambda x: x['is_ps_ks'],
        UTXOColumns.AMOUNT: lambda x: x['balance'],
        UTXOColumns.HEIGHT: lambda x: x['height'],
        UTXOColumns.OUTPOINT: lambda x: x['outpoint'],
    }

    def __init__(self, parent):
        super(UTXOModel, self).__init__(parent)
        Logger.__init__(self)
        self.parent = parent
        self.wallet = self.parent.wallet
        self.coin_items = list()
        # setup bg thread to get updated data
        self.data_ready.connect(self.on_get_data, Qt.BlockingQueuedConnection)
        self.get_data_thread = GetDataThread(self, self.get_coins,
                                             self.data_ready, self)
        self.get_data_thread.start()

    def set_view(self, utxo_list):
        self.view = utxo_list

    def headerData(self, section, orientation, role):
        if role != Qt.DisplayRole:
            return
        return {
            UTXOColumns.ADDRESS: _('Address'),
            UTXOColumns.LABEL: _('Label'),
            UTXOColumns.PS_ROUNDS: _('PS Rounds'),
            UTXOColumns.KEYSTORE_TYPE : _('Keystore'),
            UTXOColumns.AMOUNT: _('Amount'),
            UTXOColumns.HEIGHT: _('Height'),
            UTXOColumns.OUTPOINT: _('Output point'),
        }[section]

    def flags(self, idx):
        extra_flags = Qt.NoItemFlags
        if idx.column() in self.view.editable_columns:
            extra_flags |= Qt.ItemIsEditable
        return super().flags(idx) | extra_flags

    def columnCount(self, parent: QModelIndex):
        return len(UTXOColumns)

    def rowCount(self, parent: QModelIndex):
        return len(self.coin_items)

    def index(self, row: int, column: int, parent: QModelIndex):
        if not parent.isValid():  # parent is root
            if len(self.coin_items) > row:
                return self.createIndex(row, column, self.coin_items[row])
        return QModelIndex()

    def parent(self, index: QModelIndex):
        return QModelIndex()

    def hasChildren(self, index: QModelIndex):
        return not index.isValid()

    def sort(self, col, order):
        if self.coin_items:
            self.process_changes(self.sorted(self.coin_items, col, order))

    def sorted(self, coin_items, col, order):
        return sorted(coin_items, key=self.SORT_KEYS[col], reverse=order)

    def data(self, index: QModelIndex, role: Qt.ItemDataRole) -> QVariant:
        assert index.isValid()
        col = index.column()
        coin_item = index.internalPointer()
        address = coin_item['address']
        is_frozen_addr = coin_item['is_frozen_addr']
        is_frozen_coin = coin_item['is_frozen_coin']
        height = coin_item['height']
        outpoint = coin_item['outpoint']
        out_short = coin_item['out_short']
        label = coin_item['label']
        balance = coin_item['balance']
        ps_rounds = coin_item['ps_rounds']
        is_ps_ks = coin_item['is_ps_ks']
        if ps_rounds is None:
            ps_rounds = 'N/A'
        elif ps_rounds == PSCoinRounds.COLLATERAL:
            ps_rounds = 'Collateral'
        elif ps_rounds == PSCoinRounds.OTHER:
            ps_rounds = 'Other'
        else:
            ps_rounds = str(ps_rounds)
        if role == Qt.ToolTipRole:
            if col == UTXOColumns.ADDRESS and is_frozen_addr:
                return QVariant(_('Address is frozen'))
            elif col == UTXOColumns.OUTPOINT:
                if is_frozen_coin:
                    return QVariant(f'{outpoint}\n{_("Coin is frozen")}')
                else:
                    return QVariant(outpoint)
        elif role not in (Qt.DisplayRole, Qt.EditRole):
            if role == Qt.TextAlignmentRole:
                if col in [UTXOColumns.AMOUNT, UTXOColumns.HEIGHT,
                           UTXOColumns.PS_ROUNDS, UTXOColumns.KEYSTORE_TYPE]:
                    return QVariant(Qt.AlignRight|Qt.AlignVCenter)
                else:
                    return QVariant(Qt.AlignVCenter)
            elif role == Qt.FontRole:
                return QVariant(QFont(MONOSPACE_FONT))
            elif role == Qt.BackgroundRole:
                if col == UTXOColumns.ADDRESS and is_frozen_addr:
                    return QVariant(ColorScheme.BLUE.as_color(True))
                elif col == UTXOColumns.OUTPOINT and is_frozen_coin:
                    return QVariant(ColorScheme.BLUE.as_color(True))
        elif col == UTXOColumns.OUTPOINT:
            return QVariant(out_short)
        elif col == UTXOColumns.ADDRESS:
            return QVariant(address)
        elif col == UTXOColumns.LABEL:
            return QVariant(label)
        elif col == UTXOColumns.AMOUNT:
            return QVariant(balance)
        elif col == UTXOColumns.HEIGHT:
            return QVariant(height)
        elif col == UTXOColumns.PS_ROUNDS:
            return QVariant(ps_rounds)
        elif col == UTXOColumns.KEYSTORE_TYPE:
            return QVariant(_('PS Keystore') if is_ps_ks else _('Main'))
        else:
            return QVariant()

    @profiler
    def get_coins(self):
        coin_items = []

        show_ps = self.view.show_ps
        show_ps_ks = self.view.show_ps_ks
        w = self.wallet
        if show_ps == 0:  # All
            utxos = w.get_utxos(include_ps=True)
        elif show_ps == 1:  # PrivateSend
            utxos = w.get_utxos(min_rounds=PSCoinRounds.COLLATERAL)
        elif show_ps == 2:  # PS Other coins
            utxos = w.get_utxos(min_rounds=PSCoinRounds.MINUSINF)
            utxos = [c for c in utxos if c['ps_rounds'] <= PSCoinRounds.OTHER]
        else:  # Regular
            utxos = w.get_utxos()
        if show_ps_ks == 1:     # PS Keystore
            utxos = [c for c in utxos if c['is_ps_ks']]
        elif show_ps_ks == 2:   # Main Keystore
            utxos = [c for c in utxos if not c['is_ps_ks']]
        utxos.sort(key=sort_utxos_by_ps_rounds)
        for i, utxo in enumerate(utxos):
            address = utxo['address']
            value = utxo['value']
            prev_h = utxo['prevout_hash']
            prev_n = utxo['prevout_n']
            outpoint = f'{prev_h}:{prev_n}'
            coin_items.append({
                'address': address,
                'value': value,
                'prevout_n': prev_n,
                'prevout_hash': prev_h,
                'height': utxo['height'],
                'coinbase': utxo['coinbase'],
                'islock': utxo['islock'],
                'ps_rounds': utxo['ps_rounds'],
                'is_ps_ks': utxo['is_ps_ks'],
                # append model fields
                'ix': i,
                'outpoint': outpoint,
                'out_short': f'{prev_h[:16]}...:{prev_n}',
                'is_frozen_addr': w.is_frozen_address(address),
                'is_frozen_coin': w.is_frozen_coin(outpoint),
                'label': w.get_label(prev_h),
                'balance': self.parent.format_amount(value, whitespaces=True),
            })
        return coin_items

    @profiler
    def process_changes(self, coin_items):
        selected = self.view.selectionModel().selectedRows()
        selected_outpoints = []
        for idx in selected:
            selected_outpoints.append(idx.internalPointer()['outpoint'])

        if self.coin_items:
            self.beginRemoveRows(QModelIndex(), 0, len(self.coin_items)-1)
            self.coin_items.clear()
            self.endRemoveRows()

        if coin_items:
            self.beginInsertRows(QModelIndex(), 0, len(coin_items)-1)
            self.coin_items = coin_items[:]
            self.endInsertRows()

        selected_rows = []
        if selected_outpoints:
            for i, coin_item in enumerate(coin_items):
                outpoint = coin_item['outpoint']
                if outpoint in selected_outpoints:
                    selected_rows.append(i)
                    selected_outpoints.remove(outpoint)
                    if not selected_outpoints:
                        break
        if selected_rows:
            for i in selected_rows:
                idx = self.index(i, 0, QModelIndex())
                self.view.selectionModel().select(idx, self.SELECT_ROWS)

    def on_get_data(self):
        self.refresh(self.get_data_thread.res)

    @profiler
    def refresh(self, coin_items):
        if coin_items == self.coin_items:
            return
        col = self.view.header().sortIndicatorSection()
        order = self.view.header().sortIndicatorOrder()
        self.process_changes(self.sorted(coin_items, col, order))
        self.view.filter()


class UTXOList(MyTreeView):

    filter_columns = [UTXOColumns.ADDRESS, UTXOColumns.PS_ROUNDS,
                      UTXOColumns.KEYSTORE_TYPE, UTXOColumns.LABEL,
                      UTXOColumns.OUTPOINT]

    def __init__(self, parent, model):
        stretch_column = UTXOColumns.LABEL
        super().__init__(parent, self.create_menu,
                         stretch_column=stretch_column, editable_columns=[])
        self.cm = model
        self.setModel(model)
        self.wallet = self.parent.wallet
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)

        header = self.header()
        header.setDefaultAlignment(Qt.AlignCenter)
        header.setStretchLastSection(False)
        header.setSortIndicator(UTXOColumns.PS_ROUNDS, Qt.AscendingOrder)
        self.setSortingEnabled(True)
        for col in UTXOColumns:
            if col == stretch_column:
                header.setSectionResizeMode(col, QHeaderView.Stretch)
            elif col == UTXOColumns.PS_ROUNDS:
                header.setSectionResizeMode(col, QHeaderView.Fixed)
            else:
                header.setSectionResizeMode(col, QHeaderView.ResizeToContents)

        self.show_ps = 0
        self.show_ps_ks = 0
        self.ps_button = QComboBox(self)
        self.ps_button.currentIndexChanged.connect(self.toggle_ps)
        for t in [_('All'), _('PrivateSend'),
                  _('PS Other coins'), _('Regular')]:
            self.ps_button.addItem(t)
        self.ps_ks_button = QComboBox(self)
        self.ps_ks_button.currentIndexChanged.connect(self.toggle_ps_ks)
        for t in [_('All'), _('PS Keystore'), _('Main')]:
            self.ps_ks_button.addItem(t)

    def get_toolbar_buttons(self):
        return (QLabel('    %s ' % _("Filter PS Type:")),
                self.ps_button,
                QLabel('    %s ' % _("Keystore:")),
                self.ps_ks_button)

    def on_hide_toolbar(self):
        self.show_ps = 0
        self.show_ps_ks = 0
        self.update()

    def save_toolbar_state(self, state, config):
        config.set_key('show_toolbar_utxos', state)

    def toggle_ps(self, state):
        if state == self.show_ps:
            return
        self.ps_button.setCurrentIndex(state)
        self.show_ps = state
        self.update()

    def toggle_ps_ks(self, state):
        if state == self.show_ps_ks:
            return
        self.show_ps_ks = state
        self.update()

    def update(self):
        self.cm.get_data_thread.need_update.set()

    def create_menu(self, position):
        w = self.wallet
        psman = w.psman
        selected = self.selectionModel().selectedRows()
        if not selected:
            return
        menu = QMenu()
        menu.setSeparatorsCollapsible(True)
        coins = []
        for idx in selected:
            if not idx.isValid():
                return
            coins.append(idx.internalPointer())
        menu.addAction(_("Spend"), lambda: self.parent.spend_coins(coins))
        if len(coins) == 1:
            coin_item = coins[0]
            ps_rounds = coin_item['ps_rounds']
            address = coin_item['address']
            txid = coin_item['prevout_hash']
            outpoint = coin_item['outpoint']
            if (ps_rounds is not None
                    and (ps_rounds == PSCoinRounds.OTHER or ps_rounds >= 0)):
                coin_val = coin_item['value']
                mwin = self.parent
                if coin_val >= psman.min_new_denoms_from_coins_val:

                    def create_new_denoms():
                        mwin.create_new_denoms(coins, self.parent)
                    menu.addAction(_('Create New Denoms'), create_new_denoms)

                elif coin_val >= psman.min_new_collateral_from_coins_val:

                    def create_new_collateral():
                        mwin.create_new_collateral(coins, self.parent)
                    menu.addAction(_('Create New Collateral'),
                                   create_new_collateral)
            # "Details"
            tx = w.db.get_transaction(txid)
            if tx:
                # Prefer None if empty
                # (None hides the Description: field in the window)
                label = w.get_label(txid) or None
                menu.addAction(_("Details"),
                               lambda: self.parent.show_transaction(tx, label))
            # "Copy ..."
            idx = self.indexAt(position)
            if not idx.isValid():
                return
            col = idx.column()
            hd = self.cm.headerData
            column_title = hd(col, None, Qt.DisplayRole)
            if col != UTXOColumns.OUTPOINT:
                copy_text = str(self.cm.data(idx, Qt.DisplayRole).value())
            else:
                copy_text = outpoint
            if col == UTXOColumns.AMOUNT:
                copy_text = copy_text.strip()
            clipboard = self.parent.app.clipboard()
            menu.addAction(_("Copy {}").format(column_title),
                           lambda: clipboard.setText(copy_text))

            if ps_rounds is not None:
                menu.exec_(self.viewport().mapToGlobal(position))
                return

            # "Freeze coin"
            set_frozen_state_c = self.parent.set_frozen_state_of_coins
            if not w.is_frozen_coin(outpoint):
                menu.addAction(_("Freeze Coin"),
                               lambda: set_frozen_state_c([outpoint], True))
            else:
                menu.addSeparator()
                menu.addAction(_("Coin is frozen"),
                               lambda: None).setEnabled(False)
                menu.addAction(_("Unfreeze Coin"),
                               lambda: set_frozen_state_c([outpoint], False))
                menu.addSeparator()
            # "Freeze address"
            set_frozen_state_a = self.parent.set_frozen_state_of_addresses
            if not w.is_frozen_address(address):
                menu.addAction(_("Freeze Address"),
                               lambda: set_frozen_state_a([address], True))
            else:
                menu.addSeparator()
                menu.addAction(_("Address is frozen"),
                               lambda: None).setEnabled(False)
                menu.addAction(_("Unfreeze Address"),
                               lambda: set_frozen_state_a([address], False))
                menu.addSeparator()
        else:
            # multiple items selected
            ps_rounds = set([coin_item['ps_rounds'] for coin_item in coins])
            if ps_rounds != {None}:
                menu.exec_(self.viewport().mapToGlobal(position))
                return

            menu.addSeparator()
            addrs = set([coin_item['address'] for coin_item in coins])
            is_coin_frozen = [w.is_frozen_coin(coin_item['outpoint'])
                              for coin_item in coins]
            is_addr_frozen = [w.is_frozen_address(coin_item['address'])
                              for coin_item in coins]

            set_frozen_state_c = self.parent.set_frozen_state_of_coins
            if not all(is_coin_frozen):
                menu.addAction(_("Freeze Coins"),
                               lambda: set_frozen_state_c(coins, True))
            if any(is_coin_frozen):
                menu.addAction(_("Unfreeze Coins"),
                               lambda: set_frozen_state_c(coins, False))

            set_frozen_state_a = self.parent.set_frozen_state_of_addresses
            if not all(is_addr_frozen):
                menu.addAction(_("Freeze Addresses"),
                               lambda: set_frozen_state_a(addrs, True))
            if any(is_addr_frozen):
                menu.addAction(_("Unfreeze Addresses"),
                               lambda: set_frozen_state_a(addrs, False))
        menu.exec_(self.viewport().mapToGlobal(position))

    def hide_rows(self):
        for row in range(len(self.cm.coin_items)):
            if self.current_filter:
                self.hide_row(row)
            else:
                self.setRowHidden(row, QModelIndex(), False)

    def hide_row(self, row):
        model = self.cm
        for column in self.filter_columns:
            idx = model.index(row, column, QModelIndex())
            if idx.isValid():
                txt = model.data(idx, Qt.DisplayRole).value().lower()
                if self.current_filter in txt:
                    self.setRowHidden(row, QModelIndex(), False)
                    return
        self.setRowHidden(row, QModelIndex(), True)
