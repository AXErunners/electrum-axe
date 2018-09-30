# -*- mode: python -*-
import sys
from PyInstaller.utils.hooks import collect_data_files, collect_submodules


for i, x in enumerate(sys.argv):
    if x == '--name':
        cmdline_name = sys.argv[i+1]
        break
else:
    raise Exception('no name')

hiddenimports = collect_submodules('trezorlib')
hiddenimports += collect_submodules('safetlib')
hiddenimports += collect_submodules('btchip')
hiddenimports += collect_submodules('keepkeylib')
hiddenimports += collect_submodules('websocket')
hiddenimports += [
    'electrum_dash',
    'electrum_dash.base_crash_reporter',
    'electrum_dash.base_wizard',
    'electrum_dash.plot',
    'electrum_dash.qrscanner',
    'electrum_dash.websockets',
    'electrum_dash.gui.qt',
    'PyQt5.sip',

    'electrum_dash.plugins',

    'electrum_dash.plugins.hw_wallet.qt',

    'electrum_dash.plugins.audio_modem.qt',
    'electrum_dash.plugins.cosigner_pool.qt',
    'electrum_dash.plugins.digitalbitbox.qt',
    'electrum_dash.plugins.email_requests.qt',
    'electrum_dash.plugins.keepkey.qt',
    'electrum_dash.plugins.revealer.qt',
    'electrum_dash.plugins.labels.qt',
    'electrum_dash.plugins.trezor.client',
    'electrum_dash.plugins.trezor.qt',
    'electrum_dash.plugins.safe_t.client',
    'electrum_dash.plugins.safe_t.qt',
    'electrum_dash.plugins.ledger.qt',
    'electrum_dash.plugins.virtualkeyboard.qt',
]

datas = [
    ('electrum_dash/servers.json', 'electrum_dash'),
    ('electrum_dash/servers_testnet.json', 'electrum_dash'),
    ('electrum_dash/servers_regtest.json', 'electrum_dash'),
    ('electrum_dash/currencies.json', 'electrum_dash'),
    ('electrum_dash/checkpoints.json', 'electrum_dash'),
    ('electrum_dash/locale', 'electrum_dash/locale'),
    ('electrum_dash/wordlist', 'electrum_dash/wordlist'),
    ('C:\\zbarw', '.'),
]
datas += collect_data_files('trezorlib')
datas += collect_data_files('safetlib')
datas += collect_data_files('btchip')
datas += collect_data_files('keepkeylib')

# Add libusb so Trezor and Safe-T mini will work
binaries = [('C:/Python36/libusb-1.0.dll', '.')]
binaries += [('C:/x11_hash/libx11hash-0.dll', '.')]
binaries += [('C:/libsecp256k1/libsecp256k1.dll', '.')]

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

a = Analysis(['electrum-dash'],
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
          icon='icons/electrum-dash.ico',
          name=os.path.join('build\\pyi.win32\\electrum', cmdline_name))

# exe with console output
conexe = EXE(pyz,
          a.scripts,
          exclude_binaries=True,
          debug=False,
          strip=False,
          upx=False,
          console=True,
          icon='icons/electrum-dash.ico',
          name=os.path.join('build\\pyi.win32\\electrum',
                            'console-%s' % cmdline_name))

# trezorctl separate executable
tctl_a = Analysis(['C:/Python36/Scripts/trezorctl'],
                  hiddenimports=[
                    'pkgutil',
                    'win32api',
                  ],
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
           name=os.path.join('build\\pyi.win32\\electrum', 'trezorctl.exe'))

coll = COLLECT(exe, conexe, #tctl_exe,
               a.binaries,
               a.datas,
               strip=False,
               upx=False,
               name=os.path.join('dist', 'electrum-dash'))
