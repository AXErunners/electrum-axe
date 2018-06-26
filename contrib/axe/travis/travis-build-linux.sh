#!/bin/bash
set -ev

if [[ -z $TRAVIS_TAG ]]; then
  echo TRAVIS_TAG unset, exiting
  exit 1
fi

BUILD_REPO_URL=https://github.com/AXErunners/electrum-axe.git

cd build

git clone --branch $TRAVIS_TAG $BUILD_REPO_URL electrum-axe

docker run --rm \
    -v $(pwd):/opt \
    -w /opt/electrum-axe \
    -t axerunners/electrum-axe-winebuild:Linux /opt/build_linux.sh

sudo find . -name '*.po' -delete
sudo find . -name '*.pot' -delete

export WINEARCH=win32
export WINEPREFIX=/root/.wine-32
export PYHOME=$WINEPREFIX/drive_c/Python34

wget https://github.com/zebra-lucky/zbarw/releases/download/20180620/zbarw-zbarcam-0.10-win32.zip
unzip zbarw-zbarcam-0.10-win32.zip && rm zbarw-zbarcam-0.10-win32.zip

docker run --rm \
    -e WINEARCH=$WINEARCH \
    -e WINEPREFIX=$WINEPREFIX \
    -e PYHOME=$PYHOME \
    -v $(pwd):/opt \
    -v $(pwd)/electrum-axe/:$WINEPREFIX/drive_c/electrum-axe \
    -w /opt/electrum-axe \
    -t axerunners/electrum-axe-winebuild:Wine /opt/build_wine.sh

export WINEARCH=win64
export WINEPREFIX=/root/.wine-64
export PYHOME=$WINEPREFIX/drive_c/Python34

wget https://github.com/zebra-lucky/zbarw/releases/download/20180620/zbarw-zbarcam-0.10-win64.zip
unzip zbarw-zbarcam-0.10-win64.zip && rm zbarw-zbarcam-0.10-win64.zip

docker run --rm \
    -e WINEARCH=$WINEARCH \
    -e WINEPREFIX=$WINEPREFIX \
    -e PYHOME=$PYHOME \
    -v $(pwd):/opt \
    -v $(pwd)/electrum-axe/:$WINEPREFIX/drive_c/electrum-axe \
    -w /opt/electrum-axe \
    -t axerunners/electrum-axe-winebuild:Wine /opt/build_wine.sh
