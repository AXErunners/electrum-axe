#!/bin/bash

source ./contrib/travis/electrum_dash_version_env.sh;
echo wine build version is $ELECTRUM_DASH_VERSION

cd $WINEPREFIX/drive_c/electrum-dash

cp contrib/build-wine/deterministic.spec .
cp contrib/pyi_runtimehook.py .
cp contrib/pyi_tctl_runtimehook.py .

wine pip install -r contrib/requirements.txt

wine pip install x11_hash
wine pip install cython
wine pip install hidapi
wine pip install btchip-python
wine pip install keepkey
wine pip install trezor==0.7.16

wine pyinstaller -y \
    --name electrum-dash-$ELECTRUM_DASH_VERSION.exe \
    deterministic.spec

wine $WINEPREFIX/drive_c/Program\ Files/NSIS/makensis.exe /NOCD -V3 \
    /DPRODUCT_VERSION=$ELECTRUM_DASH_VERSION \
    /DWINEARCH=$WINEARCH \
    contrib/build-wine/electrum-dash.nsi
