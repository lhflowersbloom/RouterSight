# -*- coding: utf-8 -*-
"""单次健康检查：用配置文件里的正确密码连一次路由器，只打印结果。

用途：在被测程序（错误密码）仍在运行时执行，证明路由器没有被锁死。
"""
import configparser
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from routersight_router import RouterStats  # noqa: E402

here = os.path.dirname(os.path.abspath(__file__))
cp = configparser.ConfigParser()
cp.read(os.path.join(here, 'RouterSight_shipped.ini'), encoding='utf-8')
router = RouterStats(host=cp.get('Settings', 'router_host'),
                     port=cp.getint('Settings', 'router_port'),
                     username=cp.get('Settings', 'router_user'),
                     password=cp.get('Settings', 'router_password'), timeout=6.0)
try:
    ok, msg = router.test_connection()
except Exception as exc:
    ok, msg = False, '%s: %s' % (type(exc).__name__, exc)
finally:
    router.close()
print('health_check: %s - %s' % (ok, msg))
sys.exit(0 if ok else 1)
