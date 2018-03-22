#!/bin/bash

if [[ $TRAVIS_PYTHON_VERSION != 3.4 ]]; then
  exit 0
fi

if [[ -z $TRAVIS_TAG ]]; then
  exit 0
fi

cd build
BUILD_REPO_URL=https://github.com/akhavr/electrum-dash.git
git clone --branch $TRAVIS_TAG $BUILD_REPO_URL electrum-dash

docker run --rm -v $(pwd):/opt -w /opt/electrum-dash -t akhavr/electrum-dash-release:Linux /opt/build_linux.sh
docker run --rm -v $(pwd):/opt -v $(pwd)/electrum-dash/:/root/.wine/drive_c/electrum -w /opt/electrum-dash -t akhavr/electrum-dash-release:Wine /opt/build_wine.sh
