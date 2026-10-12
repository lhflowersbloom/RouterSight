# -*- coding: utf-8 -*-
"""连接失败时是否泄漏 SSH 套接字的回归测试。

刻意用**错误的密码**连续连接路由器，然后统计本进程与路由器 22 端口之间
仍处于打开状态的 TCP 连接数。若 _connect() 失败时没有关闭 SSHClient，
套接字会残留在 CLOSE_WAIT / ESTABLISHED 状态，累计到一定数量后路由器
（dropbear）会拒绝新会话 —— 表现为 "Error reading SSH protocol banner"。

用法：python leak_test.py [--host 192.168.9.1] [--rounds 6]
"""
import argparse
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from routersight_router import RouterStats  # noqa: E402


def sockets_to(host, port, pid):
    """本进程与 host:port 之间仍存在的 TCP 连接数。"""
    try:
        out = subprocess.run(['netstat', '-ano'], capture_output=True, text=True,
                             errors='replace').stdout
    except Exception as exc:
        print('netstat 不可用: %s' % exc)
        return -1
    needle = '%s:%d' % (host, port)
    count = 0
    for line in out.splitlines():
        parts = line.split()
        if len(parts) < 5 or not line.strip().upper().startswith('TCP'):
            continue
        if needle in parts[2] and parts[-1] == str(pid):
            count += 1
    return count


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--host', default='192.168.9.1')
    ap.add_argument('--port', type=int, default=22)
    ap.add_argument('--rounds', type=int, default=6)
    ap.add_argument('--delay', type=float, default=0.4)
    args = ap.parse_args()

    pid = os.getpid()
    print('本进程 pid=%d，目标 %s:%d，轮数 %d' % (pid, args.host, args.port, args.rounds))
    print('开始前残留连接: %d' % sockets_to(args.host, args.port, pid))

    for i in range(1, args.rounds + 1):
        router = RouterStats(host=args.host, port=args.port, username='root',
                             password='definitely-wrong-password', timeout=5.0)
        try:
            ok, msg = router.test_connection()
        except Exception as exc:
            ok, msg = False, '%s: %s' % (type(exc).__name__, exc)
        router.close()
        time.sleep(args.delay)
        n = sockets_to(args.host, args.port, pid)
        print('第 %d 轮: ok=%s  %-46s 残留连接=%d' % (i, ok, str(msg)[:46], n))

    final = sockets_to(args.host, args.port, pid)
    print('结束后残留连接: %d' % final)
    print('判定: %s' % ('通过（失败连接未残留套接字）' if final <= 1
                      else '未通过（泄漏 %d 个套接字）' % final))
    return 0 if final <= 1 else 1


if __name__ == '__main__':
    sys.exit(main())
