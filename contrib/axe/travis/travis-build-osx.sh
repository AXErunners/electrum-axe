#!/bin/bash
set -ev

if [[ -z $TRAVIS_TAG ]]; then
  echo TRAVIS_TAG unset, exiting
  exit 1
fi

BUILD_REPO_URL=https://github.com/AXErunners/electrum-axe.git

cd build

git clone --branch $TRAVIS_TAG $BUILD_REPO_URL electrum-axe

cd electrum-axe

export PY36BINDIR=/Library/Frameworks/Python.framework/Versions/3.6/bin/
export PATH=$PATH:$PY36BINDIR
source ./contrib/axe/travis/electrum_axe_version_env.sh;
echo wine build version is $ELECTRUM_AXE_VERSION

sudo pip3 install --upgrade pip
sudo pip3 install -r contrib/deterministic-build/requirements.txt
sudo pip3 install \
    x11_hash>=1.4 \
    pycryptodomex==3.6.1 \
    btchip-python==0.1.27 \
    keepkey==4.0.2 \
    safet==0.1.3 \
    trezor==0.10.2

pyrcc5 icons.qrc -o electrum_axe/gui/qt/icons_rc.py

export PATH="/usr/local/opt/gettext/bin:$PATH"
./contrib/make_locale
find . -name '*.po' -delete
find . -name '*.pot' -delete

cp contrib/axe/osx.spec .
cp contrib/axe/pyi_runtimehook.py .
cp contrib/axe/pyi_tctl_runtimehook.py .

pyinstaller \
    -y \
    --name electrum-axe-$ELECTRUM_AXE_VERSION.bin \
    osx.spec

sudo hdiutil create -fs HFS+ -volname "Electrum-AXE" \
    -srcfolder dist/Electrum-AXE.app \
    dist/electrum-axe-$ELECTRUM_AXE_VERSION-macosx.dmg
