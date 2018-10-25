Dash-Electrum - Lightweight Dashpay client
=====================================

::

  Licence: MIT Licence
  Author: Thomas Voegtlin
  Language: Python
  Homepage: https://electrum.dash.org/


.. image:: https://travis-ci.org/akhavr/electrum-dash.svg?branch=master
    :target: https://travis-ci.org/akhavr/electrum-dash
    :alt: Build Status





Getting started
===============


Use PPA setup
-------------

On Ubuntu/Linux Mint you can try to install Dash-Electrum with next commands::

    sudo add-apt-repository ppa:akhavr/dash-electrum
    sudo apt-get update
    sudo apt-get install dash-electrum


Use source distribution
-----------------------

Dash-Electrum is a pure python application. If you want to use the
Qt interface, install the Qt dependencies::

    sudo apt-get install python3-pyqt5

If you downloaded the official package (tar.gz), you can run
Dash-Electrum from its root directory, without installing it on your
system; all the python dependencies are included in the 'packages'
directory (except x11-hash).

To install x11-hash dependency in the 'packages' dir run once::

    pip3 install -t packages x11-hash

To run Dash-Electrum from its root directory, just do::

    ./electrum-dash

You can also install Dash-Electrum on your system, by running this command::

    sudo apt-get install python3-setuptools
    pip3 install .[fast]

This will download and install the Python dependencies used by
Dash-Electrum, instead of using the 'packages' directory.
The 'fast' extra contains some optional dependencies that we think
are often useful but they are not strictly needed.

If you cloned the git repository, you need to compile extra files
before you can run Dash-Electrum. Read the next section, "Development
Version".


Using Tor proxy
===============

Starting from Dash-Electrum release 3.2.3.1 automatic Tor Proxy
detection and use on wallet startup is added to
`Network <docs/tor/tor-proxy-on-startup.md>`_ preferences.

To use Tor Proxy on Ubuntu set it up with::

    sudo apt-get install tor
    sudo service tor start

Other platforms setup is described at `docs/tor.md <docs/tor.md>`_

Development version
===================

Check out the code from GitHub::

    git clone https://github.com/akhavr/electrum-dash.git
    cd electrum-dash

Run install (this should install dependencies)::

    pip3 install .[fast]

Render the SVG icons to PNGs (optional)::

    for i in lock unlock confirmed status_lagging status_disconnected status_connected_proxy status_connected status_waiting preferences; do convert -background none icons/$i.svg icons/$i.png; done

Compile the icons file for Qt::

    sudo apt-get install pyqt5-dev-tools
    pyrcc5 icons.qrc -o electrum_dash/gui/qt/icons_rc.py

Compile the protobuf description file::

    sudo apt-get install protobuf-compiler
    protoc --proto_path=electrum_dash --python_out=electrum_dash electrum_dash/paymentrequest.proto

Create translations (optional)::

    sudo apt-get install python-requests gettext
    ./contrib/make_locale




Creating Binaries
=================


To create binaries, create the 'packages' directory::

    ./contrib/make_packages

This directory contains the python dependencies used by Dash-Electrum.

Android
-------

See `electrum_dash/gui/kivy/Readme.txt` file.
