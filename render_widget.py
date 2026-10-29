"""Render the desktop widget (offscreen) in both themes, upscaled 3x for review.

Writes widget_dark_3x.png and widget_light_3x.png next to this script.
Each theme gets its own event-loop turn so the re-laid-out cards are painted
before the grab (grabbing straight after update_layout() captures a blank).
"""
import os
import sys

os.environ.setdefault('QT_LOGGING_RULES', 'qt.qpa.fonts=false')
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
# Windows 下离屏渲染要显式指字体目录才画得出字；Linux 交给 fontconfig
if sys.platform == 'win32':
    os.environ.setdefault('QT_QPA_FONTDIR', r'C:\Windows\Fonts')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import QTimer
from PIL import Image
import RouterSight as N

app = QApplication(sys.argv)
app.setStyle('Fusion')
app.setQuitOnLastWindowClosed(False)
widget = N.RouterWidget()
widget.show()

THEMES = [(1, 'widget_dark_3x.png'), (0, 'widget_light_3x.png')]
state = {'i': 0}


def apply_next():
    if state['i'] >= len(THEMES):
        print('cards:', [t[0] for t in widget._get_selected_charts()])
        widget.close_router()
        app.quit()
        return
    theme, _ = THEMES[state['i']]
    widget.preview_config = {'theme': theme}
    widget.update_layout()
    widget.show()
    app.processEvents()
    QTimer.singleShot(700, grab_current)


def grab_current():
    theme, name = THEMES[state['i']]
    path = name.replace('_3x', '')
    app.processEvents()
    shot = widget.grab()
    # The widget is translucent; composite over neutral grey so cards stay visible
    # in a preview image regardless of the desktop behind it.
    shot.save(path)
    im = Image.open(path).convert('RGBA')
    alpha = im.getchannel('A')
    print('   raw %s alpha min/max = %d/%d' % (path, alpha.getextrema()[0], alpha.getextrema()[1]))
    bg = Image.new('RGBA', im.size, (120, 120, 120, 255))
    im = Image.alpha_composite(bg, im).convert('RGB')
    im.resize((im.width * 3, im.height * 3), Image.LANCZOS).save(name)
    print('%s -> %s  (%dx%d)' % (path, name, im.width * 3, im.height * 3))
    state['i'] += 1
    QTimer.singleShot(300, apply_next)


QTimer.singleShot(5000, apply_next)
sys.exit(app.exec_())
