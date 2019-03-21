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
brew upgrade gmp

curl -O https://www.python.org/ftp/python/3.6.8/python-3.6.8-macosx10.6.pkg
curl -O https://bootstrap.pypa.io/get-pip.py
sudo installer -pkg python-3.6.8-macosx10.6.pkg -target /
sudo python3 get-pip.py

mkdir libusb
curl https://homebrew.bintray.com/bottles/libusb-1.0.22.el_capitan.bottle.tar.gz | tar xz --directory libusb
cp libusb/libusb/1.0.22/lib/libusb-1.0.dylib .

curl -O -L https://github.com/zebra-lucky/secp256k1/releases/download/0.1/libsecp256k1-0.1-osx.tgz
tar -xzf libsecp256k1-0.1-osx.tgz
cp libsecp256k1/libsecp256k1.0.dylib .
