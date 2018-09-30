# -*- coding: utf-8 -*-

import sys


try:
    from x11_hash import getPoWHash
    import_success = True
    load_libx11hash = False
except ImportError:
    import_success = False
    load_libx11hash = True


if load_libx11hash:
    from ctypes import cdll, create_string_buffer, byref

    if sys.platform == 'darwin':
        name = 'libx11hash.dylib'
    elif sys.platform in ('windows', 'win32'):
        name = 'libx11hash-0.dll'
    else:
        name = 'libx11hash.so'

    try:
        lx11hash = cdll.LoadLibrary(name)
        x11_hash = lx11hash.x11_hash
    except:
        load_libx11hash = False


if load_libx11hash:
    hash_out = create_string_buffer(32)

    def getPoWHash(header):
        x11_hash(header, byref(hash_out))
        return hash_out.raw


if not import_success and not load_libx11hash:
    raise ImportError('Can not import x11_hash')
