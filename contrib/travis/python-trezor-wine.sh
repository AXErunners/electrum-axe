#!/bin/bash
set -ev
test -d cython-hidapi || git clone  https://github.com/trezor/cython-hidapi
(cd cython-hidapi; git pull; git submodule init; git submodule update)
test -d python-trezor || git clone --branch 0.7.x https://github.com/trezor/python-trezor

cat  > ./.build-trezor.sh <<EOF
wine python -m pip install -U pip setuptools
wine python -m pip install cython
ls /opt/cython-hidapi
cd /opt/cython-hidapi; wine python setup.py build
ls /opt/python-trezor
cd /opt/python-trezor; wine python setup.py build install bdist
EOF

mkdir -p python-trezor/dist  # make sure it's owned by current user
docker run --rm -t --privileged  -v $(pwd):/opt \
       -e WINEPREFIX="/wine/wine-py2.7.8-32" \
       ogrisel/python-winbuilder \
       sh /opt/.build-trezor.sh

(cd python-trezor/dist ; unzip -o trezor-*.win32.zip)
