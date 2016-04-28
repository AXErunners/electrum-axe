from PyQt4.QtGui import *
from PyQt4.QtCore import *


from electrum_dash.i18n import _
from electrum_dash.masternode_budget import BudgetProposal, BudgetVote

import util

class ProposalsModel(QAbstractTableModel):
    """Model of budget proposals."""
    NAME = 0
    URL = 1
    START_BLOCK = 2
    END_BLOCK = 3
    AMOUNT = 4
    ADDRESS = 5
    TXID = 6
    TOTAL_FIELDS = 7
    def __init__(self, parent=None):
        super(ProposalsModel, self).__init__(parent)
        self.proposals = []
        headers = [
            {Qt.DisplayRole: _('Name'),},
            {Qt.DisplayRole: _('URL'),},
            {Qt.DisplayRole: _('Start Block'),},
            {Qt.DisplayRole: _('End Block'),},
            {Qt.DisplayRole: _('Amount'),},
            {Qt.DisplayRole: _('Address'),},
            {Qt.DisplayRole: _('Fee Tx'),},
        ]
        for d in headers:
            d[Qt.EditRole] = d[Qt.DisplayRole]
        self.headers = headers

    def set_proposals(self, proposals):
        self.beginResetModel()
        self.proposals = list(proposals)
        self.endResetModel()

    def columnCount(self, parent=QModelIndex()):
        return self.TOTAL_FIELDS

    def rowCount(self, parent=QModelIndex()):
        return len(self.proposals)

    def headerData(self, section, orientation, role = Qt.DisplayRole):
        if orientation != Qt.Horizontal:
            return None
        if role not in [Qt.EditRole, Qt.DisplayRole, Qt.ToolTipRole]:
            return None

        try:
            data = self.headers[section][role]
        except (IndexError, KeyError):
            return None
        return QVariant(data)

    def data(self, index, role = Qt.DisplayRole):
        if not index.isValid():
            return None
        if role not in [Qt.EditRole, Qt.DisplayRole, Qt.ToolTipRole, Qt.FontRole]:
            return None

        data = None
        p = self.proposals[index.row()]
        c = index.column()

        if c == self.NAME:
            data = p.proposal_name
        elif c == self.URL:
            data = p.proposal_url
        elif c == self.START_BLOCK:
            data = p.start_block
            if role == Qt.FontRole:
                data = util.MONOSPACE_FONT
        elif c == self.END_BLOCK:
            data = p.end_block
            if role == Qt.FontRole:
                data = util.MONOSPACE_FONT
        elif c == self.AMOUNT:
            data = p.payment_amount
        elif c == self.ADDRESS:
            data = p.address
            if role == Qt.FontRole:
                data = util.MONOSPACE_FONT
        elif c == self.TXID:
            data = p.fee_txid
            if role == Qt.FontRole:
                data = util.MONOSPACE_FONT

        return QVariant(data)

class ProposalsWidget(QWidget):
    """Widget that displays masternode budget proposals."""
    def __init__(self, dialog, parent=None):
        super(ProposalsWidget, self).__init__(parent)
        self.dialog = dialog
        self.manager = dialog.manager

        self.model = ProposalsModel()
        self.proxy_model = QSortFilterProxyModel()
        self.proxy_model.setSourceModel(self.model)
        self.view = QTableView()
        self.view.setModel(self.proxy_model)
        self.view.setSortingEnabled(True)

        self.view.setSelectionMode(QAbstractItemView.SingleSelection)
        self.view.setSelectionBehavior(QAbstractItemView.SelectRows)

        header = self.view.horizontalHeader()
        header.setHighlightSections(False)
        header.setResizeMode(self.model.NAME, QHeaderView.ResizeToContents)
        header.setResizeMode(self.model.URL, QHeaderView.Stretch)
        header.setResizeMode(self.model.ADDRESS, QHeaderView.ResizeToContents)
        header.setResizeMode(self.model.TXID, QHeaderView.ResizeToContents)

        self.view.verticalHeader().setVisible(False)
        self.view.sortByColumn(self.model.NAME, Qt.AscendingOrder)
        self.view.selectionModel().selectionChanged.connect(self.on_view_selection_changed)

        self.refresh_button = QPushButton(_('Refresh'))
        self.refresh_button.clicked.connect(self.refresh_proposals)

        self.editor = ProposalEditor(self)

        vbox = QVBoxLayout()
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.addWidget(QLabel(_('Proposals:')))
        vbox.addWidget(self.view)
        vbox.addLayout(util.Buttons(self.refresh_button))
        vbox.addWidget(self.editor)
        self.setLayout(vbox)

    def refresh_proposals(self):
        """Update proposals."""
        proposals = self.manager.retrieve_proposals()
        self.model.set_proposals(proposals)
        self.view.sortByColumn(self.proxy_model.sortColumn(), self.proxy_model.sortOrder())
        self.view.selectRow(0)

    def on_view_selection_changed(self, selected, deselected):
        """Update the data widget mapper."""
        idx = 0
        try:
            idx = selected.indexes()[0]
        except IndexError:
            pass
        self.editor.mapper.setCurrentIndex(idx.row())

class ProposalEditor(QWidget):
    """Editor for proposals."""
    def __init__(self, main_widget, parent=None):
        super(ProposalEditor, self).__init__(parent)
        self.main_widget = main_widget

        self.name_edit = QLineEdit()
        self.url_edit = QLineEdit()
        self.start_block_edit = QLineEdit()
        self.end_block_edit = QLineEdit()
        self.amount_edit = QLineEdit()
        self.address_edit = QLineEdit()
        self.txid_edit = QLineEdit()
        for i in [self.name_edit, self.url_edit, self.start_block_edit, self.end_block_edit,
                self.amount_edit, self.address_edit, self.txid_edit]:
            i.setReadOnly(True)

        self.mapper = QDataWidgetMapper()
        self.mapper.setModel(self.main_widget.proxy_model)
        self.mapper.setSubmitPolicy(QDataWidgetMapper.ManualSubmit)

        self.mapper.addMapping(self.name_edit, ProposalsModel.NAME)
        self.mapper.addMapping(self.url_edit, ProposalsModel.URL)
        self.mapper.addMapping(self.start_block_edit, ProposalsModel.START_BLOCK)
        self.mapper.addMapping(self.end_block_edit, ProposalsModel.END_BLOCK)
        self.mapper.addMapping(self.amount_edit, ProposalsModel.AMOUNT)
        self.mapper.addMapping(self.address_edit, ProposalsModel.ADDRESS)
        self.mapper.addMapping(self.txid_edit, ProposalsModel.TXID)

        block_hbox = QHBoxLayout()
        block_hbox.addWidget(self.start_block_edit)
        block_hbox.addWidget(QLabel(' - '))
        block_hbox.addWidget(self.end_block_edit)

        self.vote_combo = QComboBox()
        self.vote_combo.addItem(_('Yes'))
        self.vote_combo.addItem(_('No'))
        self.vote_button = QPushButton(_('Vote'))
        self.vote_button.clicked.connect(self.cast_vote)

        vote_hbox = util.Buttons(self.vote_combo, self.vote_button)

        form = QFormLayout()
        form.addRow(_('Name:'), self.name_edit)
        form.addRow(_('URL:'), self.url_edit)
        form.addRow(_('Blocks:'), block_hbox)
        form.addRow(_('Monthly Payment:'), self.amount_edit)
        form.addRow(_('Payment Address:'), self.address_edit)
        form.addRow(_('Fee TxID:'), self.txid_edit)

        form.addRow(_('Vote:'), vote_hbox)
        self.setLayout(form)

    def cast_vote(self):
        name = str(self.name_edit.text())
        vote_yes = True if self.vote_combo.currentIndex() == 0 else False
        self.main_widget.dialog.cast_vote(name, vote_yes)
