#!/bin/bash

wineboot && sleep 5

source ./contrib/travis/electrum_dash_version_env.sh;
echo wine build version is $ELECTRUM_DASH_VERSION

cp contrib/build-wine/deterministic.spec .
cp contrib/pyi_runtimehook.py .
cp contrib/pyi_tctl_runtimehook.py .
cp /root/.wine/drive_c/Python27/Lib/site-packages/requests/cacert.pem .

wine /root/.wine/drive_c/Python27/Scripts/pyinstaller.exe \
    -y \
    --name electrum-dash-$ELECTRUM_DASH_VERSION.exe \
    deterministic.spec

cp /opt/electrum-dash/contrib/build-wine/electrum-dash.nsi /root/.wine/drive_c/
cd /root/.wine/drive_c/electrum

wine c:\\"Program Files (x86)"\\NSIS\\makensis.exe -V1 \
    /DPRODUCT_VERSION=$ELECTRUM_DASH_VERSION c:\\electrum-dash.nsi
