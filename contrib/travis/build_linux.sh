#!/bin/sh

pyrcc5 icons.qrc -o gui/qt/icons_rc.py
python3 setup.py sdist --format=zip,gztar
