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


PLUGINS_LIST = [
    'audio_modem',
    'cosigner_pool',
    'digitalbitbox',
    'email_requests',
    'hw_wallet',
    'keepkey',
    'labels',
    'ledger',
    'trezor',
    'virtualkeyboard',
]


class PluginsImporter(object):

    def find_module(self, name):
        return self

    def load_module(self, name):
        split = name.split('.')
        if split[-1] == 'qt':
            plugin_module = getattr(__import__('.'.join(split[1:])), split[-2])
            return getattr(plugin_module, 'qt')
        else:
            module_name = split[-1]
            return getattr(__import__(name), module_name)


_old_find_loader = pkgutil.find_loader
def _new_find_loader(fullname):
    if fullname.startswith('electrum_dash_plugins.'):
        return PluginsImporter()
    else:
        return _old_find_loader(fullname)
pkgutil.find_loader = _new_find_loader


_old_iter_modules = pkgutil.iter_modules
def _new_iter_modules(path=None, prefix=''):
    if path and len(path) == 1 and path[0].endswith('electrum_dash_plugins'):
        for p in PLUGINS_LIST:
            yield PluginsImporter(), 'electrum_dash_plugins.%s' % p, True
    else:
        for loader, name, ispkg in _old_iter_modules(path, prefix):
            yield loader, name, ispkg
pkgutil.iter_modules = _new_iter_modules
