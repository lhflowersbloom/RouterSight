"""Render the tray/context menu offscreen so the themed menu can be inspected
without touching the user's desktop.  Writes ui_menu.png next to this file."""
import os
import sys

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
# Windows 下离屏渲染要显式指字体目录才画得出字；Linux 交给 fontconfig
if sys.platform == 'win32':
    os.environ.setdefault('QT_QPA_FONTDIR', r'C:\Windows\Fonts')
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from PyQt5.QtWidgets import QApplication, QMenu          # noqa: E402
import RouterSight as N                                   # noqa: E402

app = QApplication(sys.argv)
app.setStyle('Fusion')

widget = N.RouterWidget()
menu = getattr(widget, '_tray_menu', None)
if menu is None:
    widget._create_tray_menu()
    menu = widget._tray_menu

print('tray labels:', [a.text() for a in menu.actions()])
menu.show()
app.processEvents()
menu.adjustSize()
app.processEvents()
out = os.path.join(HERE, 'ui_menu.png')
menu.grab().save(out)
print('menu -> %s  (%dx%d)' % (out, menu.width(), menu.height()))

menu.hide()
widget.close()
print('OK')
os._exit(0)
