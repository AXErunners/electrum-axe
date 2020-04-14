#!/bin/bash

source ./contrib/axe/travis/electrum_axe_version_env.sh;
echo wine build version is $AXE_ELECTRUM_VERSION

mv /opt/zbarw $WINEPREFIX/drive_c/

mv /opt/x11_hash $WINEPREFIX/drive_c/

mv /opt/libsecp256k1/libsecp256k1-0.dll \
   /opt/libsecp256k1/libsecp256k1.dll
mv /opt/libsecp256k1 $WINEPREFIX/drive_c/

cd $WINEPREFIX/drive_c/electrum-axe

rm -rf build
rm -rf dist/electrum-axe

cp contrib/axe/deterministic.spec .
cp contrib/axe/pyi_runtimehook.py .
cp contrib/axe/pyi_tctl_runtimehook.py .

wine python -m pip install --no-warn-script-location -r contrib/deterministic-build/requirements.txt
wine python -m pip install --no-warn-script-location -r contrib/deterministic-build/requirements-hw.txt
wine python -m pip install --no-warn-script-location -r contrib/deterministic-build/requirements-binaries.txt
wine python -m pip install --no-warn-script-location PyInstaller==3.6 --no-use-pep517

wine pyinstaller --clean -y \
    --name electrum-axe-$AXE_ELECTRUM_VERSION.exe \
    deterministic.spec

if [[ $WINEARCH == win32 ]]; then
    NSIS_EXE="$WINEPREFIX/drive_c/Program Files/NSIS/makensis.exe"
else
    NSIS_EXE="$WINEPREFIX/drive_c/Program Files (x86)/NSIS/makensis.exe"
fi

wine "$NSIS_EXE" /NOCD -V3 \
    /DPRODUCT_VERSION=$AXE_ELECTRUM_VERSION \
    /DWINEARCH=$WINEARCH \
    contrib/axe/electrum-axe.nsi
