import webbrowser

from PyQt5.QtGui import *
from PyQt5.QtCore import *
from PyQt5.QtWidgets import *

from electrum_dash.i18n import _
from electrum_dash.masternode_budget import BudgetProposal, BudgetVote
from electrum_dash.masternode_manager import BUDGET_FEE_CONFIRMATIONS
from electrum_dash.util import block_explorer_URL, print_error, format_satoshis_plain

from .amountedit import BTCAmountEdit
from . import util

# Color used when displaying proposals that we created.
MY_PROPOSAL_COLOR = '#80ff80'
# Color used when displaying payment addresses that belong to us.
MY_ADDRESS_COLOR = '#80ff80'

def budget_explorer_url(item_type, identifier):
    """Get the URL for a budget proposal explorer."""
    if item_type == 'proposal':
        return 'https://dashwhale.org/p/%s' % identifier

class ProposalsModel(QAbstractTableModel):
    """Model of budget proposals."""
    NAME = 0
    URL = 1
    YES_COUNT = 2
    NO_COUNT = 3
    START_BLOCK = 4
    END_BLOCK = 5
    AMOUNT = 6
    ADDRESS = 7
    TXID = 8
    TOTAL_FIELDS = 9
    def __init__(self, parent=None):
        super(ProposalsModel, self).__init__(parent)
        self.proposals = []
        headers = [
            {Qt.DisplayRole: _('Name'),},
            {Qt.DisplayRole: _('URL'),},
            {Qt.DisplayRole: _('Yes Votes'),},
            {Qt.DisplayRole: _('No Votes'),},
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
        elif c == self.YES_COUNT:
            data = p.yes_count
        elif c == self.NO_COUNT:
            data = p.no_count
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
            if role in [Qt.DisplayRole, Qt.EditRole]:
                data = format_satoshis_plain(data)
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
    def __init__(self, dialog, model, parent=None):
        super(ProposalsWidget, self).__init__(parent)
        self.dialog = dialog
        self.manager = dialog.manager

        self.model = model
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

        self.editor = ProposalEditor(self)

        vbox = QVBoxLayout()
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.addWidget(QLabel(_('Proposals:')))
        vbox.addWidget(self.view)
        vbox.addWidget(self.editor)
        self.setLayout(vbox)

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


class ProposalsTab(QWidget):
    """Wallet tab for budget proposals."""
    def __init__(self, parent):
        super(QWidget, self).__init__(parent)
        self.parent = parent
        self.tree = ProposalsTreeWidget(parent)

        # Proposals that have been paid for but not submitted.
        self.unsubmitted_proposals = []

        description = ''.join(['You can create a budget proposal below. ',
                'Proposals require 5 DASH to create. ',
                'Your proposal can be submitted once the collateral transaction has enough confirmations.'])
        description = QLabel(_(description))
        description.setWordWrap(True)

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText(_('Name of your proposal'))
        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText(_('URL that your proposal can be found at'))
        self.payments_count_edit = QSpinBox()
        self.payments_count_edit.setRange(1, 1000000)
        self.start_block_edit = QSpinBox()
        self.start_block_edit.setRange(0, 1000000)

        self.address_edit = QLineEdit()
        self.address_edit.setPlaceholderText(_('Address that will receive payments'))

        self.amount_edit = BTCAmountEdit(self.parent.get_decimal_point)

        self.create_proposal_button = QPushButton(_('Create Proposal'))
        self.create_proposal_button.clicked.connect(self.create_proposal)
        self.submit_ready_proposals_button = QPushButton(_('Submit Confirmed Proposals'))
        self.submit_ready_proposals_button.clicked.connect(self.submit_waiting_proposals)
        self.submit_ready_proposals_button.setEnabled(False)
        self.ready_proposals = QLabel()
        self.ready_proposals.setVisible(False)

        form = QFormLayout()
        form.addRow(_('Proposal Name:'), self.name_edit)
        form.addRow(_('Proposal URL:'), self.url_edit)
        form.addRow(_('Number of Payments:'), self.payments_count_edit)
        form.addRow(_('Starting Block:'), self.start_block_edit)
        form.addRow(_('Payment Address:'), self.address_edit)
        form.addRow(_('Monthly DASH Payment:'), self.amount_edit)

        vbox = QVBoxLayout()
        vbox.addWidget(self.tree)
        vbox.addWidget(description)
        vbox.addLayout(form)

        vbox.addLayout(util.Buttons(self.create_proposal_button))
        vbox.addLayout(util.Buttons(self.ready_proposals, self.submit_ready_proposals_button))
        self.setLayout(vbox)

    def get_model(self):
        """Get the model so that other widgets can display proposals."""
        return self.tree.model

    def update(self, proposals):
        self.tree.update(proposals, self.parent)
        self.start_block_edit.setMinimum(self.parent.network.get_local_height())

        # Check if we have unsubmitted proposals.
        self.update_unsubmitted_proposals()

    def update_unsubmitted_proposals(self):
        """Update the list of unsubmitted proposals."""
        self.unsubmitted_proposals = []
        for p in self.parent.masternode_manager.proposals:
            if p.fee_txid and not p.submitted and not p.rejected:
                tx_height = self.wallet.get_tx_height(p.fee_txid)
                if tx_height.conf < BUDGET_FEE_CONFIRMATIONS:
                    continue

                item = (p.proposal_name, p.fee_txid)
                if item not in self.unsubmitted_proposals:
                    self.unsubmitted_proposals.append(item)

        can_submit = len(self.unsubmitted_proposals) > 0
        self.submit_ready_proposals_button.setEnabled(can_submit)

        num = len(self.unsubmitted_proposals)
        noun = 'proposal%s' % ('' if num == 1 else 's')
        article = 'is' if num == 1 else 'are'
        self.ready_proposals.setText(str(num) + _(' %s %s ready to be submitted.' % (noun, article)))
        self.ready_proposals.setVisible(can_submit)

    def create_proposal_from_widgets(self):
        """Get BudgetProposal keyword arguments from our widgets and instantiate one."""
        kwargs = {}
        kwargs['proposal_name'] = str(self.name_edit.text())
        kwargs['proposal_url'] = str(self.url_edit.text())
        kwargs['start_block'] = self.start_block_edit.value()
        kwargs['address'] = str(self.address_edit.text())
        kwargs['payment_amount'] = self.amount_edit.get_amount()

        proposal = BudgetProposal(**kwargs)
        # Assign end_block using the number of payments.
        proposal.set_payments_count(self.payments_count_edit.value())
        # Raise if proposal is invalid.
        proposal.check_valid()
        return proposal

    def create_proposal(self):
        manager = self.parent.masternode_manager

        try:
            proposal = self.create_proposal_from_widgets()
        except Exception as e:
            return QMessageBox.critical(self, _('Error'), _(str(e)))

        pw = None
        if manager.wallet.has_password():
            pw = self.parent.password_dialog(msg=_('Please enter your password to create a budget proposal.'))
            if pw is None:
                return

        manager.add_proposal(proposal)

        def sign_done(proposal, tx):
            print_error('proposal tx sign done: %s' % proposal.proposal_name)
            if tx:
                label = _('Budget Proposal Tx: ') + proposal.proposal_name
                self.parent.broadcast_transaction(tx, label)
                self.parent.masternode_manager.save()
        self.create_proposal_tx(proposal, pw, sign_done)

    def create_proposal_tx(self, proposal, pw, callback):
        """Create and sign the proposal fee transaction."""
        result = [False]
        def tx_thread():
            return self.parent.masternode_manager.create_proposal_tx(proposal.proposal_name, pw, save=False)

        def on_tx_made(tx):
            result[0] = tx

        def on_done():
            callback(proposal, result[0])

        self.waiting_dialog = util.WaitingDialog(self, _('Creating Transaction...'), tx_thread, on_tx_made, on_done)
        self.waiting_dialog.start()

    def submit_waiting_proposals(self):
        """Submit the proposals that are ready to the network."""
        # Submit the proposals that are ready.
        results = [('', '', False)] * len(self.unsubmitted_proposals)

        def submit_thread():
            for i, (proposal_name, txid) in enumerate(self.unsubmitted_proposals):
                errmsg, success = self.parent.masternode_manager.submit_proposal(proposal_name, save=False)
                results[i] = (proposal_name, errmsg, success)
                if success:
                    print_error('Sucessfully submitted proposal "%s"' % proposal_name)
                else:
                    print_error('Failed to submit proposal "%s": %s' % (proposal_name, errmsg))
            return results

        def on_done():
            msg = ''
            for proposal_name, errmsg, success in results:
                if success:
                    msg += '<b>' + proposal_name + '</b>' + _(': submitted successfully.')
                else:
                    msg += '<b>' + proposal_name + '</b>' + _(': failed! "%s"' % errmsg)

                msg += '\n'
            QMessageBox.information(self, _('Results'), msg)
            self.update_unsubmitted_proposals()
            self.parent.masternode_manager.save()

        self.waiting_dialog = util.WaitingDialog(self, _('Submitting Proposals...'), submit_thread, on_complete=on_done)
        self.waiting_dialog.start()




class ProposalsTreeWidget(util.MyTreeWidget):
    """Widget compatible with other wallet GUI tabs."""
    def __init__(self, parent=None):
        super(ProposalsTreeWidget, self).__init__(parent, self.create_menu, [_('Name'), _('URL'), _('Yes Votes'), _('No Votes'),
                    _('Start Block'), _('End Block'), _('Amount'), _('Address'), _('Fee Tx')], 0)

        header = self.header()
        header.setResizeMode(ProposalsModel.NAME, QHeaderView.ResizeToContents)
        header.setResizeMode(ProposalsModel.URL, QHeaderView.Stretch)
        header.setResizeMode(ProposalsModel.YES_COUNT, QHeaderView.ResizeToContents)
        header.setResizeMode(ProposalsModel.NO_COUNT, QHeaderView.ResizeToContents)
        header.setResizeMode(ProposalsModel.ADDRESS, QHeaderView.ResizeToContents)
        header.setResizeMode(ProposalsModel.TXID, QHeaderView.ResizeToContents)

        self.model = ProposalsModel()

    def edit_label(self, item, column=None):
        return

    def update(self, proposals, main_window):
        item = self.currentItem()
        current_proposal = item.data(ProposalsModel.TXID, Qt.UserRole).toString() if item else None

        self.model.set_proposals(proposals)
        self.clear()
        row_count = self.model.rowCount()
        if row_count < 1:
            return
        for r in range(row_count):
            get_data = lambda col, row=r: self.model.data(self.model.index(row, col))
            name = _(str(get_data(ProposalsModel.NAME).toString()))
            url = _(str(get_data(ProposalsModel.URL).toString()))
            yes_count = str(get_data(ProposalsModel.YES_COUNT).toString())
            no_count = str(get_data(ProposalsModel.NO_COUNT).toString())
            start_block = str(get_data(ProposalsModel.START_BLOCK).toString())
            end_block = str(get_data(ProposalsModel.END_BLOCK).toString())
            amount = str(get_data(ProposalsModel.AMOUNT).toString())
            address = str(get_data(ProposalsModel.ADDRESS).toString())
            txid = str(get_data(ProposalsModel.TXID).toString())
            display_txid = '%s...%s' % (txid[0:8], txid[-8:])

            item = QTreeWidgetItem( [name, url, yes_count, no_count, start_block, end_block, amount, address, display_txid] )
            item.setFont(ProposalsModel.START_BLOCK, QFont(util.MONOSPACE_FONT))
            item.setFont(ProposalsModel.END_BLOCK, QFont(util.MONOSPACE_FONT))
            item.setFont(ProposalsModel.ADDRESS, QFont(util.MONOSPACE_FONT))
            item.setFont(ProposalsModel.TXID, QFont(util.MONOSPACE_FONT))

            if name:
                item.setData(ProposalsModel.NAME, Qt.UserRole, name)
            if txid:
                item.setData(ProposalsModel.TXID, Qt.UserRole, txid)

            is_my_proposal = False
            if main_window.masternode_manager.get_proposal(name) is not None:
                is_my_proposal = True
            if is_my_proposal:
                item.setBackground(ProposalsModel.NAME, QBrush(QColor(MY_PROPOSAL_COLOR)))
                item.setToolTip(ProposalsModel.NAME, _('You created this proposal.'))

            is_my_address = main_window.wallet.is_mine(address)
            if is_my_address:
                item.setBackground(ProposalsModel.ADDRESS, QBrush(QColor(MY_ADDRESS_COLOR)))
                item.setToolTip(ProposalsModel.ADDRESS, _('You own this address.'))

            self.addTopLevelItem(item)

            if current_proposal == name:
                self.setCurrentItem(item)


    def create_menu(self, position):
        self.selectedIndexes()
        item = self.currentItem()
        if not item:
            return

        name = str(item.data(ProposalsModel.NAME, Qt.UserRole).toString())
        if not name:
            return
        fee_txid = str(item.data(ProposalsModel.TXID, Qt.UserRole).toString())
        if not fee_txid:
            return

        proposal_explorer_url = budget_explorer_url('proposal', name)
        fee_tx_url = block_explorer_URL(self.parent.config, 'tx', fee_txid)

        menu = QMenu()
        menu.addAction(_("View on budget explorer"), lambda: webbrowser.open(proposal_explorer_url))
        menu.addAction(_("View transaction on block explorer"), lambda: webbrowser.open(fee_tx_url))

        menu.exec_(self.viewport().mapToGlobal(position))
