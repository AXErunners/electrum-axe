# -*- coding: utf-8 -*-

import os
import ipaddress
import json
from bls_py import bls

from PyQt5.QtGui import QFont, QPixmap
from PyQt5.QtCore import Qt, pyqtSignal, pyqtSlot, QFileInfo
from PyQt5.QtWidgets import (QLineEdit, QComboBox, QListWidget, QDoubleSpinBox,
                             QAbstractItemView, QListWidgetItem, QWizardPage,
                             QRadioButton, QButtonGroup, QVBoxLayout, QLabel,
                             QGroupBox, QCheckBox, QPushButton, QGridLayout,
                             QFileDialog, QWizard)

from electrum_axe import axe_tx
from electrum_axe.bitcoin import COIN, is_b58_address
from electrum_axe.axe_tx import TxOutPoint
from electrum_axe.protx import ProTxMN, ProTxService, ProRegTxExc
from electrum_axe.util import bfh, bh2u

from .util import MONOSPACE_FONT, icon_path, read_QIcon


class ValidationError(Exception): pass


class HwWarnError(Exception): pass


class SLineEdit(QLineEdit):
    '''QLineEdit with strip on text() method'''
    def text(self):
        return super().text().strip()


class SComboBox(QComboBox):
    '''QComboBox with strip on currentText() method'''
    def currentText(self):
        return super().currentText().strip()


class OutputsList(QListWidget):
    '''Widget that displays available 1000 AXE outputs.'''
    outputSelected = pyqtSignal(dict, name='outputSelected')
    def __init__(self, parent=None):
        super(OutputsList, self).__init__(parent)
        self.outputs = {}
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        sel_model = self.selectionModel()
        sel_model.selectionChanged.connect(self.on_selection_changed)

    def add_output(self, d):
        '''Add a valid output.'''
        label = '%s:%s' % (d['prevout_hash'], d['prevout_n'])
        self.outputs[label] = d
        item = QListWidgetItem(label)
        item.setFont(QFont(MONOSPACE_FONT))
        self.addItem(item)

    def add_outputs(self, outputs):
        list(map(self.add_output, outputs))

    def clear(self):
        super(OutputsList, self).clear()
        self.outputs.clear()

    def on_selection_changed(self, selected, deselected):
        '''Emit the selected output.'''
        items = self.selectedItems()
        if not items:
            return
        if not self.outputs:
            return
        self.outputSelected.emit(self.outputs[str(items[0].text())])


class OperationTypeWizardPage(QWizardPage):

    def __init__(self, parent=None):
        super(OperationTypeWizardPage, self).__init__(parent)
        self.parent = parent
        self.setTitle('Operation type')
        self.setSubTitle('Select opeartion type and ownership properties.')

        self.rb_import = QRadioButton('Import and register legacy Masternode '
                                      'as DIP3 Masternode')
        self.rb_create = QRadioButton('Create and registern DIP3 Masternode')
        self.rb_connect = QRadioButton('Connect to registered DIP3 Masternode')
        self.rb_import.setChecked(True)
        self.rb_connect.setEnabled(False)
        self.button_group = QButtonGroup()
        self.button_group.addButton(self.rb_import)
        self.button_group.addButton(self.rb_create)
        self.button_group.addButton(self.rb_connect)
        gb_vbox = QVBoxLayout()
        gb_vbox.addWidget(self.rb_import)
        gb_vbox.addWidget(self.rb_create)
        gb_vbox.addWidget(self.rb_connect)
        self.gb_create = QGroupBox('Select operation type')
        self.gb_create.setLayout(gb_vbox)

        self.cb_owner = QCheckBox('I am an owner of this Masternode')
        self.cb_operator = QCheckBox('I am an operator of this Masternode')
        self.cb_owner.setChecked(True)
        self.cb_owner.stateChanged.connect(self.cb_state_changed)
        self.cb_operator.setChecked(True)
        self.cb_operator.stateChanged.connect(self.cb_state_changed)
        self.cb_owner.setEnabled(False)
        gb_vbox = QVBoxLayout()
        gb_vbox.addWidget(self.cb_owner)
        gb_vbox.addWidget(self.cb_operator)
        self.gb_owner = QGroupBox('Set ownership type')
        self.gb_owner.setLayout(gb_vbox)

        layout = QVBoxLayout()
        layout.addWidget(self.gb_create)
        layout.addStretch(1)
        layout.addWidget(self.gb_owner)
        self.setLayout(layout)

    def nextId(self):
        if self.rb_import.isChecked():
            return self.parent.IMPORT_LEGACY_PAGE
        else:
            return self.parent.COLLATERAL_PAGE

    @pyqtSlot()
    def cb_state_changed(self):
        self.completeChanged.emit()

    def isComplete(self):
        return self.cb_operator.isChecked() or self.cb_owner.isChecked()

    def validatePage(self):
        self.parent.new_mn = ProTxMN()
        self.parent.new_mn.alias = 'default'
        self.parent.new_mn.is_operated = self.cb_operator.isChecked()
        self.parent.new_mn.is_owned = self.cb_owner.isChecked()
        return True


class ImportLegacyWizardPage(QWizardPage):

    def __init__(self, parent=None):
        super(ImportLegacyWizardPage, self).__init__(parent)
        self.parent = parent
        self.setTitle('Import Legacy Masternode')
        self.setSubTitle('Select legacy Masternode to import.')

        legacy = self.parent.legacy
        legacy.load()
        lmns = sorted([lmn.dump() for lmn in legacy.masternodes],
                      key=lambda x: x.get('alias', ''))

        self.lmns_cbox = SComboBox(self)
        self.lmns_dict = {}
        for i, lmn in enumerate(lmns):
            alias = lmn.get('alias', 'Unknown alias %s' % i)
            self.lmns_cbox.addItem(alias)
            self.lmns_dict[alias] = lmn
        self.lmns_cbox.currentIndexChanged.connect(self.on_change_lmn)
        self.imp_btn = QPushButton('Load from masternode.conf')
        self.imp_btn.clicked.connect(self.load_masternode_conf)

        service_label = QLabel('Service:')
        self.service = QLabel()
        collateral_val_label = QLabel('Collateral Outpoint Value:')
        self.collateral_val = QLabel()
        self.collateral_value = None
        collateral_label = QLabel('Collateral Outpoint:')
        self.collateral = QLabel()
        collateral_addr_label = QLabel('Collateral Address:')
        self.collateral_addr = QLabel()
        self.err_label = QLabel('Error:')
        self.err_label.setObjectName('err-label')
        self.err = QLabel()
        self.err.setObjectName('err-label')
        self.err_label.hide()
        self.err.hide()

        layout = QGridLayout()
        layout.addWidget(self.imp_btn, 0, 0, 1, -1)
        layout.addWidget(self.lmns_cbox, 1, 0, 1, -1)
        layout.setColumnStretch(2, 1)
        layout.addWidget(service_label, 3, 0)
        layout.addWidget(self.service, 3, 1)
        layout.addWidget(collateral_addr_label, 4, 0)
        layout.addWidget(self.collateral_addr, 4, 1)
        layout.addWidget(collateral_val_label, 5, 0)
        layout.addWidget(self.collateral_val, 5, 1)
        layout.addWidget(collateral_label, 6, 0)
        layout.addWidget(self.collateral, 6, 1)
        layout.addWidget(self.err_label, 8, 0)
        layout.addWidget(self.err, 8, 1)
        self.setLayout(layout)

    def initializePage(self):
        self.update_lmn_data(self.lmns_cbox.currentText())

    @pyqtSlot()
    def on_change_lmn(self):
        self.update_lmn_data(self.lmns_cbox.currentText())

    @pyqtSlot()
    def load_masternode_conf(self):
        dlg = QFileDialog
        conf_fname = dlg.getOpenFileName(self, 'Open masternode.con',
                                         '', 'Conf Files (*.conf)')[0]
        if not conf_fname:
            return

        try:
            with open(conf_fname, 'r') as f:
                conflines = f.readlines()
        except Exception:
            conflines = []
        if not conflines:
            return

        conflines = filter(lambda x: not x.startswith('#'),
                           [l.strip() for l in conflines])

        conflines = filter(lambda x: len(x.split()) == 5, conflines)
        res = []
        for l in conflines:
            res_d = {}
            alias, service, delegate, c_hash, c_index = l.split()

            res_d['alias'] = 'masternode.conf:%s' % alias
            try:
                ip, port = self.parent.validate_service(service)
                res_d['addr'] = {'ip': ip, 'port': int(port)}
                c_index = int(c_index)
            except Exception:
                continue
            res_d['vin'] = {
                'prevout_hash': c_hash,
                'prevout_n': c_index,
            }
            res.append(res_d)

        if not res:
            return
        else:
            res = sorted(res, key=lambda x: x.get('alias'))

        while True:
            idx = self.lmns_cbox.findText('masternode.conf:',
                                          Qt.MatchStartsWith)
            if idx < 0:
                break
            self.lmns_cbox.removeItem(idx)

        for i, r in enumerate(res):
            alias = r.get('alias')
            self.lmns_cbox.addItem(alias)
            if not i:
                first_alias = alias
            self.lmns_dict[alias] = r
        self.lmns_cbox.setFocus()
        first_alias_idx = self.lmns_cbox.findText(first_alias)
        self.lmns_cbox.setCurrentIndex(first_alias_idx)

    def update_lmn_data(self, current):
        if not current:
            return
        self.alias = current
        lmn = self.lmns_dict.get(current)

        addr = lmn.get('addr', {})
        ip = addr.get('ip')
        port = addr.get('port')
        if addr and port:
            try:
                ip_check = ipaddress.ip_address(ip)
                if ip_check.version == 4:
                    service = '%s:%s' % (ip, port)
                else:
                    service = '[%s]:%s' % (ip, port)
            except ValueError:
                service = ''
        else:
            service = ''
        self.service.setText(service)

        vin = lmn.get('vin', {})
        address = vin.get('address')
        prevout_hash = vin.get('prevout_hash')
        prevout_n = vin.get('prevout_n')
        value = vin.get('value')

        if not address:
            wallet = self.parent.wallet
            coins = wallet.get_utxos(domain=None, excluded=None,
                                     mature=True, confirmed_only=True)
            coins = filter(lambda x: (x['prevout_hash'] == prevout_hash
                                          and x['prevout_n'] == prevout_n),
                           coins)
            coins = list(coins)
            if coins:
                address = coins[0]['address']
                value = coins[0]['value']
            else:
                address = ''
                value = 0

        if prevout_hash:
            val_axe = '%s AXE' % (value/COIN) if value else ''
            self.collateral_val.setText(val_axe)
            self.collateral_value = value
            self.collateral.setText('%s:%s' % (prevout_hash, prevout_n))
            self.collateral_addr.setText(address)
        else:
            self.collateral_val.setText('')
            self.collateral_value = None
            self.collateral.setText('')
            self.collateral_addr.setText('')
        self.completeChanged.emit()

    def isComplete(self):
        self.hide_error()
        if self.service.text() and self.collateral.text():
            return True
        return False

    def hide_error(self):
        self.err_label.hide()
        self.err.hide()

    def validatePage(self):
        try:
            ip, port = self.parent.validate_service(self.service.text())
            coll = self.parent.validate_collateral(self.collateral.text(),
                                                   self.collateral_addr.text(),
                                                   self.collateral_value)
        except ValidationError as e:
            self.err.setText(str(e))
            self.err_label.show()
            self.err.show()
            return False
        else:
            collateral_addr = self.collateral_addr.text()

        new_mn = self.parent.new_mn
        new_mn.alias = self.alias
        new_mn.collateral = TxOutPoint(bfh(coll[0])[::-1], coll[1])
        new_mn.service = ProTxService(ip, port)
        self.parent.collateral_addr = collateral_addr
        return True

    def nextId(self):
        return self.parent.SERVICE_PAGE


class SelectAddressesWizardPage(QWizardPage):

    def __init__(self, parent=None):
        super(SelectAddressesWizardPage, self).__init__(parent)
        self.parent = parent
        self.setTitle('Select Addresses')
        self.setSubTitle('Select Masternode owner/voting/payout addresses.')

        layout = QGridLayout()
        self.o_addr_label = QLabel('Owner Address (must differ from '
                                   'collateral):')
        self.o_addr = SComboBox()
        self.o_addr.setEditable(True)
        self.o_addr.editTextChanged.connect(self.on_change_addr)
        self.v_addr_label = QLabel('Voting Address (must differ from '
                                   'collateral):')
        self.v_addr = SComboBox()
        self.v_addr.setEditable(True)
        self.v_addr.editTextChanged.connect(self.on_change_addr)
        self.p_addr_label = QLabel('Payout Address (must differ from '
                                   'owner/voting/collateral):')
        self.p_addr = SComboBox()
        self.p_addr.setEditable(True)
        self.p_addr.editTextChanged.connect(self.on_change_addr)
        self.err_label = QLabel('Error:')
        self.err_label.setObjectName('err-label')
        self.err = QLabel()
        self.err.setObjectName('err-label')
        self.err_label.hide()
        self.err.hide()
        self.hw_err = QLabel()
        self.hw_err.setWordWrap(True)
        self.hw_err.setObjectName('err-label')
        self.hw_err.hide()
        self.cb_ignore = QCheckBox('Ignore warning and continue.')
        self.cb_ignore.stateChanged.connect(self.on_change_ignore)
        self.cb_ignore.hide()

        layout.addWidget(self.o_addr_label, 0, 0, 1, -1)
        layout.addWidget(self.o_addr, 1, 0, 1, -1)
        layout.addWidget(self.v_addr_label, 3, 0, 1, -1)
        layout.addWidget(self.v_addr, 4, 0, 1, -1)
        layout.addWidget(self.p_addr_label, 6, 0, 1, -1)
        layout.addWidget(self.p_addr, 7, 0, 1, -1)
        layout.setColumnStretch(1, 1)
        layout.setRowStretch(2, 1)
        layout.setRowStretch(5, 1)
        layout.addWidget(self.err_label, 8, 0)
        layout.addWidget(self.err, 8, 1)
        layout.addWidget(self.hw_err, 9, 0, 1, -1)
        layout.addWidget(self.cb_ignore, 10, 0, 1, -1)
        self.setLayout(layout)

        unused = self.parent.wallet.get_unused_addresses()
        for addr in unused:
            self.o_addr.addItem(addr)
            self.v_addr.addItem(addr)
            self.p_addr.addItem(addr)
        self.o_addr.setEditText('')
        self.v_addr.setEditText('')
        self.p_addr.setEditText('')

    def initializePage(self):
        self.new_mn = new_mn = self.parent.new_mn
        unused = self.parent.wallet.get_unused_addresses()

        if not self.o_addr.currentText():
            owner_addr = new_mn.owner_addr
            if owner_addr:
                self.o_addr.setEditText(owner_addr)
            else:
                self.o_addr.setEditText(unused[0])

        if not self.v_addr.currentText():
            voting_addr = new_mn.voting_addr
            if voting_addr:
                self.v_addr.setEditText(voting_addr)
            else:
                self.v_addr.setEditText(unused[0])

        if not self.p_addr.currentText():
            payout_address = new_mn.payout_address
            if payout_address:
                self.p_addr.setEditText(payout_address)
            else:
                self.p_addr.setEditText(unused[1])

    @pyqtSlot()
    def on_change_addr(self):
        self.completeChanged.emit()

    @pyqtSlot()
    def on_change_ignore(self):
        if self.cb_ignore.isChecked():
            self.hw_err.hide()

    def isComplete(self):
        self.hide_error()
        if (self.o_addr.currentText()
                and self.v_addr.currentText()
                and self.p_addr.currentText()):
            return True
        return False

    def hide_error(self):
        self.err_label.hide()
        self.err.hide()

    def validatePage(self):
        o_addr = self.o_addr.currentText()
        v_addr = self.v_addr.currentText()
        p_addr = self.p_addr.currentText()
        ignore_hw_warn = self.cb_ignore.isChecked()
        try:
            self.parent.validate_addresses(o_addr, v_addr, p_addr,
                                           ignore_hw_warn)
        except ValidationError as e:
            self.err.setText(str(e))
            self.err_label.show()
            self.err.show()
            return False
        except HwWarnError as e:
            self.hw_err.setText(str(e))
            self.hw_err.show()
            self.cb_ignore.show()
            return False

        new_mn = self.parent.new_mn
        new_mn.owner_addr = o_addr
        new_mn.voting_addr = v_addr
        new_mn.payout_address = p_addr
        return True

    def nextId(self):
        return self.parent.BLS_KEYS_PAGE


class BlsKeysWizardPage(QWizardPage):

    def __init__(self, parent=None):
        super(BlsKeysWizardPage, self).__init__(parent)
        self.parent = parent
        layout = QGridLayout()

        self.bls_pub_label = QLabel('BLS Public key:')
        self.bls_pub = SLineEdit()
        self.bls_pub.textChanged.connect(self.on_pub_changed)

        self.op_reward_label = QLabel('Operator Reward:')
        self.op_reward = QDoubleSpinBox()
        self.op_reward.setRange(0.0, 100.0)
        self.op_reward.setSingleStep(0.01)
        self.op_reward.setSuffix('%')
        self.op_reward_label.hide()
        self.op_reward.hide()

        self.bls_priv_label = QLabel('BLS Private key:')
        self.bls_priv_label.hide()
        self.bls_priv = SLineEdit()
        self.bls_priv.setReadOnly(True)
        self.bls_priv.hide()
        self.gen_btn = QPushButton('Generate new BLS keypair')
        self.gen_btn.clicked.connect(self.generate_bls_keypair)
        self.gen_btn.hide()
        self.bls_info_label = QLabel()
        self.bls_info_label.setWordWrap(True)
        self.bls_info_label.setObjectName('info-label')
        self.bls_info_label.hide()
        self.bls_info_edit = SLineEdit()
        self.bls_info_edit.setReadOnly(True)
        self.bls_info_edit.hide()

        self.err_label = QLabel('Error:')
        self.err_label.setObjectName('err-label')
        self.err = QLabel()
        self.err.setObjectName('err-label')
        self.err_label.hide()
        self.err.hide()

        layout.addWidget(self.bls_pub_label, 0, 0)
        layout.addWidget(self.bls_pub, 1, 0)

        layout.addWidget(self.op_reward_label, 3, 0)
        layout.addWidget(self.op_reward, 4, 0)
        layout.addWidget(self.bls_priv_label, 3, 0)
        layout.addWidget(self.bls_priv, 4, 0)

        layout.addWidget(self.gen_btn, 6, 0, 1, -1)

        layout.addWidget(self.bls_info_label, 8, 0)
        layout.addWidget(self.bls_info_edit, 9, 0)

        layout.addWidget(self.err_label, 10, 0)
        layout.addWidget(self.err, 10, 1)

        layout.setColumnStretch(0, 1)
        layout.setRowStretch(2, 1)
        layout.setRowStretch(5, 1)
        layout.setRowStretch(7, 1)
        self.setLayout(layout)

    def hide_error(self):
        self.err_label.hide()
        self.err.hide()

    def show_error(self, err):
        self.err.setText(err)
        self.err_label.show()
        self.err.show()

    def initializePage(self):
        parent = self.parent
        new_mn = parent.new_mn
        start_id = parent.startId()
        self.op_reward_label.hide()
        self.op_reward.hide()
        if not new_mn.is_operated:
            self.bls_priv_label.hide()
            self.bls_priv.hide()
            self.gen_btn.hide()
            self.bls_info_label.hide()
            self.bls_info_edit.hide()
            self.bls_pub.setReadOnly(False)
            if self.bls_priv.text():
                self.bls_pub.setText('')
                self.bls_priv.setText('')
            if start_id in parent.UPD_ENTER_PAGES:
                if not self.bls_pub.text():
                    self.bls_pub.setText(new_mn.pubkey_operator)
                self.setTitle('Operator BLS key setup')
                self.setSubTitle('Update operator BLS public key')
            else:
                self.op_reward_label.show()
                self.op_reward.show()
                self.setTitle('Operator BLS key and reward')
                self.setSubTitle('Enter operator BLS public key and '
                                 'operator reward percent')
            return

        self.setTitle('BLS keys setup')
        if start_id in parent.UPD_ENTER_PAGES:
            self.setSubTitle('Regenerate BLS keypair, setup axed')
            if not self.bls_priv.text():
                self.bls_priv.setText(new_mn.bls_privk)
                self.bls_pub.setText(new_mn.pubkey_operator)
        else:
            self.setSubTitle('Generate BLS keypair, setup axed')

        if not self.bls_priv.text():
            self.generate_bls_keypair()

        self.bls_pub.setReadOnly(True)
        self.bls_priv_label.show()
        self.bls_priv.show()
        self.gen_btn.show()

    def generate_bls_keypair(self):
        random_seed = bytes(os.urandom(32))
        bls_privk = bls.PrivateKey.from_seed(random_seed)
        bls_pubk = bls_privk.get_public_key()
        bls_privk_hex = bh2u(bls_privk.serialize())
        bls_pubk_hex = bh2u(bls_pubk.serialize())
        self.bls_info_label.setText('BLS keypair generated. Before '
                                    'registering new Masternode copy next '
                                    'line to ~/.axecore/axed.conf and '
                                    'restart masternode:')
        self.bls_info_label.show()
        self.bls_info_edit.setText('masternodeblsprivkey=%s' % bls_privk_hex)
        self.bls_info_edit.show()
        self.bls_pub.setText(bls_pubk_hex)
        self.bls_priv.setText(bls_privk_hex)

    @pyqtSlot()
    def on_pub_changed(self):
        self.hide_error()

    def validatePage(self):
        new_mn = self.parent.new_mn
        bls_pub = self.bls_pub.text()
        bls_priv = self.bls_priv.text()

        if not new_mn.is_operated:
            if len(bls_pub) == 0:  # allow set later
                return True

            if len(bls_pub) != 96:
                self.show_error('Wrong lenght of BLS public key')
                return False
            if bls_pub.strip('01234567890abcdefABCDEF'):
                self.show_error('Wrong format of BLS public key')
                return False
            try:
                bls.PublicKey.from_bytes(bfh(bls_pub))
            except BaseException as e:
                self.show_error(str(e))
                return False

            op_reward = self.op_reward.value()
            if op_reward > 0.0:
                new_mn.op_reward = round(op_reward * 100)
            new_mn.bls_privk = ''
            new_mn.pubkey_operator = bls_pub
            return True

        new_mn.bls_privk = bls_priv
        new_mn.pubkey_operator = bls_pub
        return True

    def nextId(self):
        return self.parent.SAVE_DIP3_PAGE


class SaveDip3WizardPage(QWizardPage):

    def __init__(self, parent=None):
        super(SaveDip3WizardPage, self).__init__(parent)
        self.parent = parent
        self.setCommitPage(True)
        self.new_mn = None
        self.layout = QGridLayout()

        self.alias = SLineEdit()
        self.alias.textChanged.connect(self.on_alias_changed)
        self.err_label = QLabel('Error:')
        self.err_label.setObjectName('err-label')
        self.err = QLabel()
        self.err.setObjectName('err-label')
        self.err_label.hide()
        self.err.hide()
        ownership_label = QLabel('Ownership:')
        self.ownership = QLabel()
        type_label = QLabel('Type:')
        self.type = QLabel()
        mode_label = QLabel('Mode:')
        self.mode = QLabel()
        collateral_label = QLabel('Collateral:')
        self.collateral = QLabel()
        service_label = QLabel('Service:')
        self.service = QLabel()
        owner_addr_label = QLabel('Owner Address:')
        self.owner_addr = QLabel()
        pubkey_op_label = QLabel('PubKeyOperator:')
        self.pubkey_op = QLabel()
        voting_addr_label = QLabel('Voting Address:')
        self.voting_addr = QLabel()

        self.payout_address_label = QLabel('Payout Address:')
        self.payout_address_label.hide()
        self.payout_address = QLabel()
        self.payout_address.hide()

        self.op_reward_label = QLabel('Operator Reward percent:')
        self.op_reward_label.hide()
        self.op_reward = QLabel()
        self.op_reward.hide()

        self.op_payout_address_label = QLabel('Operator Payout Address:')
        self.op_payout_address_label.hide()
        self.op_payout_address = QLabel()
        self.op_payout_address.hide()

        self.cb_make_tx = QCheckBox()
        self.cb_make_tx.setChecked(True)

        self.layout.addWidget(self.alias, 0, 0, 1, 2)
        self.layout.addWidget(self.err_label, 1, 0)
        self.layout.addWidget(self.err, 1, 1)

        self.layout.addWidget(ownership_label, 2, 0)
        self.layout.addWidget(self.ownership, 2, 1)
        self.layout.addWidget(type_label, 3, 0)
        self.layout.addWidget(self.type, 3, 1)
        self.layout.addWidget(mode_label, 4, 0)
        self.layout.addWidget(self.mode, 4, 1)
        self.layout.addWidget(collateral_label, 5, 0)
        self.layout.addWidget(self.collateral, 5, 1)
        self.layout.addWidget(service_label, 6, 0)
        self.layout.addWidget(self.service, 6, 1)

        self.layout.addWidget(owner_addr_label, 7, 0)
        self.layout.addWidget(self.owner_addr, 7, 1)
        self.layout.addWidget(pubkey_op_label, 8, 0)
        self.layout.addWidget(self.pubkey_op, 8, 1)
        self.layout.addWidget(voting_addr_label, 9, 0)
        self.layout.addWidget(self.voting_addr, 9, 1)

        self.layout.addWidget(self.payout_address_label, 10, 0)
        self.layout.addWidget(self.payout_address, 10, 1)

        self.layout.addWidget(self.op_reward_label, 11, 0)
        self.layout.addWidget(self.op_reward, 11, 1)

        self.layout.addWidget(self.op_payout_address_label, 12, 0)
        self.layout.addWidget(self.op_payout_address, 12, 1)

        self.layout.setColumnStretch(1, 1)
        self.layout.setRowStretch(13, 1)
        self.layout.addWidget(self.cb_make_tx, 14, 1, Qt.AlignRight)
        self.setLayout(self.layout)

    def initializePage(self):
        self.new_mn = new_mn = self.parent.new_mn

        self.ownership.setText('')
        self.collateral.setText('')
        self.service.setText('')
        self.owner_addr.setText('')
        self.pubkey_op.setText('')
        self.voting_addr.setText('')
        self.payout_address.setText('')
        self.payout_address.hide()
        self.payout_address_label.hide()
        self.op_reward.setText('')
        self.op_reward.hide()
        self.op_reward_label.hide()
        self.op_payout_address.setText('')
        self.op_payout_address.hide()
        self.op_payout_address_label.hide()

        if not self.alias.text():
            self.alias.setText(new_mn.alias)

        if new_mn.is_owned and new_mn.is_operated:
            ownership = 'This wallet is owns and operates on new Masternode'
        elif new_mn.is_owned:
            ownership = ('This wallet is owns on new Masternode '
                         '(external operator)')
        elif new_mn.is_operated:
            ownership = ('This wallet is operates on new Masternode')
        else:
            ownership = 'None'
        self.ownership.setText(ownership)

        self.type.setText(str(new_mn.type))
        self.mode.setText(str(new_mn.mode))
        collateral = str(new_mn.collateral)
        self.collateral.setText(collateral)
        self.service.setText(str(new_mn.service))

        self.owner_addr.setText(new_mn.owner_addr)
        self.pubkey_op.setText(new_mn.pubkey_operator)
        self.voting_addr.setText(new_mn.voting_addr)

        if new_mn.payout_address:
            self.payout_address.setText(new_mn.payout_address)
            self.payout_address.show()
            self.payout_address_label.show()

        if new_mn.op_reward:
            self.op_reward.setText('%s%%' % (new_mn.op_reward/100))
            self.op_reward.show()
            self.op_reward_label.show()

        if new_mn.op_payout_address:
            self.op_payout_address.setText(new_mn.op_payout_address)
            self.op_payout_address.show()
            self.op_payout_address_label.show()

        parent = self.parent
        start_id = parent.startId()
        if start_id == parent.OPERATION_TYPE_PAGE:
            tx_name = 'ProRegTx'
            op_type = 'save'
        elif start_id == parent.UPD_SRV_PAGE:
            tx_name = 'ProUpServTx'
            op_type = 'update'
        elif start_id == parent.UPD_REG_PAGE:
            tx_name = 'ProUpRegTx'
            op_type = 'update'
        elif start_id == parent.COLLATERAL_PAGE:
            tx_name = 'UnknownTx'
            op_type = 'save'
        elif start_id == parent.SERVICE_PAGE:
            tx_name = 'UnknownTx'
            op_type = 'save'
        else:
            tx_name = 'Unknown'
            op_type = 'unknown'

        self.setTitle('%s DIP3 masternode' % op_type.capitalize())
        self.setSubTitle('Examine parameters and %s Masternode.' % op_type)
        tx_cb_label_text = 'Make %s after saving Masternode data' % tx_name
        self.cb_make_tx.setText(tx_cb_label_text)
        if start_id == parent.OPERATION_TYPE_PAGE:
            self.parent.setButtonText(QWizard.CommitButton,
                                      op_type.capitalize())
        else:
            self.cb_make_tx.hide()
            self.alias.setReadOnly(True)
            if start_id in [parent.UPD_SRV_PAGE, parent.UPD_REG_PAGE]:
                self.parent.setButtonText(QWizard.CommitButton,
                                          'Prepare %s' % tx_name)
            else:
                self.cb_make_tx.setCheckState(Qt.Unchecked)
                self.parent.setButtonText(QWizard.CommitButton,
                                          op_type.capitalize())

    @pyqtSlot()
    def on_alias_changed(self):
        self.completeChanged.emit()

    def isComplete(self):
        if self.new_mn is not None and self.alias.text():
            return True
        return False

    def validatePage(self):
        parent = self.parent
        start_id = parent.startId()
        alias = self.alias.text()
        if start_id == parent.OPERATION_TYPE_PAGE:
            try:
                parent.validate_alias(self.alias.text())
            except ValidationError as e:
                self.err.setText(str(e))
                self.err_label.show()
                self.err.show()
                return False
        self.new_mn.alias = alias

        dip3_tab = parent.parent()
        if start_id == parent.OPERATION_TYPE_PAGE:
            parent.manager.add_mn(self.new_mn)
            dip3_tab.w_model.reload_data()
            parent.saved_mn = alias
        elif start_id in [parent.COLLATERAL_PAGE, parent.SERVICE_PAGE]:
            parent.manager.update_mn(alias, self.new_mn)
            dip3_tab.w_model.reload_alias(alias)
            parent.saved_mn = alias
        if self.cb_make_tx.isChecked():
            manager = parent.manager
            gui = parent.gui
            try:
                if start_id == parent.OPERATION_TYPE_PAGE:
                    pro_tx = manager.prepare_pro_reg_tx(alias)
                    tx_descr = 'ProRegTx'
                    tx_type = axe_tx.SPEC_PRO_REG_TX
                elif start_id == parent.UPD_SRV_PAGE:
                    pro_tx = manager.prepare_pro_up_srv_tx(self.new_mn)
                    tx_descr = 'ProUpServTx'
                    tx_type = axe_tx.SPEC_PRO_UP_SERV_TX
                elif start_id == parent.UPD_REG_PAGE:
                    pro_tx = manager.prepare_pro_up_reg_tx(self.new_mn)
                    tx_descr = 'ProUpRegTx'
                    tx_type = axe_tx.SPEC_PRO_UP_REG_TX
            except ProRegTxExc as e:
                gui.show_error(e)
                return True
            gui.payto_e.setText(manager.wallet.get_unused_address())
            gui.extra_payload.set_extra_data(tx_type, pro_tx)
            gui.show_extra_payload()
            gui.tabs.setCurrentIndex(gui.tabs.indexOf(gui.send_tab))
            parent.pro_tx_prepared = tx_descr
        return True

    def nextId(self):
        return self.parent.DONE_PAGE


class DoneWizardPage(QWizardPage):

    def __init__(self, parent=None):
        super(DoneWizardPage, self).__init__(parent)
        self.parent = parent
        self.setTitle('All done')
        self.setSubTitle('All operations completed successfully.')

        self.layout = QVBoxLayout()
        self.setLayout(self.layout)

    def nextId(self):
        return -1

    def initializePage(self):
        parent = self.parent
        start_id = parent.startId()
        if parent.saved_mn:
            if start_id == parent.OPERATION_TYPE_PAGE:
                operation = 'Created'
            else:
                operation = 'Updated'
            new_label_text = ('%s Masternode with alias: %s.' %
                              (operation, parent.saved_mn))
            new_mn_label = QLabel(new_label_text)
            self.layout.addWidget(new_mn_label)
        if parent.pro_tx_prepared:
            new_tx_label = QLabel('Prepared %s transaction to send.' %
                                  parent.pro_tx_prepared)
            self.layout.addWidget(new_tx_label)
        self.layout.addStretch(1)


class CollateralWizardPage(QWizardPage):

    def __init__(self, parent=None):
        super(CollateralWizardPage, self).__init__(parent)
        self.parent = parent
        self.legacy = parent.gui.masternode_manager
        self.setTitle('Select Collateral')
        self.setSubTitle('Select collateral output for Masternode.')

        self.frozen_cb = QCheckBox('Include frozen addresses')
        self.frozen_cb.setChecked(False)
        self.frozen_cb.stateChanged.connect(self.frozen_state_changed)
        self.not_found = QLabel('No 1000 AXE outputs were found.')
        self.not_found.setObjectName('err-label')
        self.not_found.hide()

        self.outputs_list = OutputsList()
        self.outputs_list.outputSelected.connect(self.on_set_output)

        self.hash_label = QLabel('Transaction hash:')
        self.hash = SLineEdit()
        self.hash.setReadOnly(True)
        self.index_label = QLabel('Output index:')
        self.index = SLineEdit()
        self.index.setReadOnly(True)
        self.addr_label = QLabel('Output address:')
        self.addr = SLineEdit()
        self.addr.setReadOnly(True)
        self.value = SLineEdit()
        self.value.setReadOnly(True)
        self.value.hide()
        self.err_label = QLabel('Error:')
        self.err_label.setObjectName('err-label')
        self.err = QLabel()
        self.err.setObjectName('err-label')
        self.err_label.hide()
        self.err.hide()

        self.layout = QGridLayout()
        self.layout.addWidget(self.frozen_cb, 0, 0)
        self.layout.addWidget(self.not_found, 0, 1, Qt.AlignRight)
        self.layout.addWidget(self.outputs_list, 1, 0, 1, -1)
        self.layout.addWidget(self.hash_label, 2, 0)
        self.layout.addWidget(self.hash, 2, 1)
        self.layout.addWidget(self.index_label, 3, 0)
        self.layout.addWidget(self.index, 3, 1)
        self.layout.addWidget(self.addr_label, 4, 0)
        self.layout.addWidget(self.addr, 4, 1)
        self.layout.addWidget(self.err_label, 5, 0)
        self.layout.addWidget(self.err, 5, 1)
        self.layout.addWidget(self.value, 6, 1)

        self.layout.setColumnStretch(1, 1)
        self.layout.setRowStretch(6, 1)
        self.setLayout(self.layout)

    def hide_error(self):
        self.err_label.hide()
        self.err.hide()

    def show_error(self, err):
        self.err.setText(err)
        self.err_label.show()
        self.err.show()

    @pyqtSlot()
    def frozen_state_changed(self):
        self.hide_error()
        self.not_found.hide()
        new_mn = self.parent.new_mn
        self.scan_for_outputs()
        if new_mn.collateral.hash and new_mn.collateral.index >= 0:
            if not self.select_collateral(new_mn.collateral):
                self.hash.setText(bh2u(new_mn.collateral.hash[::-1]))
                self.index.setText(str(new_mn.collateral.index))

    def scan_for_outputs(self):
        self.outputs_list.clear()
        wallet = self.parent.wallet
        if self.frozen_cb.isChecked():
            excluded = None
        else:
            excluded = wallet.frozen_addresses
        coins = wallet.get_utxos(domain=None, excluded=excluded,
                                 mature=True, confirmed_only=True)
        coins = list(filter(lambda x: (x['value'] == (1000 * COIN)), coins))

        if len(coins) > 0:
            self.outputs_list.add_outputs(coins)
        else:
            self.not_found.show()

    def select_collateral(self, c):
        if not c.hash or c.index < 0:
            return
        match = self.outputs_list.findItems(str(c), Qt.MatchExactly)
        if len(match):
            self.outputs_list.setCurrentItem(match[0])
            return True
        return False

    def on_set_output(self, vin):
        self.hide_error()
        self.hash.setText(vin.get('prevout_hash', ''))
        self.index.setText(str(vin.get('prevout_n', '')))
        self.addr.setText(vin.get('address', ''))
        self.value.setText(str(vin.get('value', '')))
        self.completeChanged.emit()

    def initializePage(self):
        new_mn = self.parent.new_mn
        self.scan_for_outputs()
        if new_mn.collateral.hash and new_mn.collateral.index >= 0:
            if not self.select_collateral(new_mn.collateral):
                self.hash.setText(bh2u(new_mn.collateral.hash[::-1]))
                self.index.setText(str(new_mn.collateral.index))

    def isComplete(self):
        return len(self.hash.text()) == 64

    def validatePage(self):
        parent = self.parent
        new_mn = parent.new_mn
        start_id = parent.startId()
        if start_id in parent.UPD_ENTER_PAGES:
            skip_alias = new_mn.alias
        else:
            skip_alias = None
        try:
            c_hash = self.hash.text()
            c_index = int(self.index.text())
            c_addr = self.addr.text()
            value = self.value.text()
            c_value = int(value if value else 0)
            collateral = '%s:%s' % (c_hash, c_index)
            parent.validate_collateral(collateral, c_addr, c_value,
                                       skip_alias=skip_alias)
        except ValidationError as e:
            self.show_error(str(e))
            return False

        new_mn.collateral = TxOutPoint(bfh(c_hash)[::-1], c_index)
        new_mn.protx_hash = ''  # reset hash for removed masternodes
        parent.collateral_addr = c_addr
        return True

    def nextId(self):
        return self.parent.SERVICE_PAGE


class ServiceWizardPage(QWizardPage):

    def __init__(self, parent=None):
        super(ServiceWizardPage, self).__init__(parent)
        self.parent = parent
        self.cur_service = None
        self.setTitle('Service params')
        self.setSubTitle('Select masternode IP address and port.')

        layout = QGridLayout()

        self.srv_addr_label = QLabel('Masternode Service Address:')
        self.srv_addr = SLineEdit()
        self.srv_addr.textChanged.connect(self.on_service_changed)
        self.srv_port_label = QLabel('Masternode Service Port:')
        self.srv_port = SLineEdit()
        self.srv_port.textChanged.connect(self.on_service_changed)

        self.err_label = QLabel('Error:')
        self.err_label.setObjectName('err-label')
        self.err = QLabel()
        self.err.setObjectName('err-label')
        self.err_label.hide()
        self.err.hide()

        layout.addWidget(self.srv_addr_label, 0, 0)
        layout.addWidget(self.srv_addr, 0, 1)
        layout.addWidget(self.srv_port_label, 0, 2)
        layout.addWidget(self.srv_port, 0, 3)

        layout.addWidget(self.err_label, 1, 0)
        layout.addWidget(self.err, 1, 1, 1, -1)
        layout.setColumnStretch(1, 1)
        layout.setRowStretch(2, 1)
        self.setLayout(layout)

    def hide_error(self):
        self.err_label.hide()
        self.err.hide()

    def show_error(self, err):
        self.err.setText(err)
        self.err_label.show()
        self.err.show()

    @pyqtSlot()
    def on_service_changed(self):
        self.completeChanged.emit()

    def isComplete(self):
        self.hide_error()
        if self.srv_addr.text() and self.srv_port.text():
            return True
        return False

    def initializePage(self):
        new_mn = self.parent.new_mn
        str_mn_service = str(new_mn.service)
        if self.cur_service is None or self.cur_service != str_mn_service:
            self.cur_service = str_mn_service
            self.srv_addr.setText(new_mn.service.ip)
            self.srv_port.setText('%d' % new_mn.service.port)

    def validatePage(self):
        try:
            ip = self.srv_addr.text()
            ipaddress.ip_address(ip)
        except ValueError:
            self.show_error('Wrong service address specified')
            return False
        try:
            port = int(self.srv_port.text())
        except ValueError:
            self.show_error('Service port must be integer number')
            return False
        if not 1 <= port <= 65535:
            self.show_error('Service port must be in range 1-65535')
            return False
        self.parent.new_mn.service = ProTxService(ip, port)
        return True

    def nextId(self):
        if self.parent.new_mn.is_owned:
            return self.parent.SELECT_ADDR_PAGE
        else:
            return self.parent.BLS_KEYS_PAGE


class UpdSrvWizardPage(QWizardPage):

    def __init__(self, parent=None):
        super(UpdSrvWizardPage, self).__init__(parent)
        self.parent = parent
        self.setTitle('Update Service Features of Masternode')
        self.setSubTitle('Set Masternode service parameters.')

        layout = QGridLayout()

        self.srv_addr_label = QLabel('Masternode Service Address:')
        self.srv_addr = SLineEdit()
        self.srv_addr.textChanged.connect(self.on_service_changed)
        self.srv_port_label = QLabel('Masternode Service Port:')
        self.srv_port = SLineEdit()
        self.srv_port.textChanged.connect(self.on_service_changed)

        self.op_p_addr_label = QLabel('Operarot Payout Address:')
        self.op_p_addr = SComboBox()
        self.op_p_addr.setEditable(True)
        self.op_p_addr_label.hide()
        self.op_p_addr.hide()

        self.err_label = QLabel('Error:')
        self.err_label.setObjectName('err-label')
        self.err = QLabel()
        self.err.setObjectName('err-label')
        self.err_label.hide()
        self.err.hide()

        layout.addWidget(self.srv_addr_label, 0, 0)
        layout.addWidget(self.srv_addr, 0, 1)
        layout.addWidget(self.srv_port_label, 0, 2)
        layout.addWidget(self.srv_port, 0, 3)
        layout.addWidget(self.op_p_addr_label, 1, 0)
        layout.addWidget(self.op_p_addr, 1, 1, 1, -1)

        layout.addWidget(self.err_label, 2, 0)
        layout.addWidget(self.err, 2, 1, 1, -1)
        layout.setColumnStretch(1, 1)
        layout.setRowStretch(3, 1)
        self.setLayout(layout)

    def nextId(self):
        return self.parent.SAVE_DIP3_PAGE

    def hide_error(self):
        self.err_label.hide()
        self.err.hide()

    def show_error(self, err):
        self.err.setText(err)
        self.err_label.show()
        self.err.show()

    def initializePage(self):
        self.upd_mn = upd_mn = self.parent.new_mn
        if not upd_mn:
            return
        self.srv_addr.setText(upd_mn.service.ip)
        self.srv_port.setText('%d' % upd_mn.service.port)

        if not upd_mn.is_owned and upd_mn.is_operated:
            unused = self.parent.wallet.get_unused_addresses()
            cur_op_p_addr = self.op_p_addr.currentText()
            for addr in unused:
                self.op_p_addr.addItem(addr)
            self.op_p_addr.setEditText(cur_op_p_addr)
            self.op_p_addr_label.show()
            self.op_p_addr.show()
            if not self.op_p_addr.currentText():
                op_payout_address = upd_mn.op_payout_address
                if op_payout_address:
                    self.op_p_addr.setEditText(op_payout_address)
                else:
                    self.op_p_addr.setEditText(unused[0])

    @pyqtSlot()
    def on_service_changed(self):
        self.completeChanged.emit()

    def isComplete(self):
        self.hide_error()
        if self.srv_addr.text() and self.srv_port.text():
            return True
        return False

    def validatePage(self):
        try:
            ip = self.srv_addr.text()
            ipaddress.ip_address(ip)
        except ValueError:
            self.show_error('Wrong service address specified')
            return False
        try:
            port = int(self.srv_port.text())
        except ValueError:
            self.show_error('Service port must be integer number')
            return False
        if not 1 <= port <= 65535:
            self.show_error('Service port must be in range 1-65535')
            return False
        self.upd_mn.service = ProTxService(ip, port)

        if not self.upd_mn.is_owned and self.upd_mn.is_operated:
            op_p_addr = self.op_p_addr.currentText()
            if op_p_addr and not is_b58_address(op_p_addr):
                self.show_error('Wrong operator payout address format')
                return False
            self.upd_mn.op_payout_address = op_p_addr

        return True


class UpdRegWizardPage(QWizardPage):

    def __init__(self, parent=None):
        super(UpdRegWizardPage, self).__init__(parent)
        self.parent = parent
        self.setTitle('Update addresses')
        self.setSubTitle('Update Masternode voting/payout addresses.')

        layout = QGridLayout()
        self.v_addr_label = QLabel('Voting Address (must differ from '
                                   'collateral):')
        self.v_addr = SComboBox()
        self.v_addr.setEditable(True)
        self.v_addr.editTextChanged.connect(self.on_change_addr)
        self.p_addr_label = QLabel('Payout Address (must differ from '
                                   'owner/voting/collateral):')
        self.p_addr = SComboBox()
        self.p_addr.setEditable(True)
        self.p_addr.editTextChanged.connect(self.on_change_addr)
        self.err_label = QLabel('Error:')
        self.err_label.setObjectName('err-label')
        self.err = QLabel()
        self.err.setObjectName('err-label')
        self.err_label.hide()
        self.err.hide()

        layout.addWidget(self.v_addr_label, 0, 0, 1, -1)
        layout.addWidget(self.v_addr, 1, 0, 1, -1)
        layout.addWidget(self.p_addr_label, 3, 0, 1, -1)
        layout.addWidget(self.p_addr, 4, 0, 1, -1)
        layout.setColumnStretch(1, 1)
        layout.setRowStretch(2, 1)
        layout.addWidget(self.err_label, 5, 0)
        layout.addWidget(self.err, 5, 1)
        self.setLayout(layout)

        unused = self.parent.wallet.get_unused_addresses()
        for addr in unused:
            self.v_addr.addItem(addr)
            self.p_addr.addItem(addr)
        self.v_addr.setEditText('')
        self.p_addr.setEditText('')

    def nextId(self):
        return self.parent.BLS_KEYS_PAGE

    def initializePage(self):
        self.upd_mn = upd_mn = self.parent.new_mn
        unused = self.parent.wallet.get_unused_addresses()

        if not self.v_addr.currentText():
            voting_addr = upd_mn.voting_addr
            if voting_addr:
                self.v_addr.setEditText(voting_addr)
            else:
                self.v_addr.setEditText(unused[0])

        if not self.p_addr.currentText():
            payout_address = upd_mn.payout_address
            if payout_address:
                self.p_addr.setEditText(payout_address)
            else:
                self.p_addr.setEditText(unused[1])

    @pyqtSlot()
    def on_change_addr(self):
        self.completeChanged.emit()

    def isComplete(self):
        self.hide_error()
        if (self.v_addr.currentText() and self.p_addr.currentText()):
            return True
        return False

    def show_error(self, err):
        self.err.setText(err)
        self.err_label.show()
        self.err.show()

    def hide_error(self):
        self.err_label.hide()
        self.err.hide()

    def validatePage(self):
        v_addr = self.v_addr.currentText()
        p_addr = self.p_addr.currentText()

        if not v_addr:
            self.show_error('No voting address set')
            return False
        if not is_b58_address(v_addr):
            self.show_error('Wrong voting address format')
            return False
        self.upd_mn.voting_addr = v_addr

        if not p_addr:
            self.show_error('No payout address set')
            return False
        if not is_b58_address(p_addr):
            self.show_error('Wrong payout address format')
            return False
        self.upd_mn.payout_address = p_addr
        return True


class Dip3MasternodeWizard(QWizard):

    OPERATION_TYPE_PAGE = 1
    IMPORT_LEGACY_PAGE = 2
    SERVICE_PAGE = 3
    SELECT_ADDR_PAGE = 4
    BLS_KEYS_PAGE = 5
    SAVE_DIP3_PAGE = 6
    DONE_PAGE = 7

    COLLATERAL_PAGE = 100
    UPD_SRV_PAGE = 101
    UPD_REG_PAGE = 102

    UPD_ENTER_PAGES  = [COLLATERAL_PAGE, SERVICE_PAGE,
                        UPD_SRV_PAGE, UPD_REG_PAGE]

    def __init__(self, parent, mn=None, start_id=None):
        super(Dip3MasternodeWizard, self).__init__(parent)
        self.gui = parent.gui
        self.legacy = parent.gui.masternode_manager
        self.manager = parent.manager
        self.wallet = parent.wallet

        if mn:
            self.new_mn = ProTxMN.from_dict(mn.as_dict())
        else:
            self.new_mn = None
        self.collateral_addr = None
        self.saved_mn = False
        self.pro_tx_prepared = False

        self.setPage(self.OPERATION_TYPE_PAGE, OperationTypeWizardPage(self))
        self.setPage(self.IMPORT_LEGACY_PAGE, ImportLegacyWizardPage(self))
        self.setPage(self.SELECT_ADDR_PAGE, SelectAddressesWizardPage(self))
        self.setPage(self.BLS_KEYS_PAGE, BlsKeysWizardPage(self))
        self.setPage(self.SAVE_DIP3_PAGE, SaveDip3WizardPage(self))
        self.setPage(self.DONE_PAGE, DoneWizardPage(self))
        self.setPage(self.COLLATERAL_PAGE, CollateralWizardPage(self))
        self.setPage(self.SERVICE_PAGE, ServiceWizardPage(self))
        self.setPage(self.UPD_SRV_PAGE, UpdSrvWizardPage(self))
        self.setPage(self.UPD_REG_PAGE, UpdRegWizardPage(self))

        if start_id:
            self.setStartId(start_id)
            title = 'Update DIP3 Masternode'
        else:
            title = 'Add DIP3 Masternode'

        logo = QPixmap(icon_path('tab_dip3.png'))
        logo = logo.scaledToWidth(32, mode=Qt.SmoothTransformation)
        self.setWizardStyle(QWizard.ClassicStyle)
        self.setPixmap(QWizard.LogoPixmap, logo)
        self.setWindowTitle(title)
        self.setWindowIcon(read_QIcon('electrum-axe.png'))
        self.setMinimumSize(1000, 450)

    def validate_alias(self, alias):
        if not alias:
            raise ValidationError('Alias not set')
        if len(alias) > 32:
            raise ValidationError('Masternode alias can not be longer '
                                  'than 32 characters')
        if alias in self.manager.mns.keys():
            raise ValidationError('Masternode with alias %s already exists' %
                                  alias)
        return alias

    def validate_service(self, service):
        if not service:
            raise ValidationError('No service value specified')
        try:
            if ']' in service:          # IPv6 [ipv6]:portnum
                ip, port = service.split(']')
                ip = ip[1:]             # remove opening square bracket
                ipaddress.ip_address(ip)
                port = int(port[1:])    # remove colon before portnum
            else:                       # IPv4 ipv4:portnum
                ip, port = service.split(':')
                ipaddress.ip_address(ip)
                port = int(port)
        except BaseException:
            raise ValidationError('Wrong service format specified')
        return ip, port

    def validate_collateral(self, outpoint, addr, value, skip_alias=None):
        outpoint = outpoint.split(':')
        if len(outpoint) != 2:
            raise ValidationError('Wrong collateral format')
        prevout_hash, prevout_n = outpoint
        prevout_n = int(prevout_n)

        coins = self.wallet.get_utxos(domain=None, excluded=None,
                                      mature=True, confirmed_only=True)

        coins = filter(lambda x: (x['prevout_hash'] == prevout_hash
                                  and x['prevout_n'] == prevout_n),
                       coins)
        coins = list(coins)
        if not coins:
            raise ValidationError('Provided Outpoint not found in the wallet')

        c_vin = coins[0]

        if not value:
            raise ValidationError('No collateral value specified')
        if not addr:
            raise ValidationError('No collateral address specified')
        if not outpoint:
            raise ValidationError('No collateral outpoint specified')

        if not value == 1000 * COIN or not value == c_vin['value']:
            raise ValidationError('Wrong collateral value')


        if prevout_hash:
            if skip_alias:
                mns_collaterals = [(mns.as_dict())['collateral']
                                   for mns in self.manager.mns.values()
                                   if mns.alias != skip_alias]
            else:
                mns_collaterals = [(mns.as_dict())['collateral']
                                   for mns in self.manager.mns.values()]
            mns_collaterals = ['%s:%s' % (c['hash'], c['index'])
                               for c in mns_collaterals]
            coll_str = '%s:%s' % (prevout_hash, prevout_n)
            if coll_str in mns_collaterals:
                raise ValidationError('Provided Outpoint already used '
                                      'in saved DIP3 Masternodes')

        return prevout_hash, prevout_n, addr

    def validate_addresses(self, o_addr, v_addr, p_addr, ignore_hw_warn):
        c_addr = self.collateral_addr

        if c_addr == o_addr or c_addr == v_addr or c_addr == p_addr:
            raise ValidationError('Addresses must differ from collateral '
                                  'address %s' % c_addr)

        if p_addr == o_addr or p_addr == v_addr:
            raise ValidationError('Payout address must differ from owner'
                                  'and voting addresses')

        if not self.wallet.is_mine(o_addr):
            raise ValidationError('Owner address not found in the wallet')
        keystore = self.wallet.keystore
        if not hasattr(keystore, 'sign_digest') and not ignore_hw_warn:
            raise HwWarnError('Warning: sign_digest not implemented in '
                              'hardware wallet keystores. You can not use '
                              'this wallet to sign ProUpRegTx. However you '
                              'can register masternode. But in future it is '
                              'not possible to change voting/payout addresses '
                              'and operator public BLS key')

        if not is_b58_address(v_addr):
            raise ValidationError('Wrong voting address format')
        if not is_b58_address(p_addr):
            raise ValidationError('Wrong payout address format')
        return o_addr, v_addr, p_addr


class Dip3FileWizard(QWizard):

    OP_TYPE_PAGE = 1
    EXPORT_PAGE = 2
    IMPORT_PAGE = 3
    DONE_PAGE = 4

    def __init__(self, parent, mn=None, start_id=None):
        super(Dip3FileWizard, self).__init__(parent)
        self.gui = parent.gui
        self.manager = parent.manager
        self.wallet = parent.wallet

        self.setPage(self.OP_TYPE_PAGE, FileOpTypeWizardPage(self))
        self.setPage(self.EXPORT_PAGE, ExportToFileWizardPage(self))
        self.setPage(self.IMPORT_PAGE, ImportFromFileWizardPage(self))
        self.setPage(self.DONE_PAGE, FileDoneWizardPage(self))
        self.saved_aliases = []
        self.saved_path = None
        self.imported_aliases = []
        self.skipped_aliases = []
        self.imported_path = None

        title = 'Export/Import DIP3 Masternodes to/from file'
        logo = QPixmap(icon_path('tab_dip3.png'))
        logo = logo.scaledToWidth(32, mode=Qt.SmoothTransformation)
        self.setWizardStyle(QWizard.ClassicStyle)
        self.setPixmap(QWizard.LogoPixmap, logo)
        self.setWindowTitle(title)
        self.setWindowIcon(read_QIcon('electrum-axe.png'))
        self.setMinimumSize(1000, 450)


class FileOpTypeWizardPage(QWizardPage):

    def __init__(self, parent=None):
        super(FileOpTypeWizardPage, self).__init__(parent)
        self.parent = parent
        self.setTitle('Operation type')
        self.setSubTitle('Select opeartion type.')

        self.rb_export = QRadioButton('Export DIP3 Masternodes to file')
        self.rb_import = QRadioButton('Import DIP3 Masternodes from file')
        self.rb_export.setChecked(True)
        self.button_group = QButtonGroup()
        self.button_group.addButton(self.rb_export)
        self.button_group.addButton(self.rb_import)
        gb_vbox = QVBoxLayout()
        gb_vbox.addWidget(self.rb_export)
        gb_vbox.addWidget(self.rb_import)
        self.gb_op_type = QGroupBox('Select operation type')
        self.gb_op_type.setLayout(gb_vbox)

        layout = QVBoxLayout()
        layout.addWidget(self.gb_op_type)
        layout.addStretch(1)
        self.setLayout(layout)

    def nextId(self):
        if self.rb_export.isChecked():
            return self.parent.EXPORT_PAGE
        else:
            return self.parent.IMPORT_PAGE


class ExportToFileWizardPage(QWizardPage):

    def __init__(self, parent=None):
        super(ExportToFileWizardPage, self).__init__(parent)
        self.parent = parent
        self.setCommitPage(True)
        self.setTitle('Export to file')
        self.setSubTitle('Export DIP3 Masternodes to file.')

        self.lb_aliases = QLabel('Exported DIP3 Masternodes:')
        self.lw_aliases = QListWidget()
        self.lw_aliases.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.sel_model = self.lw_aliases.selectionModel()
        self.sel_model.selectionChanged.connect(self.on_selection_changed)
        aliases = self.parent.manager.mns.keys()
        self.lw_aliases.addItems(aliases)
        self.lw_aliases.selectAll()

        layout = QVBoxLayout()
        layout.addWidget(self.lb_aliases)
        layout.addWidget(self.lw_aliases)
        self.setLayout(layout)

    def initializePage(self):
        self.parent.setButtonText(QWizard.CommitButton, 'Save')

    @pyqtSlot()
    def on_selection_changed(self):
        self.aliases = [i.text() for i in self.lw_aliases.selectedItems()]
        self.completeChanged.emit()

    def isComplete(self):
        return len(self.aliases) > 0

    def nextId(self):
        return self.parent.DONE_PAGE

    def validatePage(self):
        fdlg = QFileDialog(self, 'Save DIP3 Masternodes', os.getenv('HOME'))
        fdlg.setOptions(QFileDialog.DontConfirmOverwrite)
        fdlg.setAcceptMode(QFileDialog.AcceptSave)
        fdlg.setFileMode(QFileDialog.AnyFile)
        fdlg.setNameFilter("ProTx (*.protx)");
        fdlg.exec()

        if not fdlg.result():
            return False

        self.path = fdlg.selectedFiles()
        if len(self.path) > 0:
            self.path = self.path[0]

        if self.path.find('*') > 0 or self.path.find('?') > 0:
            return False

        fi = QFileInfo(self.path)
        if fi.suffix() != 'protx':
            self.path = '%s.protx' % self.path
            fi = QFileInfo(self.path)

        if fi.exists():
            overwrite_msg = 'Overwrite existing file?\n%s'
            res = self.parent.gui.question(overwrite_msg % self.path)
            if not res:
                return False

        manager = self.parent.manager
        store_data = {'mns': {}}
        with open(self.path, 'w') as fd:
            for alias, mn in manager.mns.items():
                if alias not in self.aliases:
                    continue
                store_data['mns'][alias] = mn.as_dict()
            fd.write(json.dumps(store_data, indent=4))
        self.parent.saved_aliases = self.aliases
        self.parent.saved_path = self.path
        return True


class ImportFromFileWizardPage(QWizardPage):

    def __init__(self, parent=None):
        super(ImportFromFileWizardPage, self).__init__(parent)
        self.parent = parent
        self.setCommitPage(True)
        self.setTitle('Import from file')
        self.setSubTitle('Import DIP3 Masternodes from file.')

        self.imp_btn = QPushButton('Load *.protx file')
        self.imp_btn.clicked.connect(self.on_load_protx)
        owerwrite_msg = 'Overwrite existing Masternodes with same aliases'
        self.cb_overwrite = QCheckBox(owerwrite_msg)

        self.lw_i_label = QLabel('Imported aliases')
        self.lw_i_aliases = QListWidget()
        self.lw_i_aliases.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.i_sel_model = self.lw_i_aliases.selectionModel()
        self.i_sel_model.selectionChanged.connect(self.on_i_selection_changed)
        self.i_aliases = []

        self.lw_w_label = QLabel('Existing aliases')
        self.lw_w_aliases = QListWidget()
        self.lw_w_aliases.setSelectionMode(QAbstractItemView.NoSelection)
        aliases = self.parent.manager.mns.keys()
        self.lw_w_aliases.addItems(aliases)

        layout = QGridLayout()
        layout.addWidget(self.imp_btn, 0, 0)
        layout.addWidget(self.cb_overwrite, 0, 2)
        layout.addWidget(self.lw_i_label, 1, 0)
        layout.addWidget(self.lw_w_label, 1, 2)
        layout.addWidget(self.lw_i_aliases, 2, 0)
        layout.addWidget(self.lw_w_aliases, 2, 2)
        layout.setColumnStretch(0, 5)
        layout.setColumnStretch(1, 1)
        layout.setColumnStretch(2, 5)
        self.setLayout(layout)

    def initializePage(self):
        self.parent.setButtonText(QWizard.CommitButton, 'Import')

    def nextId(self):
        return self.parent.DONE_PAGE

    @pyqtSlot()
    def on_load_protx(self):
        fdlg = QFileDialog(self, 'Load DIP3 Masternodes', os.getenv('HOME'))
        fdlg.setAcceptMode(QFileDialog.AcceptOpen)
        fdlg.setFileMode(QFileDialog.AnyFile)
        fdlg.setNameFilter("ProTx (*.protx)");
        fdlg.exec()

        if not fdlg.result():
            return False

        self.path = fdlg.selectedFiles()
        if len(self.path) > 0:
            self.path = self.path[0]

        self.lw_i_aliases.clear()
        with open(self.path, 'r') as fd:
            try:
                import_data = json.loads(fd.read())
                import_data = import_data.get('mns', None)
                if import_data is None:
                    raise Exception('No mns key found in protx file')
                if not isinstance(import_data, dict):
                    raise Exception('Wrong mns key format')
                aliases = import_data.keys()
                self.lw_i_aliases.addItems(aliases)
                self.lw_i_aliases.selectAll()
                self.import_data = import_data
            except Exception as e:
                self.parent.gui.show_error('Wrong file format: %s' % str(e))

    @pyqtSlot()
    def on_i_selection_changed(self):
        self.i_aliases = [i.text() for i in self.lw_i_aliases.selectedItems()]
        self.completeChanged.emit()

    def isComplete(self):
        return len(self.i_aliases) > 0

    def validatePage(self):
        overwrite = self.cb_overwrite.isChecked()
        manager = self.parent.manager
        aliases = manager.mns.keys()
        for ia in self.i_aliases:
            mn = ProTxMN.from_dict(self.import_data[ia])
            if ia in aliases:
                if overwrite:
                    manager.update_mn(ia, mn)
                    self.parent.imported_aliases.append(ia)
                else:
                    self.parent.skipped_aliases.append(ia)
                    continue
            else:
                self.parent.manager.add_mn(mn)
                self.parent.imported_aliases.append(ia)
        if len(self.parent.imported_aliases) > 0:
            dip3_tab = self.parent.parent()
            dip3_tab.w_model.reload_data()
        self.parent.imported_path = self.path
        return True

class FileDoneWizardPage(QWizardPage):

    def __init__(self, parent=None):
        super(FileDoneWizardPage, self).__init__(parent)
        self.parent = parent
        self.setTitle('All done')
        self.setSubTitle('All operations completed successfully.')

        self.layout = QVBoxLayout()
        self.setLayout(self.layout)

    def nextId(self):
        return -1

    def initializePage(self):
        parent = self.parent
        if parent.saved_path:
            aliases = ', '.join(parent.saved_aliases)
            path = parent.saved_path
            self.layout.addWidget(QLabel('Aliases: %s' % aliases))
            self.layout.addWidget(QLabel('Saved to file: %s' % path))
        elif parent.imported_path:
            aliases = ', '.join(parent.imported_aliases)
            skipped = ', '.join(parent.skipped_aliases)
            path = parent.imported_path
            self.layout.addWidget(QLabel('Imported from file: %s' % path))
            if aliases:
                self.layout.addWidget(QLabel('Impored Aliases: %s' % aliases))
            if skipped:
                self.layout.addWidget(QLabel('Skipped Aliases: %s' % skipped))
        self.layout.addStretch(1)
