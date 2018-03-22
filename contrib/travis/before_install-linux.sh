#!/bin/bash

if [[ $TRAVIS_PYTHON_VERSION != 3.4 ]]; then
  exit 0
fi

if [[ -z $TRAVIS_TAG ]]; then
  exit 0
fi

cd build

docker build -f Dockerfile-linux -t akhavr/electrum-dash-release:Linux .
./python-x11_hash-wine.sh
./python-trezor-wine.sh
docker build -f Dockerfile-wine -t akhavr/electrum-dash-release:Wine .
