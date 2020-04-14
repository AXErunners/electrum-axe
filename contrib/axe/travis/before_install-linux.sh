#!/bin/bash
set -ev

docker pull zebralucky/electrum-dash-winebuild:LinuxPy36

docker pull zebralucky/electrum-dash-winebuild:LinuxAppImage

docker pull zebralucky/electrum-dash-winebuild:WinePy36
