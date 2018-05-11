#!/bin/bash
BUILD_REPO_URL=https://github.com/akhavr/electrum-axe.git

cd build

if [[ -z $TRAVIS_TAG ]]; then
  exit 0
else
  git clone --branch $TRAVIS_TAG $BUILD_REPO_URL electrum-axe
fi

cd electrum-axe

export PY36BINDIR=/Library/Frameworks/Python.framework/Versions/3.6/bin/
export PATH=$PATH:$PY36BINDIR
source ./contrib/travis/electrum_axe_version_env.sh;
echo wine build version is $ELECTRUM_AXE_VERSION

sudo pip3 install -r contrib/requirements.txt
sudo pip3 install \
    x11_hash>=1.4 \
    btchip-python==0.1.24 \
    keepkey==4.0.2 \
    trezor==0.7.16

pyrcc5 icons.qrc -o gui/qt/icons_rc.py

cp contrib/osx.spec .
cp contrib/pyi_runtimehook.py .
cp contrib/pyi_tctl_runtimehook.py .

pyinstaller \
    -y \
    --name electrum-axe-$ELECTRUM_AXE_VERSION.bin \
    osx.spec

sudo hdiutil create -fs HFS+ -volname "Electrum-AXE" \
    -srcfolder dist/Electrum-AXE.app \
    dist/electrum-axe-$ELECTRUM_AXE_VERSION-macosx.dmg
