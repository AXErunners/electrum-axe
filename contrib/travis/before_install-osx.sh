#!/bin/bash
set -ev

if [[ -z $TRAVIS_TAG ]]; then
  exit 0
fi

cd build

brew update
brew install zebra-lucky/qt5/qt5

curl -O https://www.python.org/ftp/python/3.6.5/python-3.6.5-macosx10.6.pkg
curl -O https://bootstrap.pypa.io/get-pip.py
sudo installer -pkg python-3.6.5-macosx10.6.pkg -target /
sudo python3 get-pip.py

sudo pip3 install SIP==4.19.8
sudo pip3 install PyQt5==5.7.1
sudo pip3 install Cython==0.28.1
sudo pip3 install PyInstaller==3.3.1
