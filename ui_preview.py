# -*- coding: utf-8 -*-
'''Offscreen render of the settings dialog (both themes) for visual review.

QT_QPA_FONTDIR points at C:\\Windows\\Fonts, otherwise the offscreen platform
has no fonts and every label renders blank.
    python mod\\ui_preview.py
'''
import os
import sys

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ['QT_QPA_FONTDIR'] = r'C:\Windows\Fonts'

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.chdir(HERE)

from PyQt5.QtWidgets import QApplication  # noqa: E402

app = QApplication([])
app.setStyle('Fusion')
import RouterSight as M  # noqa: E402

dlg = M.SettingsDialog()
dlg.show()
app.processEvents()

for index, name in ((1, 'dark'), (0, 'light')):
    dlg.theme_select.setCurrentIndex(index)
    app.processEvents()
    dlg.adjustSize()
    app.processEvents()
    out = os.path.join(HERE, 'ui_%s.png' % name)
    dlg.grab().save(out)
    print(name, dlg.width(), 'x', dlg.height(), '->', out, os.path.getsize(out))

links = M.ShortcutLinksDialog()
links.resize(links.sizeHint())
app.processEvents()
out = os.path.join(HERE, 'ui_links.png')
links.grab().save(out)
print('links', links.width(), 'x', links.height(), '->', out, os.path.getsize(out))
