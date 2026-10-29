# -*- coding: utf-8 -*-
'''渲染密码框「小眼睛」的两种状态（隐藏 / 显示明文），用于目视确认。'''
import os
import sys

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
# Windows 下离屏渲染要显式指字体目录才画得出字；Linux 交给 fontconfig
if sys.platform == 'win32':
    os.environ['QT_QPA_FONTDIR'] = r'C:\Windows\Fonts'

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.chdir(HERE)

from PyQt5.QtWidgets import QApplication  # noqa: E402

app = QApplication([])
app.setStyle('Fusion')
import RouterSight as M  # noqa: E402

dlg = M.SettingsDialog()
dlg.router_password.setText('Qwer4321')
dlg.show()
app.processEvents()

for index, theme in ((1, 'dark'), (0, 'light')):
    dlg.theme_select.setCurrentIndex(index)
    app.processEvents()
    for checked, state in ((False, 'hidden'), (True, 'shown')):
        dlg.password_eye_button.setChecked(checked)
        app.processEvents()
        dlg.adjustSize()
        app.processEvents()
        out = os.path.join(HERE, 'ui_eye_%s_%s.png' % (theme, state))
        dlg.grab().save(out)
        row = dlg.router_password.parentWidget()
        dlg.router_password.parentWidget().grab().save(
            os.path.join(HERE, 'ui_eye_row_%s_%s.png' % (theme, state)))
        mode = '明文' if dlg.router_password.echoMode() == dlg.router_password.Normal else '掩码'
        print('%s/%s echoMode=%s -> %s' % (theme, state, mode, os.path.basename(out)))
    dlg.password_eye_button.setChecked(False)
    app.processEvents()
