#!/bin/sh

./contrib/make_locale
./contrib/make_packages
mv contrib/packages .
python3 setup.py sdist --format=zip,gztar
