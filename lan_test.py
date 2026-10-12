"""Prove the 2x/3x display bug and that the fix removes it.

Pulls a large stream from the router (a one-directional LAN flow), samples the
router's interfaces while it runs, and reports for each sample:

  * the interface NetSight now displays, with its two directions kept apart;
  * what the OLD code showed - Netdata's system.net = sum of |InOctets| + |OutOctets|
    over every interface, which counts one flow once per link it crosses.

Run:  python lan_test.py [--mb 600] [--password X]
"""
import argparse
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import paramiko
from netsight_router import RouterStats

MONITORED = ('eth0', 'eth1', 'br-lan')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--mb', type=int, default=600)
    parser.add_argument('--password', default=os.environ.get('NETSIGHT_ROUTER_PASSWORD', ''))
    parser.add_argument('--interface', default='eth1')
    args = parser.parse_args()

    password = args.password
    if not password:
        print('need --password or NETSIGHT_ROUTER_PASSWORD')
        return 2

    rs = RouterStats(host='192.168.9.1', port=22, username='root', password=password, interface=args.interface)
    ok, message = rs.test_connection()
    print('connection:', ok, '-', message)
    if not ok:
        return 1

    count = max(1, args.mb * 1024 // 64)
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect('192.168.9.1', port=22, username='root', password=password, timeout=8, allow_agent=False, look_for_keys=False)
    transport = client.get_transport()
    transport.set_keepalive(15)
    print('pulling %d MB from the router over the LAN (one direction only)...' % args.mb)

    done = threading.Event()

    def pull():
        try:
            channel = transport.open_session()
            channel.exec_command('dd if=/dev/zero bs=64k count=%d 2>/dev/null' % count)
            channel.settimeout(None)
            while True:
                chunk = channel.recv(262144)
                if not chunk:
                    break
        except Exception as exc:
            print('transfer error:', exc)
        finally:
            done.set()

    rs.sample()
    worker = threading.Thread(target=pull, daemon=True)
    worker.start()
    time.sleep(0.6)

    rows = []
    while not done.is_set():
        sample = rs.sample()
        net = sample.get('net', {})
        chosen = net.get(args.interface, {})
        legacy = sum(abs(item.get('rx_kbps', 0.0)) + abs(item.get('tx_kbps', 0.0)) for item in net.values())
        rows.append((chosen.get('rx_kbps', 0.0), chosen.get('tx_kbps', 0.0), legacy,
                     [(name, round(net.get(name, {}).get('rx_kbps', 0.0), 1), round(net.get(name, {}).get('tx_kbps', 0.0), 1)) for name in MONITORED]))
        time.sleep(1.0)

    worker.join(timeout=5)
    client.close()
    rs.close()

    print()
    print('%-26s %-24s %-22s' % ('NEW display (one iface)', 'what OLD code showed', 'per-interface rx/tx kb/s'))
    print('%-26s %-24s %-22s' % ('down / up kb/s', 'all-iface |in|+|out|', 'eth0, eth1, br-lan'))
    print('-' * 96)
    peak = 0.0
    for down, up, legacy, per in rows:
        peak = max(peak, down, up)
        print('%-26s %-24s %s' % ('%9.1f / %-9.1f' % (down, up), '%12.1f kb/s' % legacy, per))

    active = [row for row in rows if max(row[0], row[1]) > 200.0]
    if active and peak > 0:
        first = active[len(active) // 2]
        one_way = max(first[0], first[1])
        ratio = first[2] / one_way if one_way else 0.0
        print()
        print('active sample: one interface sees %.1f kb/s one-way; the old all-interface sum showed %.1f kb/s (%.1fx).'
              % (one_way, first[2], ratio))
        print('verdict:', 'OLD WOULD HAVE DOUBLED (or worse)' if ratio > 1.4 else 'no multiplying flow observed')
    else:
        print()
        print('verdict: transfer too fast to catch - increase --mb')
    return 0


if __name__ == '__main__':
    sys.exit(main())
