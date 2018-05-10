# -*- coding: utf-8 -*-
"""PyInstaller runtime hook"""
import imp
import sys
import pkgutil


_old_find_module = imp.find_module
def _new_find_module(name, *args, **kwargs):
    if name in ['lib', 'gui', 'plugins']:
        return (None, name, ('', '', 5))
    else:
        return _old_find_module(name, *args, **kwargs)
imp.find_module = _new_find_module


_old_load_module = imp.load_module
def _new_load_module(name, file, pathname, description):
    if pathname in ['lib', 'gui', 'plugins']:
        return __import__(name)
    else:
        return _old_load_module(name, file, pathname, description)
imp.load_module = _new_load_module


PLUGINS_PREFIX = 'electrum_dash_plugins'

KEYSTORE_PLUGINS = [
    'hw_wallet',
    'digitalbitbox',
    'keepkey',
    'ledger',
    'trezor',
]

OTHER_PLUGINS= [
    'audio_modem',
    'cosigner_pool',
    'email_requests',
    'labels',
    'virtualkeyboard',
]

OTHER_PLUGINS = list(map(lambda p: '%s.%s' % (PLUGINS_PREFIX, p), OTHER_PLUGINS))

PLUGINS = KEYSTORE_PLUGINS + OTHER_PLUGINS


class PluginsImporter(object):
    def find_module(self, name):
        return self

    def load_module(self, name):
        if name in KEYSTORE_PLUGINS:
            return getattr(__import__('%s.%s' % (PLUGINS_PREFIX, name)), name)
        elif name in OTHER_PLUGINS:
            return getattr(__import__(name), name.split('.')[-1])
        elif name.endswith('.qt'):
            split = name.split('.')
            if split[0] != split[1]:
                plugin_module = getattr(__import__(name), split[-2])
                return getattr(plugin_module, 'qt')
            else:
                path = '.'.join(split[1:])
                plugin_module = getattr(__import__(path), split[-2])
                return getattr(plugin_module, 'qt')
        else:
            raise Exception('Can not import %s' % name)


_old_find_loader = pkgutil.find_loader
def _new_find_loader(fullname):
    if fullname.startswith('%s.' % PLUGINS_PREFIX):
        return PluginsImporter()
    else:
        return _old_find_loader(fullname)
pkgutil.find_loader = _new_find_loader


_old_iter_modules = pkgutil.iter_modules
def _new_iter_modules(path=None, prefix=''):
    if path and len(path) == 1 and path[0].endswith(PLUGINS_PREFIX):
        for p in PLUGINS:
            yield PluginsImporter(), p, True
    else:
        for loader, name, ispkg in _old_iter_modules(path, prefix):
            yield loader, name, ispkg
pkgutil.iter_modules = _new_iter_modules
