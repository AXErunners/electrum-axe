# -*- coding: utf-8 -*-

import time

from PyQt5.QtCore import Qt, QTimer, pyqtSlot
from PyQt5.QtGui import QColor, QPainter, QTextCursor, QIcon, QPixmap
from PyQt5.QtWidgets import (QPlainTextEdit, QCheckBox, QSpinBox, QVBoxLayout,
                             QPushButton, QLabel, QDialog, QGridLayout,
                             QTabWidget, QWidget, QProgressBar, QHBoxLayout,
                             QMessageBox, QStyle, QStyleOptionSpinBox, QAction,
                             QApplication, QWizardPage, QWizard, QRadioButton,
                             QButtonGroup, QGroupBox, QLineEdit)

from electrum_axe import mnemonic
from electrum_axe.axe_ps import filter_log_line, PSLogSubCat, PSStates
from electrum_axe.i18n import _
from electrum_axe.util import InvalidPassword

from .installwizard import MSG_ENTER_PASSWORD
from .util import (HelpLabel, MessageBoxMixin, read_QIcon, custom_message_box,
                   ColorScheme, icon_path, WindowModalDialog, CloseButton,
                   Buttons, CancelButton, OkButton)
from .password_dialog import PasswordLayout, PW_NEW, PW_CHANGE
from .transaction_dialog import show_transaction
from .qrtextedit import ShowQRTextEdit
from .seed_dialog import SeedLayout


ps_dialogs = []  # Otherwise python randomly garbage collects the dialogs


def protected_with_parent(func):
    def request_password(self, *args, **kwargs):
        mwin = kwargs.pop('mwin')
        parent = kwargs.get('parent')
        password = None
        while mwin.wallet.has_keystore_encryption():
            password = mwin.password_dialog(parent=parent)
            if password is None:
                # User cancelled password input
                return
            try:
                mwin.wallet.check_password(password)
                break
            except Exception as e:
                mwin.show_error(str(e), parent=parent)
                continue
        if password is None:
            psman = mwin.wallet.psman
            if not psman.is_hw_ks:
                return func(self, *args, **kwargs)
            while psman.is_ps_ks_encrypted():
                password = mwin.password_dialog(parent=parent)
                if password is None:
                    # User cancelled password input
                    return
                try:
                    psman.ps_keystore.check_password(password)
                    break
                except Exception as e:
                    mwin.show_error(str(e), parent=parent)
                    continue
        kwargs['password'] = password
        return func(self, *args, **kwargs)
    return request_password


class FilteredPlainTextEdit(QPlainTextEdit):

    def contextMenuEvent(self, event):
        f_copy = QAction(_('Copy filtered'), self)
        f_copy.triggered.connect(lambda checked: self.copy_filtered())
        f_copy.setEnabled(self.textCursor().hasSelection())

        copy_icon = QIcon.fromTheme('edit-copy')
        if copy_icon:
            f_copy.setIcon(copy_icon)

        menu = self.createStandardContextMenu(event.pos())
        menu.insertAction(menu.actions()[0], f_copy)
        menu.exec_(event.globalPos())

    def copy_filtered(self):
        cursor = self.textCursor()
        if not cursor.hasSelection():
            return

        all_lines = self.toPlainText().splitlines()
        sel_beg = cursor.selectionStart()
        sel_end = cursor.selectionEnd()
        l_beg = 0
        result_lines = []
        for i in range(len(all_lines)):
            cur_line = all_lines[i]
            cur_len = len(cur_line)
            l_end = l_beg + cur_len

            if l_end > sel_beg and l_beg < sel_end:
                filtered_line = filter_log_line(cur_line)
                l_sel_start = None if sel_beg <= l_beg else sel_beg - l_beg
                l_sel_end = None if sel_end >= l_end else sel_end - l_beg
                clipped_line = filtered_line[l_sel_start:l_sel_end]
                result_lines.append(clipped_line)

            l_beg += (cur_len + 1)
            if l_beg > sel_end:
                break
        QApplication.clipboard().setText('\n'.join(result_lines))


class AxeSpinBox(QSpinBox):

    def paintEvent(self, event):
        super(AxeSpinBox, self).paintEvent(event)
        styled_element = QStyle.SE_LineEditContents
        panel = QStyleOptionSpinBox()
        self.initStyleOption(panel)
        textRect = self.style().subElementRect(styled_element, panel, self)
        textRect.adjust(2, 0, -30, 0)
        painter = QPainter(self)
        painter.setPen(QColor(ColorScheme.DEFAULT.as_color()))
        painter.drawText(textRect, Qt.AlignRight | Qt.AlignVCenter, 'Axe')


def find_ps_dialog(mwin):
    for d in ps_dialogs:
        if d.wallet == mwin.wallet:
            return d


def show_ps_dialog(mwin, d=None):
    if not d:
        d = find_ps_dialog(mwin)
    if d:
        d.raise_()
        d.activateWindow()
    else:
        if mwin.wallet.psman.unsupported:
            d = PSDialogUnsupportedPS(mwin)
        else:
            d = PSDialog(mwin)
        d.show()
        ps_dialogs.append(d)


def show_ps_dialog_or_wizard(mwin):
    w = mwin.wallet
    psman = w.psman
    if (psman.w_type == 'standard' and psman.is_hw_ks
            and 'ps_keystore' not in w.db.data):
        wiz = PSKeystoreWizard(mwin)
        wiz.open()
    else:
        show_ps_dialog(mwin)


def hide_ps_dialog(mwin):
    for d in ps_dialogs:
        if d.wallet == mwin.wallet:
            d.close()


class WarnLabel(HelpLabel):

    def __init__(self, text, help_text, cb_text, get_cb_value, cb_callback):
        super(WarnLabel, self).__init__(text, help_text)
        self.get_cb_value = get_cb_value
        self.cb_callback = cb_callback
        self.cb_text = cb_text

    def mouseReleaseEvent(self, x):
        self.show_warn()

    def show_warn(self):
        cb = QCheckBox(self.cb_text)
        cb.setChecked(self.get_cb_value())
        cb.stateChanged.connect(self.cb_callback)
        text = f'{self.help_text}\n\n'
        custom_message_box(icon=QMessageBox.Warning, parent=self,
                           title=_('Warning'), text=text, checkbox=cb)


class ShowPSKsSeedDlg(WindowModalDialog):

    def __init__(self, parent, seed, passphrase):
        WindowModalDialog.__init__(self, parent, ('Axe Electrum - %s %s' %
                                                  (_('PS Keystore'),
                                                   _('Seed'))))
        self.setMinimumWidth(600)
        vbox = QVBoxLayout(self)
        title =  _('Your wallet generation seed is:')
        slayout = SeedLayout(title=title, seed=seed, msg=True,
                             passphrase=passphrase)
        vbox.addLayout(slayout)
        vbox.addLayout(Buttons(CloseButton(self)))


class PSKsPasswordDlg(WindowModalDialog):

    def __init__(self, parent, wallet):
        WindowModalDialog.__init__(self, parent)
        OK_button = OkButton(self)
        if not wallet.psman.is_ps_ks_encrypted():
            msg = _('Your PrivateSend Keystore is not protected.')
            msg += ' ' + _('Use this dialog to add a password to it.')
            has_password = False
        else:
            msg = _('Your PrivateSend Keystore is password protected.')
            msg += ' ' + _('Use this dialog to change password on it.')
            has_password = True
        self.playout = PasswordLayout(msg=msg, kind=PW_CHANGE,
                                      OK_button=OK_button,
                                      has_password=has_password)
        self.setWindowTitle(self.playout.title())
        vbox = QVBoxLayout(self)
        vbox.addLayout(self.playout.layout())
        vbox.addStretch(1)
        vbox.addLayout(Buttons(CancelButton(self), OK_button))
        self.playout.encrypt_cb.hide()

    def run(self):
        if not self.exec_():
            return False, None, None
        return True, self.playout.old_password(), self.playout.new_password()


class PSDialogUnsupportedPS(QDialog, MessageBoxMixin):

    def __init__(self, mwin):
        QDialog.__init__(self, parent=None)
        self.setMinimumSize(900, 480)
        self.setWindowIcon(read_QIcon('electrum-axe.png'))
        self.mwin = mwin
        self.wallet = mwin.wallet
        self.psman = psman = mwin.wallet.psman
        title = '%s - %s' % (_('PrivateSend'), str(self.wallet))
        self.setWindowTitle(title)

        layout = QGridLayout()
        self.setLayout(layout)

        ps_unsupported_label = QLabel(psman.unsupported_msg)
        ps_unsupported_label.setWordWrap(True)
        layout.addWidget(ps_unsupported_label, 0, 0, 1, -1)

        self.close_btn = b = QPushButton(_('Close'))
        b.setDefault(True)
        b.clicked.connect(self.close)
        layout.addWidget(b, 2, 1)
        layout.setRowStretch(1, 1)
        layout.setColumnStretch(0, 1)

    def closeEvent(self, event):
        try:
            ps_dialogs.remove(self)
        except ValueError:
            pass


class PSDialog(QDialog, MessageBoxMixin):

    def __init__(self, mwin):
        QDialog.__init__(self, parent=None)
        self.setMinimumSize(900, 480)
        self.setWindowIcon(read_QIcon('electrum-axe.png'))
        self.mwin = mwin
        self.wallet = mwin.wallet
        self.psman = mwin.wallet.psman
        title = '%s - %s' % (_('PrivateSend'), str(self.wallet))
        self.setWindowTitle(title)
        self.ps_signal_connected = False

        layout = QGridLayout()
        self.setLayout(layout)
        self.tabs = QTabWidget(self)
        self.close_btn = b = QPushButton(_('Close'))
        b.setDefault(True)
        b.clicked.connect(self.close)
        layout.addWidget(self.tabs, 0, 0, 1, -1)
        layout.setColumnStretch(0, 1)
        layout.addWidget(b, 1, 1)

        self.add_mixing_tab()
        self.update_mixing_status()
        self.update_balances()
        self.add_info_tab()
        self.info_update()
        self.info_data_buttons_update()
        self.add_ps_ks_tab()
        self.add_log_tab()
        self.mwin.ps_signal.connect(self.on_ps_signal)
        self.ps_signal_connected = True
        self.is_hiding = False
        self.incoming_msg = False
        self.init_log()
        self.tabs.currentChanged.connect(self.on_tabs_changed)

    def showEvent(self, event):
        super(PSDialog, self).showEvent(event)
        QTimer.singleShot(0, self.on_shown)

    def on_shown(self):
        if self.psman.show_warn_electrumx:
            self.warn_ex_label.show_warn()

    def reject(self):
        self.close()

    def closeEvent(self, event):
        self.is_hiding = True
        if self.incoming_msg:
            self.is_hiding = False
            event.ignore()
            return
        self.log_handler.notify = False
        if self.ps_signal_connected:
            self.ps_signal_connected = False
            self.mwin.ps_signal.disconnect(self.on_ps_signal)
        event.accept()
        try:
            ps_dialogs.remove(self)
        except ValueError:
            pass

    def resizeEvent(self, event):
        self.log_view.ensureCursorVisible()
        return super(PSDialog, self).resizeEvent(event)

    def on_tabs_changed(self, idx):
        if self.tabs.currentWidget() == self.log_tab:
            self.append_log_tail()
            self.log_handler.notify = True
        else:
            self.log_handler.notify = False

    def on_ps_signal(self, event, args):
        if event == 'ps-log-changes':
            psman = args[0]
            if psman == self.psman:
                if self.log_handler.head > self.log_head:
                    self.clear_log_head()
                if self.log_handler.tail > self.log_tail:
                    self.append_log_tail()
        elif event == 'ps-wfl-changes':
            wallet = args[0]
            if wallet == self.wallet:
                self.info_update()
        elif event in ['ps-reserved-changes', 'ps-keypairs-changes']:
            wallet = args[0]
            if wallet == self.wallet:
                self.info_update()
        elif event == 'ps-data-changes':
            wallet = args[0]
            if wallet == self.wallet:
                self.update_balances()
                self.info_update()
        elif event == 'ps-state-changes':
            wallet, msg, msg_type = args
            if wallet == self.wallet:
                self.update_mixing_status()
                self.info_data_buttons_update()

    def add_mixing_tab(self):
        self.mixing_tab = QWidget()
        grid = QGridLayout(self.mixing_tab)
        psman = self.psman

        # warn_electrumx
        warn_ex_text = psman.warn_electrumx_data()
        warn_ex_help = psman.warn_electrumx_data(full_txt=True)

        def get_show_warn_electrumx_value():
            return not psman.show_warn_electrumx

        def on_show_warn_electrumx_changed(x):
            psman.show_warn_electrumx = (x != Qt.Checked)

        warn_cb_text = _('Do not show this on PrivateSend dialog open.')
        self.warn_ex_label = WarnLabel(warn_ex_text, warn_ex_help,
                                       warn_cb_text,
                                       get_show_warn_electrumx_value,
                                       on_show_warn_electrumx_changed)
        i = grid.rowCount()
        grid.addWidget(self.warn_ex_label, i, 0, 1, -1)

        # keep_amount
        keep_amount_text = psman.keep_amount_data()
        keep_amount_help = psman.keep_amount_data(full_txt=True)
        keep_amount_label = HelpLabel(keep_amount_text + ':', keep_amount_help)
        self.keep_amount_sb = AxeSpinBox()
        self.keep_amount_sb.setMinimum(psman.min_keep_amount)
        self.keep_amount_sb.setMaximum(psman.max_keep_amount)
        self.keep_amount_sb.setValue(psman.keep_amount)

        def on_keep_amount_change():
            psman.keep_amount = self.keep_amount_sb.value()
            self.update_balances()
        self.keep_amount_sb.valueChanged.connect(on_keep_amount_change)

        i = grid.rowCount()
        grid.addWidget(keep_amount_label, i, 0)
        grid.addWidget(self.keep_amount_sb, i, 2)

        # mix_rounds
        mix_rounds_text = psman.mix_rounds_data()
        mix_rounds_help = psman.mix_rounds_data(full_txt=True)
        mix_rounds_label = HelpLabel(mix_rounds_text + ':', mix_rounds_help)
        self.mix_rounds_sb = QSpinBox()
        self.mix_rounds_sb.setMinimum(psman.min_mix_rounds)
        self.mix_rounds_sb.setMaximum(psman.max_mix_rounds)
        self.mix_rounds_sb.setValue(psman.mix_rounds)

        def on_mix_rounds_change():
            psman.mix_rounds = self.mix_rounds_sb.value()
            self.update_balances()
        self.mix_rounds_sb.valueChanged.connect(on_mix_rounds_change)

        i = grid.rowCount()
        grid.addWidget(mix_rounds_label, i, 0)
        grid.addWidget(self.mix_rounds_sb, i, 2)

        # mixing control
        self.mixing_ctl_btn = QPushButton(psman.mixing_control_data())

        def mixing_ctl_btn_pressed():
            if psman.state == PSStates.Ready:
                need_new_kp, prev_kp_state = psman.check_need_new_keypairs()
                if need_new_kp:
                    self.start_mixing(prev_kp_state)
                else:
                    psman.start_mixing(None)
            elif psman.state == PSStates.Mixing:
                psman.stop_mixing()
            elif psman.state == PSStates.Disabled:
                psman.enable_ps()
        self.mixing_ctl_btn.clicked.connect(mixing_ctl_btn_pressed)

        i = grid.rowCount()
        grid.addWidget(self.mixing_ctl_btn, i, 0, 1, -1)

        # mixing progress
        mix_progress_text = psman.mixing_progress_data()
        mix_progress_help = psman.mixing_progress_data(full_txt=True)
        mix_progress_label = \
            HelpLabel(mix_progress_text + ':', mix_progress_help)
        self.mix_progress_bar = QProgressBar()

        i = grid.rowCount()
        grid.addWidget(mix_progress_label, i, 0)
        grid.addWidget(self.mix_progress_bar, i, 2)

        # ps balance
        ps_balance_text = psman.ps_balance_data()
        ps_balance_help = psman.ps_balance_data(full_txt=True)
        ps_balance_label = HelpLabel(ps_balance_text + ':', ps_balance_help)
        self.ps_balance_amount = QLabel()

        i = grid.rowCount()
        grid.addWidget(ps_balance_label, i, 0)
        grid.addWidget(self.ps_balance_amount, i, 2)

        # denominated balance
        dn_balance_text = psman.dn_balance_data()
        dn_balance_help = psman.dn_balance_data(full_txt=True)
        dn_balance_label = HelpLabel(dn_balance_text + ':', dn_balance_help)
        self.dn_balance_amount = QLabel()

        i = grid.rowCount()
        grid.addWidget(dn_balance_label, i, 0)
        grid.addWidget(self.dn_balance_amount, i, 2)

        # create_sm_denoms
        self.create_sm_denoms_bnt = QPushButton(psman.create_sm_denoms_data())

        def on_create_sm_denoms(x):
            denoms_by_vals = psman.calc_denoms_by_values()
            if (not denoms_by_vals
                    or not psman.check_big_denoms_presented(denoms_by_vals)):
                msg = psman.create_sm_denoms_data(no_denoms_txt=True)
                self.show_error(msg)
            else:
                if psman.check_enough_sm_denoms(denoms_by_vals):
                    q = psman.create_sm_denoms_data(enough_txt=True)
                else:
                    q = psman.create_sm_denoms_data(confirm_txt=True)
                if self.question(q):
                    self.mwin.create_small_denoms(denoms_by_vals, self)
        self.create_sm_denoms_bnt.clicked.connect(on_create_sm_denoms)

        i = grid.rowCount()
        grid.addWidget(self.create_sm_denoms_bnt, i, 0, 1, -1)

        # max_sessions
        max_sessions_text = psman.max_sessions_data()
        max_sessions_help = psman.max_sessions_data(full_txt=True)
        max_sessions_label = \
            HelpLabel(max_sessions_text + ':', max_sessions_help)
        self.max_sessions_sb = QSpinBox()
        self.max_sessions_sb.setMinimum(psman.min_max_sessions)
        self.max_sessions_sb.setMaximum(psman.max_max_sessions)
        self.max_sessions_sb.setValue(psman.max_sessions)

        def on_max_sessions_change():
            psman.max_sessions = self.max_sessions_sb.value()
        self.max_sessions_sb.valueChanged.connect(on_max_sessions_change)

        i = grid.rowCount()
        grid.addWidget(max_sessions_label, i, 0)
        grid.addWidget(self.max_sessions_sb, i, 2)

        # kp_timeout
        kp_timeout_text = psman.kp_timeout_data()
        kp_timeout_help = psman.kp_timeout_data(full_txt=True)
        kp_timeout_label = HelpLabel(kp_timeout_text + ':', kp_timeout_help)
        self.kp_timeout_sb = QSpinBox()
        self.kp_timeout_sb.setMinimum(psman.min_kp_timeout)
        self.kp_timeout_sb.setMaximum(psman.max_kp_timeout)
        self.kp_timeout_sb.setValue(psman.kp_timeout)

        def on_kp_timeout_change():
            psman.kp_timeout = self.kp_timeout_sb.value()
        self.kp_timeout_sb.valueChanged.connect(on_kp_timeout_change)

        i = grid.rowCount()
        grid.addWidget(kp_timeout_label, i, 0)
        grid.addWidget(self.kp_timeout_sb, i, 2)

        # group_history
        group_hist_cb = QCheckBox(psman.group_history_data(full_txt=True))
        group_hist_cb.setChecked(psman.group_history)

        def on_group_hist_state_changed(x):
            psman.group_history = (x == Qt.Checked)
            self.mwin.history_model.refresh('on_grouping_change')
        group_hist_cb.stateChanged.connect(on_group_hist_state_changed)

        i = grid.rowCount()
        grid.addWidget(group_hist_cb, i, 0, 1, -1)

        # notify_ps_txs
        notify_txs_cb = QCheckBox(psman.notify_ps_txs_data(full_txt=True))
        notify_txs_cb.setChecked(psman.notify_ps_txs)

        def on_notify_txs_state_changed(x):
            psman.notify_ps_txs = (x == Qt.Checked)
        notify_txs_cb.stateChanged.connect(on_notify_txs_state_changed)

        i = grid.rowCount()
        grid.addWidget(notify_txs_cb, i, 0, 1, -1)

        # subscribe_spent
        sub_spent_cb = QCheckBox(psman.subscribe_spent_data(full_txt=True))
        sub_spent_cb.setChecked(psman.subscribe_spent)

        def on_sub_spent_state_changed(x):
            psman.subscribe_spent = (x == Qt.Checked)
        sub_spent_cb.stateChanged.connect(on_sub_spent_state_changed)

        i = grid.rowCount()
        grid.addWidget(sub_spent_cb, i, 0, 1, -1)

        # allow_others
        allow_others_cb = QCheckBox(psman.allow_others_data(full_txt=True))
        allow_others_cb.setChecked(psman.allow_others)

        def on_allow_others_changed(x):
            if x == Qt.Checked:
                q = psman.allow_others_data(qt_question=True)
                if self.question(q):
                    psman.allow_others = True
                else:
                    allow_others_cb.setCheckState(Qt.Unchecked)
            else:
                psman.allow_others = False
            self.mwin.update_avalaible_amount()
        allow_others_cb.stateChanged.connect(on_allow_others_changed)

        i = grid.rowCount()
        grid.addWidget(allow_others_cb, i, 0, 1, -1)

        # final tab setup
        i = grid.rowCount()
        grid.setRowStretch(i, 1)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(2, 1)
        self.tabs.addTab(self.mixing_tab, _('Mixing'))

    def start_mixing(self, prev_kp_state):
        password = None
        psman = self.psman
        while self.wallet.has_keystore_encryption():
            password = self.mwin.password_dialog(parent=self)
            if password is None:
                # User cancelled password input
                psman.keypairs_state = prev_kp_state
                return
            try:
                self.wallet.check_password(password)
                break
            except Exception as e:
                self.show_error(str(e))
                continue
        if password is None and psman.is_hw_ks:
            while psman.is_ps_ks_encrypted():
                password = self.mwin.password_dialog(parent=self)
                if password is None:
                    # User cancelled password input
                    psman.keypairs_state = prev_kp_state
                    return
                try:
                    psman.ps_keystore.check_password(password)
                    break
                except Exception as e:
                    self.show_error(str(e))
                    continue
        self.wallet.psman.start_mixing(password)

    def add_info_tab(self):
        self.ps_info_tab = QWidget()
        self.ps_info_view = QPlainTextEdit()
        self.ps_info_view.setReadOnly(True)

        btns_hbox = QHBoxLayout()
        btns = QWidget()
        btns.setLayout(btns_hbox)

        self.clear_ps_data_bnt = QPushButton(_('Clear PS data'))

        def clear_ps_data():
            if self.question(self.psman.CLEAR_PS_DATA_MSG):
                self.psman.clear_ps_data()
        self.clear_ps_data_bnt.clicked.connect(clear_ps_data)

        btns_hbox.addWidget(self.clear_ps_data_bnt)

        self.find_untracked_bnt = QPushButton(_('Find untracked PS txs'))

        def find_untracked_ps_txs():
            self.psman.find_untracked_ps_txs_from_gui()
        self.find_untracked_bnt.clicked.connect(find_untracked_ps_txs)

        btns_hbox.addWidget(self.find_untracked_bnt)

        ps_info_vbox = QVBoxLayout()
        ps_info_vbox.addWidget(self.ps_info_view)
        ps_info_vbox.addWidget(btns)
        self.ps_info_tab.setLayout(ps_info_vbox)
        self.tabs.addTab(self.ps_info_tab, _('Info'))

    def add_log_tab(self):
        self.log_handler = self.psman.log_handler
        self.log_tab = QWidget()
        self.log_view = FilteredPlainTextEdit()
        self.log_view.setMaximumBlockCount(1000)
        self.log_view.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.log_view.setReadOnly(True)

        clear_log_btn = QPushButton(_('Clear Log'))
        clear_log_btn.clicked.connect(self.clear_log)

        log_vbox = QVBoxLayout()
        log_vbox.addWidget(self.log_view)
        log_vbox.addWidget(clear_log_btn)
        self.log_tab.setLayout(log_vbox)
        self.tabs.addTab(self.log_tab, _('Log'))

    def add_ps_ks_tab(self):
        psman = self.psman
        if not psman.is_hw_ks:
            return
        self.ps_ks_tab = QWidget()
        grid = QGridLayout()
        self.ps_ks_tab.setLayout(grid)

        grid.addWidget(QLabel(_('Master Public Key')), 0, 0)
        mpk = psman.ps_keystore.get_master_public_key()
        mpk_text = ShowQRTextEdit()
        mpk_text.setMaximumHeight(150)
        mpk_text.addCopyButton(self.mwin.app)
        mpk_text.setText(mpk)
        grid.addWidget(mpk_text, 1, 0)
        grid.setRowStretch(2, 1)

        self.seed_btn = QPushButton(_('Show Seed'))

        def show_ps_ks_seed_dlg():
            self.show_ps_ks_seed_dialog(mwin=self.mwin, parent=self)

        self.seed_btn.clicked.connect(show_ps_ks_seed_dlg)
        grid.addWidget(self.seed_btn, 3, 0)

        if psman.is_ps_ks_encrypted():
            pwd_btn_text = _('Change Password')
        else:
            pwd_btn_text = _('Set Password')
        self.password_btn = QPushButton(pwd_btn_text)
        self.password_btn.clicked.connect(self.change_ps_ks_password_dialog)
        grid.addWidget(self.password_btn, 4, 0)

        self.export_privk_btn = QPushButton(_('Export Private Keys'))

        def export_ps_ks_privkeys_dlg():
            self.mwin.export_privkeys_dialog(ps_ks_only=True, mwin=self.mwin,
                                             parent=self)

        self.export_privk_btn.clicked.connect(export_ps_ks_privkeys_dlg)
        grid.addWidget(self.export_privk_btn, 5, 0)

        if psman.is_hw_ks:
            send_funds_to_main_txt = _('Send all coins to hardware wallet')
        else:
            send_funds_to_main_txt = _('Send all coins to main keystore')
        self.send_funds_to_main_btn = QPushButton(send_funds_to_main_txt)

        def send_funds_to_main_ks():
            self.mwin.send_funds_to_main_ks(mwin=self.mwin, parent=self)

        self.send_funds_to_main_btn.clicked.connect(send_funds_to_main_ks)
        grid.addWidget(self.send_funds_to_main_btn, 6, 0)


        warn_ps_ks_cb = QCheckBox(psman.warn_ps_ks_data())
        warn_ps_ks_cb.setChecked(psman.show_warn_ps_ks)

        def on_warn_ps_ks_changed(x):
            psman.show_warn_ps_ks = (x == Qt.Checked)
        warn_ps_ks_cb.stateChanged.connect(on_warn_ps_ks_changed)
        grid.addWidget(warn_ps_ks_cb, 7, 0)

        self.tabs.addTab(self.ps_ks_tab, _('PS Keystore'))

    @protected_with_parent
    def show_ps_ks_seed_dialog(self, parent, password):
        psman = self.psman
        seed = psman.ps_keystore.get_seed(password)
        passphrase = psman.ps_keystore.get_passphrase(password)
        d = ShowPSKsSeedDlg(parent, seed, passphrase)
        d.exec_()

    def change_ps_ks_password_dialog(self):
        psman = self.psman
        d = PSKsPasswordDlg(self, self.wallet)
        ok, old_password, new_password = d.run()
        if not ok:
            return
        try:
            psman.update_ps_ks_password(old_password, new_password)
        except InvalidPassword as e:
            self.show_error(str(e))
            return
        except BaseException:
            self.logger.exception('Failed to update PS Keystore password')
            self.show_error(_('Failed to update PS Keystore password'))
            return
        if psman.is_ps_ks_encrypted():
            msg = _('Password was updated successfully')
            pwd_btn_text = _('Change Password')
        else:
            msg = _('Password is disabled, this wallet is not protected')
            pwd_btn_text = _('Set Password')
        self.show_message(msg, title=_("Success"))
        self.password_btn.setText(pwd_btn_text)

    def update_mixing_status(self):
        psman = self.psman
        if psman.state in [PSStates.Disabled, PSStates.Ready, PSStates.Mixing]:
            self.mixing_ctl_btn.setEnabled(True)
        else:
            self.mixing_ctl_btn.setEnabled(False)
        if psman.state in psman.mixing_running_states:
            self.keep_amount_sb.setEnabled(False)
            self.mix_rounds_sb.setEnabled(False)
            self.create_sm_denoms_bnt.setEnabled(False)
        else:
            self.keep_amount_sb.setEnabled(True)
            self.mix_rounds_sb.setEnabled(True)
            self.create_sm_denoms_bnt.setEnabled(True)
        self.mixing_ctl_btn.setText(psman.mixing_control_data())

    def update_balances(self):
        wallet = self.wallet
        psman = self.psman
        dn_balance = wallet.get_balance(include_ps=False, min_rounds=0)
        dn_amount = self.mwin.format_amount_and_units(sum(dn_balance))
        self.dn_balance_amount.setText(dn_amount)
        ps_balance = wallet.get_balance(include_ps=False,
                                        min_rounds=psman.mix_rounds)
        ps_amount = self.mwin.format_amount_and_units(sum(ps_balance))
        self.ps_balance_amount.setText(ps_amount)
        self.mix_progress_bar.setValue(psman.mixing_progress())

    def info_update(self):
        lines = self.psman.get_ps_data_info()
        self.ps_info_view.setPlainText('\n'.join(lines))

    def info_data_buttons_update(self):
        psman = self.psman
        if psman.state in [PSStates.Ready, PSStates.Errored]:
            self.clear_ps_data_bnt.setEnabled(True)
        else:
            self.clear_ps_data_bnt.setEnabled(False)
        if psman.state == PSStates.Ready:
            self.find_untracked_bnt.setEnabled(True)
        else:
            self.find_untracked_bnt.setEnabled(False)

    def init_log(self):
        self.log_head = self.log_handler.head
        self.log_tail = self.log_head

    def append_log_tail(self):
        log_handler = self.log_handler
        log_tail = log_handler.tail
        lv = self.log_view
        vert_sb = self.log_view.verticalScrollBar()
        was_at_end = (vert_sb.value() == vert_sb.maximum())
        for i in range(self.log_tail, log_tail):
            log_line = ''
            log_record = log_handler.log.get(i, None)
            if log_record:
                created = time.localtime(log_record.created)
                created = time.strftime('%x %X', created)
                log_line = f'{created} {log_record.msg}'
                if log_record.subcat == PSLogSubCat.WflDone:
                    log_line = f'<font color="#1c75bc">{log_line}</font>'
                elif log_record.subcat == PSLogSubCat.WflOk:
                    log_line = f'<font color="#32b332">{log_line}</font>'
                elif log_record.subcat == PSLogSubCat.WflErr:
                    log_line = f'<font color="#BC1E1E">{log_line}</font>'
            lv.appendHtml(log_line)
            if was_at_end:
                cursor = self.log_view.textCursor()
                cursor.movePosition(QTextCursor.End)
                self.log_view.setTextCursor(cursor)
                self.log_view.ensureCursorVisible()
        self.log_tail = log_tail

    def clear_log_head(self):
        self.log_head = self.log_handler.head

    def clear_log(self):
        self.log_view.clear()
        self.log_handler.clear_log()


class SeedOperationWizardPage(QWizardPage):

    def __init__(self, parent=None):
        super(SeedOperationWizardPage, self).__init__(parent)
        self.parent = parent
        self.setTitle(_('PrivateSend Kestore'))
        self.setSubTitle(_('Do you want to create a new seed, or to'
                           ' restore a wallet using an existing seed?'))

        self.rb_create = QRadioButton(_('Create a new seed'))
        self.rb_restore = QRadioButton(_('I already have a seed'))
        self.rb_create.setChecked(True)
        self.button_group = QButtonGroup()
        self.button_group.addButton(self.rb_create)
        self.button_group.addButton(self.rb_restore)
        gb_vbox = QVBoxLayout()
        gb_vbox.addWidget(self.rb_create)
        gb_vbox.addWidget(self.rb_restore)
        self.gb_create = QGroupBox(_('Select operation type'))
        self.gb_create.setLayout(gb_vbox)

        layout = QVBoxLayout()
        layout.addWidget(self.gb_create)
        self.setLayout(layout)

    def nextId(self):
        if self.rb_create.isChecked():
            return self.parent.CREATE_SEED_PAGE
        else:
            return self.parent.ENTER_SEED_PAGE


class CreateSeedWizardPage(QWizardPage):

    def __init__(self, parent=None):
        super(CreateSeedWizardPage, self).__init__(parent)
        self.parent = parent
        self.setTitle(_('PrivateSend Kestore Seed'))
        self.setSubTitle(_('Your wallet generation seed is:'))
        self.layout = QVBoxLayout()
        self.setLayout(self.layout)
        self.main_widget = QWidget()
        self.layout.addWidget(self.main_widget)

    def initializePage(self):
        self.layout.removeWidget(self.main_widget)
        self.main_widget.setParent(None)
        self.main_widget = QWidget()
        self.layout.addWidget(self.main_widget)

        self.parent.seed_text = mnemonic.Mnemonic('en').make_seed('standard')
        self.slayout = SeedLayout(seed=self.parent.seed_text, msg=True,
                                  options=['ext'])
        self.main_widget.setLayout(self.slayout)

    def nextId(self):
        if self.slayout.is_ext:
            return self.parent.REQUEST_PASS_PAGE
        else:
            return self.parent.CONFIRM_SEED_PAGE

    def validatePage(self):
        self.parent.is_ext = self.slayout.is_ext
        self.parent.is_restore = False
        return True


class RequestPassphraseWizardPage(QWizardPage):

    def __init__(self, parent=None):
        super(RequestPassphraseWizardPage, self).__init__(parent)
        self.parent = parent
        self.setTitle(_('Seed extension'))
        subtitle = '\n'.join([
            _('You may extend your seed with custom words.'),
            _('Your seed extension must be saved together with your seed.'),
        ])
        self.setSubTitle(subtitle)

        self.pass_edit = QLineEdit()
        warning = '\n'.join([
            _('Note that this is NOT your encryption password.'),
            _('If you do not know what this is, leave this field empty.'),
        ])
        warn_label = QLabel(warning)
        layout = QVBoxLayout()
        layout.addWidget(self.pass_edit)
        layout.addWidget(warn_label)
        self.setLayout(layout)

    def nextId(self):
        if self.parent.is_restore:
            return self.parent.KEYSTORE_PWD_PAGE
        else:
            return self.parent.CONFIRM_SEED_PAGE

    def validatePage(self):
        self.parent.seed_ext_text = self.pass_edit.text()
        return True


class ConfirmSeedWizardPage(QWizardPage):

    def __init__(self, parent=None):
        super(ConfirmSeedWizardPage, self).__init__(parent)
        self.parent = parent
        self.setTitle(_('Confirm Seed'))
        subtitle = ' '.join([
            _('Your seed is important!'),
            _('If you lose your seed, your money will be permanently lost.'),
            _('To make sure that you have properly saved your seed,'
              ' please retype it here.')
        ])
        self.setSubTitle(subtitle)
        self.layout = QVBoxLayout()
        self.setLayout(self.layout)
        self.main_widget = QWidget()
        self.layout.addWidget(self.main_widget)
        self.seed_ok = False

    def initializePage(self):
        self.layout.removeWidget(self.main_widget)
        self.main_widget.setParent(None)
        self.main_widget = QWidget()
        self.layout.addWidget(self.main_widget)

        self.slayout = SeedLayout(is_seed=lambda x: x == self.parent.seed_text,
                                  options=[], on_edit_cb=self.set_seed_ok)
        self.main_widget.setLayout(self.slayout)
        self.seed_ok = self.slayout.is_seed(self.slayout.get_seed())

    def set_seed_ok(self, seed_ok):
        self.seed_ok = seed_ok
        self.completeChanged.emit()

    def nextId(self):
        if self.parent.is_ext:
            return self.parent.CONFIRM_PASS_PAGE
        else:
            return self.parent.KEYSTORE_PWD_PAGE

    def isComplete(self):
        return self.seed_ok


class ConfirmPassphraseWizardPage(QWizardPage):

    def __init__(self, parent=None):
        super(ConfirmPassphraseWizardPage, self).__init__(parent)
        self.parent = parent
        self.setTitle(_('Confirm Seed Extension'))
        message = '\n'.join([
            _('Your seed extension must be saved together with your seed.'),
            _('Please type it here.'),
        ])
        self.setSubTitle(message)
        layout = QVBoxLayout()
        self.pass_edit = QLineEdit()
        self.pass_edit.textChanged.connect(self.on_pass_edit_changed)
        layout.addWidget(self.pass_edit)
        self.setLayout(layout)

    @pyqtSlot()
    def on_pass_edit_changed(self):
        self.completeChanged.emit()

    def nextId(self):
        return self.parent.KEYSTORE_PWD_PAGE

    def isComplete(self):
        return self.pass_edit.text() == self.parent.seed_ext_text


class EnterSeedWizardPage(QWizardPage):

    def __init__(self, parent=None):
        super(EnterSeedWizardPage, self).__init__(parent)
        self.parent = parent
        self.setTitle(_('Enter Seed'))
        subtitle = _('Please enter your seed phrase in order'
                     ' to restore your wallet.')
        self.setSubTitle(subtitle)
        self.layout = QVBoxLayout()
        self.setLayout(self.layout)
        self.main_widget = QWidget()
        self.layout.addWidget(self.main_widget)
        self.seed_ok = False

    def initializePage(self):
        self.layout.removeWidget(self.main_widget)
        self.main_widget.setParent(None)
        self.main_widget = QWidget()
        self.layout.addWidget(self.main_widget)

        self.slayout = SeedLayout(is_seed=mnemonic.is_seed,
                                  options=['ext'], on_edit_cb=self.set_seed_ok)
        self.main_widget.setLayout(self.slayout)
        self.seed_ok = self.slayout.is_seed(self.slayout.get_seed())

    def set_seed_ok(self, seed_ok):
        self.seed_ok = seed_ok
        self.completeChanged.emit()

    def nextId(self):
        if self.slayout.is_ext:
            return self.parent.REQUEST_PASS_PAGE
        else:
            return self.parent.KEYSTORE_PWD_PAGE

    def isComplete(self):
        return self.seed_ok

    def validatePage(self):
        self.parent.seed_text = self.slayout.get_seed()
        self.parent.is_ext = self.slayout.is_ext
        self.parent.is_restore = True
        return True


class PSKeysotrePasswdWizardPage(QWizardPage):

    def __init__(self, parent=None):
        super(PSKeysotrePasswdWizardPage, self).__init__(parent)
        self.parent = parent
        self.setTitle(_('Encrypt PrivateSend Keystore'))
        self.setSubTitle('Set password for PrivateSend keystore encryption')
        self.layout = QVBoxLayout()
        self.setLayout(self.layout)
        self.main_widget = QWidget()
        self.layout.addWidget(self.main_widget)
        self.passwd_ok = False

    def initializePage(self):
        self.layout.removeWidget(self.main_widget)
        self.main_widget.setParent(None)
        self.main_widget = QWidget()
        self.layout.addWidget(self.main_widget)

        self.playout = PasswordLayout(msg=MSG_ENTER_PASSWORD, kind=PW_NEW,
                                      OK_button=None,
                                      on_edit_cb=self.set_passwd_ok)
        self.playout.encrypt_cb.hide()
        self.main_widget.setLayout(self.playout.layout())
        self.passwd_ok = \
            self.playout.new_pw.text() == self.playout.conf_pw.text()

    def set_passwd_ok(self, passwd_ok):
        self.passwd_ok = passwd_ok
        self.completeChanged.emit()

    def nextId(self):
        return self.parent.DONE_KEYSTORE_PAGE

    def isComplete(self):
        return self.passwd_ok

    def validatePage(self):
        self.parent.keystore_password = self.playout.new_password()
        return True


class DonePSKeysotreWizardPage(QWizardPage):

    def __init__(self, parent=None):
        super(DonePSKeysotreWizardPage, self).__init__(parent)
        self.parent = parent
        self.setTitle(_('Done'))
        self.setSubTitle(_('PrivateSend Kestore Created'))


        layout = QVBoxLayout()
        self.err_lbl = QLabel()
        self.err_lbl.setObjectName('err-label')
        self.err_lbl.hide()
        layout.addWidget(self.err_lbl)
        self.seed_lbl = QLabel()
        layout.addWidget(self.seed_lbl)
        self.seed_ext_lbl = QLabel()
        layout.addWidget(self.seed_ext_lbl)
        self.setLayout(layout)

    def initializePage(self):
        seed_text = self.parent.seed_text
        is_ext = self.parent.is_ext
        seed_ext_text = self.parent.seed_ext_text
        keystore_password = self.parent.keystore_password

        try:
            psman = self.parent.wallet.psman
            psman.create_ps_ks_from_seed_ext_password(seed_text, seed_ext_text,
                                                      keystore_password)
            seed_lbl_text = '%s: %s' % (_('Seed'), seed_text)
            self.seed_lbl.setText(seed_lbl_text)
            if is_ext:
                seed_ext_lbl_text = '%s: %s' % (_('Seed Extension'),
                                                seed_ext_text)
                self.seed_ext_lbl.setText(seed_ext_lbl_text)
            else:
                self.seed_ext_lbl.setText('')
        except Exception as e:
            self.err_lbl.setText(f'Error: {str(e)}')
            self.err_lbl.show()


class PSKeystoreWizard(QWizard):

    SEED_OPERATION_PAGE = 1
    CREATE_SEED_PAGE = 2
    REQUEST_PASS_PAGE = 3
    CONFIRM_SEED_PAGE = 4
    CONFIRM_PASS_PAGE = 5
    ENTER_SEED_PAGE = 6
    KEYSTORE_PWD_PAGE = 7
    DONE_KEYSTORE_PAGE = 8

    def __init__(self, parent):
        super(PSKeystoreWizard, self).__init__(parent)
        self.gui = parent
        self.wallet = parent.wallet
        self.seed_text = ''
        self.is_ext = False
        self.seed_ext_text = ''
        self.keystore_password = None

        self.setPage(self.SEED_OPERATION_PAGE, SeedOperationWizardPage(self))
        self.setPage(self.CREATE_SEED_PAGE, CreateSeedWizardPage(self))
        self.setPage(self.REQUEST_PASS_PAGE, RequestPassphraseWizardPage(self))
        self.setPage(self.CONFIRM_SEED_PAGE, ConfirmSeedWizardPage(self))
        self.setPage(self.CONFIRM_PASS_PAGE, ConfirmPassphraseWizardPage(self))
        self.setPage(self.ENTER_SEED_PAGE, EnterSeedWizardPage(self))
        self.setPage(self.KEYSTORE_PWD_PAGE, PSKeysotrePasswdWizardPage(self))
        self.setPage(self.DONE_KEYSTORE_PAGE, DonePSKeysotreWizardPage(self))

        logo = QPixmap(icon_path('privatesend.png'))
        logo = logo.scaledToWidth(32, mode=Qt.SmoothTransformation)
        self.setWizardStyle(QWizard.ClassicStyle)
        self.setOption(QWizard.NoBackButtonOnLastPage, True)
        self.setOption(QWizard.NoCancelButtonOnLastPage, True)
        self.setPixmap(QWizard.LogoPixmap, logo)
        self.setWindowTitle(_('PrivateSend Keystore Wizard'))
        self.setWindowIcon(read_QIcon('electrum-axe.png'))
        self.setMinimumSize(800, 450)
