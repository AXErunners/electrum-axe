#!/bin/bash
set -ev

if [[ -z $TRAVIS_TAG ]]; then
  exit 0
fi

cd build

brew update

brew install cartr/qt4/pyqt@4
sudo pip2 install Cython

sudo pip2 install pyinstaller==3.2.1
