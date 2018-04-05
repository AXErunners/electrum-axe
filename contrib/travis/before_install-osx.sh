#!/bin/bash
set -ev

if [[ -z $TRAVIS_TAG ]]; then
  exit 0
fi

cd build

brew update
brew install zebra-lucky/qt5/python3
brew install zebra-lucky/qt5/qt5

sudo pip3 install SIP==4.19.8
sudo pip3 install PyQt5==5.7.1
sudo pip3 install Cython==0.28.1
sudo pip3 install PyInstaller==3.2.1
