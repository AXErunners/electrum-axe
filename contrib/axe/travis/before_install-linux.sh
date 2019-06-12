#!/bin/bash
set -ev

if [[ -z $TRAVIS_TAG ]]; then
  echo TRAVIS_TAG unset, exiting
  exit 1
fi

docker pull zebralucky/electrum-dash-winebuild:LinuxPy36
docker pull zebralucky/electrum-dash-winebuild:LinuxAppImage
docker pull zebralucky/electrum-dash-winebuild:WinePy36
