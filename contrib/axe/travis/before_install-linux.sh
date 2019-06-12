#!/bin/bash
set -ev

if [[ -z $TRAVIS_TAG ]]; then
  echo TRAVIS_TAG unset, exiting
  exit 1
fi

docker pull axerunners/electrum-axe-winebuild:LinuxPy36
docker pull axerunners/electrum-axe-winebuild:LinuxAppImage
docker pull axerunners/electrum-axe-winebuild:WinePy36
