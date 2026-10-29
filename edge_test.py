# -*- coding: utf-8 -*-
"""Functional test for 靠边隐藏 geometry + 鼠标穿透 ex-style.

Runs on the real Windows platform but with WA_DontShowOnScreen so the widget is
created (valid HWND, real screen geometry) without ever appearing on the desktop.
"""
import ctypes
import os
import sys

# Windows 下离屏渲染要显式指字体目录才画得出字；Linux 交给 fontconfig
if sys.platform == 'win32':
    os.environ.setdefault('QT_QPA_FONTDIR', r'C:\Windows\Fonts')
from PyQt5.QtCore import Qt  # noqa: E402
from PyQt5.QtWidgets import QApplication  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import RouterSight as N  # noqa: E402

app = QApplication(sys.argv)
widget = N.RouterWidget()
widget.setAttribute(Qt.WA_DontShowOnScreen, True)
widget.show()
app.processEvents()

area = widget._screen_area_for(widget.pos())
print('screen area  :', area.left(), area.top(), area.right(), area.bottom())
print('widget size  :', widget.width(), widget.height())

ok = True


def check(label, got, want):
    global ok
    good = got == want
    ok = ok and good
    print('  %-26s %-28s %s' % (label, got, 'OK' if good else 'FAIL want %s' % (want,)))


# ---- dock detection + flush + hide + reveal on all four edges -------------
for edge in ('left', 'right', 'top', 'bottom'):
    start = {'left': N.QPoint(area.left() + 3, 300),
             'right': N.QPoint(area.right() + 1 - widget.width() - 3, 300),
             'top': N.QPoint(600, area.top() + 3),
             'bottom': N.QPoint(600, area.bottom() + 1 - widget.height() - 3)}[edge]
    widget.move(start)
    check('%s detect' % edge, widget._detect_dock_edge(), edge)
    widget._dock_to_edge()
    check('%s dock_edge' % edge, widget._dock_edge, edge)
    flush = widget.pos()
    check('%s flush visible' % edge, widget._edge_hidden, False)
    widget._hide_at_edge()
    hidden = widget.pos()
    check('%s hidden flag' % edge, widget._edge_hidden, True)
    if edge == 'left':
        check('  left strip', hidden.x() + widget.width() - area.left(), N.EDGE_HIDE_STRIP)
    if edge == 'right':
        check('  right strip', area.right() + 1 - hidden.x(), N.EDGE_HIDE_STRIP)
    if edge == 'top':
        check('  top strip', hidden.y() + widget.height() - area.top(), N.EDGE_HIDE_STRIP)
    if edge == 'bottom':
        check('  bottom strip', area.bottom() + 1 - hidden.y(), N.EDGE_HIDE_STRIP)
    widget._reveal_from_edge()
    check('%s reveal' % edge, widget.pos(), flush)

# ---- away from any edge = not docked --------------------------------------
widget.move(area.left() + 120, area.top() + 120)
check('middle detect', widget._detect_dock_edge(), None)
widget._dock_to_edge()
check('middle undock', widget._dock_edge, None)
check('middle timer off', widget._edge_timer.isActive(), False)

# ---- click-through: real WS_EX_TRANSPARENT round trip ---------------------
import platform  # noqa: E402
if platform.system() == 'Windows':
    hwnd = int(widget.winId())
    user32 = ctypes.windll.user32
    GWL_EXSTYLE = -20
    WS_EX_TRANSPARENT = 0x00000020
    WS_EX_LAYERED = 0x00080000
    before = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    print('  hwnd 0x%x exstyle before 0x%08x' % (hwnd, before & 0xFFFFFFFF))
    widget._apply_click_through(True)
    on = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    check('穿透 on  TRANS set', bool(on & WS_EX_TRANSPARENT), True)
    check('穿透 on  LAYERED set', bool(on & WS_EX_LAYERED), True)
    widget._apply_click_through(False)
    off = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    check('穿透 off TRANS cleared', bool(off & WS_EX_TRANSPARENT), False)
    check('穿透 off style restored', off, before)

# ---- tray menu must not offer 显示/隐藏 or 锁定/解锁 ------------------------
labels = [text for text, _slot in widget._tray_actions()]
print('tray labels  :', labels)
check('no 显示/隐藏', any('显示' in t for t in labels), False)
check('no 锁定/解锁', any('锁定' in t for t in labels), False)
check('has 鼠标穿透', any('穿透' in t for t in labels), True)

# ---- config: new keys present, legacy keys still readable ------------------
cm = widget.config_manager
print('edge_hide=%s click_through=%s' % (cm.getboolean('edge_hide', True), cm.getboolean('click_through', False)))
print('config file  :', cm.config_file)
print('has legacy key widget_locked :', cm.config.has_option('Settings', 'widget_locked'))

widget._edge_timer.stop()
print('\nRESULT:', 'ALL OK' if ok else 'FAILURES PRESENT')
sys.exit(0 if ok else 1)
