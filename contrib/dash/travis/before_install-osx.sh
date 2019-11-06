#!/bin/bash
set -ev

if [[ -z $TRAVIS_TAG ]]; then
  echo TRAVIS_TAG unset, exiting
  exit 1
fi

cd build

brew update
brew tap zebra-lucky/qt5
brew install zebra-lucky/qt5/qt
brew install gettext
brew install libusb
cp /usr/local/Cellar/libusb/1.0.*/lib/libusb-1.0.dylib .

PYTHON_VERSION=3.6.8
PYFTP=https://www.python.org/ftp/python/$PYTHON_VERSION
PYPKG_NAME=python-$PYTHON_VERSION-macosx10.6.pkg
PY_SHA256=3c5fd87a231eca3ee138b0cdc2be6517a7ca428304d41901a86b51c6a22b910c
echo "$PY_SHA256  $PYPKG_NAME" > $PYPKG_NAME.sha256
curl -O $PYFTP/$PYPKG_NAME
shasum -a256 -s -c $PYPKG_NAME.sha256
sudo installer -pkg $PYPKG_NAME -target /
rm $PYPKG_NAME $PYPKG_NAME.sha256

curl -O -L https://github.com/zebra-lucky/secp256k1/releases/download/0.1/libsecp256k1-0.1-osx.tgz
tar -xzf libsecp256k1-0.1-osx.tgz
cp libsecp256k1/libsecp256k1.0.dylib .
