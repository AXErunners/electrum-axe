#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Search and replaces BTC addresses and private keys in WIF to DASH variant"""

import click
import imp
import re

imp.load_module('electrum_dash', *imp.find_module('../../electrum_dash'))

from electrum_dash import constants
from electrum_dash.bitcoin import (b58_address_to_hash160, hash160_to_b58_address,
                         serialize_privkey, DecodeBase58Check, WIF_SCRIPT_TYPES)
from electrum_dash.util import inv_dict


ADDR_PATTERN = re.compile(
    '([123456789ABCDEFGHJKLMNPQRSTUVWXYZ'
    'abcdefghijkmnopqrstuvwxyz]{20,80})')

def deserialize_btc_priv(val):
    try:
        vch = DecodeBase58Check(val)
    except:
        return None, None, None

    if vch[0] != 0x80:
        return None, None, None

    if len(vch) not in [33, 34]:
        return None, None, None

    txin_type = inv_dict(WIF_SCRIPT_TYPES)[vch[0] - 0x80]
    compressed = len(vch) == 34

    return txin_type, vch[1:33], compressed


CONTEXT_SETTINGS = dict(help_option_names=['-h', '--help'])
@click.command(context_settings=CONTEXT_SETTINGS)
@click.option('-i', '--input-file', required=True,
              help='Input file')
@click.option('-n', '--dry-run', is_flag=True,
              help='Only show what will be changed')
@click.option('-o', '--output-file',
              help='Output file')
@click.option('-p', '--inplace', is_flag=True,
              help='Replace data inplace')
@click.option('-t', '--testnet', is_flag=True,
              help='Use testnet network constants')
def main(**kwargs):
    input_file = kwargs.pop('input_file')
    output_file = kwargs.pop('output_file', None)
    inplace = kwargs.pop('inplace', False)
    dry_run = kwargs.pop('dry_run', False)
    testnet = kwargs.pop('testnet', False)

    if testnet:
        constants.set_testnet()
        BTC_ADDRTYPE_P2PKH = 111
        BTC_ADDRTYPE_P2SH = 196
    else:
        BTC_ADDRTYPE_P2PKH = 0
        BTC_ADDRTYPE_P2SH = 5

    net = constants.net

    if inplace:
        output_file = input_file

    olines = []
    total_sub = 0
    for ln, l in enumerate(open(input_file, 'r').read().splitlines()):
        pos = 0
        ol = ''

        while pos < len(l):
            m = ADDR_PATTERN.search(l, pos)
            if not m:
                ol += l[pos:]
                break

            ol += l[pos:m.start()]
            val = m.group()

            try:
                addrtype, h = b58_address_to_hash160(val)
            except:
                h = None

            if h and addrtype == BTC_ADDRTYPE_P2PKH:
                new_val = hash160_to_b58_address(h, net.ADDRTYPE_P2PKH)
                total_sub +=1
            elif h and addrtype == BTC_ADDRTYPE_P2SH:
                new_val = hash160_to_b58_address(h, net.ADDRTYPE_P2SH)
                total_sub +=1
            else:
                new_val = None


            if not new_val:
                try:
                    txin_type, privkey, compressed = deserialize_btc_priv(val)
                except Exception as e:
                    privkey = None

                if privkey:
                    new_val = serialize_privkey(privkey, compressed, txin_type,
                                                internal_use=True)

            if dry_run and new_val:
                print('line %s, col %s: %s => %s' % (
                    ln, m.start(), val, new_val
                ))

            ol += new_val if new_val else val
            pos = m.end()

        olines.append(ol)

    out = '\n'.join(olines)
    if not output_file:
        print(out)
    elif not dry_run:
        with open(output_file, 'w') as wfd:
            wfd.write('%s\n' % out)
    else:
        print('Total sub count:', total_sub)


if __name__ == '__main__':
    main()
