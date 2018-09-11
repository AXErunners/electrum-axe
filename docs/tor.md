# Using Dash-Electrum with Tor Proxy

## Use Tor Proxy on startup

Starting from Dash-Electrum release 3.2.3 automatic Tor Proxy
detection and use on wallet startup is added to
[Network](tor/tor-proxy-on-startup.md) preferences.

If this option is on (Default), Tor Proxy is detected firstly on proxy
configured in Network preferences and then on ports 9050, 9051.
If successfuly detected, then this proxy enabled for use,
else warning message about absent Tor proxy displayed.

## Setting up Tor proxy

* [Android](tor/tor-android.md)
* [Linux](tor/tor-linux.md)
* [macOS](tor/tor-osx.md)
* [Windows](tor/tor-windows.md)
