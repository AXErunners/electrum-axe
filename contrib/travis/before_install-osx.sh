#!/bin/bash
set -ev

if [[ -z $TRAVIS_TAG ]]; then
  exit 0
fi

cd build

brew update
export PATH="/usr/local/opt/python@3/bin:$PATH"
export PATH="/usr/local/opt/python@3/libexec/bin:$PATH"

brew install pyqt5
sudo pip3 install Cython

# https://github.com/pyinstaller/pyinstaller/issues/3359#issuecomment-370276763
sudo pip3 install git+https://github.com/bjones1/pyinstaller.git@pyqt5_fix
