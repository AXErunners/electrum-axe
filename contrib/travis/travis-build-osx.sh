#!/bin/bash
BUILD_REPO_URL=https://github.com/akhavr/electrum-dash.git

export PATH="/usr/local/opt/python@3/bin:$PATH"
export PATH="/usr/local/opt/python@3/libexec/bin:$PATH"

cd build

if [[ -z $TRAVIS_TAG ]]; then
  exit 0
else
  git clone --branch $TRAVIS_TAG $BUILD_REPO_URL electrum-dash
fi

cd electrum-dash

source ./contrib/travis/electrum_dash_version_env.sh;
echo wine build version is $ELECTRUM_DASH_VERSION

sudo pip3 install -r contrib/requirements.txt
sudo pip3 install \
    x11_hash>=1.4 \
    btchip-python \
    keepkey \
    trezor==0.7.16

pyrcc5 icons.qrc -o gui/qt/icons_rc.py

cp contrib/osx.spec .
cp contrib/pyi_runtimehook.py .
cp contrib/pyi_tctl_runtimehook.py .

pyinstaller \
    -y \
    --name electrum-dash-$ELECTRUM_DASH_VERSION.bin \
    osx.spec

sudo hdiutil create -fs HFS+ -volname "Electrum-DASH" \
    -srcfolder dist/Electrum-DASH.app \
    dist/electrum-dash-$ELECTRUM_DASH_VERSION-macosx.dmg
