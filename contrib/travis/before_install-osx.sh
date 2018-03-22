#!/bin/bash
set -ev

if [[ -z $TRAVIS_TAG ]]; then
  exit 0
fi

cd build

brew update
export PATH="/usr/local/opt/python@2/bin:$PATH"
export PATH="/usr/local/opt/python@2/libexec/bin:$PATH"

brew install akhavr/qt4/pyqt@4
sudo pip2 install Cython

sudo pip2 install pyinstaller==3.2.1
