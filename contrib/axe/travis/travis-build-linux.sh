#!/bin/bash
set -ev

cd build
if [[ -n $TRAVIS_TAG ]]; then
    BUILD_REPO_URL=https://github.com/axerunners/electrum-axe.git
    git clone --branch $TRAVIS_TAG $BUILD_REPO_URL electrum-axe
else
    git clone .. electrum-axe
fi


mkdir -p electrum-axe/dist
docker run --rm \
    -v $(pwd):/opt \
    -w /opt/electrum-axe \
    -t zebralucky/electrum-dash-winebuild:LinuxPy36 /opt/build_linux.sh


sudo find . -name '*.po' -delete
sudo find . -name '*.pot' -delete


docker run --rm \
    -v $(pwd):/opt \
    -w /opt/electrum-axe/contrib/axe/travis \
    -t zebralucky/electrum-dash-winebuild:LinuxAppImage ./build_appimage.sh


TOR_PROXY_VERSION=0.4.2.6
TOR_PROXY_PATH=https://github.com/zebra-lucky/tor-proxy/releases/download
TOR_DIST=electrum-axe/dist/tor-proxy-setup.exe

TOR_FILE=${TOR_PROXY_VERSION}/tor-proxy-${TOR_PROXY_VERSION}-win32-setup.exe
wget -O ${TOR_DIST} ${TOR_PROXY_PATH}/${TOR_FILE}
TOR_SHA=243d364015d340142b6a6d701c6509261e4574fa3009ba5febbe3982f25e7b46
echo "$TOR_SHA  $TOR_DIST" > sha256.txt
shasum -a256 -s -c sha256.txt


export WINEARCH=win32
export WINEPREFIX=/root/.wine-32
export PYHOME=$WINEPREFIX/drive_c/Python36


ZBARW_PATH=https://github.com/zebra-lucky/zbarw/releases/download/20180620
ZBARW_FILE=zbarw-zbarcam-0.10-win32.zip
wget ${ZBARW_PATH}/${ZBARW_FILE}
unzip ${ZBARW_FILE} && rm ${ZBARW_FILE}

X11_HASH_PATH=https://github.com/zebra-lucky/x11_hash/releases/download/1.4.1
X11_HASH_FILE=x11_hash-1.4.1-win32.zip
wget ${X11_HASH_PATH}/${X11_HASH_FILE}
unzip ${X11_HASH_FILE} && rm ${X11_HASH_FILE}

LSECP256K1_PATH=https://github.com/zebra-lucky/secp256k1/releases/download/0.1
LSECP256K1_FILE=libsecp256k1-0.1-win32.zip
wget ${LSECP256K1_PATH}/${LSECP256K1_FILE}
unzip ${LSECP256K1_FILE} && rm ${LSECP256K1_FILE}


docker run --rm \
    -e WINEARCH=$WINEARCH \
    -e WINEPREFIX=$WINEPREFIX \
    -e PYHOME=$PYHOME \
    -v $(pwd):/opt \
    -v $(pwd)/electrum-axe/:$WINEPREFIX/drive_c/electrum-axe \
    -w /opt/electrum-axe \
    -t zebralucky/electrum-dash-winebuild:WinePy36 /opt/build_wine.sh


export WINEARCH=win64
export WINEPREFIX=/root/.wine-64
export PYHOME=$WINEPREFIX/drive_c/Python36


ZBARW_FILE=zbarw-zbarcam-0.10-win64.zip
wget ${ZBARW_PATH}/${ZBARW_FILE}
unzip ${ZBARW_FILE} && rm ${ZBARW_FILE}

X11_HASH_FILE=x11_hash-1.4.1-win64.zip
wget ${X11_HASH_PATH}/${X11_HASH_FILE}
unzip ${X11_HASH_FILE} && rm ${X11_HASH_FILE}

LSECP256K1_FILE=libsecp256k1-0.1-win64.zip
wget ${LSECP256K1_PATH}/${LSECP256K1_FILE}
unzip ${LSECP256K1_FILE} && rm ${LSECP256K1_FILE}

rm ${TOR_DIST} sha256.txt
TOR_FILE=${TOR_PROXY_VERSION}/tor-proxy-${TOR_PROXY_VERSION}-win64-setup.exe
wget -O ${TOR_DIST} ${TOR_PROXY_PATH}/${TOR_FILE}
TOR_SHA=0fcd79d167f866f570e6714974309b95d82f87fe872aca86067a52e811fb9421
echo "$TOR_SHA  $TOR_DIST" > sha256.txt
shasum -a256 -s -c sha256.txt


docker run --rm \
    -e WINEARCH=$WINEARCH \
    -e WINEPREFIX=$WINEPREFIX \
    -e PYHOME=$PYHOME \
    -v $(pwd):/opt \
    -v $(pwd)/electrum-axe/:$WINEPREFIX/drive_c/electrum-axe \
    -w /opt/electrum-axe \
    -t zebralucky/electrum-dash-winebuild:WinePy36 /opt/build_wine.sh
