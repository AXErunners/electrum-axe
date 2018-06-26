#!/bin/sh

pyrcc5 icons.qrc -o gui/qt/icons_rc.py
./contrib/make_locale
./contrib/make_packages
mv contrib/packages .
python3 setup.py sdist --format=zip,gztar
