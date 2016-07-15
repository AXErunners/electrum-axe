#!/usr/bin/env python2

# python setup.py sdist --format=zip,gztar

from setuptools import setup
import os
import sys
import platform
import imp
import argparse

version = imp.load_source('version', 'lib/version.py')

if sys.version_info[:3] < (2, 7, 0):
    sys.exit("Error: Electrum-DASH requires Python version >= 2.7.0...")

data_files = []

if platform.system() in ['Linux', 'FreeBSD', 'DragonFly']:
    parser = argparse.ArgumentParser()
    parser.add_argument('--root=', dest='root_path', metavar='dir', default='/')
    opts, _ = parser.parse_known_args(sys.argv[1:])
    usr_share = os.path.join(sys.prefix, "share")
    if not os.access(opts.root_path + usr_share, os.W_OK) and \
       not os.access(opts.root_path, os.W_OK):
        if 'XDG_DATA_HOME' in os.environ.keys():
            usr_share = os.environ['$XDG_DATA_HOME']
        else:
            usr_share = os.path.expanduser('~/.local/share')
    data_files += [
        (os.path.join(usr_share, 'applications/'), ['electrum-dash.desktop']),
        (os.path.join(usr_share, 'pixmaps/'), ['icons/electrum-dash.png'])
    ]

setup(
    name="Electrum-DASH",
    version=version.ELECTRUM_VERSION,
    install_requires=[
        'slowaes>=0.1a1',
        'ecdsa>=0.9',
        'pbkdf2',
        'requests',
        'qrcode',
        'protobuf',
        'dnspython',
        'jsonrpclib',
        'trezor>=0.6.3',
        'x11_hash>=1.4',
    ],
    dependency_links=[
        'git+https://github.com/mazaclub/x11_hash@1.4#egg=x11_hash-1.4',
        'git+https://github.com/electrum-dash/python-trezor@v0.6.13#egg=trezor',
    ],
    packages=[
        'electrum_dash',
        'electrum_dash_gui',
        'electrum_dash_gui.qt',
        'electrum_dash_plugins',
        'electrum_dash_plugins.audio_modem',
        'electrum_dash_plugins.cosigner_pool',
        'electrum_dash_plugins.email_requests',
        'electrum_dash_plugins.exchange_rate',
        'electrum_dash_plugins.hw_wallet',
        'electrum_dash_plugins.keepkey',
        'electrum_dash_plugins.labels',
        'electrum_dash_plugins.ledger',
        'electrum_dash_plugins.plot',
        'electrum_dash_plugins.trezor',
        'electrum_dash_plugins.virtualkeyboard',
    ],
    package_dir={
        'electrum_dash': 'lib',
        'electrum_dash_gui': 'gui',
        'electrum_dash_plugins': 'plugins',
    },
    package_data={
        'electrum_dash': [
            'www/index.html',
            'wordlist/*.txt',
            'locale/*/LC_MESSAGES/electrum.mo',
        ]
    },
    scripts=['electrum-dash'],
    data_files=data_files,
    description="Lightweight Dashpay Wallet",
    author="mazaclub",
    license="MIT License",
    url="https://electrum-dash.org",
    long_description="""Lightweight Dashpay Wallet"""
)
