"""Offscreen smoke test: build the widget, let the router source feed it, report + snapshot.

Renders with the offscreen Qt platform (needs QT_QPA_FONTDIR so text is drawn),
so nothing appears on the user's desktop.
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
import RouterSight as N

app = QApplication(sys.argv)
app.setStyle('Fusion')
app.setQuitOnLastWindowClosed(False)
widget = N.RouterWidget()
widget.show()

print('charts       :', sorted(widget.charts.keys()))
print('data source  :', widget.get_data_source())
print('charts cfg   :', [t[0] for t in widget._get_selected_charts()])

samples = []


def grab():
    widget.grab().save('widget_preview.png')


def sample():
    c = widget.charts
    samples.append((round(c['cpu'].value, 1), round(c['memory'].value, 1),
                    round(c['disk'].value, 1), round(c['network'].value, 1),
                    round(c.get('upload').value, 1) if c.get('upload') else None,
                    c['connections'].tcp_value, c['connections'].udp_value,
                    widget.is_online))


def finish():
    sample()
    grab()
    print('--- samples (cpu%, mem%, diskKiB/s, downKbps, upKbps, tcp, udp, online) ---')
    for s in samples:
        print('   ', s)
    print('--- card text (what the widget paints) ---')
    order = ['cpu', 'memory', 'disk', 'network', 'upload', 'connections']
    for k in order:
        ch = widget.charts.get(k)
        if ch is None:
            print('    %-12s MISSING' % k)
            continue
        print('    %-12s %s' % (k, ch.title + ' / ' + ch._format_value_text()))
    ns = (widget.metrics_data or {}).get('router', {})
    print('interface    :', ns.get('interface'), '| source:', ns.get('source'),
          '| rx_kbps:', ns.get('rx_kbps'), '| tx_kbps:', ns.get('tx_kbps'))
    print('last error   :', getattr(widget, 'last_error', None) or '(none)')
    dlg = N.SettingsDialog(widget)
    print('settings dlg :', dlg.size().width(), 'x', dlg.size().height())
    dlg.grab().save('dialog_preview.png')
    try:
        dlg.net_interface.setCurrentIndex(0)
        print('iface combo  :', [dlg.net_interface.itemData(i) for i in range(dlg.net_interface.count())])
    except Exception as exc:
        print('iface combo  : error', exc)
    print('card checks  :', {name: cb.isChecked() for name, cb in (
        ('cpu', dlg.show_cpu_chart), ('mem', dlg.show_memory_chart), ('disk', dlg.show_disk_chart),
        ('down', dlg.show_network_chart), ('up', dlg.show_upload_chart),
        ('conn', dlg.show_connections_chart), ('edge_hide', dlg.edge_hide),
        ('click_through', dlg.click_through))})
    widget.close_router()
    app.quit()


for t in (2000, 4000, 6000):
    QTimer.singleShot(t, sample)
QTimer.singleShot(6200, finish)
sys.exit(app.exec_())
