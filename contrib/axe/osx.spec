# -*- mode: python -*-
import os
import os.path
import sys
from PyInstaller.utils.hooks import collect_data_files, collect_submodules


for i, x in enumerate(sys.argv):
    if x == '--name':
        cmdline_name = sys.argv[i+1]
        break
else:
    raise Exception('no name')

PY36BINDIR =  os.environ.get('PY36BINDIR')

hiddenimports = collect_submodules('trezorlib')
hiddenimports += collect_submodules('safetlib')
hiddenimports += collect_submodules('btchip')
hiddenimports += collect_submodules('keepkeylib')
hiddenimports += collect_submodules('websocket')
hiddenimports += [
    'electrum_axe',
    'electrum_axe.base_crash_reporter',
    'electrum_axe.base_wizard',
    'electrum_axe.plot',
    'electrum_axe.qrscanner',
    'electrum_axe.websockets',
    'electrum_axe.gui.qt',
    'PyQt5.sip',

    'electrum_axe.plugins',

    'electrum_axe.plugins.hw_wallet.qt',

    'electrum_axe.plugins.audio_modem.qt',
    'electrum_axe.plugins.cosigner_pool.qt',
    'electrum_axe.plugins.digitalbitbox.qt',
    'electrum_axe.plugins.email_requests.qt',
    'electrum_axe.plugins.keepkey.qt',
    'electrum_axe.plugins.revealer.qt',
    'electrum_axe.plugins.labels.qt',
    'electrum_axe.plugins.trezor.client',
    'electrum_axe.plugins.trezor.qt',
    'electrum_axe.plugins.safe_t.client',
    'electrum_axe.plugins.safe_t.qt',
    'electrum_axe.plugins.ledger.qt',
    'electrum_axe.plugins.virtualkeyboard.qt',
]

datas = [
    ('electrum_axe/servers.json', 'electrum_axe'),
    ('electrum_axe/servers_testnet.json', 'electrum_axe'),
    ('electrum_axe/servers_regtest.json', 'electrum_axe'),
    ('electrum_axe/currencies.json', 'electrum_axe'),
    ('electrum_axe/checkpoints.json', 'electrum_axe'),
    ('electrum_axe/locale', 'electrum_axe/locale'),
    ('electrum_axe/wordlist', 'electrum_axe/wordlist'),
]
datas += collect_data_files('trezorlib')
datas += collect_data_files('safetlib')
datas += collect_data_files('btchip')
datas += collect_data_files('keepkeylib')

# Add libusb so Trezor and Safe-T mini will work
binaries = [('../libusb-1.0.dylib', '.')]
binaries += [('../libsecp256k1.0.dylib', '.')]
binaries += [('/usr/local/lib/libgmp.10.dylib', '.')]

# https://github.com/pyinstaller/pyinstaller/wiki/Recipe-remove-tkinter-tcl
sys.modules['FixTk'] = None
excludes = ['FixTk', 'tcl', 'tk', '_tkinter', 'tkinter', 'Tkinter']
excludes += [
    'PyQt5.QtBluetooth',
    'PyQt5.QtCLucene',
    'PyQt5.QtDBus',
    'PyQt5.Qt5CLucene',
    'PyQt5.QtDesigner',
    'PyQt5.QtDesignerComponents',
    'PyQt5.QtHelp',
    'PyQt5.QtLocation',
    'PyQt5.QtMultimedia',
    'PyQt5.QtMultimediaQuick_p',
    'PyQt5.QtMultimediaWidgets',
    'PyQt5.QtNetwork',
    'PyQt5.QtNetworkAuth',
    'PyQt5.QtNfc',
    'PyQt5.QtOpenGL',
    'PyQt5.QtPositioning',
    'PyQt5.QtQml',
    'PyQt5.QtQuick',
    'PyQt5.QtQuickParticles',
    'PyQt5.QtQuickWidgets',
    'PyQt5.QtSensors',
    'PyQt5.QtSerialPort',
    'PyQt5.QtSql',
    'PyQt5.Qt5Sql',
    'PyQt5.Qt5Svg',
    'PyQt5.QtTest',
    'PyQt5.QtWebChannel',
    'PyQt5.QtWebEngine',
    'PyQt5.QtWebEngineCore',
    'PyQt5.QtWebEngineWidgets',
    'PyQt5.QtWebKit',
    'PyQt5.QtWebKitWidgets',
    'PyQt5.QtWebSockets',
    'PyQt5.QtXml',
    'PyQt5.QtXmlPatterns',
    'PyQt5.QtWebProcess',
    'PyQt5.QtWinExtras',
]

a = Analysis(['electrum-axe'],
             hiddenimports=hiddenimports,
             datas=datas,
             binaries=binaries,
             excludes=excludes,
             runtime_hooks=['pyi_runtimehook.py'])

# http://stackoverflow.com/questions/19055089/
for d in a.datas:
    if 'pyconfig' in d[0]:
        a.datas.remove(d)
        break

pyz = PYZ(a.pure)

exe = EXE(pyz,
          a.scripts,
          exclude_binaries=True,
          debug=False,
          strip=False,
          upx=False,
          console=False,
          icon='icons/electrum-axe.ico',
          name=os.path.join('build/electrum-axe/electrum-axe', cmdline_name))

# trezorctl separate bin
tctl_a = Analysis([os.path.join(PY36BINDIR, 'trezorctl')],
                  hiddenimports=['pkgutil'],
                  excludes=excludes,
                  runtime_hooks=['pyi_tctl_runtimehook.py'])

tctl_pyz = PYZ(tctl_a.pure)

tctl_exe = EXE(tctl_pyz,
           tctl_a.scripts,
           exclude_binaries=True,
           debug=False,
           strip=False,
           upx=False,
           console=True,
           name=os.path.join('build/electrum-axe/electrum-axe', 'trezorctl.bin'))

coll = COLLECT(exe, #tctl_exe,
               a.binaries,
               a.datas,
               strip=False,
               upx=False,
               name=os.path.join('dist', 'electrum-axe'))

app = BUNDLE(coll,
             name=os.path.join('dist', 'Axe Electrum.app'),
             appname="Axe Electrum",
	         icon='electrum-axe.icns',
             version = 'ELECTRUM_VERSION')
