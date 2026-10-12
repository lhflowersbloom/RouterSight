# -*- coding: utf-8 -*-
"""确认「连续用错密码」不会再把路由器的 SSH 会话占满。

背景：修复前 _connect() 失败不关闭 SSHClient，残留套接字累计到 5 个后
路由器（dropbear）会拒绝一切新会话（Error reading SSH protocol banner）。
本脚本用错密码连续尝试，每一轮之后立刻用**正确**密码做一次真实连接；
只要正确连接始终成功，就说明路由器没有被锁死。

密码从配置文件中读取，不写在脚本里。
用法：python recover_test.py [--ini RouterSight_shipped.ini] [--rounds 4]
"""
import argparse
import configparser
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from routersight_router import RouterStats  # noqa: E402


def connect(host, port, user, password):
    router = RouterStats(host=host, port=port, username=user, password=password, timeout=6.0)
    try:
        ok, msg = router.test_connection()
    except Exception as exc:
        ok, msg = False, '%s: %s' % (type(exc).__name__, exc)
    finally:
        router.close()
    return ok, msg


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser()
    ap.add_argument('--ini', default=os.path.join(here, 'RouterSight_shipped.ini'))
    ap.add_argument('--rounds', type=int, default=4)
    ap.add_argument('--gap', type=float, default=1.5)
    args = ap.parse_args()

    cp = configparser.ConfigParser()
    if not cp.read(args.ini, encoding='utf-8'):
        print('读不到配置文件: %s' % args.ini)
        return 2
    host = cp.get('Settings', 'router_host', fallback='192.168.9.1')
    port = cp.getint('Settings', 'router_port', fallback=22)
    user = cp.get('Settings', 'router_user', fallback='root')
    password = cp.get('Settings', 'router_password', fallback='')
    print('目标 %s:%d 用户 %s（密码来自 %s）' % (host, port, user, os.path.basename(args.ini)))

    ok, msg = connect(host, port, user, password)
    print('起始校验（正确密码）: %s - %s' % (ok, msg))
    if not ok:
        print('起始就不通，先排查网络，本测试无意义')
        return 2

    all_ok = True
    for i in range(1, args.rounds + 1):
        bad_ok, bad_msg = connect(host, port, user, 'wrong-password-%d' % i)
        time.sleep(args.gap)
        good_ok, good_msg = connect(host, port, user, password)
        all_ok = all_ok and good_ok
        print('第 %d 轮: 错误密码 -> %-28s | 紧接着正确密码 -> %s (%s)'
              % (i, str(bad_msg)[:28], good_ok, str(good_msg)[:30]))

    time.sleep(args.gap)
    final_ok, final_msg = connect(host, port, user, password)
    all_ok = all_ok and final_ok
    print('结束校验（正确密码）: %s - %s' % (final_ok, final_msg))
    print('判定: %s' % ('通过（错误密码轰炸后路由器仍正常接受连接）' if all_ok
                      else '未通过（路由器被占满，正确密码也连不上）'))
    return 0 if all_ok else 1


if __name__ == '__main__':
    sys.exit(main())
