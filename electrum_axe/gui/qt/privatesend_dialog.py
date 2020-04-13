# -*- coding: utf-8 -*-

import time

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QColor, QPainter, QTextCursor, QIcon
from PyQt5.QtWidgets import (QPlainTextEdit, QCheckBox, QSpinBox, QVBoxLayout,
                             QPushButton, QLabel, QDialog, QGridLayout,
                             QTabWidget, QWidget, QProgressBar, QHBoxLayout,
                             QMessageBox, QStyle, QStyleOptionSpinBox, QAction,
                             QApplication)

from electrum_axe.axe_ps import filter_log_line, PSLogSubCat, PSStates
from electrum_axe.i18n import _

from .util import (HelpLabel, MessageBoxMixin, read_QIcon, custom_message_box,
                   ColorScheme)


ps_dialogs = []  # Otherwise python randomly garbage collects the dialogs


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

        # final tab setup
        i = grid.rowCount()
        grid.setRowStretch(i, 1)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(2, 1)
        self.tabs.addTab(self.mixing_tab, _('Mixing'))

    def start_mixing(self, prev_kp_state):
        password = None
        while self.wallet.has_password():
            password = self.mwin.password_dialog(parent=self)
            if password is None:
                # User cancelled password input
                self.psman.keypairs_state = prev_kp_state
                return
            try:
                self.wallet.check_password(password)
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

    def update_mixing_status(self):
        psman = self.psman
        if psman.state in [PSStates.Disabled, PSStates.Ready, PSStates.Mixing]:
            self.mixing_ctl_btn.setEnabled(True)
        else:
            self.mixing_ctl_btn.setEnabled(False)
        if psman.state in psman.mixing_running_states:
            self.keep_amount_sb.setEnabled(False)
            self.mix_rounds_sb.setEnabled(False)
        else:
            self.keep_amount_sb.setEnabled(True)
            self.mix_rounds_sb.setEnabled(True)
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
