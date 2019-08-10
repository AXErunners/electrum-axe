#!/bin/bash
set -ev

if [[ -z $TRAVIS_TAG ]]; then
  echo TRAVIS_TAG unset, exiting
  exit 1
fi

BUILD_REPO_URL=https://github.com/akhavr/electrum-dash.git

cd build

git clone --branch $TRAVIS_TAG $BUILD_REPO_URL electrum-dash

cd electrum-dash

export PY36BINDIR=/Library/Frameworks/Python.framework/Versions/3.6/bin/
export PATH=$PATH:$PY36BINDIR
source ./contrib/dash/travis/electrum_dash_version_env.sh;
echo osx build version is $DASH_ELECTRUM_VERSION


git submodule init
git submodule update

info "Building CalinsQRReader..."
d=contrib/CalinsQRReader
pushd $d
rm -fr build
xcodebuild || fail "Could not build CalinsQRReader"
popd

sudo pip3 install --no-warn-script-location -r contrib/deterministic-build/requirements.txt
sudo pip3 install --no-warn-script-location -r contrib/deterministic-build/requirements-hw.txt
sudo pip3 install --no-warn-script-location -r contrib/deterministic-build/requirements-binaries.txt
sudo pip3 install --no-warn-script-location x11_hash>=1.4
sudo pip3 install --no-warn-script-location PyInstaller==3.4 --no-use-pep517

export PATH="/usr/local/opt/gettext/bin:$PATH"
./contrib/make_locale
find . -name '*.po' -delete
find . -name '*.pot' -delete

cp contrib/dash/osx.spec .
cp contrib/dash/pyi_runtimehook.py .
cp contrib/dash/pyi_tctl_runtimehook.py .

pyinstaller \
    -y \
    --name electrum-dash-$DASH_ELECTRUM_VERSION.bin \
    osx.spec

sudo hdiutil create -fs HFS+ -volname "Dash Electrum" \
    -srcfolder dist/Dash\ Electrum.app \
    dist/Dash-Electrum-$DASH_ELECTRUM_VERSION-macosx.dmg
