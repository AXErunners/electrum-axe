============
.. image:: icons/electrum-axe.png
    :alt: Electrum-AXE logo
.. image:: https://travis-ci.org/AXErunners/electrum-axe.svg?branch=master
    :target: https://travis-ci.org/AXErunners/electrum-axe
Axe Electrum - Lightweight AXE client
    :alt: Build Status

Getting started
---------------


Use PPA setup
-------------

On Ubuntu/Linux Mint you can try to install Axe Electrum with next commands::

    sudo add-apt-repository ppa:axerunners/axe-electrum
    sudo apt-get update
    sudo apt-get install axe-electrum


Use source distribution
-----------------------

Axe Electrum is a pure python application. If you want to use the
Qt interface, install the Qt dependencies::

    sudo apt-get install python3-pyqt5

If you downloaded the official package (tar.gz), you can run
Axe Electrum from its root directory without installing it on your
system; all the python dependencies are included in the 'packages'
directory (except x11-hash).

To install x11-hash dependency in the 'packages' dir run once::

    python3 -m pip install -t packages x11-hash

To install precise tested versions of HW libs (trezor, ledeger, etc) run once::

    python3 -m pip install -t packages -r contrib/deterministic-build/requirements-hw.txt

To install precise tested version of pyqt5 run once::

    python3 -m pip install -t packages -r contrib/deterministic-build/requirements-binaries.txt

To run Axe Electrum from its root directory, just do::

    ./electrum-axe

You can also install Axe Electrum on your system, by running this command::

    sudo apt-get install python3-setuptools
    python3 -m pip install .[fast]

This will download and install the Python dependencies used by
Axe Electrum instead of using the 'packages' directory.
The 'fast' extra contains some optional dependencies that we think
are often useful but they are not strictly needed.

If you cloned the git repository, you need to compile extra files
before you can run Axe Electrum. Read the next section, "Development
Version".


Using Tor proxy
===============

Starting from Axe Electrum release 3.2.3.1 automatic Tor Proxy
detection and use on wallet startup is added to
`Network <docs/tor/tor-proxy-on-startup.md>`_ preferences.

To use Tor Proxy on Ubuntu set it up with::

    sudo apt-get install tor
    sudo service tor start

Other platforms setup is described at `docs/tor.md <docs/tor.md>`_

Development version
===================

Check out the code from GitHub::

    git clone https://github.com/axerunners/electrum-axe.git
    cd electrum-axe

Run install (this should install dependencies)::

    python3 -m pip install .[fast]


Compile the protobuf description file::

    sudo apt-get install protobuf-compiler
    protoc --proto_path=electrum_axe --python_out=electrum_axe electrum_axe/paymentrequest.proto

Create translations (optional)::

    sudo apt-get install python-requests gettext
    ./contrib/make_locale
