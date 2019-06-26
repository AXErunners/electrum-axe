#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import aiorpcx
import asyncio
import errno
import encodings.idna  # noqa: F401 (need for pyinstaller build)
import fcntl
import json
import os
import socket
import ssl
import stat
import sys
import time
from aiorpcx import RPCSession


CLIENT_NAME = 'exsrvmonit'
HOME_DIR = os.path.expanduser('~')
DATA_DIR = os.path.join(HOME_DIR, f'.{CLIENT_NAME}')
RECENT_FNAME = os.path.join(DATA_DIR, 'recent_data')
PID_FNAME = os.path.join(DATA_DIR, f'{CLIENT_NAME}.pid')
PID = str(os.getpid())
MIN_PROTO_VERSION = '1.4'
NUM_RECENT_DATA = 1440
SERVERS_LIST = [
    'electrum.dash.siampm.com:50002',
    'drk.p2pay.com:50002',
]


def get_ssl_context():
    sslc = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
    sslc.check_hostname = False
    sslc.verify_mode = ssl.CERT_NONE
    return sslc


def peer_info_as_dict(peer):
    res = {} 
    res['ip'] = peer[0] 
    res['hostname'] = peer[1] 
    for i in peer[2]: 
        if i.startswith('s') and len(i) > 1: 
            res['ssl_port'] = i[1:] 
    return res


def read_recent_file():
    if not os.path.isfile(RECENT_FNAME):
        return []
    with open(RECENT_FNAME, 'r', encoding='utf-8') as f:
        data = f.read()
        return json.loads(data)


def save_recent_file(recent):
    s = json.dumps(recent, indent=4, sort_keys=True)
    with open(RECENT_FNAME, 'w', encoding='utf-8') as f:
        f.write(s)


def add_to_recent_file(checked, failed):
    recent_data = {
        'time': time.time(),
        'checked_cnt': len(checked),
        'checked': checked,
        'failed_cnt': len(failed),
        'failed': list(failed)
    }
    recent = read_recent_file()
    recent.insert(0, recent_data)
    recent = recent[:NUM_RECENT_DATA]
    save_recent_file(recent)
    return recent


def list_recent_file():
    recent = reversed(read_recent_file())
    for r in recent:
        check_time = time.ctime(r['time'])
        checked_cnt = r['checked_cnt']
        failed_cnt = r['failed_cnt']
        print(f'{check_time}: checked {checked_cnt}, failed {failed_cnt}')
        if checked_cnt:
            print('\tChecked:')
            for k, v in r['checked'].items():
                print(f'\t\t{k}: {v}')
        if failed_cnt:
            print('\tFailed:')
            for s in r['failed']:
                print(f'\t\t{s}')


async def gather_info(server):
    try:
        host, port = server.split(':')
        sslc = get_ssl_context()
        res = {'server': server}
        async with aiorpcx.Connector(RPCSession, host=host,
                                     port=int(port), ssl=sslc) as session:
            ver = await session.send_request('server.version',
                                             [CLIENT_NAME, MIN_PROTO_VERSION])
            peers = await session.send_request('server.peers.subscribe')
            peers = [peer_info_as_dict(p) for p in peers]
            res.update({'version': ver[0], 'proto': ver[1], 'peers': peers})
            return res
    except aiorpcx.jsonrpc.RPCError:
        return res
    except (ConnectionError, TimeoutError):
        return res
    except socket.error as e:
        if e.errno == errno.ECONNREFUSED:
            return res
        raise


def check_servers_less_for_period(recent):
    recent_len = len(recent)
    minimal = args.minimal
    num_fails = args.num_fails
    if recent[0]['checked_cnt'] < minimal:
        if recent_len < num_fails:
            return
        for i in range(1, num_fails):
            if recent[i]['checked_cnt'] >= minimal:
                return
        if (recent_len > num_fails
                and recent[num_fails]['checked_cnt'] < minimal):
            return
        alert_msg_subj = f'Number of runing servers below {minimal}'
        alert_msg_body = (f'In the last {num_fails} checks number of'
                          f' runing servers below {minimal}.')
        return (alert_msg_subj, alert_msg_body)
    else:
        if recent_len < num_fails + 1:
            return
        for i in range(1, num_fails+1):
            if recent[i]['checked_cnt'] >= minimal:
                return
        alert_msg_subj = f'Number of runing servers above {minimal}'
        alert_msg_body = f'Number of runing servers again above {minimal}.'
        return (alert_msg_subj, alert_msg_body)


def check_recent_and_alert(recent, check_fn):
    alert_data = check_fn(recent)
    if not alert_data:
        return

    subj, body = alert_data

    if args.notify_cron:
        print(f'{subj}:\n{body}')

    # TODO: send emails via external services
    #if args.email_to:
    #    email_subj = f'[{CLIENT_NAME.capitalize()}] {subj}'


async def main():
    known = set(args.servers)
    failed = set()
    checked = dict()
    to_check = known.difference(checked).difference(failed)
    while to_check:
        done, pending = await asyncio.wait([gather_info(s) for s in to_check])
        for fut in done:
            res = fut.result()
            server = res['server']
            if 'version' not in res:
                failed.add(server)
            else:
                peers = res.pop('peers')
                version = res['version']
                checked[server] = version
                known.add(server)
                for p in peers:
                    if 'ssl_port' not in p:
                        continue
                    hostname = p['hostname']
                    ip = p['ip']
                    ssl_port = p['ssl_port']
                    if f'{hostname}:{ssl_port}' in known:
                        continue
                    if f'{ip}:{ssl_port}' in known:
                        continue
                    known.add(f'{hostname}:{ssl_port}')
        to_check = known.difference(checked).difference(failed)
    recent = add_to_recent_file(checked, failed)
    check_recent_and_alert(recent, check_servers_less_for_period)


def run_exclusive():
    if os.path.exists(DATA_DIR):
        if not os.path.isdir(DATA_DIR):
            print(f'{DATA_DIR} is not directory')
            sys.exit(1)
    else:
        os.mkdir(DATA_DIR)
        os.chmod(DATA_DIR, stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
    if args.list_recent:
        list_recent_file()
        sys.exit(0)
    try:
        ex_lock = False
        with open(PID_FNAME, 'wb', 0) as fp:
            fcntl.lockf(fp, fcntl.LOCK_EX | fcntl.LOCK_NB)
            ex_lock = True
            fp.write(f'{PID}\n'.encode())
            loop = asyncio.get_event_loop()
            loop.run_until_complete(main())
    except OSError as e:
        if e.errno in [errno.EACCES, errno.EAGAIN]:
            print(f'can not get exclusive access to {PID_FNAME}')
            sys.exit(1)
        else:
            raise
    finally:
        if ex_lock:
            os.unlink(PID_FNAME)


parser = argparse.ArgumentParser()
parser.add_argument('-c', '--notify-cron', default=False, action='store_true',
                    help='Notify cron by msg to console instead sending email')
parser.add_argument('-e', '--email-to', nargs='+', default=[],
                    help='List of emails to send alerts', metavar='EMAIL')
parser.add_argument('-l', '--list-recent', default=False, action='store_true',
                    help='List recent checks results')
parser.add_argument('-m', '--minimal', type=int, default=2, metavar='COUNT',
                    help='Minimal count of checked servers to not alert')
parser.add_argument('-n', '--num-fails', type=int, default=2, metavar='COUNT',
                    help='Number of sequential fails of check to alert')
parser.add_argument('-s', '--servers', nargs='+', default=SERVERS_LIST,
                    help='List of servers to check', metavar='SERVER')
args = parser.parse_args()
run_exclusive()
