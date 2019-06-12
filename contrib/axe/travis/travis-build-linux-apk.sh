#!/bin/bash
set -ev

if [[ -z $TRAVIS_TAG ]]; then
  echo TRAVIS_TAG unset, exiting
  exit 1
fi

BUILD_REPO_URL=https://github.com/AXErunners/electrum-axe.git

cd build

git clone --branch $TRAVIS_TAG $BUILD_REPO_URL electrum-axe

pushd electrum-axe
./contrib/make_locale
find . -name '*.po' -delete
find . -name '*.pot' -delete
popd

sudo chown -R 1000 electrum-axe

docker run --rm \
    -v $(pwd)/electrum-axe:/home/buildozer/build \
    -t axerunners/electrum-axe-winebuild:Kivy33x bash -c \
    'rm -rf packages && ./contrib/make_packages && ./contrib/make_apk'
