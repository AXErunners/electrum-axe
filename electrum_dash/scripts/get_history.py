#!/usr/bin/env python3

import sys
from .. import Network
from electrum_dash.util import json_encode, print_msg
from electrum_dash import bitcoin

try:
    addr = sys.argv[1]
except Exception:
    print("usage: get_history <dash_address>")
    sys.exit(1)

n = Network()
n.start()
_hash = bitcoin.address_to_scripthash(addr)
h = n.get_history_for_scripthash(_hash)
print_msg(json_encode(h))
