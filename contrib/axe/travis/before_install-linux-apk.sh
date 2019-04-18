#!/bin/bash
set -ev

if [[ -z $TRAVIS_TAG ]]; then
  echo TRAVIS_TAG unset, exiting
  exit 1
fi

docker pull axerunners/electrum-axe-winebuild:Kivy33x
