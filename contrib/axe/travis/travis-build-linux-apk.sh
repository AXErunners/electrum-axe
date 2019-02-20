#!/bin/bash
set -ev

if [[ -z $TRAVIS_TAG ]]; then
  echo TRAVIS_TAG unset, exiting
  exit 1
fi

BUILD_REPO_URL=https://github.com/AXErunners/electrum-axe.git

cd build

git clone --branch $TRAVIS_TAG $BUILD_REPO_URL electrum-axe

docker run --rm \
    -v $(pwd):/opt \
    -w /opt/electrum-axe \
    -t axerunners/electrum-axe-winebuild:Linux /opt/build_linux.sh

sudo find . -name '*.po' -delete
sudo find . -name '*.pot' -delete

sudo chown -R 1000 electrum-axe

docker run --rm \
    -v $(pwd)/electrum-axe:/home/buildozer/build \
    -t axerunners/electrum-axe-winebuild:KivyPy36 bash -c \
    'export LANG=en_US.utf-8 && rm -rf packages && ./contrib/make_packages && ./contrib/make_apk'
