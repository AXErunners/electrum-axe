#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import getpass
import imp
import json
import base64

try:
    import click
    import colorama
    from colorama import Fore, Style
except ImportError as e:
    print('Import error:', e)
    print('To run script install required packages with the next command:\n\n'
          'pip install click colorama')
    sys.exit(1)

try:
    imp.load_module('electrum_axe', *imp.find_module('../electrum_axe'))
    from electrum_axe import constants, keystore, storage, SimpleConfig
    from electrum_axe.version import ELECTRUM_VERSION
    from electrum_axe.gui.qt import update_checker
    from electrum_axe.plugin import Plugins
    from electrum_axe.storage import WalletStorage
    from electrum_axe.util import InvalidPassword
    from electrum_axe.wallet import Wallet
except ImportError as e:
    print('Import error:', e)


HOME_DIR = os.path.expanduser('~')
CONFIG_NAME = '.update-last-version-axe-electrum'
SIGNING_KEYS = update_checker.UpdateCheck.VERSION_ANNOUNCEMENT_SIGNING_KEYS
LATEST_VER_FNAME = '.latest-version'
COMMIT_MSG_TEMPLATE = 'set {fname} to {version}'


def read_config():
    '''Read and parse JSON from config file from HOME dir'''
    config_path = os.path.join(HOME_DIR, CONFIG_NAME)
    if not os.path.isfile(config_path):
        return {}

    try:
        with open(config_path, 'r') as f:
            data = f.read()
            return json.loads(data)
    except Exception as e:
        print('Error: Cannot read config file:', e)
        return {}


def get_connected_hw_devices(plugins):
    supported_plugins = plugins.get_hardware_support()
    # scan devices
    devices = []
    devmgr = plugins.device_manager
    for splugin in supported_plugins:
        name, plugin = splugin.name, splugin.plugin
        if not plugin:
            e = splugin.exception
            print_stderr(f"{name}: error during plugin init: {repr(e)}")
            continue
        try:
            u = devmgr.unpaired_device_infos(None, plugin)
        except Exception:
            devmgr.print_error(f'error getting device infos for {name}: {e}')
            continue
        devices += list(map(lambda x: (name, x), u))
    return devices


def get_passwd_for_hw_device_encrypted_storage(plugins):
    devices = get_connected_hw_devices(plugins)
    if len(devices) == 0:
        print_msg('Error: No connected hw device found. '
                  'Cannot decrypt this wallet.')
        sys.exit(1)
    elif len(devices) > 1:
        print_msg('Warning: multiple hardware devices detected. '
                  'The first one will be used to decrypt the wallet.')
    name, device_info = devices[0]
    plugin = plugins.get_plugin(name)
    derivation = storage.get_derivation_used_for_hw_device_encryption()
    try:
        xpub = plugin.get_xpub(device_info.device.id_, derivation,
                               'standard', plugin.handler)
    except UserCancelled:
        sys.exit(0)
    password = keystore.Xpub.get_pubkey_from_xpub(xpub, ())
    return password


def get_password(check_fn):
    while True:
        password = getpass.getpass('%sInput wallet password '
                                   '(Enter to exit):%s ' %
                                   (Fore.GREEN, Style.RESET_ALL))
        if not password:
            sys.exit(0)
        try:
            check_fn(password)
        except InvalidPassword:
            password = ''
            print('%sInvalid password%s' %
                  (Fore.RED, Style.RESET_ALL))
        if password:
            return password


class SignApp(object):
    def __init__(self, **kwargs):
        '''Get app settings from options'''
        self.make_commit = kwargs.pop('make_commit')
        self.password = kwargs.pop('password')
        self.signing_key = kwargs.pop('signing_key')
        self.testnet = kwargs.pop('testnet')
        self.wallet_path = kwargs.pop('wallet')

        script_config = read_config()
        if script_config:
            self.make_commit = (self.make_commit
                                or script_config.get('make_commit', False))
            self.signing_key = (self.signing_key
                                or script_config.get('signing_key', False))
            self.testnet = (self.testnet
                            or script_config.get('testnet', False))
            self.wallet_path = (self.wallet_path
                                or script_config.get('wallet', False))
        if self.wallet_path:
            self.wallet_path = os.path.expanduser(self.wallet_path)
        self.config_options = {'cwd': os.getcwd()}
        self.config_options['password'] = self.password
        self.config_options['testnet'] = self.testnet
        self.config_options['wallet_path'] = self.wallet_path
        self.config = SimpleConfig(self.config_options)
        if self.config.get('testnet'):
            constants.set_testnet()
        self.storage = WalletStorage(self.config.get_wallet_path())

    def load_wallet(self, storage):
        print('Lodaing wallet: %s' % self.config.get_wallet_path())
        password = None
        if storage.is_encrypted():
            if storage.is_encrypted_with_hw_device():
                plugins = Plugins(self.config, 'cmdline')
                password = get_passwd_for_hw_device_encrypted_storage(plugins)
                storage.decrypt(password)
            else:
                password = get_password(storage.decrypt)

        self.wallet = Wallet(self.storage)

        if self.wallet.has_password() and not password:
            password = get_password(self.wallet.check_password)
        self.config_options['password'] = password

    def commit_latest_version(self):
        commit_msg = COMMIT_MSG_TEMPLATE.format(fname=LATEST_VER_FNAME,
                                                version=ELECTRUM_VERSION)
        print('commiting: %s' % commit_msg)
        os.system('git add ./%s' % LATEST_VER_FNAME)
        os.system('git commit -m "%s"' % commit_msg)

    def run(self):
        self.load_wallet(self.storage)
        if self.signing_key:
            address = self.signing_key
        else:
            address = SIGNING_KEYS[0]
        message = ELECTRUM_VERSION
        password = self.config_options.get('password')
        print('Signing version: %s' % message)
        print('with address: %s' % address)
        sig = self.wallet.sign_message(address, message, password)
        sig = base64.b64encode(sig).decode('ascii')
        content = {
            'version': ELECTRUM_VERSION,
            'signatures': {
                address: sig
            }
        }
        content_json = json.dumps(content, indent=4)
        print(content_json)
        with open('./%s' % LATEST_VER_FNAME, 'w') as fd:
            fd.write('%s\n' % content_json)
        if self.make_commit:
            self.commit_latest_version()


CONTEXT_SETTINGS = dict(help_option_names=['-h', '--help'])


@click.command(context_settings=CONTEXT_SETTINGS)
@click.option('-c', '--make-commit', is_flag=True,
              help='make commit with changed %s file' % LATEST_VER_FNAME)
@click.option('-p', '--password',
              help='wallet password')
@click.option('-s', '--signing-key',
              help='address to sign message')
@click.option('-t', '--testnet', is_flag=True,
              help='use testnet')
@click.option('-w', '--wallet',
              help='wallet path')
def main(**kwargs):
    app = SignApp(**kwargs)
    app.run()


if __name__ == '__main__':
    colorama.init()
    main()
