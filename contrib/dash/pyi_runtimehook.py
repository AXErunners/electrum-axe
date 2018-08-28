# -*- coding: utf-8 -*-
"""PyInstaller runtime hook"""
import pkgutil


PLUGINS_PREFIX = 'electrum_dash.plugins'

KEYSTORE_PLUGINS = [
    'hw_wallet',
    'digitalbitbox',
    'keepkey',
    'ledger',
    'safe_t',
    'trezor',
]

OTHER_PLUGINS= [
    'audio_modem',
    'cosigner_pool',
    'email_requests',
    'labels',
    'revealer',
    'virtualkeyboard',
]

PLUGINS = KEYSTORE_PLUGINS + OTHER_PLUGINS
PLUGINS_FULL_PATH = list(map(lambda p: '%s.%s' % (PLUGINS_PREFIX, p), PLUGINS))


class PluginsImporter(object):
    def __init__(self, name):
        self.name = name

    def load_module(self):
        name = self.name
        res = __import__(name)
        for p in name.split('.')[1:]:
            res = getattr(res, p)
        return res


_old_find_loader = pkgutil.find_loader
def _new_find_loader(fullname):
    if fullname.startswith('%s.' % PLUGINS_PREFIX):
        return PluginsImporter(fullname)
    else:
        return _old_find_loader(fullname)
pkgutil.find_loader = _new_find_loader


_old_iter_modules = pkgutil.iter_modules
def _new_iter_modules(path=None, prefix=''):
    if path and len(path) == 1 and path[0].endswith('plugins'):
        for p in PLUGINS:
            yield PluginsImporter(p), p, True
    else:
        for loader, name, ispkg in _old_iter_modules(path, prefix):
            yield loader, name, ispkg
pkgutil.iter_modules = _new_iter_modules
