#!/bin/bash

source ./contrib/travis/electrum_dash_version_env.sh;
echo wine build version is $ELECTRUM_DASH_VERSION

cd $WINEPREFIX/drive_c/electrum-dash

rm -rf build
rm -rf dist/electrum-dash

cp contrib/build-wine/deterministic.spec .
cp contrib/pyi_runtimehook.py .
cp contrib/pyi_tctl_runtimehook.py .

wine pip install -r contrib/requirements.txt

wine pip install x11_hash
wine pip install cython
wine pip install hidapi
wine pip install btchip-python==0.1.24
wine pip install keepkey==4.0.2
wine pip install trezor==0.7.16

wine pyinstaller -y \
    --name electrum-dash-$ELECTRUM_DASH_VERSION.exe \
    deterministic.spec

if [[ $WINEARCH == win32 ]]; then
    NSIS_EXE="$WINEPREFIX/drive_c/Program Files/NSIS/makensis.exe"
else
    NSIS_EXE="$WINEPREFIX/drive_c/Program Files (x86)/NSIS/makensis.exe"
fi

wine "$NSIS_EXE" /NOCD -V3 \
    /DPRODUCT_VERSION=$ELECTRUM_DASH_VERSION \
    /DWINEARCH=$WINEARCH \
    contrib/build-wine/electrum-dash.nsi
