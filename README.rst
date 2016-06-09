Electrum-DASH - lightweight Dash client
==========================================

::

  Licence: GNU GPL v3
  Original Author: Thomas Voegtlin
  Port Maintainer: Tyler Willis, Holger Schinzel
  Language: Python
  Homepage: https://electrum-dash.org/


.. image:: https://travis-ci.org/dashpay/electrum-dash.svg?branch=master
    :target: https://travis-ci.org/dashpay/electrum-dash
    :alt: Build Status


1. GETTING STARTED
------------------

To run Electrum from this directory, just do::

    ./electrum-dash

If you install Electrum on your system, you can run it from any
directory.

If you have pip, you can do::

    python setup.py sdist
    sudo pip install --pre dist/Electrum-DASH-2.0.tar.gz


If you don't have pip, install with::

    python setup.py sdist
    sudo python setup.py install



To start Electrum from your web browser, see
https://electrum-dash.org/dash_URIs.html



2. HOW OFFICIAL PACKAGES ARE CREATED
------------------------------------

On Linux/Windows::

    pyrcc4 icons.qrc -o gui/qt/icons_rc.py
    python setup.py sdist --format=zip,gztar

On Mac OS X::

    # On port based installs
    sudo python setup-release.py py2app

    # On brew installs
    ARCHFLAGS="-arch i386 -arch x86_64" sudo python setup-release.py py2app --includes sip

    sudo hdiutil create -fs HFS+ -volname "Electrum-DASH" -srcfolder dist/Electrum-DASH.app dist/electrum-dash-VERSION-macosx.dmg
