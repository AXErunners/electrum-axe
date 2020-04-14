#!/bin/bash
set -ev

if [[ $ELECTRUM_MAINNET == "true" ]] && [[ -z $IS_RELEASE ]]; then
    # do not build mainnet apk if is not release
    exit 0
fi

docker pull zebralucky/electrum-dash-winebuild:Kivy33x
