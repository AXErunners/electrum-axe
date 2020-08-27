#!/bin/bash
set -ev

export PY36BINDIR=/Library/Frameworks/Python.framework/Versions/3.6/bin/
export PATH=$PATH:$PY36BINDIR
source ./contrib/axe/travis/electrum_axe_version_env.sh;
echo osx build version is $AXE_ELECTRUM_VERSION


cd build
if [[ -n $TRAVIS_TAG ]]; then
    BUILD_REPO_URL=https://github.com/axerunners/electrum-axe.git
    git clone --branch $TRAVIS_TAG $BUILD_REPO_URL electrum-axe
    PIP_CMD="sudo python3 -m pip"
else
    git clone .. electrum-axe
    python3 -m virtualenv env
    source env/bin/activate
    PIP_CMD="pip"
fi
cd electrum-axe


if [[ -n $TRAVIS_TAG ]]; then
    git submodule init
    git submodule update

    echo "Building CalinsQRReader..."
    d=contrib/CalinsQRReader
    pushd $d
    rm -fr build
    xcodebuild || fail "Could not build CalinsQRReader"
    popd
fi


$PIP_CMD install --no-warn-script-location \
    -r contrib/deterministic-build/requirements.txt
$PIP_CMD install --no-warn-script-location \
    -r contrib/deterministic-build/requirements-hw.txt
$PIP_CMD install --no-warn-script-location \
    -r contrib/deterministic-build/requirements-binaries.txt
$PIP_CMD install --no-warn-script-location x11_hash>=1.4
$PIP_CMD install --no-warn-script-location PyInstaller==3.6 --no-use-pep517

pushd electrum_axe
git clone https://github.com/axerunners/electrum-axe-locale/ locale-repo
mv locale-repo/locale .
rm -rf locale-repo
find locale -name '*.po' -delete
find locale -name '*.pot' -delete
popd

cp contrib/axe/osx.spec .
cp contrib/axe/pyi_runtimehook.py .
cp contrib/axe/pyi_tctl_runtimehook.py .

pyinstaller --clean \
    -y \
    --name electrum-axe-$AXE_ELECTRUM_VERSION.bin \
    osx.spec

sudo hdiutil create -fs HFS+ -volname "Axe Electrum" \
    -srcfolder dist/Axe\ Electrum.app \
    dist/Axe-Electrum-$AXE_ELECTRUM_VERSION-macosx.dmg
