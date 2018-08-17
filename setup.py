#!/usr/bin/env python3

# python setup.py sdist --format=zip,gztar

from setuptools import setup
import os
import sys
import platform
import imp
import argparse

with open('contrib/requirements/requirements.txt') as f:
    requirements = f.read().splitlines()

with open('contrib/requirements/requirements-hw.txt') as f:
    requirements_hw = f.read().splitlines()

version = imp.load_source('version', 'lib/version.py')

if sys.version_info[:3] < (3, 4, 0):
    sys.exit("Error: Electrum-AXE requires Python version >= 3.4.0...")

data_files = []

if platform.system() in ['Linux', 'FreeBSD', 'DragonFly']:
    parser = argparse.ArgumentParser()
    parser.add_argument('--root=', dest='root_path', metavar='dir', default='/')
    opts, _ = parser.parse_known_args(sys.argv[1:])
    usr_share = os.path.join(sys.prefix, "share")
    icons_dirname = 'pixmaps'
    if not os.access(opts.root_path + usr_share, os.W_OK) and \
       not os.access(opts.root_path, os.W_OK):
        icons_dirname = 'icons'
        if 'XDG_DATA_HOME' in os.environ.keys():
            usr_share = os.environ['XDG_DATA_HOME']
        else:
            usr_share = os.path.expanduser('~/.local/share')
    data_files += [
        (os.path.join(usr_share, 'applications/'), ['electrum-axe.desktop']),
        (os.path.join(usr_share, icons_dirname), ['icons/electrum-axe.png'])
    ]

extras_require = {
    'hardware': requirements_hw,
    'fast': ['pycryptodomex'],
    ':python_version < "3.5"': ['typing>=3.0.0'],
}
extras_require['full'] = extras_require['hardware'] + extras_require['fast']


setup(
    name="Electrum-AXE",
    version=version.ELECTRUM_VERSION,
    install_requires=requirements,
    extras_require=extras_require,
    packages=[
        'electrum_axe',
        'electrum_axe_gui',
        'electrum_axe_gui.qt',
        'electrum_axe_plugins',
        'electrum_axe_plugins.audio_modem',
        'electrum_axe_plugins.cosigner_pool',
        'electrum_axe_plugins.email_requests',
        'electrum_axe_plugins.hw_wallet',
        'electrum_axe_plugins.keepkey',
        'electrum_axe_plugins.labels',
        'electrum_axe_plugins.ledger',
        'electrum_axe_plugins.revealer',
        'electrum_axe_plugins.trezor',
        'electrum_axe_plugins.digitalbitbox',
        'electrum_axe_plugins.virtualkeyboard',
    ],
    package_dir={
        'electrum_axe': 'lib',
        'electrum_axe_gui': 'gui',
        'electrum_axe_plugins': 'plugins',
    },
    package_data={
        '': ['*.txt', '*.json', '*.ttf', '*.otf'],
        'electrum_axe': [
            'wordlist/*.txt',
            'locale/*/LC_MESSAGES/electrum.mo',
        ],
    },
    scripts=['electrum-axe'],
    data_files=data_files,
    description="Lightweight AXE Wallet",
    maintainer="ddude",
    maintainer_email="ddude@axerunners.com",
    license="MIT License",
    url="https://axerunners.com",
    long_description="""Lightweight AXE Wallet"""
)
