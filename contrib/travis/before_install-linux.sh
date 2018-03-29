#!/bin/bash

if [[ $TRAVIS_PYTHON_VERSION != 3.4 ]]; then
  exit 0
fi

if [[ -z $TRAVIS_TAG ]]; then
  exit 0
fi

docker pull zebralucky/electrum-dash-winebuild:Linux
docker pull zebralucky/electrum-dash-winebuild:Wine
