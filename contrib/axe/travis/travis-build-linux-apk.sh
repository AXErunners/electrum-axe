#!/bin/bash
set -ev

if [[ $ELECTRUM_MAINNET == "true" ]] && [[ -z $IS_RELEASE ]]; then
    # do not build mainnet apk if is not release
    exit 0
fi

cd build
if [[ -n $TRAVIS_TAG ]]; then
    BUILD_REPO_URL=https://github.com/axerunners/electrum-axe.git
    git clone --branch $TRAVIS_TAG $BUILD_REPO_URL electrum-axe
else
    git clone .. electrum-axe
fi


pushd electrum-axe
./contrib/make_locale
find . -name '*.po' -delete
find . -name '*.pot' -delete
popd

DOCKER_CMD="rm -rf packages"
DOCKER_CMD="$DOCKER_CMD && ./contrib/make_packages"
DOCKER_CMD="$DOCKER_CMD && rm -rf packages/bls_py"
DOCKER_CMD="$DOCKER_CMD && rm -rf packages/python_bls*"
DOCKER_CMD="$DOCKER_CMD && ./contrib/make_apk"

if [[ $ELECTRUM_MAINNET == "false" ]]; then
    DOCKER_CMD="$DOCKER_CMD release-testnet"
fi

sudo chown -R 1000 electrum-axe
docker run --rm \
    -v $(pwd)/electrum-axe:/home/buildozer/build \
    -t zebralucky/electrum-dash-winebuild:Kivy33x bash -c \
    "$DOCKER_CMD"
