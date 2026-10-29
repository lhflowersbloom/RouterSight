# ============================================================================
# RouterSight 路由视界 — 基于 NetSight v2.1.1 反编译源码修改而来
# Project         : RouterSight（路由器监控桌面小组件），由 NetSight 更名而来
# Modification    : 去掉 Netdata 依赖，改用 SSH 直读 iStoreOS 路由器；下载/上传分开统计（MB/s）；
#                   Windows 11 风格主题、靠边隐藏、鼠标穿透；取消锁定/解锁与显示/隐藏
#
# Source artifact : C:\Users\admin\Documents\NetSight.exe
#                   sha256 b91b56de5a5f3df7ccb4be552b87a9d6222f99626ce9de4b17ba20c08e04db06
#                   46,371,224 bytes, PE32+ x64
#                   PyInstaller one-file archive (packaged Python 3.13)
# Container       : PyInstaller CArchive -> NetSight-2.pyc (222,936 bytes), the
#                   ONLY application module; everything else in the archive is
#                   PyQt5 / stdlib / requests / cryptography / urllib3.
# Unpacked with   : pyinstxtractor-ng 2026.7.3
# Decompiled with : pycdc (ejfkdev/pycdc v0.6.0, Rust) — the only tool tested
#                   here that handles CPython 3.13 bytecode (Decompyle++/uncompyle6
#                   fail on 3.13 CALL_KW).
# Verified against: code objects marshal-loaded from NetSight-2.pyc with
#                   CPython 3.13.7 (254 code objects; 214/235 named functions
#                   contain every string constant and attribute name exactly).
# Hand-corrected  : 3 sites where pycdc emitted invalid/incomplete code, each
#                   restored from the bytecode disassembly:
#                     1. FaviconManager.fetch_favicon — the nested try, the
#                        common-location loop body and the file write were lost.
#                     2. ShortcutLinksDialog.import_from_text — a stray empty
#                        try/except block was invented.
#                     3. RouterWidget._get_config_value — "None(None, 0)" and
#                        "None(None, 0.0)" restored to getint/getfloat calls.
#                   Those 3 lines are exactly the only SyntaxWarnings CPython
#                   reports for the raw output; the corrected file compiles clean.
#
# Raw unmodified decompiler output: NetSight-2.rust.py (same directory).
# Identifier names and comments below are pycdc's; the original source names
# were not recoverable from the bytecode.
#
# ---------------------------------------------------------------------------
# MODIFIED (router mode — Netdata no longer required)
#   * CPU / RAM / disk / connection / traffic metrics are read from the iStoreOS
#     router itself over SSH (see routersight_router.py; read-only /proc probe).
#   * The network card no longer sums In+Out over all interfaces — that sum was
#     the "LAN transfer reads 2x" bug. One interface is reported, and download
#     and upload are separate cards.
#   * Settings gained a 路由器 (SSH) section: address / port / user / password /
#     interface. data_source=router selects it; data_source=netdata keeps the
#     original HTTP behaviour.
# ---------------------------------------------------------------------------
# ============================================================================
import sys
import os
import json
import time
import configparser
import warnings
import socket
import gc
import subprocess
import shutil
import re
from urllib.parse import urlparse, urljoin
from typing import (Dict, Any, Optional, List, Tuple, Union)
from html.parser import HTMLParser
from concurrent.futures import ThreadPoolExecutor
from PyQt5.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QMenu, QSizePolicy, QSystemTrayIcon, QAction, QColorDialog, QPushButton, QTextEdit, QGroupBox, QSpinBox, QComboBox, QCheckBox, QDialog, QFormLayout, QLineEdit, QGridLayout, QDialogButtonBox, QMessageBox, QTableWidget, QTableWidgetItem, QAbstractItemView, QDoubleSpinBox, QSlider, QFrame, QToolButton, QScrollArea)
from PyQt5.QtGui import (QPainter, QPen, QColor, QFont, QFontMetrics, QIcon, QPixmap, QPalette, QPainterPath, QBrush, QDesktopServices, QWheelEvent, QCursor)
from PyQt5.QtCore import (Qt, QTimer, QRect, QPoint, QSize, pyqtSignal, QRectF, QPointF, QUrl, QPropertyAnimation, QEasingCurve, pyqtProperty, QMetaObject)
from PyQt5.QtNetwork import (QNetworkAccessManager, QNetworkRequest, QNetworkReply)
try:
    from routersight_router import RouterStats, RouterStatsError
    _ROUTER_IMPORT_ERROR = ''
except Exception as _router_import_exc:  # keeps the app usable if the module is missing
    _ROUTER_IMPORT_ERROR = str(_router_import_exc)

    class RouterStatsError(Exception):
        pass

    class RouterStats:
        def __init__(self, *args, **kwargs):
            raise RouterStatsError('路由器模块不可用: %s' % _ROUTER_IMPORT_ERROR)
warnings.filterwarnings('ignore', message='.*sipPyTypeDict.*')
if sys.stdout is not None:
    sys.stdout.flush()


# ------------------------------------------------------------------ 平台适配
# Windows 走原有逻辑；Linux（AppImage）下资源目录、字体与系统集成都需要换一套做法。

def is_linux():
    return sys.platform.startswith('linux')


def app_base_dir():
    '''数据目录：Windows 为 exe 同目录；AppImage 为 .AppImage 文件所在目录。

    AppImage 运行时 sys.executable 指向只读挂载点 (/tmp/.mount_*/usr/bin)，
    配置写在那里重启即丢，所以改用 $APPIMAGE 的父目录，保持"绿色版"体验。
    '''
    if is_linux() and os.environ.get('APPIMAGE'):
        return os.path.dirname(os.path.abspath(os.environ['APPIMAGE']))
    if getattr(sys, 'frozen', False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def writable_base_dir():
    '''app_base_dir() 可写就返回它，否则退到 ~/.config/RouterSight。'''
    base = app_base_dir()
    try:
        if os.path.isdir(base) and os.access(base, os.W_OK):
            return base
    except Exception:
        pass
    fallback = os.path.join(os.path.expanduser('~'), '.config', 'RouterSight')
    try:
        os.makedirs(fallback, exist_ok=True)
    except Exception:
        pass
    return fallback


_FONT_FAMILY_CACHE = {}


def ui_font_family():
    '''界面字体：Windows 用微软雅黑，Linux 按 fontconfig 的实际可用字体挑一个 CJK 字体。'''
    if not is_linux():
        return '微软雅黑'
    cached = _FONT_FAMILY_CACHE.get('family')
    if cached:
        return cached
    family = 'Noto Sans CJK SC'
    try:
        from PyQt5.QtGui import QFontDatabase
        available = set(QFontDatabase().families())
        for name in ('Noto Sans CJK SC', 'Source Han Sans SC', 'Noto Sans SC',
                     'Sarasa Gothic SC', 'WenQuanYi Micro Hei', 'Droid Sans Fallback',
                     'DejaVu Sans'):
            if name in available:
                family = name
                break
    except Exception:
        pass
    _FONT_FAMILY_CACHE['family'] = family
    return family


def ui_font(size, weight=QFont.Normal):
    return QFont(ui_font_family(), size, weight)


def ui_font_px(pixel_size, weight=QFont.Normal):
    '''按像素字号建字体。

    卡片是按固定像素设计的（默认 250x120），而"点"字号会随屏幕 DPI 放大，
    X11 上 Xft.dpi 一改，文字就撑破卡片、标题与数值叠在一起。
    改用像素字号后，组件尺寸和文字排版都不再受 DPI 影响，
    保持与 Windows 100% 缩放时一致的观感。
    '''
    font = QFont(ui_font_family())
    font.setPixelSize(max(1, int(pixel_size)))
    font.setWeight(weight)
    return font


class ConfigManager:
    '''配置管理类 - 代码结构优化版'''

    DEFAULT_CONFIG = {'api_url': 'http://192.168.100.1:19999/api/v1/allmetrics?format=json', 'refresh_interval': '1', 'data_points': '50', 'layout_option': '2', 'theme': '1', 'card_opacity': '70', 'text_opacity': '50', 'chart_opacity': '90', 'card_radius': '5', 'widget_width': '250', 'widget_height': '120', 'widget_x': '-1', 'widget_y': '-1', 'widget_visible': 'True', 'widget_locked': 'False', 'widget_stays_on_top': 'False', 'show_cpu_chart': 'True', 'show_memory_chart': 'True', 'show_disk_chart': 'True', 'show_network_chart': 'True', 'show_upload_chart': 'True', 'show_connections_chart': 'True', 'edge_hide': 'True', 'click_through': 'False', 'data_source': 'router', 'router_host': '192.168.9.1', 'router_port': '22', 'router_user': 'root', 'router_password': '', 'router_key': '', 'net_interface': 'auto', 'auto_start': 'False', 'stays_on_top': 'False', 'animation_enabled': 'True', 'cache_enabled': 'True', 'performance_mode': '0', 'shortcut_button_size': '20', 'shortcut_button_radius': '5', 'shortcut_links': '[]', 'shortcut_button_position': 'bottom', 'shortcut_button_alignment': 'left', 'shortcut_display_mode': 'none', 'shortcut_animation_mode': 'default', 'shortcut_button_offset_x': '0', 'shortcut_button_offset_y': '0', 'shortcut_border_width': '0', 'shortcut_button_spacing': '5', 'shortcut_hover_scale': '1.2', 'shortcut_border_opacity': '100', 'ui_scale': '0', 'close_to_tray': 'True', 'hide_from_taskbar': 'True'}
    def __init__(self, config_file: str='RouterSight_config.ini'):
        if hasattr(self, '_initialized'):
            return
        base_dir = writable_base_dir()
        self.config_file = os.path.join(base_dir, config_file) if not os.path.isabs(config_file) else config_file
        if not os.path.exists(self.config_file):
            legacy = os.path.join(base_dir, 'NetSight_config.ini')
            if os.path.exists(legacy):
                try:
                    shutil.copyfile(legacy, self.config_file)
                except Exception:
                    pass
        self.config = configparser.ConfigParser()
        self._cache = {}
        self.load_config()
        self._initialized = True

    def load_config(self):
        if os.path.exists(self.config_file):
            try:
                self.config.read(self.config_file, encoding='utf-8')
                # The ini is only rewritten when the user hits 保存设置, so a file
                # written by an older version is missing newer keys. Fill them in
                # from DEFAULT_CONFIG (in memory only) instead of returning False.
                if not self.config.has_section('Settings'):
                    self.config.add_section('Settings')
                for key, value in self.DEFAULT_CONFIG.items():
                    if not self.config.has_option('Settings', key):
                        self.config.set('Settings', key, value)
                self._cache.clear()
            except Exception:
                self.create_default_config()
            return
        self.create_default_config()

    def create_default_config(self):
        self.config['Settings'] = self.DEFAULT_CONFIG
        self.save_config()

    def save_config(self):
        try:
            if os.path.exists(self.config_file):
                shutil.copy2(self.config_file, self.config_file + '.bak')
            with open(self.config_file, 'w', encoding='utf-8') as configfile:
                self.config.write(configfile)
        except Exception as e:
            print(f'保存配置失败: {e}')

    def get(self, key: str, fallback: Any=None) -> str:
        cache_key = f'get_{key}_{fallback}'
        if cache_key in self._cache:
            return self._cache[cache_key]
        value = self.config.get('Settings', key, fallback=fallback)
        self._cache[cache_key] = value
        return value

    def getint(self, key: str, fallback: int=0) -> int:
        cache_key = f'getint_{key}_{fallback}'
        if cache_key in self._cache:
            return self._cache[cache_key]
        try:
            value = self.config.getint('Settings', key, fallback=fallback)
        except (ValueError, configparser.NoOptionError):
            value = fallback
        self._cache[cache_key] = value
        return value

    def getfloat(self, key: str, fallback: float=0.0) -> float:
        cache_key = f'getfloat_{key}_{fallback}'
        if cache_key in self._cache:
            return self._cache[cache_key]
        try:
            value = self.config.getfloat('Settings', key, fallback=fallback)
        except (ValueError, configparser.NoOptionError):
            value = fallback
        self._cache[cache_key] = value
        return value

    def getboolean(self, key: str, fallback: bool=False) -> bool:
        cache_key = f'getboolean_{key}_{fallback}'
        if cache_key in self._cache:
            return self._cache[cache_key]
        try:
            value = self.config.getboolean('Settings', key, fallback=fallback)
        except (ValueError, configparser.NoOptionError):
            value = fallback
        self._cache[cache_key] = value
        return value

    def set(self, key: str, value: Any):
        if not self.config.has_section('Settings'):
            self.config['Settings'] = {}
        self.config.set('Settings', key, str(value))
        self._cache.clear()

    def get_shortcut_links(self) -> List[Dict]:
        try:
            return json.loads(self.get('shortcut_links', '[]'))
        except:
            return []

    def set_shortcut_links(self, links: List[Dict]):
        try:
            self.set('shortcut_links', json.dumps(links, ensure_ascii=False))
            return
        except Exception as e:
            print(f'保存快捷链接失败: {e}')


class NetworkManager:
    @staticmethod
    def check_api_connectivity(api_url, timeout=2):
        if not api_url or not api_url.strip():
            return False
        try:
            parsed_url = urlparse(api_url.strip())
            host = parsed_url.hostname or '192.168.100.1'
            port = parsed_url.port or 19999
            socket.setdefaulttimeout(timeout)
            sock = socket.create_connection((host, port), timeout=timeout)
            sock.close()
        except (OSError, ValueError, socket.timeout, socket.gaierror):
            socket.setdefaulttimeout(None)
            return False
        finally:
            socket.setdefaulttimeout(None)
        return True


class FaviconHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.favicons = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() == 'link':
            attrs_dict = dict(attrs)
            rel = attrs_dict.get('rel', '').lower()
            href = attrs_dict.get('href', '')
            if 'icon' in rel:
                if href:
                    sizes = attrs_dict.get('sizes', '')
                    priority = 0
                    if 'apple-touch-icon' in rel:
                        priority += 10
                    if sizes:
                        match = re.match('(\\d+)x(\\d+)', sizes)
                        if match:
                            width = int(match.group(1))
                            height = int(match.group(2))
                            priority += min(width * height / 100, 5)
                    self.favicons.append({'url': href, 'priority': priority, 'rel': rel, 'sizes': sizes})


class FaviconManager:
    _instance = None
    _cache_dir = None
    _cache = {}
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @classmethod
    def get_cache_dir(cls):
        if cls._cache_dir is None:
            home_dir = os.path.expanduser('~')
            cls._cache_dir = os.path.join(home_dir, '.routersight', 'favicons')
            os.makedirs(cls._cache_dir, exist_ok=True)
        return cls._cache_dir

    @classmethod
    def get_favicon_path(cls, url):
        parsed = urlparse(url)
        domain = parsed.netloc.split(':')[0] if ':' in parsed.netloc else parsed.netloc
        filename = f'{hash(domain) & 4294967295:08x}.ico'
        return os.path.join(cls.get_cache_dir(), filename)

    @classmethod
    def fetch_favicon(cls, url):
        try:
            parsed_url = urlparse(url)
            domain = parsed_url.netloc
            base_url = f'{parsed_url.scheme}://{domain}'
            cache_path = cls.get_favicon_path(url)
            if os.path.exists(cache_path) and os.path.getsize(cache_path) > 100:
                return cache_path
            import requests
            from requests.exceptions import RequestException, Timeout
            try:
                response = requests.get(url, timeout=5)
                response.raise_for_status()
                html_content = response.text
                parser = FaviconHTMLParser()
                parser.feed(html_content)
                favicon_url = None
                if parser.favicons:
                    parser.favicons.sort(key=lambda x: x['priority'], reverse=True)
                    favicon_url = parser.favicons[0]['url']
                    if not favicon_url.startswith(('http://', 'https://')):
                        favicon_url = urljoin(base_url, favicon_url)
                if not favicon_url:
                    common_locations = ['/favicon.ico', '/favicon.png', '/favicon.jpg', '/favicon.gif', '/apple-touch-icon.png', '/apple-touch-icon-precomposed.png']
                    for location in common_locations:
                        test_url = urljoin(base_url, location)
                        try:
                            test_response = requests.head(test_url, timeout=2)
                            if test_response.status_code == 200:
                                favicon_url = test_url
                                break
                        except:
                            continue
                if favicon_url:
                    favicon_response = requests.get(favicon_url, timeout=5)
                    favicon_response.raise_for_status()
                    with open(cache_path, 'wb') as f:
                        f.write(favicon_response.content)
                    return cache_path
            except (RequestException, Timeout) as e:
                print(f'获取favicon失败 ({url}): {e}')
        except Exception as e:
            print(f'处理favicon时出错 ({url}): {e}')
        return None


class PerformanceOptimizer:
    def __init__(self):
        self.mode = 0
        self.last_gc_time = time.time()
        self.gc_interval = 30

    def set_mode(self, mode):
        self.mode = mode
        if mode == 1:
            self.gc_interval = 60
            return
        if mode == 2:
            self.gc_interval = 15
            return
        self.gc_interval = 30

    def optimize_memory(self):
        current_time = time.time()
        if current_time - self.last_gc_time >= self.gc_interval:
            gc.collect()
            self.last_gc_time = current_time

    def get_animation_speed(self, base_speed=0.15):
        if self.mode == 1:
            return base_speed * 0.7
        if self.mode == 2:
            return base_speed * 1.5
        return base_speed


class ShortcutButton(QWidget):
    clicked = pyqtSignal(str)
    favicon_loaded = pyqtSignal()
    def __init__(self, name, link, icon_char=None, icon_image=None, border_color=None, border_opacity=None, parent=None):
        super().__init__(parent)
        self.name = name
        self.link = self._clean_path(link) if link else link
        self.icon_char = icon_char
        self.icon_image = self._clean_path(icon_image) if icon_image else icon_image
        self.favicon_path = None
        self.is_web_link = False
        self.favicon_loading = False
        self.favicon_loaded_success = False
        if self.link and self.link.startswith(('http://', 'https://')):
            self.is_web_link = True
        self.border_color, self.border_opacity = self._parse_border_color(border_color, border_opacity)
        self.display_char = self._get_display_char()
        self.size = 20
        self.radius = 5
        self.border_width = 0
        self._opacity = 1.0
        self._scale = 1.0
        self.is_hovered = False
        self.is_pressed = False
        self.hover_animation = QPropertyAnimation(self, b'scale')
        self.hover_animation.setDuration(150)
        self.hover_animation.setEasingCurve(QEasingCurve.OutBack)
        self.calculated_size = self.size + abs(self.border_width) * 2
        self.setFixedSize(self.calculated_size, self.calculated_size)
        self.setMouseTracking(True)
        self.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.favicon_loaded.connect(self.on_favicon_loaded)

    def _parse_border_color(self, border_color, border_opacity):
        if border_color:
            if isinstance(border_color, str) and border_color.startswith('rgba('):
                import re
                match = re.match('rgba\\((\\d+),\\s*(\\d+),\\s*(\\d+),\\s*([\\d.]+)\\)', border_color)
                if match:
                    r, g, b, a = map(float, match.groups())
                    color = QColor(int(r), int(g), int(b))
                    opacity = int(a * 100)
                    return color, opacity
                color = QColor(border_color)
                opacity = border_opacity if border_opacity is not None else 100
                return color, opacity
            color = QColor(border_color)
            opacity = border_opacity if border_opacity is not None else 100
            return color, opacity
        return QColor(0, 0, 0), border_opacity if border_opacity is None else 100

    def _get_display_char(self) -> str:
        if self.icon_image and self.icon_image.strip() and os.path.exists(self._clean_path(self.icon_image)):
            return
        if self.icon_char and self.icon_char.strip():
            return self.icon_char.strip()[0].upper()
        if self.name and self.name.strip():
            return self.name.strip()[0].upper()
        if self.link and self.link.startswith(('http://', 'https://')):
            try:
                parsed_url = urlparse(self.link)
                domain = parsed_url.netloc
                if domain:
                    if domain.startswith('www.'):
                        domain = domain[4:]
                    if domain:
                        return domain[0].upper()
                    return '?'
            except:
                return '?'
        if self.link:
            clean_link = self._clean_path(self.link)
            if os.path.splitext(clean_link)[1]:
                ext = os.path.splitext(clean_link)[1]
                if len(ext) > 1:
                    return ext[1].upper()
        return '?'

    def _clean_path(self, path: Optional[str]) -> Optional[str]:
        if not path:
            return path
        cleaned = path.strip()
        if cleaned.startswith('"') and cleaned.endswith('"') or cleaned.startswith("'") and cleaned.endswith("'"):
            cleaned = cleaned[1:-1]
        return cleaned

    @pyqtProperty(float)
    def opacity(self):
        return self._opacity

    @opacity.setter
    def opacity(self, value):
        self._opacity = max(0.0, min(1.0, value))
        self.update()

    @pyqtProperty(float)
    def scale(self):
        return self._scale

    @scale.setter
    def scale(self, value):
        self._scale = max(0.0, min(2.0, value))
        self.update()

    def set_size(self, size):
        self.size = size
        self.calculated_size = self.size + abs(self.border_width) * 2
        self.setFixedSize(self.calculated_size, self.calculated_size)
        self.update()

    def set_radius(self, radius):
        self.radius = radius
        self.update()

    def set_border_width(self, width):
        self.border_width = width
        self.calculated_size = self.size + abs(self.border_width) * 2
        self.setFixedSize(self.calculated_size, self.calculated_size)
        self.update()

    def set_border_color(self, color, opacity=None):
        self.border_color, self.border_opacity = self._parse_border_color(color, opacity)
        self.update()

    def set_border_opacity(self, opacity):
        self.border_opacity = max(0, min(100, opacity))
        self.update()

    def get_border_color_string(self):
        if self.border_opacity < 100:
            return f'rgba({self.border_color.red()}, {self.border_color.green()}, {self.border_color.blue()}, {self.border_opacity / 100:.2f})'
        return self.border_color.name()

    def start_favicon_load(self):
        if not self.is_web_link or self.favicon_loading or self.favicon_loaded_success:
            return
        self.favicon_loading = True
        executor = ThreadPoolExecutor(max_workers=1)
        def load_favicon():
            try:
                favicon_path = FaviconManager.fetch_favicon(self.link)
                if favicon_path and os.path.exists(favicon_path):
                    self.favicon_path = favicon_path
                    self.favicon_loaded_success = True
                    self.favicon_loaded.emit()
            except Exception as e:
                print(f'加载favicon失败: {e}')
            finally:
                self.favicon_loading = False

        executor.submit(load_favicon)
        executor.shutdown(wait=False)

    def on_favicon_loaded(self):
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        bg_color, text_color = self._get_theme_colors()
        card_opacity, text_opacity = self._get_opacity_settings()
        bg_alpha = int(card_opacity * self._opacity)
        text_alpha = int(text_opacity * self._opacity)
        bg_color.setAlpha(bg_alpha)
        text_color.setAlpha(text_alpha)
        center_x = self.width() / 2
        center_y = self.height() / 2
        painter.save()
        if self._scale != 1.0:
            painter.translate(center_x, center_y)
            painter.scale(self._scale, self._scale)
            painter.translate(-center_x, -center_y)
        scaled_width = self.width()
        scaled_height = self.height()
        total_rect = QRectF(0, 0, scaled_width, scaled_height)
        border_offset = self.border_width
        button_rect = QRectF(total_rect.left() + border_offset, total_rect.top() + border_offset, total_rect.width() - 2 * border_offset, total_rect.height() - 2 * border_offset)
        if self.border_width != 0:
            if self.border_width > 0:
                border_rect = total_rect
                border_radius = self.radius + self.border_width
            else:
                border_rect = QRectF(total_rect.left() - self.border_width, total_rect.top() - self.border_width, total_rect.width() + 2 * self.border_width, total_rect.height() + 2 * self.border_width)
                border_radius = max(0, self.radius + self.border_width)
            border_path = QPainterPath()
            border_path.addRoundedRect(border_rect, border_radius, border_radius)
            border_color = QColor(self.border_color)
            border_alpha = int(bg_alpha * (self.border_opacity / 100.0))
            border_color.setAlpha(border_alpha)
            painter.fillPath(border_path, border_color)
        path = QPainterPath()
        path.addRoundedRect(button_rect, self.radius, self.radius)
        if self.is_pressed:
            bg_color = bg_color.darker(120)
        elif self.is_hovered:
            bg_color = bg_color.lighter(120)
        painter.fillPath(path, bg_color)
        painter.restore()
        painter.save()
        if self._scale != 1.0:
            painter.translate(center_x, center_y)
            painter.scale(self._scale, self._scale)
            painter.translate(-center_x, -center_y)
        scaled_button_rect = QRectF(button_rect.left(), button_rect.top(), button_rect.width(), button_rect.height())
        display_done = False
        if not display_done:
            if self.icon_image:
                clean_icon_path = self._clean_path(self.icon_image)
                if clean_icon_path and os.path.exists(clean_icon_path):
                    try:
                        self._draw_icon_image(painter, scaled_button_rect, clean_icon_path)
                        display_done = True
                    except Exception as e:
                        print(f'显示图标图片失败: {e}, 路径: {clean_icon_path}')
        if not display_done:
            if self.is_web_link and self.favicon_path and os.path.exists(self.favicon_path):
                try:
                    self._draw_icon_image(painter, scaled_button_rect, self.favicon_path)
                    display_done = True
                except Exception as e:
                    print(f'显示favicon失败: {e}')
                    if not self.favicon_loading:
                        self.start_favicon_load()
        if not display_done:
            if self.display_char:
                self._draw_text_icon(painter, scaled_button_rect, text_color)
                if self.is_web_link and not self.favicon_loading and not self.favicon_loaded_success:
                    self.start_favicon_load()
        painter.restore()

    def _draw_icon_image(self, painter, rect, icon_path):
        icon_path = self._clean_path(icon_path)
        if not icon_path or not os.path.exists(icon_path):
            return
        try:
            pixmap = QPixmap(icon_path)
            if pixmap.isNull():
                raise ValueError(f'无法加载图片: {icon_path}')
            margin = 1
            target_rect = QRectF(rect.left() + margin, rect.top() + margin, rect.width() - 2 * margin, rect.height() - 2 * margin)
            clip_path = QPainterPath()
            clip_path.addRoundedRect(target_rect, max(0, self.radius - margin), max(0, self.radius - margin))
            painter.setClipPath(clip_path)
            pixmap_ratio = pixmap.width() / pixmap.height()
            target_ratio = target_rect.width() / target_rect.height()
            if pixmap_ratio > target_ratio:
                scaled_height = target_rect.height()
                scaled_width = pixmap.width() * (scaled_height / pixmap.height())
                x, y = target_rect.center().x() - scaled_width / 2, target_rect.top()
            else:
                scaled_width = target_rect.width()
                scaled_height = pixmap.height() * (scaled_width / pixmap.width())
                x, y = target_rect.left(), target_rect.center().y() - scaled_height / 2
            painter.save()
            painter.setOpacity(self._opacity)
            painter.drawPixmap(QRectF(x, y, scaled_width, scaled_height), pixmap, QRectF(0, 0, pixmap.width(), pixmap.height()))
            painter.restore()
            painter.setClipping(False)
            return
        except Exception as e:
            print(f'绘制图标失败: {e}')
            text_color = QColor(255, 255, 255)
            text_color.setAlpha(int(255 * self._opacity))
            self._draw_text_icon(painter, rect, text_color)

    def _draw_text_icon(self, painter, rect, text_color):
        painter.setPen(QPen(text_color, 1))
        font = ui_font(max(10, int(self.size * self._scale) // 3), QFont.Bold)
        painter.setFont(font)
        painter.drawText(rect, Qt.AlignCenter, self.display_char)

    def _get_theme_colors(self):
        main_window = self._get_main_window()
        is_dark = main_window.is_dark_theme() if main_window and hasattr(main_window, 'is_dark_theme') else False
        if is_dark:
            return QColor(25, 28, 36), QColor(230, 233, 240)
        return QColor(255, 255, 255), QColor(27, 27, 27)

    def _get_opacity_settings(self):
        main_window = self._get_main_window()
        card_opacity, text_opacity = 255, 255
        if main_window:
            if hasattr(main_window, 'get_card_opacity'):
                card_opacity = int(255 * main_window.get_card_opacity() / 100)
            if hasattr(main_window, 'get_text_opacity'):
                text_opacity = int(255 * main_window.get_text_opacity() / 100)
        return card_opacity, text_opacity

    def _get_main_window(self):
        parent = self.parent()
        while parent and not hasattr(parent, 'is_dark_theme'):
            parent = parent.parent()
        if not parent or not hasattr(parent, 'is_dark_theme'):
            app = QApplication.instance()
            if app:
                for widget in app.topLevelWidgets():
                    if not hasattr(widget, 'is_dark_theme'):
                        continue
                    return widget
        return parent

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.is_pressed = True
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            if self.is_pressed:
                self.is_pressed = False
                self.update()
                if self.rect().contains(event.pos()):
                    self.clicked.emit(self.link)

    def enterEvent(self, event):
        self.is_hovered = True
        self.setCursor(Qt.PointingHandCursor)
        main_window = self._get_main_window()
        hover_scale = 1.2
        if main_window and hasattr(main_window, 'get_shortcut_hover_scale'):
            hover_scale = main_window.get_shortcut_hover_scale()
        if self.hover_animation.state() == QPropertyAnimation.Running:
            self.hover_animation.stop()
        self.hover_animation.setStartValue(self._scale)
        self.hover_animation.setEndValue(hover_scale)
        self.hover_animation.start()
        self.update()

    def leaveEvent(self, event):
        self.is_hovered = False
        self.is_pressed = False
        self.setCursor(Qt.ArrowCursor)
        if self.hover_animation.state() == QPropertyAnimation.Running:
            self.hover_animation.stop()
        self.hover_animation.setStartValue(self._scale)
        self.hover_animation.setEndValue(1.0)
        self.hover_animation.start()
        self.update()


class BorderColorWidget(QWidget):
    color_changed = pyqtSignal(str, int)
    def __init__(self, border_color='#000000', border_opacity=100, parent=None):
        super().__init__(parent)
        self.border_color = border_color
        self.border_opacity = border_opacity
        self.init_ui()

    def init_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(2)
        self.color_block = QLabel()
        self.color_block.setFixedSize(20, 16)
        self.update_color_block_style()
        self.opacity_spinbox = QSpinBox()
        self.opacity_spinbox.setRange(0, 100)
        self.opacity_spinbox.setValue(self.border_opacity)
        self.opacity_spinbox.setSuffix(' %')
        self.opacity_spinbox.setFixedWidth(60)
        self.opacity_spinbox.valueChanged.connect(self.on_opacity_spinbox_changed)
        layout.addWidget(self.color_block)
        layout.addWidget(self.opacity_spinbox)
        layout.addStretch()

    def update_color_block_style(self):
        self.color_block.setStyleSheet(f'\n            background-color: {self.get_color_string()}; \n            border: 1px solid gray;\n            border-radius: 3px;\n        ')

    def get_color_string(self):
        color = QColor(self.border_color)
        if self.border_opacity < 100:
            return f'rgba({color.red()}, {color.green()}, {color.blue()}, {self.border_opacity / 100:.2f})'
        return color.name()

    def wheelEvent(self, event: QWheelEvent):
        if event.buttons() == Qt.MiddleButton or event.modifiers() == Qt.NoModifier:
            delta = event.angleDelta().y()
            if delta > 0:
                new_opacity = min(100, self.border_opacity + 5)
            else:
                new_opacity = max(0, self.border_opacity - 5)
            self.border_opacity = new_opacity
            self.opacity_spinbox.setValue(new_opacity)
            self.update_display()
            self.color_changed.emit(self.border_color, self.border_opacity)
            event.accept()
            return
        super().wheelEvent(event)

    def on_opacity_spinbox_changed(self, value):
        self.border_opacity = value
        self.update_display()
        self.color_changed.emit(self.border_color, self.border_opacity)

    def update_display(self):
        self.update_color_block_style()

    def set_color(self, color, opacity):
        self.border_color = color
        self.border_opacity = opacity
        self.opacity_spinbox.setValue(opacity)
        self.update_display()


class CustomColorDialog(QColorDialog):
    realtime_color_changed = pyqtSignal(QColor, int)
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('选择描边颜色')
        self.setOption(QColorDialog.ShowAlphaChannel, True)
        self.setOption(QColorDialog.DontUseNativeDialog, True)
        self.opacity_slider = QSlider(Qt.Horizontal)
        self.opacity_slider.setRange(0, 100)
        self.opacity_slider.setValue(100)
        self.opacity_slider.setTickPosition(QSlider.TicksBelow)
        self.opacity_slider.setTickInterval(10)
        self.opacity_label = QLabel('透明度: 100%')
        opacity_container = QWidget()
        opacity_layout = QVBoxLayout(opacity_container)
        opacity_layout.setContentsMargins(10, 10, 10, 10)
        opacity_row_layout = QHBoxLayout()
        opacity_row_layout.addWidget(QLabel('透明度:'))
        opacity_row_layout.addWidget(self.opacity_slider)
        opacity_row_layout.addWidget(self.opacity_label)
        opacity_layout.addLayout(opacity_row_layout)
        main_layout = self.layout() or QVBoxLayout(self)
        main_layout.addWidget(opacity_container)
        self.opacity_slider.valueChanged.connect(self.update_opacity_label)
        self.currentColorChanged.connect(self.on_current_color_changed)
        self.opacity_slider.valueChanged.connect(self.emit_realtime_color)
        apply_theme_to_dialog(self)

    def update_opacity_label(self, value):
        self.opacity_label.setText(f'透明度: {value}%')

    def on_current_color_changed(self, color):
        color.setAlpha(int(self.opacity_slider.value() * 255 / 100))
        self.setCurrentColor(color)
        self.emit_realtime_color()

    def emit_realtime_color(self):
        color = self.currentColor()
        opacity = self.opacity_slider.value()
        color.setAlpha(int(opacity * 255 / 100))
        self.realtime_color_changed.emit(color, opacity)

    def get_color_with_opacity(self):
        color = self.currentColor()
        color.setAlpha(int(self.opacity_slider.value() * 255 / 100))
        return color


class ShortcutLinksDialog(QDialog):
    realtime_border_color_changed = pyqtSignal(int, str, int)
    preview_update_requested = pyqtSignal(int)
    shortcut_data_changed = pyqtSignal(int, dict)
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('编辑快捷方式链接')
        self.setFixedSize(600, 650)
        self.links = []
        self.color_dialog = None
        self.current_preview_button = None
        self.editing_mode = False
        self.init_ui()

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        table_group = QGroupBox('快捷方式列表')
        table_layout = QVBoxLayout()
        self.table = QTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels(['👁️‍🗨️', '✅', '名称', '字标', '图片路径', '描边透明', '链接地址'])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.AllEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setMinimumSectionSize(10)
        self.table.verticalHeader().setDefaultSectionSize(20)
        self.table.setColumnWidth(0, 24)
        self.table.setColumnWidth(1, 24)
        self.table.setColumnWidth(2, 60)
        self.table.setColumnWidth(3, 40)
        self.table.setColumnWidth(4, 100)
        self.table.setColumnWidth(5, 70)
        table_layout.addWidget(self.table)
        button_layout = QHBoxLayout()
        self.add_button = QPushButton('添加连接')
        self.add_button.clicked.connect(self.add_row)
        self.delete_button = QPushButton('删除选中')
        self.delete_button.clicked.connect(self.delete_selected)
        self.clear_button = QPushButton('清空所有')
        self.clear_button.clicked.connect(self.clear_all)
        button_layout.addWidget(self.add_button)
        button_layout.addWidget(self.delete_button)
        button_layout.addWidget(self.clear_button)
        table_layout.addLayout(button_layout)
        table_group.setLayout(table_layout)
        main_layout.addWidget(table_group)
        manual_group = QGroupBox('手动输入（备用方式）')
        manual_layout = QVBoxLayout()
        instruction = QLabel('每行一个链接，格式：勾选状态|显示名称|图标字符(可选)|图标图片路径(可选)|描边颜色(可选)|透明度(可选)|链接地址')
        instruction.setWordWrap(True)
        manual_layout.addWidget(instruction)
        example = QLabel('示例：1|谷歌|G||#FF0000|80|https://www.google.com')
        example.setObjectName('dim')
        manual_layout.addWidget(example)
        self.text_edit = QTextEdit()
        self.text_edit.setMaximumHeight(120)
        self.text_edit.setPlaceholderText('每行格式：勾选状态|名称|图标字符|图标图片路径|描边颜色|透明度|链接\n勾选状态：1表示显示，0表示隐藏\n图标字符和图标图片路径可留空，优先使用图标图片\n描边颜色：支持颜色名称(如red)或十六进制颜色码(如#FF0000)\n透明度：0-100的整数，100表示完全不透明\n链接可以是网页URL、文件夹路径或程序路径\n图标图片会自动缩放并裁切以填充按钮，保留1像素边缘')
        manual_layout.addWidget(self.text_edit)
        manual_button_layout = QHBoxLayout()
        self.import_button = QPushButton('导入到表格')
        self.import_button.clicked.connect(self.import_from_text)
        self.export_button = QPushButton('从表格导出')
        self.export_button.clicked.connect(self.export_to_text)
        manual_button_layout.addWidget(self.import_button)
        manual_button_layout.addWidget(self.export_button)
        manual_layout.addLayout(manual_button_layout)
        manual_group.setLayout(manual_layout)
        main_layout.addWidget(manual_group)
        self.status_label = QLabel('就绪')
        self.status_label.setObjectName('dim')
        main_layout.addWidget(self.status_label)
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        button_box.button(QDialogButtonBox.Ok).setText('确定')
        button_box.button(QDialogButtonBox.Cancel).setText('取消')
        main_layout.addWidget(button_box)
        apply_theme_to_dialog(self)

    def showEvent(self, event):
        super().showEvent(event)
        self.editing_mode = True
        main_window = self._get_main_window()
        if main_window:
            if hasattr(main_window, 'get_shortcut_display_mode'):
                display_mode = main_window.get_shortcut_display_mode()
                if display_mode == 'hover':
                    main_window._update_shortcut_buttons_visibility(force_show=True)

    def closeEvent(self, event):
        super().closeEvent(event)
        self.editing_mode = False
        main_window = self._get_main_window()
        if main_window:
            if hasattr(main_window, '_update_shortcut_buttons_visibility'):
                main_window._update_shortcut_buttons_visibility()

    def _get_main_window(self):
        parent = self.parent()
        while parent and not hasattr(parent, 'is_dark_theme'):
            parent = parent.parent()
        return parent

    def set_links(self, links):
        self.links = links
        self.update_table()

    def get_links(self):
        links = []
        for row in range(self.table.rowCount()):
            try:
                checkbox_widget = self.table.cellWidget(row, 1)
                enabled = checkbox_widget.isChecked() if checkbox_widget and isinstance(checkbox_widget, QCheckBox) else True
                name_item = self.table.item(row, 2)
                icon_char_item = self.table.item(row, 3)
                icon_image_item = self.table.item(row, 4)
                link_item = self.table.item(row, 6)
                name = name_item.text().strip() if name_item else ''
                icon_char = (icon_char_item.text().strip() if icon_char_item else '')[:1]
                icon_image = icon_image_item.text().strip() if icon_image_item else ''
                link = link_item.text().strip() if link_item else ''
                border_color = '#000000'
                border_opacity = 100
                color_widget = self.table.cellWidget(row, 5)
                if color_widget and isinstance(color_widget, BorderColorWidget):
                    border_color = color_widget.border_color
                    border_opacity = color_widget.border_opacity
                if link or name or icon_char or icon_image:
                    links.append({'enabled': enabled, 'name': name, 'icon_char': icon_char or None, 'icon_image': icon_image or None, 'border_color': border_color, 'border_opacity': border_opacity, 'link': link})
                    continue
            except Exception as e:
                print(f'获取链接数据错误: {e}')
        return links

    def update_table(self):
        try:
            self.table.cellChanged.disconnect(self.on_cell_changed)
        except:
            pass
        self.table.setRowCount(0)
        for link in self.links:
            self.add_table_row(link)
        self.table.cellChanged.connect(self.on_cell_changed)

    def add_table_row(self, link_data=None):
        row = self.table.rowCount()
        self.table.insertRow(row)
        link_data = link_data or {'enabled': True, 'name': '', 'icon_char': '', 'icon_image': '', 'border_color': '#000000', 'border_opacity': 100, 'link': ''}
        preview_label = QLabel()
        preview_label.setFixedSize(20, 20)
        preview_label.setAlignment(Qt.AlignCenter)
        preview_label.setStyleSheet('border: 1px solid gray; border-radius: 3px;')
        temp_button = ShortcutButton(link_data.get('name', ''), link_data.get('link', ''), link_data.get('icon_char'), link_data.get('icon_image'), link_data.get('border_color', '#000000'), link_data.get('border_opacity', 100))
        temp_button.setFixedSize(40, 40)
        pixmap = QPixmap(40, 40)
        pixmap.fill(Qt.transparent)
        temp_button.render(pixmap)
        preview_label.setPixmap(pixmap)
        preview_label.setAlignment(Qt.AlignCenter)
        self.table.setCellWidget(row, 0, preview_label)
        enabled_checkbox = QCheckBox()
        enabled_checkbox.setChecked(link_data.get('enabled', True))
        enabled_checkbox.stateChanged.connect((lambda state, r=row: self.update_preview(r)))
        checkbox_widget = QWidget()
        checkbox_layout = QHBoxLayout(checkbox_widget)
        checkbox_layout.addWidget(enabled_checkbox)
        checkbox_layout.setAlignment(Qt.AlignCenter)
        checkbox_layout.setContentsMargins(0, 0, 0, 0)
        checkbox_widget.setLayout(checkbox_layout)
        self.table.setCellWidget(row, 1, checkbox_widget)
        name_item = QTableWidgetItem(link_data.get('name', ''))
        name_item.setTextAlignment(Qt.AlignCenter)
        self.table.setItem(row, 2, name_item)
        icon_char_item = QTableWidgetItem(link_data.get('icon_char', ''))
        icon_char_item.setTextAlignment(Qt.AlignCenter)
        self.table.setItem(row, 3, icon_char_item)
        icon_image_item = QTableWidgetItem(link_data.get('icon_image', ''))
        icon_image_item.setTextAlignment(Qt.AlignCenter)
        self.table.setItem(row, 4, icon_image_item)
        border_color = link_data.get('border_color', '#000000')
        border_opacity = link_data.get('border_opacity', 100)
        color_widget = BorderColorWidget(border_color, border_opacity)
        color_widget.color_changed.connect((lambda color, opacity, r=row: self.on_border_color_changed(r, color, opacity)))
        color_widget.color_block.mousePressEvent = lambda event, r=row: self.choose_color(r)
        self.table.setCellWidget(row, 5, color_widget)
        link_item = QTableWidgetItem(link_data.get('link', ''))
        link_item.setTextAlignment(Qt.AlignCenter)
        self.table.setItem(row, 6, link_item)

    def on_border_color_changed(self, row, color, opacity):
        self.update_preview(row)
        border_color = color if opacity == 100 else f'rgba({QColor(color).red()}, {QColor(color).green()}, {QColor(color).blue()}, {opacity / 100:.2f})'
        link_data = self.get_row_data(row)
        if link_data:
            self.shortcut_data_changed.emit(row, link_data)

    def on_cell_changed(self, row, column):
        if column in (2, 3, 4, 6):
            self.update_preview(row)
            if column == 4:
                link_data = self.get_row_data(row)
                if link_data:
                    self.shortcut_data_changed.emit(row, link_data)
                    self.preview_update_requested.emit(row)

    def get_row_data(self, row):
        '''获取指定行的完整数据'''

        try:
            checkbox_widget = self.table.cellWidget(row, 1)
            enabled = checkbox_widget.isChecked() if checkbox_widget and isinstance(checkbox_widget, QCheckBox) else True
            name_item = self.table.item(row, 2)
            icon_char_item = self.table.item(row, 3)
            icon_image_item = self.table.item(row, 4)
            link_item = self.table.item(row, 6)
            name = name_item.text().strip() if name_item else ''
            icon_char = (icon_char_item.text().strip() if icon_char_item else '')[:1]
            icon_image = icon_image_item.text().strip() if icon_image_item else ''
            link = link_item.text().strip() if link_item else ''
            border_color = '#000000'
            border_opacity = 100
            color_widget = self.table.cellWidget(row, 5)
            if color_widget and isinstance(color_widget, BorderColorWidget):
                border_color = color_widget.border_color
                border_opacity = color_widget.border_opacity
            return {'enabled': enabled, 'name': name, 'icon_char': icon_char or None, 'icon_image': icon_image or None, 'border_color': border_color, 'border_opacity': border_opacity, 'link': link}
        except Exception as e:
            print(f'获取行数据错误: {e}')

    def update_preview(self, row):
        try:
            name = self.table.item(row, 2).text() if self.table.item(row, 2) else ''
            icon_char = self.table.item(row, 3).text() if self.table.item(row, 3) else ''
            icon_image = self.table.item(row, 4).text() if self.table.item(row, 4) else ''
            link = self.table.item(row, 6).text() if self.table.item(row, 6) else ''
            border_color = '#000000'
            border_opacity = 100
            color_widget = self.table.cellWidget(row, 5)
            if color_widget and isinstance(color_widget, BorderColorWidget):
                border_color = color_widget.border_color
                border_opacity = color_widget.border_opacity
            temp_button = ShortcutButton(name, link, icon_char, icon_image, border_color, border_opacity)
            temp_button.setFixedSize(40, 40)
            pixmap = QPixmap(40, 40)
            pixmap.fill(Qt.transparent)
            temp_button.render(pixmap)
            preview_label = self.table.cellWidget(row, 0)
            if preview_label:
                preview_label.setPixmap(pixmap)
                return
        except Exception as e:
            print(f'更新预览错误: {e}')

    def add_row(self):
        self.add_table_row()
        self.table.scrollToBottom()
        self.status_label.setText('已添加新行')

    def delete_selected(self):
        selected_rows = self.table.selectionModel().selectedRows()
        if not selected_rows:
            self.status_label.setText('请先选择要删除的行')
            return
        for model_index in sorted(selected_rows, key=(lambda x: x.row()), reverse=True):
            self.table.removeRow(model_index.row())
        self.status_label.setText(f'已删除 {len(selected_rows)} 行')

    def clear_all(self):
        reply = QMessageBox.question(self, '确认清空', '确定要清空所有快捷方式吗？', QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            self.table.setRowCount(0)
            self.status_label.setText('已清空所有快捷方式')

    def import_from_text(self):
        text = self.text_edit.toPlainText().strip()
        if not text:
            self.status_label.setText('请输入要导入的内容')
            return
        lines = text.split('\n')
        imported_count = 0
        for line in lines:
            line = line.strip()
            parts = line.split('|')
            if len(parts) < 7:
                self.status_label.setText(f'格式错误: {line}')
                continue
            try:
                enabled, name, icon_char, icon_image, border_color, border_opacity, link = [part.strip() for part in parts[:7]]
                if not (not link and not name and not icon_char) or icon_image:
                    self.add_table_row({'enabled': bool(int(enabled)), 'name': name, 'icon_char': icon_char, 'icon_image': icon_image, 'border_color': border_color, 'border_opacity': int(border_opacity) if border_opacity else 100, 'link': link})
                    imported_count += 1
            except Exception as e:
                print(f'导入错误: {e}')
                continue
        self.status_label.setText(
            f'成功导入 {imported_count} 个快捷方式' if imported_count > 0
            else '没有成功导入任何快捷方式')

    def export_to_text(self):
        links = self.get_links()
        text_lines = []
        for link in links:
            line = f'{1 if link.get('enabled', True) else 0}|{link.get('name', '')}|{link.get('icon_char', '')}|{link.get('icon_image', '')}|{link.get('border_color', '#000000')}|{link.get('border_opacity', 100)}|{link.get('link', '')}'
            text_lines.append(line)
        self.text_edit.setPlainText('\n'.join(text_lines))
        self.status_label.setText(f'已导出 {len(text_lines)} 个快捷方式')

    def choose_color(self, row):
        color_widget = self.table.cellWidget(row, 5)
        if not isinstance(color_widget, BorderColorWidget):
            return
        border_color = color_widget.border_color
        border_opacity = color_widget.border_opacity
        if isinstance(border_color, str) and border_color.startswith('rgba('):
            import re
            match = re.match('rgba\\((\\d+),\\s*(\\d+),\\s*(\\d+),\\s*([\\d.]+)\\)', border_color)
            if match:
                r, g, b, a = map(float, match.groups())
                initial_color = QColor(int(r), int(g), int(b))
                border_opacity = int(a * 100)
            else:
                initial_color = QColor(border_color)
        else:
            initial_color = QColor(border_color)
        initial_color.setAlpha(int(border_opacity * 255 / 100))
        self.color_dialog = CustomColorDialog(self)
        self.color_dialog.setCurrentColor(initial_color)
        self.color_dialog.opacity_slider.setValue(border_opacity)
        self.current_preview_button = row
        self.color_dialog.realtime_color_changed.connect((lambda color, opacity, r=row: self.on_realtime_color_changed(r, color, opacity)))
        if self.color_dialog.exec_() == QDialog.Accepted:
            final_color = self.color_dialog.get_color_with_opacity()
            opacity = self.color_dialog.opacity_slider.value()
            color_widget.set_color(final_color.name(), opacity)
            self.update_preview(row)
        self.color_dialog = None
        self.current_preview_button = None

    def on_realtime_color_changed(self, row, color, opacity):
        name = self.table.item(row, 2).text() if self.table.item(row, 2) else ''
        icon_char = self.table.item(row, 3).text() if self.table.item(row, 3) else ''
        icon_image = self.table.item(row, 4).text() if self.table.item(row, 4) else ''
        link = self.table.item(row, 6).text() if self.table.item(row, 6) else ''
        border_color = color.name() if opacity == 100 else f'rgba({color.red()}, {color.green()}, {color.blue()}, {opacity / 100:.2f})'
        temp_button = ShortcutButton(name, link, icon_char, icon_image, border_color, opacity)
        temp_button.setFixedSize(40, 40)
        pixmap = QPixmap(40, 40)
        pixmap.fill(Qt.transparent)
        temp_button.render(pixmap)
        preview_label = self.table.cellWidget(row, 0)
        if preview_label:
            preview_label.setPixmap(pixmap)
        color_widget = self.table.cellWidget(row, 5)
        if color_widget and isinstance(color_widget, BorderColorWidget):
            color_widget.set_color(color.name(), opacity)
        link_data = self.get_row_data(row)
        if link_data:
            self.shortcut_data_changed.emit(row, link_data)


class MetricChart(QWidget):
    CHART_COLORS = {'cpu': QColor(52, 152, 219), 'memory': QColor(46, 204, 113), 'disk': QColor(243, 156, 18), 'network': QColor(155, 89, 182), 'connections': QColor(231, 76, 60)}
    def __init__(self, title, chart_type='default', parent=None):
        super().__init__(parent)
        self.title = title
        self.chart_type = chart_type
        self.value = 0
        self.data_points = 70
        self.tcp_value = 0
        self.udp_value = 0
        self.data = [0.0] * self.data_points
        self.display_data = [0.0] * self.data_points
        self.target_data = [0.0] * self.data_points
        self.max_value = 100
        self.display_title = title
        self.animation_timer = QTimer(self)
        self.animation_timer.timeout.connect(self._update_animation)
        self.is_animating = False
        self.animation_enabled = True
        self.cached_path = None
        self.cached_fill_path = None
        self.path_dirty = True
        self.last_paint_rect = QRectF()
        self.last_paint_time = 0
        self.min_paint_interval = 0.033
        self.setFixedSize(60, 116)
        self.color = self.CHART_COLORS.get(chart_type, self.CHART_COLORS['cpu'])
        if parent and hasattr(parent, 'performance_optimizer'):
            self.performance_optimizer = parent.performance_optimizer
            return
        self.performance_optimizer = PerformanceOptimizer()

    def set_animation_enabled(self, enabled):
        self.animation_enabled = enabled
        if not enabled:
            if self.is_animating:
                self.is_animating = False
                self.animation_timer.stop()
                self.display_data = self.target_data[:]
                self.path_dirty = True
                self.update()

    def set_compact_title(self, compact):
        title_map = {'CPU 使用率': 'CPU', '内存使用': '内存', '磁盘 I/O': '磁盘', '下载速度': '下载', '上传速度': '上传', 'TCP/UDP 连接': '连接'}
        if compact:
            self.display_title = title_map.get(self.title, self.title)
            return
        self.display_title = self.title

    def update_data(self, value):
        self.value = value
        for data_list in self.data, self.target_data, self.display_data:
            data_list.append(float(value))
            if len(data_list) > self.data_points:
                data_list.pop(0)
        if self.animation_enabled:
            if not self.is_animating:
                self.is_animating = True
                self.animation_timer.start(16)
        else:
            self.display_data = self.target_data[:]
        self.path_dirty = True
        if self.chart_type in ('disk', 'network', 'connections'):
            self.max_value = max(max(self.data) * 1.2, 10)
        else:
            self.max_value = 100
        current_time = time.time()
        if current_time - self.last_paint_time >= self.min_paint_interval:
            self.update()
            self.last_paint_time = current_time

    def update_connections_data(self, tcp_value, udp_value):
        self.tcp_value = tcp_value
        self.udp_value = udp_value
        self.update_data(tcp_value + udp_value)

    def _update_animation(self):
        if not self.animation_enabled:
            return
        max_diff = 0.0001
        animation_completed = True
        animation_speed = self.performance_optimizer.get_animation_speed(0.15)
        for i in range(len(self.display_data)):
            diff = abs(self.target_data[i] - self.display_data[i])
            if diff > max_diff:
                animation_completed = False
                t = max(0.05, min(0.3, (1 - diff / (abs(self.target_data[i]) + 1)) * animation_speed))
                self.display_data[i] = self.display_data[i] * (1 - t) + self.target_data[i] * t
        if animation_completed:
            self.is_animating = False
            self.animation_timer.stop()
            self.display_data = self.target_data[:]
        self.path_dirty = True
        current_time = time.time()
        if current_time - self.last_paint_time >= self.min_paint_interval:
            self.update()
            self.last_paint_time = current_time

    def update_data_points(self, new_data_points):
        if new_data_points == self.data_points:
            return
        self.data_points = new_data_points
        for data_list in self.data, self.display_data, self.target_data:
            if len(data_list) > new_data_points:
                del data_list[:len(data_list) - new_data_points]
            elif len(data_list) < new_data_points:
                data_list[:0] = [0.0] * (new_data_points - len(data_list))

    def _get_theme_colors(self):
        parent = self.parent()
        if parent and hasattr(parent, 'is_dark_theme') and parent.is_dark_theme():
            return QColor(25, 28, 36), QColor(230, 233, 240)
        return QColor(255, 255, 255), QColor(27, 27, 27)

    def _get_opacity_settings(self):
        if hasattr(self, '_cached_opacity') and not self.path_dirty:
            return self._cached_opacity
        parent = self.parent()
        settings = {'card_opacity': 255, 'text_opacity': 76, 'chart_opacity': 90, 'card_radius': 5}
        if parent:
            for attr, key in (('get_card_opacity', 'card_opacity'), ('get_text_opacity', 'text_opacity'), ('get_chart_opacity', 'chart_opacity'), ('get_card_radius', 'card_radius')):
                if hasattr(parent, attr):
                    value = getattr(parent, attr)()
                    settings[key] = int(255 * value / 100) if key in ('card_opacity', 'text_opacity') else value
        self._cached_opacity = settings
        return settings

    def _format_value_text(self):
        value = self.value
        if self.chart_type == 'network':
            mbs = value / 8192.0
            if mbs >= 100:
                return f'{mbs:.0f} MB/s'
            if mbs >= 10:
                return f'{mbs:.1f} MB/s'
            return f'{mbs:.2f} MB/s'
        if self.chart_type == 'disk':
            if value >= 1024:
                return f'{value / 1024:.1f} MB/s'
            return f'{value:.1f} KiB/s'
        if self.chart_type == 'connections':
            return f'{self.tcp_value:.0f}/{self.udp_value:.0f}'
        return f'{value:.1f}%'

    def paintEvent(self, event):
        current_time = time.time()
        if current_time - self.last_paint_time < self.min_paint_interval and not self.path_dirty:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        bg_color, text_color = self._get_theme_colors()
        opacity_settings = self._get_opacity_settings()
        bg_color.setAlpha(opacity_settings['card_opacity'])
        text_color.setAlpha(opacity_settings['text_opacity'])
        path = QPainterPath()
        rect = QRectF(0, 0, self.width(), self.height())
        path.addRoundedRect(rect, opacity_settings['card_radius'], opacity_settings['card_radius'])
        painter.fillPath(path, bg_color)
        layout_option = self.parent().get_layout_option() if self.parent() and hasattr(self.parent(), 'get_layout_option') else 2
        if layout_option == 1:
            self._paint_single_line_mode(painter, text_color, opacity_settings)
        elif layout_option == 4:
            self._paint_compact_mode(painter, text_color, opacity_settings)
        else:
            self._paint_normal_mode(painter, text_color)
        self.last_paint_time = current_time

    def _paint_normal_mode(self, painter, text_color):
        # 先画曲线、后画文字：曲线填充再亮也不会盖住数值
        if len(self.data) > 1:
            self._draw_chart(painter)
        title_px, value_px = self._calculate_font_sizes()
        title_font = ui_font_px(title_px, QFont.Bold)
        value_font = ui_font_px(value_px, QFont.Bold)
        title_metrics = QFontMetrics(title_font)
        value_metrics = QFontMetrics(value_font)
        # 基線由真实字体度量推出，不再写死像素值：两行文字整体在卡片顶部居中对齐，
        # 行高无论多大都不会互相盖住。
        block_height = title_metrics.height() + value_metrics.height()
        top = max(1, (min(self.height(), block_height + 6) - block_height) // 2 + 1)
        title_baseline = top + title_metrics.ascent()
        value_baseline = top + title_metrics.height() + value_metrics.ascent()

        painter.setPen(QPen(text_color, 1))
        painter.setFont(title_font)
        title_text = getattr(self, 'display_title', self.title)
        elided_title = title_metrics.elidedText(title_text, Qt.ElideRight, self.width() - 10)
        painter.drawText(5, title_baseline, elided_title)
        painter.setFont(value_font)
        value_text = self._format_value_text()
        elided_value = value_metrics.elidedText(value_text, Qt.ElideRight, self.width() - 10)
        painter.drawText(5, value_baseline, elided_value)

    def _paint_single_line_mode(self, painter, text_color, opacity_settings):
        if len(self.data) > 1:
            self._draw_single_line_chart(painter, opacity_settings)
        painter.setPen(QPen(text_color, 1))
        # 像素字号：与卡片像素尺寸同一坐标系，不随 DPI 单独放大
        font_size = 11 if self.height() < 30 else 12 if self.height() < 50 else 13
        font = ui_font_px(font_size, QFont.Bold)
        painter.setFont(font)
        title_text = getattr(self, 'display_title', self.title)
        value_text = self._format_value_text()
        full_text = f'{title_text}: {value_text}'
        text_metrics = painter.fontMetrics()
        text_width, text_height = text_metrics.width(full_text), text_metrics.height()
        x = (self.width() - text_width) / 2
        y = (self.height() + text_height) / 2 - 4
        elided_text = text_metrics.elidedText(full_text, Qt.ElideRight, self.width() - 10)
        painter.drawText(int(x), int(y), elided_text)

    def _paint_compact_mode(self, painter, text_color, opacity_settings):
        if len(self.data) > 1:
            self._draw_chart(painter)
        font_size = 11 if self.width() < 50 else 13 if self.width() < 70 else 16
        font = ui_font_px(font_size, QFont.Bold)
        painter.setFont(font)
        painter.setPen(QPen(text_color, 1))
        title_text = getattr(self, 'display_title', self.title)
        text_metrics = painter.fontMetrics()
        text_width, text_height = text_metrics.width(title_text), text_metrics.height()
        x = (self.width() - text_width) / 2
        y = (self.height() + text_height) / 2 - 2
        elided_text = text_metrics.elidedText(title_text, Qt.ElideRight, self.width() - 10)
        painter.drawText(int(x), int(y), elided_text)

    def _calculate_font_sizes(self):
        '''按卡片像素高度推算两行字号，再按实际字体度量回缩。

        原实现用固定点字号 + 固定像素基线（10 / 22），在 96dpi 下刚好，但字号会
        随 DPI 放大而基线不会，144dpi 屏幕上标题和数值就压到一起。这里改成：
        字号从卡片高度算出 → 用 QFontMetrics 量出真实行高 → 放不下就继续缩小。
        '''
        height = max(12, self.height())
        value_px = max(9, min(26, int(round(height * 0.32))))
        title_px = max(7, min(16, int(round(value_px * 0.75))))
        # 顶部文字最多占 17px 以外的空间，剩下的留给曲线（至少 14px），
        # 这样矮卡片上文字会稍微回缩，而不是把曲线挤没或压住数值。
        limit = max(14, height - 17)
        while value_px > 8 and title_px > 6:
            title_h = QFontMetrics(ui_font_px(title_px, QFont.Bold)).height()
            value_h = QFontMetrics(ui_font_px(value_px, QFont.Bold)).height()
            if title_h + value_h <= limit:
                break
            value_px -= 1
            title_px = max(6, int(round(value_px * 0.75)))
        return (title_px, value_px)

    def _draw_chart(self, painter):
        opacity_settings = self._get_opacity_settings()
        top_margin, bottom_margin, side_margins = self._calculate_chart_margins()
        chart_rect = QRectF(side_margins, top_margin, self.width() - 2 * side_margins, self.height() - top_margin - bottom_margin)
        if chart_rect.width() > 0:
            if chart_rect.height() > 0:
                self._draw_chart_path(painter, chart_rect, opacity_settings['chart_opacity'])

    def _draw_single_line_chart(self, painter, opacity_settings):
        top_margin, bottom_margin, side_margins = 5, 5, 5
        chart_rect = QRectF(side_margins, top_margin, self.width() - 2 * side_margins, self.height() - top_margin - bottom_margin)
        if chart_rect.width() > 0:
            if chart_rect.height() > 0:
                self._draw_chart_path(painter, chart_rect, opacity_settings['chart_opacity'])

    def _text_block_height(self):
        '''两行文字（标题 + 数值）的实际像素高度，用于给曲线留出顶部空间。'''
        try:
            title_px, value_px = self._calculate_font_sizes()
            return (QFontMetrics(ui_font_px(title_px, QFont.Bold)).height()
                    + QFontMetrics(ui_font_px(value_px, QFont.Bold)).height())
        except Exception:
            return 0

    def _calculate_chart_margins(self):
        height = self.height()
        if height < 30:
            base, bottom, side = 15, 3, 3
        elif height < 50:
            base, bottom, side = 18, 3, 4
        elif height < 80:
            base, bottom, side = 25, 4, 5
        else:
            base, bottom, side = 35, 5, 5
        # 曲线从文字下方开始：顶部留白不小于两行文字的实际高度，
        # 否则曲线填充会把数值盖住（浅色/深色主题都一样）。
        top = max(base, self._text_block_height() + 3)
        top = min(top, max(6, height - 16))
        return (top, bottom, side)

    def _draw_chart_path(self, painter, chart_rect, chart_opacity):
        chart_width, chart_height = chart_rect.width(), chart_rect.height()
        if chart_width < 10 or chart_height < 10:
            return
        if not self.path_dirty:
            if self.cached_path and self.cached_fill_path and self.last_paint_rect == chart_rect:
                painter.setPen(Qt.NoPen)
                brush_color = QColor(self.color.red(), self.color.green(), self.color.blue(), int(255 * chart_opacity / 100 * 0.71))
                painter.setBrush(brush_color)
                painter.drawPath(self.cached_fill_path)
                pen = QPen(self.color, 1.2)
                painter.setPen(pen)
                painter.setBrush(Qt.NoBrush)
                painter.drawPath(self.cached_path)
                return
        fill_opacity = int(255 * chart_opacity / 100 * 0.71)
        pen = QPen(self.color, 1.2)
        painter.setPen(pen)
        brush_color = QColor(self.color.red(), self.color.green(), self.color.blue(), fill_opacity)
        painter.setBrush(brush_color)
        data_to_draw = self.display_data
        if len(data_to_draw) < 2:
            return
        path = QPainterPath()
        points = []
        for i in range(len(data_to_draw)):
            x = chart_rect.left() + i / (len(data_to_draw) - 1) * chart_width
            y = max(chart_rect.top(), min(chart_rect.bottom(), chart_rect.bottom() - data_to_draw[i] / self.max_value * chart_height if self.max_value > 0 else chart_rect.bottom()))
            points.append(QPointF(x, y))
        path.moveTo(points[0])
        tension = 0.3
        for i in range(1, len(points)):
            p1, p2 = points[i - 1], points[i]
            p0 = points[i - 2] if i > 1 else p1
            p3 = points[i + 1] if i < len(points) - 1 else p2
            control1 = QPointF(p1.x() + (p2.x() - p0.x()) * tension / 3, p1.y() + (p2.y() - p0.y()) * tension / 3)
            control2 = QPointF(p2.x() - (p3.x() - p1.x()) * tension / 3, p2.y() - (p3.y() - p1.y()) * tension / 3)
            path.cubicTo(control1, control2, p2)
            continue
        fill_path = QPainterPath(path)
        fill_path.lineTo(chart_rect.right(), chart_rect.bottom())
        fill_path.lineTo(chart_rect.left(), chart_rect.bottom())
        fill_path.closeSubpath()
        self.cached_path = path
        self.cached_fill_path = fill_path
        self.last_paint_rect = chart_rect
        self.path_dirty = False
        painter.setPen(Qt.NoPen)
        painter.setBrush(brush_color)
        painter.drawPath(fill_path)
        painter.setBrush(Qt.NoBrush)
        painter.setPen(pen)
        painter.drawPath(path)


EDGE_DOCK_TOLERANCE = 14   # px; how close to a screen edge counts as 停靠（靠边隐藏用）
EDGE_HIDE_STRIP = 4        # px; how much of the widget stays visible while hidden
EDGE_HIDE_DELAY = 500      # ms; cursor must stay away this long before hiding
EDGE_POLL_MS = 120         # ms; cursor poll interval for 靠边隐藏


def asset_url(name):
    '''Locate a bundled asset: <base>/assets/name, then <base>/name (_MEIPASS aware).'''
    try:
        base = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
    except Exception:
        base = os.path.abspath('.')
    for candidate in (os.path.join(base, 'assets', name), os.path.join(base, name)):
        if os.path.exists(candidate):
            return candidate.replace('\\', '/')
    return None


def _arrow_css(variant):
    '''QSpinBox/QComboBox arrows must be real images under Qt stylesheets.'''
    up = asset_url('arrow_up_%s.png' % variant)
    down = asset_url('arrow_down_%s.png' % variant)
    if not up or not down:
        return ''
    return ('QComboBox::down-arrow { image: url(%s); width: 10px; height: 6px; margin-right: 7px; }'
            'QSpinBox::up-arrow, QDoubleSpinBox::up-arrow { image: url(%s); width: 10px; height: 6px; }'
            'QSpinBox::down-arrow, QDoubleSpinBox::down-arrow { image: url(%s); width: 10px; height: 6px; }'
            % (down, up, down))


DIALOG_STYLESHEET = (
    'QDialog { background: %(window)s;'
    ' font-family: "Segoe UI Variable Text", "Segoe UI", "Microsoft YaHei UI",'
    ' "Microsoft YaHei", "PingFang SC", "Noto Sans CJK SC", "Source Han Sans SC",'
    ' "WenQuanYi Micro Hei", sans-serif; font-size: 12px; }'
    'QLabel { color: %(text)s; font-size: 12px; background: transparent; }'
    'QLabel#dim { color: %(text_dim)s; }'
    'QGroupBox { color: %(group_title)s; font-size: 12px; font-weight: 600;'
    ' background: %(panel)s; border: 1px solid %(panel_border)s; border-radius: %(radius_group)s;'
    ' margin-top: 14px; padding: 14px 12px 12px 12px; }'
    'QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top left;'
    ' left: 12px; padding: 0 6px; color: %(group_title)s; }'
    'QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QTextEdit {'
    ' background: %(input_bg)s; color: %(text)s; border: 1px solid %(input_border)s;'
    ' border-radius: %(radius_ctl)s; padding: 4px 8px; min-height: 20px; selection-background-color: %(accent)s;'
    ' selection-color: %(accent_text)s; }'
    'QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus, QTextEdit:focus {'
    ' border: 1px solid %(accent)s; }'
    'QLineEdit:disabled, QSpinBox:disabled, QComboBox:disabled { color: %(disabled)s; }'
    'QComboBox QAbstractItemView { background: %(menu_bg)s; color: %(text)s;'
    ' border: 1px solid %(input_border)s; selection-background-color: %(button_hover)s;'
    ' selection-color: %(text)s; outline: none; }'
    'QComboBox QAbstractItemView::item { min-height: 22px; }'
    'QComboBox::drop-down { subcontrol-origin: border; subcontrol-position: top right;'
    ' width: 20px; border: none; background: transparent; }'
    'QSpinBox::up-button, QDoubleSpinBox::up-button { subcontrol-origin: border;'
    ' subcontrol-position: top right; width: 17px; background: %(button_bg)s;'
    ' border-left: 1px solid %(input_border)s; border-top-right-radius: %(radius_ctl)s; }'
    'QSpinBox::down-button, QDoubleSpinBox::down-button { subcontrol-origin: border;'
    ' subcontrol-position: bottom right; width: 17px; background: %(button_bg)s;'
    ' border-left: 1px solid %(input_border)s; border-bottom-right-radius: %(radius_ctl)s; }'
    'QSpinBox::up-button:hover, QSpinBox::down-button:hover,'
    ' QDoubleSpinBox::up-button:hover, QDoubleSpinBox::down-button:hover { background: %(button_hover)s; }'
    'QCheckBox { color: %(text)s; font-size: 12px; spacing: 7px; background: transparent; }'
    'QCheckBox::indicator { width: 14px; height: 14px; border-radius: 4px;'
    ' border: 1px solid %(button_border)s; background: %(input_bg)s; }'
    'QCheckBox::indicator:checked { background: %(accent)s; border: 1px solid %(accent)s; }'
    'QPushButton { background: %(button_bg)s; color: %(text)s; border: 1px solid %(button_border)s;'
    ' border-radius: %(radius_ctl)s; padding: 6px 16px; min-height: 22px; }'
    'QPushButton:hover { background: %(button_hover)s; }'
    'QPushButton:pressed { background: %(panel_border)s; }'
    'QPushButton:disabled { color: %(disabled)s; background: %(disabled_bg)s; }'
    'QPushButton#primary { background: %(accent)s; color: %(accent_text)s; border: none;'
    ' font-weight: 600; }'
    'QPushButton#primary:hover { background: %(accent)s; }'
    'QScrollBar:vertical { background: transparent; width: 8px; margin: 2px; }'
    'QScrollBar::handle:vertical { background: %(input_border)s; border-radius: 4px; min-height: 24px; }'
    'QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }'
    'QToolTip { background: %(menu_bg)s; color: %(text)s; border: 1px solid %(input_border)s; padding: 4px; }'
    'QTextEdit { border-radius: %(radius_ctl)s; }'
    'QTableWidget { background: %(input_bg)s; color: %(text)s; border: 1px solid %(input_border)s;'
    ' border-radius: %(radius_ctl)s; gridline-color: %(panel_border)s;'
    ' selection-background-color: %(button_hover)s; selection-color: %(text)s; }'
    'QHeaderView::section { background: %(panel)s; color: %(group_title)s; border: none;'
    ' border-right: 1px solid %(panel_border)s; border-bottom: 1px solid %(panel_border)s;'
    ' padding: 5px 3px; }'
    'QTableCornerButton::section { background: %(panel)s; border: none; }'
)


def build_menu_stylesheet(t):
    '''Tray / context menu styling that matches the active theme.'''
    return ('QMenu { background-color: %(menu_bg)s; color: %(text)s;'
            ' border: 1px solid %(input_border)s; border-radius: 8px; padding: 6px; }'
            'QMenu::item { padding: 6px 22px; border-radius: 6px; }'
            'QMenu::item:selected { background-color: %(button_hover)s; }'
            'QMenu::separator { height: 1px; background: %(panel_border)s; margin: 5px 8px; }'
            % t)


def build_dialog_stylesheet(t):
    return DIALOG_STYLESHEET % t + _arrow_css(t.get('variant', 'dark'))


def apply_dialog_theme(dialog, t):
    '''Give a dialog the app look so nothing renders half-native.'''
    dialog.setStyleSheet(build_dialog_stylesheet(t))
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor(t['window']))
    palette.setColor(QPalette.WindowText, QColor(t['text']))
    palette.setColor(QPalette.Base, QColor(t['input_bg']))
    palette.setColor(QPalette.AlternateBase, QColor(t['panel']))
    palette.setColor(QPalette.Text, QColor(t['text']))
    palette.setColor(QPalette.Button, QColor(t['button_bg']))
    palette.setColor(QPalette.ButtonText, QColor(t['text']))
    palette.setColor(QPalette.Highlight, QColor(t['accent']))
    palette.setColor(QPalette.HighlightedText, QColor(t['accent_text']))
    palette.setColor(QPalette.ToolTipBase, QColor(t['menu_bg']))
    palette.setColor(QPalette.ToolTipText, QColor(t['text']))
    dialog.setPalette(palette)


def find_config_manager(widget):
    node = widget
    for _ in range(4):
        if node is None:
            break
        cm = getattr(node, 'config_manager', None)
        if cm is not None:
            return cm
        node = node.parent() if hasattr(node, 'parent') else None
    return None


def apply_theme_to_dialog(widget):
    '''Theme a secondary dialog (colour picker / shortcut editor) to match the app.'''
    index = 1
    try:
        cm = find_config_manager(widget)
        if cm is not None:
            index = cm.getint('theme', 1)
    except Exception:
        index = 1
    t = SettingsDialog.THEME_DARK if index == 1 else SettingsDialog.THEME_LIGHT
    apply_dialog_theme(widget, t)


class SettingsDialog(QDialog):
    settings_saved = pyqtSignal()
    router_test_done = pyqtSignal(bool, str, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('RouterSight 设置')
        try:
            base = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
            icon_path = os.path.join(base, 'logo.ico')
            if os.path.exists(icon_path):
                self.setWindowIcon(QIcon(icon_path))
        except Exception:
            pass
        self.current_status = False
        self.router_test_executor = ThreadPoolExecutor(max_workers=1)
        self.router_test_done.connect(self.on_router_test_done)
        self.preview_timer = QTimer()
        self.preview_timer.setSingleShot(True)
        self.preview_timer.timeout.connect(self._delayed_preview)
        self.init_ui()
        self.load_settings()
        self._apply_theme()
        natural = self.sizeHint()
        width, height = natural.width(), natural.height()
        # 小屏保护：按 sizeHint 铺开需要 1200+ px 高，1366x768 的笔记本上
        # 底部"保存设置"会被顶出屏幕。这里收敛到可用区域，超出的部分由滚动区承接。
        try:
            screen = QApplication.primaryScreen()
            avail = screen.availableGeometry() if screen is not None else None
            if avail is not None and avail.height() > 0:
                width = min(width, max(480, avail.width() - 40))
                height = min(height, max(520, avail.height() - 80))
        except Exception:
            pass
        self.setMinimumSize(480, min(480, height))
        self.resize(width, height)

    def init_ui(self):
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)
        # 内容整体有 1200+ px 高，1366x768 的笔记本按 sizeHint 铺开会把底部按钮顶出屏幕，
        # 所以内容放进滚动区，底部按钮固定在窗口下沿。
        self.content_scroll = QScrollArea(self)
        self.content_scroll.setObjectName('dialogScroll')
        self.content_scroll.setWidgetResizable(True)
        self.content_scroll.setFrameShape(QFrame.NoFrame)
        self.content_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        content = QWidget()
        content.setObjectName('dialogContent')
        self.content_scroll.viewport().setAutoFillBackground(False)
        main_layout = QVBoxLayout(content)
        main_layout.setContentsMargins(14, 12, 14, 12)
        main_layout.setSpacing(10)
        self.content_scroll.setWidget(content)
        # setWidget() 会重新打开内容控件的自动填充，这里再关一次，让主题色透上来
        content.setAutoFillBackground(False)
        outer_layout.addWidget(self.content_scroll, 1)

        self.router_group = self._create_router_group()
        card_selection_group = self._create_card_selection_group()
        display_group = self._create_display_group()
        shortcut_group = self._create_shortcut_group()
        performance_group = self._create_performance_group()
        main_layout.addWidget(self.router_group)
        main_layout.addWidget(card_selection_group)
        main_layout.addWidget(display_group)
        main_layout.addWidget(shortcut_group)
        main_layout.addWidget(performance_group)
        main_layout.addStretch(1)
        main_layout.addLayout(self._create_developer_layout())

        footer = QWidget()
        footer.setObjectName('dialogFooter')
        footer_layout = QVBoxLayout(footer)
        footer_layout.setContentsMargins(14, 4, 14, 12)
        footer_layout.addLayout(self._create_button_layout())
        outer_layout.addWidget(footer, 0)

        self._connect_signals()

    # ---------------------------------------------------------------- theming
    THEME_DARK = {
        'window': '#14161c', 'panel': '#191c24', 'panel_border': '#262b36',
        'group_title': '#8b93a7', 'text': '#d6dae3', 'text_dim': '#7d8598',
        'input_bg': '#1f2430', 'input_border': '#2c3342', 'accent': '#22d3ee',
        'accent_text': '#08131a', 'button_bg': '#232838', 'button_border': '#313a4d',
        'button_hover': '#2b3245', 'disabled': '#6b7385', 'disabled_bg': '#1b1f29',
        'menu_bg': '#1f2430', 'radius_group': '10px', 'radius_ctl': '7px',
        'variant': 'dark',
    }
    # 明亮主题按 Windows 11 (WinUI) 的浅色规范取值：灰底 + 白卡片 + 细边框 +
    # 系统蓝强调色 + 小圆角，这样和资源管理器/设置面板放在一起不违和。
    THEME_LIGHT = {
        'window': '#f3f3f3', 'panel': '#ffffff', 'panel_border': '#e5e5e5',
        'group_title': '#5c5c5c', 'text': '#1b1b1b', 'text_dim': '#6b6b6b',
        'input_bg': '#ffffff', 'input_border': '#d6d6d6', 'accent': '#0067c0',
        'accent_text': '#ffffff', 'button_bg': '#fbfbfb', 'button_border': '#d6d6d6',
        'button_hover': '#f0f0f0', 'disabled': '#9a9a9a', 'disabled_bg': '#f5f5f5',
        'menu_bg': '#fbfbfb', 'radius_group': '8px', 'radius_ctl': '4px',
        'variant': 'light',
    }

    def _theme_palette(self):
        return self.THEME_DARK if self.theme_select.currentIndex() == 1 else self.THEME_LIGHT

    def _apply_theme(self):
        '''One stylesheet for the whole dialog so nothing looks half-native.'''
        t = self._theme_palette()
        apply_dialog_theme(self, t)
        # 滚动区/底部栏默认会画自己的底色，这里一并交给主题控制，避免出现色块
        self.setStyleSheet(self.styleSheet() + (
            '\nQScrollArea#dialogScroll, QScrollArea#dialogScroll > QWidget,'
            ' QScrollArea#dialogScroll > QWidget > QWidget, QWidget#dialogContent'
            ' { background: %(window)s; border: none; }'
            ' QWidget#dialogFooter { background: %(window)s;'
            ' border-top: 1px solid %(panel_border)s; }'
            % {'window': t['window'], 'panel_border': t['panel_border']}))
        self.developer_label.setText(self.DEVELOPER_HTML % (t['text_dim'], t['accent']))
        self._refresh_password_eye()
        self.save_button.setObjectName('primary')
        self.save_button.setStyleSheet('')
        self.save_button.style().unpolish(self.save_button)
        self.save_button.style().polish(self.save_button)

    def _create_router_group(self):
        group = QGroupBox('路由器 (SSH)')
        layout = QFormLayout(group)
        self.router_host = QLineEdit()
        self.router_host.setPlaceholderText('192.168.9.1')
        self.router_port = QSpinBox()
        self.router_port.setRange(1, 65535)
        self.router_user = QLineEdit()
        self.router_user.setPlaceholderText('root')
        self.router_password = QLineEdit()
        self.router_password.setEchoMode(QLineEdit.Password)
        self.router_password.setPlaceholderText('路由器登录密码')
        # 密码框右侧的「小眼睛」：默认隐藏，点一下明文显示，便于核对输入。
        password_row = QWidget()
        password_layout = QHBoxLayout(password_row)
        password_layout.setContentsMargins(0, 0, 0, 0)
        password_layout.setSpacing(6)
        self.password_eye_button = QToolButton()
        self.password_eye_button.setCheckable(True)
        self.password_eye_button.setAutoRaise(True)
        self.password_eye_button.setCursor(Qt.PointingHandCursor)
        self.password_eye_button.setFixedSize(30, 30)
        self.password_eye_button.setToolTip('显示密码')
        self.password_eye_button.toggled.connect(self._toggle_password_visibility)
        password_layout.addWidget(self.router_password, 1)
        password_layout.addWidget(self.password_eye_button)
        self.net_interface = QComboBox()
        self.net_interface.addItem('自动（按默认路由选择）', 'auto')
        self.router_status_indicator = QLabel()
        self.router_status_indicator.setFixedSize(12, 12)
        self.router_status_indicator.setStyleSheet('background-color: gray; border-radius: 6px;')
        self.router_status_label = QLabel('未检测')
        self.test_router_button = QPushButton('测试连接')
        status_layout = QHBoxLayout()
        status_layout.setSpacing(5)
        status_layout.addWidget(self.router_status_indicator)
        status_layout.addWidget(self.router_status_label, 1)
        status_layout.addWidget(self.test_router_button)
        layout.addRow('地址:', self.router_host)
        layout.addRow('端口:', self.router_port)
        layout.addRow('用户:', self.router_user)
        layout.addRow('密码:', password_row)
        layout.addRow('网卡:', self.net_interface)
        self._seed_interfaces()
        layout.addRow('状态:', status_layout)
        return group

    def _eye_icon(self, visible, color):
        '''画一枚眼睛图标：睁眼 = 空心瞳，闭眼 = 加一道斜杠。不依赖外部资源。'''
        size = 20
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing, True)
        pen = QPen(QColor(color))
        pen.setWidthF(1.5)
        pen.setCapStyle(Qt.RoundCap)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        path = QPainterPath()
        path.moveTo(2.0, 10.0)
        path.cubicTo(6.0, 4.2, 14.0, 4.2, 18.0, 10.0)
        path.cubicTo(14.0, 15.8, 6.0, 15.8, 2.0, 10.0)
        painter.drawPath(path)
        if visible:
            painter.setBrush(QBrush(QColor(color)))
            painter.drawEllipse(QPointF(10.0, 10.0), 2.6, 2.6)
        else:
            painter.drawLine(QPointF(4.2, 16.0), QPointF(15.8, 4.0))
        painter.end()
        return QIcon(pixmap)

    def _toggle_password_visibility(self, visible):
        self.router_password.setEchoMode(QLineEdit.Normal if visible else QLineEdit.Password)
        self._refresh_password_eye()

    def _refresh_password_eye(self):
        try:
            visible = self.password_eye_button.isChecked()
            color = self._theme_palette()['accent'] if visible else self._theme_palette()['text_dim']
            self.password_eye_button.setIcon(self._eye_icon(visible, color))
            self.password_eye_button.setToolTip('隐藏密码' if visible else '显示密码')
            self.password_eye_button.setStyleSheet(
                'QToolButton { border: none; background: transparent; padding: 0px; }'
                'QToolButton:hover { background: transparent; }')
        except Exception:
            pass

    def test_router_connection(self):
        host = self.router_host.text().strip()
        if not host:
            self._update_router_status(False, '请填写地址')
            return
        self.test_router_button.setEnabled(False)
        self._update_router_status(None, '检测中...')
        settings = (host, self.router_port.value(), self.router_user.text().strip() or 'root', self.router_password.text())
        self.router_test_executor.submit(self._router_test_worker, settings)

    def _router_test_worker(self, settings):
        host, port, user, password = settings
        ok, message, interfaces = False, '', []
        try:
            router = RouterStats(host=host, port=port, username=user, password=password, timeout=5.0)
            ok, message = router.test_connection()
            interfaces = list(getattr(router, 'last_interfaces', []) or [])
            router.close()
        except Exception as exc:
            ok, message = False, str(exc)
        self.router_test_done.emit(bool(ok), str(message), interfaces)

    def _fill_interfaces(self, interfaces):
        '''Rebuild the 网卡 combo, keeping the current selection when possible.'''
        if not interfaces:
            return
        current = self.net_interface.currentData()
        self.net_interface.clear()
        self.net_interface.addItem('自动（按默认路由选择）', 'auto')
        for name in interfaces:
            self.net_interface.addItem(name, name)
        index = self.net_interface.findData(current)
        self.net_interface.setCurrentIndex(index if index >= 0 else 0)

    def _seed_interfaces(self):
        '''Pre-fill 网卡 from the running widget's last sample so the user does not
        have to press 测试连接 first.'''
        try:
            parent = self.parent()
            ns = ((getattr(parent, 'metrics_data', None) or {}).get('router') or {})
            self._fill_interfaces(list(ns.get('interfaces') or []))
        except Exception:
            pass

    def on_router_test_done(self, ok, message, interfaces):
        self.test_router_button.setEnabled(True)
        self._update_router_status(ok, message)
        if ok:
            self._fill_interfaces(interfaces)

    def _update_router_status(self, is_connected, message):
        if is_connected is None:
            color = '#FFC107'
        elif is_connected:
            color = '#4CAF50'
        else:
            color = '#F44336'
        self.router_status_indicator.setStyleSheet('background-color: %s; border-radius: 6px;' % color)
        self.router_status_label.setText(message)

    def _create_card_selection_group(self):
        group = QGroupBox('卡片选择')
        layout = QHBoxLayout(group)
        layout.setSpacing(15)
        self.show_cpu_chart = QCheckBox('CPU')
        self.show_memory_chart = QCheckBox('内存')
        self.show_disk_chart = QCheckBox('磁盘')
        self.show_network_chart = QCheckBox('下载速度')
        self.show_upload_chart = QCheckBox('上传速度')
        self.show_connections_chart = QCheckBox('连接')
        for checkbox in self.show_cpu_chart, self.show_memory_chart, self.show_disk_chart, self.show_network_chart, self.show_upload_chart, self.show_connections_chart:
            layout.addWidget(checkbox)
        layout.setContentsMargins(15, 10, 15, 10)
        return group

    def _create_display_group(self):
        group = QGroupBox('显示设置')
        layout = QGridLayout(group)
        layout.setHorizontalSpacing(15)
        layout.setVerticalSpacing(8)
        layout.setContentsMargins(15, 10, 15, 10)
        self.refresh_interval = QSpinBox()
        self.data_points = QSpinBox()
        self.layout_option = QComboBox()
        self.theme_select = QComboBox()
        self.card_opacity = QSpinBox()
        self.text_opacity = QSpinBox()
        self.chart_opacity = QSpinBox()
        self.card_radius = QSpinBox()
        self.widget_width = QSpinBox()
        self.widget_height = QSpinBox()
        self.refresh_interval.setRange(1, 300)
        self.refresh_interval.setSuffix(' 秒')
        self.data_points.setRange(20, 200)
        self.data_points.setSuffix(' 点')
        self.layout_option.addItem('每行一个卡片', 1)
        self.layout_option.addItem('每行两个卡片', 2)
        self.layout_option.addItem('每行四个卡片', 4)
        self.theme_select.addItem('明亮')
        self.theme_select.addItem('暗黑')
        self.card_opacity.setRange(0, 100)
        self.card_opacity.setSuffix(' %')
        self.text_opacity.setRange(0, 100)
        self.text_opacity.setSuffix(' %')
        self.chart_opacity.setRange(0, 100)
        self.chart_opacity.setSuffix(' %')
        self.card_radius.setRange(0, 20)
        self.card_radius.setSuffix(' 像素')
        self.widget_width.setRange(10, 1000)
        self.widget_width.setSuffix(' 像素')
        self.widget_height.setRange(10, 500)
        self.widget_height.setSuffix(' 像素')
        self.ui_scale = QSpinBox()
        self.ui_scale.setRange(0, 250)
        self.ui_scale.setSuffix(' %')
        self.ui_scale.setSpecialValueText('自动')
        self.ui_scale.setToolTip('整体缩放组件尺寸与文字。自动 = 按桌面缩放比例的 70%（100%~160%）')
        self.edge_hide = QCheckBox('靠边隐藏')
        self.edge_hide.setToolTip('拖到屏幕边缘停靠后自动收起，只留 4 像素；鼠标碰一下边缘再滑出（多显示器按光标所在屏幕，避开任务栏）')
        self.close_to_tray = QCheckBox('关闭时缩到托盘')
        self.close_to_tray.setToolTip('收到窗口后留在托盘继续监控，右键托盘图标可重新显示或退出')
        self.hide_from_taskbar = QCheckBox('不在任务栏显示')
        self.hide_from_taskbar.setToolTip('组件只在托盘里挂着，不占任务栏、不参与 Alt+Tab')
        self.click_through = QCheckBox('鼠标穿透')
        self.click_through.setToolTip('开启后鼠标点击穿透到下面的窗口，卡片不能右键也不能拖动；只能在托盘菜单里关掉')
        controls = [(0, 0, '刷新间隔:', self.refresh_interval), (0, 2, '数据数量:', self.data_points), (1, 0, '布局选项:', self.layout_option), (1, 2, '应用主题:', self.theme_select), (2, 0, '背景透明:', self.card_opacity), (2, 2, '文字透明:', self.text_opacity), (3, 0, '折线透明:', self.chart_opacity), (3, 2, '卡片圆角:', self.card_radius), (4, 0, '部件宽度:', self.widget_width), (4, 2, '部件高度:', self.widget_height), (5, 0, '界面缩放:', self.ui_scale)]
        for row, col, label_text, control in controls:
            label = QLabel(label_text)
            layout.addWidget(label, row, col, Qt.AlignRight)
            layout.addWidget(control, row, col + 1)
        layout.addWidget(QLabel('窗口行为:'), 6, 0, Qt.AlignRight)
        layout.addWidget(self.edge_hide, 6, 1)
        layout.addWidget(self.click_through, 6, 2)
        layout.addWidget(QLabel('托盘 / 任务栏:'), 7, 0, Qt.AlignRight)
        layout.addWidget(self.close_to_tray, 7, 1)
        layout.addWidget(self.hide_from_taskbar, 7, 2)
        return group

    def _create_shortcut_group(self):
        group = QGroupBox('快捷方式设置')
        layout = QGridLayout(group)
        layout.setHorizontalSpacing(15)
        layout.setVerticalSpacing(8)
        layout.setContentsMargins(15, 10, 15, 10)
        self.shortcut_button_size = QSpinBox()
        self.shortcut_button_radius = QSpinBox()
        self.shortcut_border_width = QSpinBox()
        self.shortcut_hover_scale = QDoubleSpinBox()
        self.shortcut_button_position = QComboBox()
        self.shortcut_button_alignment = QComboBox()
        self.shortcut_display_mode = QComboBox()
        self.shortcut_animation_mode = QComboBox()
        self.shortcut_button_offset_x = QSpinBox()
        self.shortcut_button_offset_y = QSpinBox()
        self.shortcut_button_spacing = QSpinBox()
        self.shortcut_button_size.setRange(20, 100)
        self.shortcut_button_size.setSuffix(' 像素')
        self.shortcut_button_radius.setRange(0, 20)
        self.shortcut_button_radius.setSuffix(' 像素')
        self.shortcut_border_width.setRange(-10, 10)
        self.shortcut_border_width.setSuffix(' 像素')
        self.shortcut_border_width.setToolTip('0:无描边 正数:向外扩展描边 负数:向内收缩描边')
        self.shortcut_hover_scale.setRange(1.0, 2.0)
        self.shortcut_hover_scale.setSingleStep(0.1)
        self.shortcut_hover_scale.setSuffix(' 倍')
        self.shortcut_hover_scale.setToolTip('鼠标悬停时按钮放大的倍数')
        self.shortcut_button_offset_x.setRange(-100, 100)
        self.shortcut_button_offset_x.setSuffix(' 像素')
        self.shortcut_button_offset_y.setRange(-100, 100)
        self.shortcut_button_offset_y.setSuffix(' 像素')
        self.shortcut_button_spacing.setRange(0, 100)
        self.shortcut_button_spacing.setSuffix(' 像素')
        self.shortcut_button_spacing.setToolTip('按钮之间的间距，位置在上方/下方时控制横向间距，在左侧/右侧时控制纵向间距')
        for combo, items in (self.shortcut_button_position, [('左侧', 'left'), ('右侧', 'right'), ('上方', 'top'), ('下方', 'bottom')]), (self.shortcut_button_alignment, [('左对齐', 'left'), ('居中', 'center'), ('右对齐', 'right')]), (self.shortcut_display_mode, [('不显示', 'none'), ('总是显示', 'always'), ('悬停显示', 'hover')]), (self.shortcut_animation_mode, [('默认', 'default'), ('淡入淡出', 'fade'), ('缩放效果', 'scale')]):
            for text, data in items:
                combo.addItem(text, data)
        controls = [(0, 0, '按钮大小:', self.shortcut_button_size), (0, 2, '按钮圆角:', self.shortcut_button_radius), (1, 0, '描边粗细:', self.shortcut_border_width), (1, 2, '悬停放大:', self.shortcut_hover_scale), (2, 0, '按钮位置:', self.shortcut_button_position), (2, 2, '对齐方式:', self.shortcut_button_alignment), (3, 0, '显示方式:', self.shortcut_display_mode), (3, 2, '动画效果:', self.shortcut_animation_mode), (4, 0, '横轴调整:', self.shortcut_button_offset_x), (4, 2, '纵轴调整:', self.shortcut_button_offset_y), (5, 0, '按钮间距:', self.shortcut_button_spacing)]
        for row, col, label_text, control in controls:
            label = QLabel(label_text)
            layout.addWidget(label, row, col, Qt.AlignRight)
            layout.addWidget(control, row, col + 1)
        self.shortcut_button_position.currentIndexChanged.connect(self._on_position_changed)
        self.edit_shortcuts_button = QPushButton('编辑快捷方式链接')
        self.edit_shortcuts_button.clicked.connect(self.edit_shortcut_links)
        layout.addWidget(self.edit_shortcuts_button, 6, 0, 1, 4)
        return group

    def _on_position_changed(self, index):
        position = self.shortcut_button_position.currentData()
        current_alignment = self.shortcut_button_alignment.currentData()
        self.shortcut_button_alignment.clear()
        if position in ('left', 'right'):
            for item, data in (('顶部对齐', 'top'), ('居中', 'center'), ('底部对齐', 'bottom')):
                self.shortcut_button_alignment.addItem(item, data)
        else:
            for item, data in (('左对齐', 'left'), ('居中', 'center'), ('右对齐', 'right')):
                self.shortcut_button_alignment.addItem(item, data)
        index = self.shortcut_button_alignment.findData(current_alignment)
        if index >= 0:
            self.shortcut_button_alignment.setCurrentIndex(index)

    def _create_performance_group(self):
        group = QGroupBox('性能设置')
        layout = QHBoxLayout(group)
        layout.setSpacing(15)
        layout.setContentsMargins(15, 10, 15, 10)
        layout.addWidget(QLabel('性能模式:'))
        self.performance_mode = QComboBox()
        for item, data in (('平衡模式', 0), ('性能模式', 1), ('节能模式', 2)):
            self.performance_mode.addItem(item, data)
        self.performance_mode.setToolTip('平衡模式：默认设置\n性能模式：提升响应速度，增加资源使用\n节能模式：降低资源使用，可能影响流畅度')
        layout.addWidget(self.performance_mode)
        self.animation_enabled = QCheckBox('启用动画效果')
        self.animation_enabled.setChecked(True)
        self.animation_enabled.setToolTip('禁用动画可以提升性能，但会影响视觉体验')
        layout.addWidget(self.animation_enabled)
        self.cache_enabled = QCheckBox('启用数据缓存')
        self.cache_enabled.setChecked(True)
        self.cache_enabled.setToolTip('启用缓存可以提升性能，但可能增加内存使用')
        layout.addWidget(self.cache_enabled)
        layout.addStretch()
        return group

    DEVELOPER_HTML = '<style> a:link {color: %s; text-decoration: none;} a:hover {color: %s;}</style>RouterSight 路由视界 v1.0（基于 <a href="https://www.koolcenter.com/t/topic/7826/1">NetSight v2.1.1</a> 修改） | 原作者：<a href="https://www.koolcenter.com/t/topic/5379">RtrBug</a> | 修改：<a href="https://zzzyy.zabc.net">知影</a> | <a href="https://www.koolcenter.com">酷友社论坛</a>'

    def _create_developer_layout(self):
        layout = QHBoxLayout()
        self.developer_label = QLabel()
        self.developer_label.setOpenExternalLinks(True)
        self.developer_label.setAlignment(Qt.AlignCenter)
        self.developer_label.setStyleSheet('QLabel { font-size: 10px; }')
        layout.addWidget(self.developer_label)
        return layout

    def _create_button_layout(self):
        layout = QHBoxLayout()
        self.save_button = QPushButton('保存设置')
        self.reset_button = QPushButton('重置默认')
        self.save_button.setDefault(True)
        layout.addStretch(1)
        layout.addWidget(self.save_button)
        layout.addWidget(self.reset_button)
        layout.addStretch(1)
        return layout

    def _connect_signals(self):
        self.save_button.clicked.connect(self.save_settings)
        self.reset_button.clicked.connect(self.reset_settings)
        self.test_router_button.clicked.connect(self.test_router_connection)
        self.theme_select.currentIndexChanged.connect(self._apply_theme)
        self._connect_preview_signals()

    def _connect_preview_signals(self):
        preview_controls = [(self.refresh_interval, 'valueChanged', int), (self.data_points, 'valueChanged', int), (self.layout_option, 'currentIndexChanged', (lambda: self.layout_option.currentData())), (self.theme_select, 'currentIndexChanged', int), (self.card_opacity, 'valueChanged', int), (self.text_opacity, 'valueChanged', int), (self.chart_opacity, 'valueChanged', int), (self.card_radius, 'valueChanged', int), (self.widget_width, 'valueChanged', int), (self.widget_height, 'valueChanged', int), (self.ui_scale, 'valueChanged', int), (self.show_cpu_chart, 'toggled', bool), (self.show_memory_chart, 'toggled', bool), (self.show_disk_chart, 'toggled', bool), (self.show_network_chart, 'toggled', bool), (self.show_upload_chart, 'toggled', bool), (self.show_connections_chart, 'toggled', bool), (self.edge_hide, 'toggled', bool), (self.click_through, 'toggled', bool), (self.close_to_tray, 'toggled', bool), (self.hide_from_taskbar, 'toggled', bool), (self.performance_mode, 'currentIndexChanged', (lambda: self.performance_mode.currentData())), (self.animation_enabled, 'toggled', bool), (self.cache_enabled, 'toggled', bool), (self.shortcut_button_size, 'valueChanged', int), (self.shortcut_button_radius, 'valueChanged', int), (self.shortcut_border_width, 'valueChanged', int), (self.shortcut_hover_scale, 'valueChanged', float), (self.shortcut_button_position, 'currentIndexChanged', str), (self.shortcut_button_alignment, 'currentIndexChanged', str), (self.shortcut_display_mode, 'currentIndexChanged', str), (self.shortcut_animation_mode, 'currentIndexChanged', str), (self.shortcut_button_offset_x, 'valueChanged', int), (self.shortcut_button_offset_y, 'valueChanged', int), (self.shortcut_button_spacing, 'valueChanged', int)]
        for control, signal, converter in preview_controls:
            if hasattr(control, signal):
                getattr(control, signal).connect(self._start_preview_timer)

    def _start_preview_timer(self):
        self.preview_timer.start(200)

    def _delayed_preview(self):
        self.preview_settings()
        if hasattr(self, 'last_animation_mode'):
            current_animation_mode = self.shortcut_animation_mode.currentData()
            if current_animation_mode != self.last_animation_mode:
                self.last_animation_mode = current_animation_mode
                if self.parent():
                    if hasattr(self.parent(), 'preview_shortcut_animation'):
                        self.parent().preview_shortcut_animation()

    def edit_shortcut_links(self):
        config = self.parent().config_manager if self.parent() and hasattr(self.parent(), 'config_manager') else ConfigManager()
        links = config.get_shortcut_links()
        dialog = ShortcutLinksDialog(self)
        dialog.set_links(links)
        dialog.shortcut_data_changed.connect(self.on_shortcut_data_changed)
        dialog.preview_update_requested.connect(self.on_shortcut_preview_update)
        if dialog.exec_() == QDialog.Accepted:
            new_links = dialog.get_links()
            config.set_shortcut_links(new_links)
            config.save_config()
            if self.parent():
                if hasattr(self.parent(), '_create_shortcut_buttons'):
                    self.parent()._create_shortcut_buttons()

    def on_shortcut_data_changed(self, row, link_data):
        '''处理快捷方式数据改变信号 - 关键修复：实时更新主窗口按钮'''

        main_window = self.parent()
        if main_window:
            if hasattr(main_window, 'update_shortcut_button_from_dialog'):
                main_window.update_shortcut_button_from_dialog(row, link_data)

    def on_shortcut_preview_update(self, row):
        '''处理快捷按钮预览更新请求'''

        main_window = self.parent()
        if main_window:
            if hasattr(main_window, '_update_main_window_shortcut_button'):
                main_window._update_main_window_shortcut_button(row)

    def load_settings(self):
        config = ConfigManager()
        self.router_host.setText(config.get('router_host'))
        try:
            self.router_port.setValue(int(config.get('router_port') or 22))
        except (TypeError, ValueError):
            self.router_port.setValue(22)
        self.router_user.setText(config.get('router_user'))
        self.router_password.setText(config.get('router_password'))
        interface = config.get('net_interface') or 'auto'
        index = self.net_interface.findData(interface)
        if index < 0:
            self.net_interface.addItem(interface, interface)
            index = self.net_interface.findData(interface)
        self.net_interface.setCurrentIndex(index if index >= 0 else 0)
        self.refresh_interval.setValue(config.getint('refresh_interval'))
        self.data_points.setValue(config.getint('data_points'))
        layout_index = self.layout_option.findData(config.getint('layout_option'))
        if layout_index >= 0:
            self.layout_option.setCurrentIndex(layout_index)
        self.theme_select.setCurrentIndex(config.getint('theme'))
        self.card_opacity.setValue(config.getint('card_opacity'))
        self.text_opacity.setValue(config.getint('text_opacity'))
        self.chart_opacity.setValue(config.getint('chart_opacity'))
        self.card_radius.setValue(config.getint('card_radius'))
        self.widget_width.setValue(config.getint('widget_width'))
        self.widget_height.setValue(config.getint('widget_height'))
        self.ui_scale.setValue(config.getint('ui_scale', 0))
        self.show_cpu_chart.setChecked(config.getboolean('show_cpu_chart'))
        self.show_memory_chart.setChecked(config.getboolean('show_memory_chart'))
        self.show_disk_chart.setChecked(config.getboolean('show_disk_chart'))
        self.show_network_chart.setChecked(config.getboolean('show_network_chart'))
        self.show_upload_chart.setChecked(config.getboolean('show_upload_chart'))
        self.edge_hide.setChecked(config.getboolean('edge_hide', True))
        self.click_through.setChecked(config.getboolean('click_through', False))
        self.close_to_tray.setChecked(config.getboolean('close_to_tray', True))
        self.hide_from_taskbar.setChecked(config.getboolean('hide_from_taskbar', True))
        self.show_connections_chart.setChecked(config.getboolean('show_connections_chart'))
        performance_index = self.performance_mode.findData(config.getint('performance_mode'))
        if performance_index >= 0:
            self.performance_mode.setCurrentIndex(performance_index)
        self.animation_enabled.setChecked(config.getboolean('animation_enabled'))
        self.cache_enabled.setChecked(config.getboolean('cache_enabled'))
        self.shortcut_button_size.setValue(config.getint('shortcut_button_size'))
        self.shortcut_button_radius.setValue(config.getint('shortcut_button_radius'))
        self.shortcut_border_width.setValue(config.getint('shortcut_border_width', 0))
        self.shortcut_hover_scale.setValue(config.getfloat('shortcut_hover_scale', 1.2))
        self.shortcut_button_spacing.setValue(config.getint('shortcut_button_spacing', 5))
        for combo, key, default in (self.shortcut_button_position, 'shortcut_button_position', 'bottom'), (self.shortcut_button_alignment, 'shortcut_button_alignment', 'left'), (self.shortcut_display_mode, 'shortcut_display_mode', 'none'), (self.shortcut_animation_mode, 'shortcut_animation_mode', 'default'):
            index = combo.findData(config.get(key, default))
            if index >= 0:
                combo.setCurrentIndex(index)
        self.shortcut_button_offset_x.setValue(config.getint('shortcut_button_offset_x', 0))
        self.shortcut_button_offset_y.setValue(config.getint('shortcut_button_offset_y', 0))
        self.last_animation_mode = self.shortcut_animation_mode.currentData()

    def save_settings(self):
        config = self.parent().config_manager if self.parent() and hasattr(self.parent(), 'config_manager') else ConfigManager()
        settings = {'refresh_interval': self.refresh_interval.value(), 'data_points': self.data_points.value(), 'layout_option': self.layout_option.currentData(), 'theme': self.theme_select.currentIndex(), 'card_opacity': self.card_opacity.value(), 'text_opacity': self.text_opacity.value(), 'chart_opacity': self.chart_opacity.value(), 'card_radius': self.card_radius.value(), 'widget_width': self.widget_width.value(), 'widget_height': self.widget_height.value(), 'ui_scale': self.ui_scale.value(), 'show_cpu_chart': self.show_cpu_chart.isChecked(), 'show_memory_chart': self.show_memory_chart.isChecked(), 'show_disk_chart': self.show_disk_chart.isChecked(), 'show_network_chart': self.show_network_chart.isChecked(), 'show_upload_chart': self.show_upload_chart.isChecked(), 'edge_hide': self.edge_hide.isChecked(), 'click_through': self.click_through.isChecked(), 'close_to_tray': self.close_to_tray.isChecked(), 'hide_from_taskbar': self.hide_from_taskbar.isChecked(), 'show_connections_chart': self.show_connections_chart.isChecked(), 'data_source': 'router', 'router_host': self.router_host.text().strip(), 'router_port': self.router_port.value(), 'router_user': self.router_user.text().strip(), 'router_password': self.router_password.text(), 'net_interface': self.net_interface.currentData() or 'auto', 'performance_mode': self.performance_mode.currentData(), 'animation_enabled': self.animation_enabled.isChecked(), 'cache_enabled': self.cache_enabled.isChecked(), 'shortcut_button_size': self.shortcut_button_size.value(), 'shortcut_button_radius': self.shortcut_button_radius.value(), 'shortcut_border_width': self.shortcut_border_width.value(), 'shortcut_hover_scale': self.shortcut_hover_scale.value(), 'shortcut_button_position': self.shortcut_button_position.currentData(), 'shortcut_button_alignment': self.shortcut_button_alignment.currentData(), 'shortcut_display_mode': self.shortcut_display_mode.currentData(), 'shortcut_animation_mode': self.shortcut_animation_mode.currentData(), 'shortcut_button_offset_x': self.shortcut_button_offset_x.value(), 'shortcut_button_offset_y': self.shortcut_button_offset_y.value(), 'shortcut_button_spacing': self.shortcut_button_spacing.value()}
        for key, value in settings.items():
            config.set(key, value)
        config.save_config()
        parent = self.parent()
        if parent is not None and hasattr(parent, 'close_router'):
            parent.close_router()
        self.settings_saved.emit()
        self.accept()

    def reset_settings(self):
        default_config = ConfigManager.DEFAULT_CONFIG
        self.refresh_interval.setValue(int(default_config['refresh_interval']))
        self.data_points.setValue(int(default_config['data_points']))
        self.layout_option.setCurrentIndex(1)
        self.theme_select.setCurrentIndex(1)
        self.card_opacity.setValue(int(default_config['card_opacity']))
        self.text_opacity.setValue(int(default_config['text_opacity']))
        self.chart_opacity.setValue(int(default_config['chart_opacity']))
        self.card_radius.setValue(int(default_config['card_radius']))
        self.widget_width.setValue(int(default_config['widget_width']))
        self.widget_height.setValue(int(default_config['widget_height']))
        for checkbox in self.show_cpu_chart, self.show_memory_chart, self.show_disk_chart, self.show_network_chart, self.show_upload_chart, self.show_connections_chart:
            checkbox.setChecked(True)
        self.edge_hide.setChecked(True)
        self.click_through.setChecked(False)
        self.close_to_tray.setChecked(True)
        self.hide_from_taskbar.setChecked(True)
        self.performance_mode.setCurrentIndex(0)
        self.animation_enabled.setChecked(True)
        self.cache_enabled.setChecked(True)
        self.shortcut_button_size.setValue(int(default_config['shortcut_button_size']))
        self.shortcut_button_radius.setValue(int(default_config['shortcut_button_radius']))
        self.shortcut_border_width.setValue(int(default_config['shortcut_border_width']))
        self.shortcut_hover_scale.setValue(float(default_config['shortcut_hover_scale']))
        self.shortcut_button_spacing.setValue(int(default_config['shortcut_button_spacing']))
        self.shortcut_button_position.setCurrentIndex(3)
        self.shortcut_button_alignment.setCurrentIndex(0)
        self.shortcut_display_mode.setCurrentIndex(0)
        self.shortcut_animation_mode.setCurrentIndex(0)
        self.shortcut_button_offset_x.setValue(0)
        self.shortcut_button_offset_y.setValue(0)
        self._apply_theme()
        self.preview_settings()

    def preview_settings(self):
        if not self.parent():
            return
        parent = self.parent()
        preview_config = {'refresh_interval': self.refresh_interval.value(), 'data_points': self.data_points.value(), 'layout_option': self.layout_option.currentData(), 'theme': self.theme_select.currentIndex(), 'card_opacity': self.card_opacity.value(), 'text_opacity': self.text_opacity.value(), 'chart_opacity': self.chart_opacity.value(), 'card_radius': self.card_radius.value(), 'widget_width': self.widget_width.value(), 'widget_height': self.widget_height.value(), 'ui_scale': self.ui_scale.value(), 'show_cpu_chart': self.show_cpu_chart.isChecked(), 'show_memory_chart': self.show_memory_chart.isChecked(), 'show_disk_chart': self.show_disk_chart.isChecked(), 'show_network_chart': self.show_network_chart.isChecked(), 'show_upload_chart': self.show_upload_chart.isChecked(), 'edge_hide': self.edge_hide.isChecked(), 'click_through': self.click_through.isChecked(), 'close_to_tray': self.close_to_tray.isChecked(), 'hide_from_taskbar': self.hide_from_taskbar.isChecked(), 'show_connections_chart': self.show_connections_chart.isChecked(), 'performance_mode': self.performance_mode.currentData(), 'animation_enabled': self.animation_enabled.isChecked(), 'cache_enabled': self.cache_enabled.isChecked(), 'shortcut_button_size': self.shortcut_button_size.value(), 'shortcut_button_radius': self.shortcut_button_radius.value(), 'shortcut_border_width': self.shortcut_border_width.value(), 'shortcut_hover_scale': self.shortcut_hover_scale.value(), 'shortcut_button_position': self.shortcut_button_position.currentData(), 'shortcut_button_alignment': self.shortcut_button_alignment.currentData(), 'shortcut_display_mode': self.shortcut_display_mode.currentData(), 'shortcut_animation_mode': self.shortcut_animation_mode.currentData(), 'shortcut_button_offset_x': self.shortcut_button_offset_x.value(), 'shortcut_button_offset_y': self.shortcut_button_offset_y.value(), 'shortcut_button_spacing': self.shortcut_button_spacing.value()}
        parent.apply_preview_settings(preview_config)


class RouterWidget(QWidget):
    router_sample_ready = pyqtSignal(object, str)

    def __init__(self):
        super().__init__()
        self.config_manager = ConfigManager()
        self.is_locked = False          # 锁定/解锁已取消：卡片始终可拖动
        self.is_stays_on_top = False
        self.drag_position = QPoint()
        self._dragging = False
        self._dock_edge = None          # 'left'/'right'/'top'/'bottom' when 停靠
        self._edge_hidden = False
        self._edge_armed = False
        self._edge_out_polls = 0
        self._skip_save = False
        self._edge_timer = QTimer(self)
        self._edge_timer.setInterval(EDGE_POLL_MS)
        self._edge_timer.timeout.connect(self._poll_edge)
        self.metrics_data = {}
        self.charts = {}
        self.network_manager = QNetworkAccessManager()
        self.current_reply = None
        self.router = None
        self.router_settings = None
        self.router_busy = False
        # 连接失败后的退避状态：路由器的 SSH 未认证连接配额很小，失败后
        # 立刻按原间隔重试会把它占满，最终连正常连接也建立不起来。
        self.router_fail_count = 0
        self.router_retry_at = 0.0
        self.router_executor = ThreadPoolExecutor(max_workers=1)
        self.router_sample_ready.connect(self.on_router_sample)
        self.last_error = ''
        self.performance_optimizer = PerformanceOptimizer()
        self.preview_config = None
        self.cached_data = {}
        self.last_data = {}
        self.is_online = True
        self.last_network_check = 0
        self.network_check_interval = 10
        self.shortcut_buttons = []
        self.button_animations = {}
        self.shortcut_hide_timer = QTimer()
        self.shortcut_buttons_visible = False
        self.shortcut_buttons_initialized = False
        self.shortcut_hide_timer.setSingleShot(True)
        self.shortcut_hide_timer.timeout.connect(self.hide_shortcut_buttons)
        self.init_ui()
        self.init_tray_icon()
        self.setup_timer()
        self.fetch_data()

    def closeEvent(self, event):
        '''关闭窗口时留在托盘继续跑；托盘里点"退出"才真正退出。'''
        try:
            # 没托盘可用时不能"关闭到托盘"，否则窗口消失又找不回来
            to_tray = (not getattr(self, '_force_quit', False)
                       and self.tray_icon is not None
                       and QSystemTrayIcon.isSystemTrayAvailable()
                       and self.config_manager.getboolean('close_to_tray'))
        except Exception:
            to_tray = False
        if to_tray:
            event.ignore()
            self.hide()
            self._notify_tray_once()
            return
        # 没有托盘可缩，关掉窗口就等于退出（否则会变成没有界面的后台进程）
        self._force_quit = True
        super().closeEvent(event)
        QApplication.quit()

    def _notify_tray_once(self):
        '''第一次缩到托盘时提示一下，免得用户以为程序被关掉了。'''
        if getattr(self, '_tray_tip_shown', False):
            return
        self._tray_tip_shown = True
        try:
            self.tray_icon.showMessage('RouterSight',
                                       '组件已收到托盘继续运行，右键托盘图标可以打开设置或退出。',
                                       QSystemTrayIcon.Information, 4000)
        except Exception:
            pass

    def toggle_widget_visible(self):
        if self.isVisible():
            self.hide()
        else:
            self.show()
            self.raise_()

    def get_resource_path(self, relative_path):
        try:
            base_path = sys._MEIPASS
        except Exception:
            base_path = os.path.abspath('.')
        return os.path.join(base_path, relative_path)

    def _window_flags(self):
        '''桌面组件默认用 Qt.Tool：不进任务栏、不参与 Alt+Tab，只在托盘里挂着。
        关掉"不在任务栏显示"后改用 Qt.Window，普通任务栏条目就回来了。'''
        flags = Qt.FramelessWindowHint
        flags |= Qt.Tool if self.config_manager.getboolean('hide_from_taskbar') else Qt.Window
        if self.config_manager.getboolean('stays_on_top'):
            flags |= Qt.WindowStaysOnTopHint
        return flags

    def init_ui(self):
        self.setWindowFlags(self._window_flags())
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setWindowTitle('RouterSight 路由视界')
        self._set_window_icon()
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        self.grid_layout = QGridLayout()
        self.grid_layout.setContentsMargins(2, 2, 2, 2)
        self.grid_layout.setSpacing(2)
        self._create_charts()
        self.update_layout()
        main_layout.addLayout(self.grid_layout)
        self.setFixedSize(self.get_widget_width(), self.get_widget_height())
        self.apply_theme()
        self._set_initial_position()
        self._set_initial_state()
        auto_start = self.config_manager.getboolean('auto_start')
        self.set_auto_start(auto_start)
        self._apply_performance_settings()
        self._update_charts_visibility()
        self._create_shortcut_buttons()
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_context_menu)
        self.setMouseTracking(True)

    def _apply_performance_settings(self):
        performance_mode = self.config_manager.getint('performance_mode')
        animation_enabled = self.config_manager.getboolean('animation_enabled')
        self.performance_optimizer.set_mode(performance_mode)
        for chart in self.charts.values():
            chart.set_animation_enabled(animation_enabled)

    def _create_charts(self):
        self.cpu_chart = MetricChart('CPU 使用率', 'cpu', self)
        self.memory_chart = MetricChart('内存使用', 'memory', self)
        self.disk_chart = MetricChart('磁盘 I/O', 'disk', self)
        self.network_chart = MetricChart('下载速度', 'network', self)
        self.network_chart.color = QColor(34, 211, 238)
        self.upload_chart = MetricChart('上传速度', 'network', self)
        self.upload_chart.color = QColor(139, 92, 246)
        self.connections_chart = MetricChart('TCP/UDP 连接', 'connections', self)
        self.charts = {'cpu': self.cpu_chart, 'memory': self.memory_chart, 'disk': self.disk_chart, 'network': self.network_chart, 'upload': self.upload_chart, 'connections': self.connections_chart}
        data_points = self.config_manager.getint('data_points')
        for chart in self.charts.values():
            chart.update_data_points(data_points)

    def _set_window_icon(self):
        try:
            icon_path = self.get_resource_path('logo.ico')
            if os.path.exists(icon_path):
                self.setWindowIcon(QIcon(icon_path))
                return
            self.setWindowIcon(QApplication.style().standardIcon(QApplication.style().SP_ComputerIcon))
            return
        except Exception:
            self.setWindowIcon(QApplication.style().standardIcon(QApplication.style().SP_ComputerIcon))

    def _create_shortcut_buttons(self):
        for button in self.shortcut_buttons:
            button.hide()
            button.deleteLater()
        self.shortcut_buttons.clear()
        self.button_animations.clear()
        links = self.config_manager.get_shortcut_links()
        button_size = self.get_shortcut_button_size()
        button_radius = self.get_shortcut_button_radius()
        border_width = self.get_shortcut_border_width()
        for link_data in links:
            if not link_data.get('enabled', True):
                continue
            name = link_data.get('name', '')
            link = link_data.get('link', '')
            icon_char = link_data.get('icon_char')
            icon_image = link_data.get('icon_image')
            border_color = link_data.get('border_color', '#000000')
            border_opacity = link_data.get('border_opacity', 100)
            if not link and not name and not icon_char and not icon_image:
                continue
            button = ShortcutButton(name, link, icon_char, icon_image, border_color, border_opacity, self)
            button.set_size(button_size)
            button.set_radius(button_radius)
            button.set_border_width(border_width)
            button.clicked.connect(self.on_shortcut_clicked)
            self._update_button_stays_on_top(button)
            self.shortcut_buttons.append(button)
            continue
        self._update_shortcut_buttons_position()
        self._update_shortcut_buttons_visibility()
        self.shortcut_buttons_initialized = True
        QTimer.singleShot(2000, self.start_favicon_loading)

    def start_favicon_loading(self):
        for button in self.shortcut_buttons:
            if not hasattr(button, 'is_web_link'):
                continue
            if button.is_web_link:
                delay = hash(button.link) % 3000
                QTimer.singleShot(delay, button.start_favicon_load)

    def _update_button_stays_on_top(self, button):
        flags = Qt.Tool | Qt.FramelessWindowHint
        if self.is_stays_on_top:
            flags |= Qt.WindowStaysOnTopHint
        button.setWindowFlags(flags)

    def _update_shortcut_buttons_visibility(self, force_show=False):
        display_mode = self.get_shortcut_display_mode()
        if force_show:
            for button in self.shortcut_buttons:
                button.show()
            self.shortcut_buttons_visible = True
            self.shortcut_hide_timer.stop()
            for button in self.shortcut_buttons:
                button.opacity = 1.0
                button.scale = 1.0
            return
        if display_mode == 'none':
            for button in self.shortcut_buttons:
                button.hide()
            self.shortcut_buttons_visible = False
            self.shortcut_hide_timer.stop()
            return
        if display_mode == 'always':
            for button in self.shortcut_buttons:
                button.show()
            self.shortcut_buttons_visible = True
            self.shortcut_hide_timer.stop()
            for button in self.shortcut_buttons:
                button.opacity = 1.0
                button.scale = 1.0
            return
        if display_mode == 'hover':
            for button in self.shortcut_buttons:
                button.hide()
            self.shortcut_buttons_visible = False
            self.shortcut_hide_timer.stop()

    def _apply_button_animations(self, show=True):
        animation_mode = self.get_shortcut_animation_mode()
        for anim in self.button_animations.values():
            if isinstance(anim, (tuple, list)):
                for a in anim:
                    if a.state() == QPropertyAnimation.Running:
                        a.stop()
            elif anim.state() == QPropertyAnimation.Running:
                anim.stop()
        self.button_animations.clear()
        if animation_mode == 'default':
            for button in self.shortcut_buttons:
                button.opacity = 1.0 if show else 0.0
                button.scale = 1.0
                if show:
                    button.show()
                else:
                    button.hide()
            return
        if animation_mode == 'fade':
            for button in self.shortcut_buttons:
                if show:
                    if not button.isVisible():
                        button.opacity = 0.0
                        button.show()
                    anim = QPropertyAnimation(button, b'opacity')
                    anim.setDuration(300)
                    anim.setStartValue(button.opacity)
                    anim.setEndValue(1.0)
                    anim.setEasingCurve(QEasingCurve.InOutQuad)
                    self.button_animations[button] = anim
                    anim.start()
                    continue
                anim = QPropertyAnimation(button, b'opacity')
                anim.setDuration(300)
                anim.setStartValue(button.opacity)
                anim.setEndValue(0.0)
                anim.setEasingCurve(QEasingCurve.InOutQuad)
                anim.finished.connect((lambda b=button: None))
                self.button_animations[button] = anim
                anim.start()
                continue
            return
        if animation_mode == 'scale':
            for button in self.shortcut_buttons:
                if show:
                    if not button.isVisible():
                        button.opacity = 0.0
                        button.scale = 0.0
                        button.show()
                    scale_anim = QPropertyAnimation(button, b'scale')
                    scale_anim.setDuration(400)
                    scale_anim.setStartValue(button.scale)
                    scale_anim.setEndValue(1.0)
                    scale_anim.setEasingCurve(QEasingCurve.OutBack)
                    opacity_anim = QPropertyAnimation(button, b'opacity')
                    opacity_anim.setDuration(300)
                    opacity_anim.setStartValue(button.opacity)
                    opacity_anim.setEndValue(1.0)
                    opacity_anim.setEasingCurve(QEasingCurve.InOutQuad)
                    self.button_animations[button] = scale_anim, opacity_anim
                    scale_anim.start()
                    opacity_anim.start()
                    continue
                scale_anim = QPropertyAnimation(button, b'scale')
                scale_anim.setDuration(400)
                scale_anim.setStartValue(button.scale)
                scale_anim.setEndValue(0.0)
                scale_anim.setEasingCurve(QEasingCurve.InBack)
                opacity_anim = QPropertyAnimation(button, b'opacity')
                opacity_anim.setDuration(300)
                opacity_anim.setStartValue(button.opacity)
                opacity_anim.setEndValue(0.0)
                opacity_anim.setEasingCurve(QEasingCurve.InOutQuad)
                opacity_anim.finished.connect((lambda b=button: None))
                self.button_animations[button] = scale_anim, opacity_anim
                scale_anim.start()
                opacity_anim.start()
                continue

    def _update_shortcut_buttons_position(self):
        if not self.shortcut_buttons:
            return
        main_rect = self.geometry()
        button_size = self.get_shortcut_button_size()
        border_width = abs(self.get_shortcut_border_width())
        actual_button_size = button_size + border_width * 2
        spacing = self.get_shortcut_button_spacing()
        position = self.get_shortcut_button_position()
        alignment = self.get_shortcut_button_alignment()
        offset_x = self.get_shortcut_button_offset_x()
        offset_y = self.get_shortcut_button_offset_y()
        if position == 'left':
            x = main_rect.left() - actual_button_size - 5 + offset_x
            base_y = self._get_alignment_base_y(main_rect, alignment, len(self.shortcut_buttons), actual_button_size, spacing) + offset_y
            for i, button in enumerate(self.shortcut_buttons):
                button_y = base_y + i * (actual_button_size + spacing)
                button.move(int(x), int(button_y))
                self._update_button_stays_on_top(button)
        elif position == 'right':
            x = main_rect.right() + 5 + offset_x
            base_y = self._get_alignment_base_y(main_rect, alignment, len(self.shortcut_buttons), actual_button_size, spacing) + offset_y
            for i, button in enumerate(self.shortcut_buttons):
                button_y = base_y + i * (actual_button_size + spacing)
                button.move(int(x), int(button_y))
                self._update_button_stays_on_top(button)
        elif position == 'top':
            y = main_rect.top() - actual_button_size - 5 + offset_y
            base_x = self._get_alignment_base_x(main_rect, alignment, len(self.shortcut_buttons), actual_button_size, spacing) + offset_x
            for i, button in enumerate(self.shortcut_buttons):
                button_x = base_x + i * (actual_button_size + spacing)
                button.move(int(button_x), int(y))
                self._update_button_stays_on_top(button)
        elif position == 'bottom':
            y = main_rect.bottom() + 5 + offset_y
            base_x = self._get_alignment_base_x(main_rect, alignment, len(self.shortcut_buttons), actual_button_size, spacing) + offset_x
            for i, button in enumerate(self.shortcut_buttons):
                button_x = base_x + i * (actual_button_size + spacing)
                button.move(int(button_x), int(y))
                self._update_button_stays_on_top(button)
        self._update_shortcut_buttons_visibility()
        for button in self.shortcut_buttons:
            button.update()

    def _get_alignment_base_y(self, main_rect, alignment, button_count, button_size, spacing):
        total_height = button_count * button_size + (button_count - 1) * spacing
        if alignment == 'top':
            return main_rect.top()
        if alignment == 'bottom':
            return main_rect.bottom() - total_height
        return main_rect.top() + (main_rect.height() - total_height) / 2

    def _get_alignment_base_x(self, main_rect, alignment, button_count, button_size, spacing):
        total_width = button_count * button_size + (button_count - 1) * spacing
        if alignment == 'left':
            return main_rect.left()
        if alignment == 'right':
            return main_rect.right() - total_width
        return main_rect.left() + (main_rect.width() - total_width) / 2

    def on_shortcut_clicked(self, link):
        try:
            clean_link = link
            if clean_link:
                temp_button = ShortcutButton('temp', clean_link, None, None)
                clean_link = temp_button._clean_path(clean_link)
            if clean_link.startswith(('http://', 'https://')):
                QDesktopServices.openUrl(QUrl(clean_link))
                return
            if clean_link and os.path.isdir(clean_link):
                if sys.platform == 'win32':
                    os.startfile(clean_link)
                    return
                if sys.platform == 'darwin':
                    subprocess.Popen(['open', clean_link])
                    return
                subprocess.Popen(['xdg-open', clean_link])
                return
            if clean_link:
                if not os.path.isfile(clean_link):
                    if any((clean_link.lower().endswith(ext) for ext in ('.exe', '.com', '.bat'))):
                        if sys.platform == 'win32':
                            os.startfile(clean_link)
                            return
                        subprocess.Popen([clean_link])
                        return
            if clean_link:
                if sys.platform == 'win32':
                    os.system(f'start {clean_link}')
                    return
                if sys.platform == 'darwin':
                    subprocess.Popen(['open', '-a', clean_link])
                    return
                subprocess.Popen([clean_link])
                return
        except Exception as e:
            QMessageBox.warning(self, '错误', f'无法打开链接: {clean_link}\n错误: {str(e)}')

    def update_layout(self):
        self.setUpdatesEnabled(False)
        try:
            for i in reversed(range(self.grid_layout.count())):
                widget = self.grid_layout.itemAt(i).widget()
                if widget:
                    widget.setParent(None)
            layout_option = self.get_layout_option()
            widget_width = self.get_widget_width()
            widget_height = self.get_widget_height()
            selected_charts = self._get_selected_charts()
            if layout_option == 1:
                self._setup_single_line_layout(selected_charts, widget_width, widget_height)
            elif layout_option == 2:
                self._setup_double_line_layout(selected_charts, widget_width, widget_height)
            elif layout_option == 4:
                self._setup_compact_layout(selected_charts, widget_width, widget_height)
            self.setFixedSize(widget_width, widget_height)
            self._update_shortcut_buttons_position()
            self.performance_optimizer.optimize_memory()
        finally:
            self.setUpdatesEnabled(True)
            self.update()

    def _get_selected_charts(self):
        selected_charts = []
        chart_configs = [('cpu', self.cpu_chart, 'show_cpu_chart'), ('memory', self.memory_chart, 'show_memory_chart'), ('disk', self.disk_chart, 'show_disk_chart'), ('network', self.network_chart, 'show_network_chart'), ('upload', self.upload_chart, 'show_upload_chart'), ('connections', self.connections_chart, 'show_connections_chart')]
        for chart_id, chart, config_key in chart_configs:
            if self.get_chart_visibility(config_key):
                selected_charts.append((chart_id, chart))
        return selected_charts or [(chart_id, chart) for chart_id, chart, _ in chart_configs]

    def get_chart_visibility(self, config_key):
        if self.preview_config is not None:
            return self.preview_config.get(config_key, self.config_manager.getboolean(config_key))
        return self.config_manager.getboolean(config_key)

    def _setup_single_line_layout(self, selected_charts, width, height):
        num_charts = len(selected_charts)
        card_height = (height - (num_charts - 1) - 4) // num_charts
        card_width = width - 4
        for _, chart in selected_charts:
            chart.setFixedSize(card_width, card_height)
        for i, (_, chart) in enumerate(selected_charts):
            self.grid_layout.addWidget(chart, i, 0)
        self.grid_layout.setVerticalSpacing(1)

    def _setup_double_line_layout(self, selected_charts, width, height):
        for _, chart in selected_charts:
            chart.set_compact_title(False)
        num_charts = len(selected_charts)
        if num_charts == 0:
            return
        if num_charts <= 2:
            self._setup_double_line_small(selected_charts, width, height)
        elif num_charts == 3:
            self._setup_double_line_three(selected_charts, width, height)
        elif num_charts == 5:
            self._setup_double_line_five(selected_charts, width, height)
        else:
            self._setup_double_line_large(selected_charts, width, height)
        self.grid_layout.setVerticalSpacing(1)

    def _setup_double_line_small(self, selected_charts, width, height):
        num_charts = len(selected_charts)
        card_height = (height - 8) // num_charts
        card_width = width - 4
        for _, chart in selected_charts:
            chart.setFixedSize(card_width, card_height)
        for i, (_, chart) in enumerate(selected_charts):
            self.grid_layout.addWidget(chart, i, 0)

    def _setup_double_line_three(self, selected_charts, width, height):
        card_height = (height - 6) // 2
        card_width = (width - 5) // 2
        for _, chart in selected_charts[:2]:
            chart.setFixedSize(card_width, card_height)
        self.grid_layout.addWidget(selected_charts[0][1], 0, 0)
        self.grid_layout.addWidget(selected_charts[1][1], 0, 1)
        selected_charts[2][1].setFixedSize(width - 4, card_height)
        self.grid_layout.addWidget(selected_charts[2][1], 1, 0, 1, 2)

    def _setup_double_line_five(self, selected_charts, width, height):
        rows = 3
        card_height = (height - 8) // rows
        card_width = (width - 5) // 2
        for _, chart in selected_charts[:4]:
            chart.setFixedSize(card_width, card_height)
        selected_charts[4][1].setFixedSize(width - 4, card_height)
        for i in range(4):
            self.grid_layout.addWidget(selected_charts[i][1], i // 2, i % 2)
        self.grid_layout.addWidget(selected_charts[4][1], 2, 0, 1, 2)

    def _setup_double_line_large(self, selected_charts, width, height):
        rows = (len(selected_charts) + 1) // 2
        card_height = (height - (rows + 3)) // rows
        card_width = (width - 5) // 2
        for _, chart in selected_charts:
            chart.setFixedSize(card_width, card_height)
        for i, (_, chart) in enumerate(selected_charts):
            self.grid_layout.addWidget(chart, i // 2, i % 2)

    def _setup_compact_layout(self, selected_charts, width, height):
        for _, chart in selected_charts:
            chart.set_compact_title(True)
        num_charts = len(selected_charts)
        if num_charts == 0:
            return
        if num_charts <= 4:
            card_width = (width - (num_charts + 3)) // num_charts
            card_height = height - 4
            for _, chart in selected_charts:
                chart.setFixedSize(card_width, card_height)
            for i, (_, chart) in enumerate(selected_charts):
                self.grid_layout.addWidget(chart, 0, i)
        else:
            rows = (num_charts + 3) // 4
            card_width = (width - 7) // 4
            card_height = (height - (rows + 3)) // rows
            for _, chart in selected_charts:
                chart.setFixedSize(card_width, card_height)
            for i, (_, chart) in enumerate(selected_charts):
                self.grid_layout.addWidget(chart, i // 4, i % 4)
        self.grid_layout.setVerticalSpacing(1)

    def is_dark_theme(self):
        if self.preview_config is not None:
            return self.preview_config.get('theme', 1) == 1
        return self.config_manager.getint('theme') == 1

    def apply_theme(self):
        '''Widget palette + tray/context menu styling for the active theme.'''
        try:
            if getattr(self, '_tray_menu', None) is not None:
                self._tray_menu.setStyleSheet(build_menu_stylesheet(self.app_theme()))
        except Exception:
            pass
        if self.is_dark_theme():
            palette = self.palette()
            palette.setColor(QPalette.Window, QColor(45, 45, 45))
            palette.setColor(QPalette.WindowText, Qt.white)
            palette.setColor(QPalette.Base, QColor(30, 30, 30))
            palette.setColor(QPalette.Text, Qt.white)
            palette.setColor(QPalette.Button, QColor(45, 45, 45))
            palette.setColor(QPalette.ButtonText, Qt.white)
            self.setPalette(palette)
            return
        self.setPalette(QApplication.style().standardPalette())

    def move_to_bottom_right(self):
        screen_rect = QApplication.desktop().availableGeometry()
        self.move(screen_rect.width() - self.width() - 20, screen_rect.height() - self.height() - 20)

    def _set_initial_position(self):
        x = self.config_manager.getint('widget_x', -1)
        y = self.config_manager.getint('widget_y', -1)
        if x >= 0 and y >= 0:
            self.move(x, y)
            return
        self.move_to_bottom_right()

    def _set_initial_state(self):
        # 显示/隐藏 菜单项已取消：卡片始终可见；锁定/解锁 也取消，始终可拖动。
        self.is_locked = False
        self.is_stays_on_top = self.config_manager.getboolean('stays_on_top', False)
        if self.is_stays_on_top:
            self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)
        self.show()
        QTimer.singleShot(0, self._apply_click_through)
        QTimer.singleShot(300, self._dock_to_edge)

    def _save_current_position(self):
        pos = self.pos()
        self.config_manager.set('widget_x', pos.x())
        self.config_manager.set('widget_y', pos.y())
        self.config_manager.save_config()
        self._update_shortcut_buttons_position()

    def _save_widget_state(self):
        self.config_manager.set('stays_on_top', self.is_stays_on_top)
        self.config_manager.save_config()

    def init_tray_icon(self):
        self.tray_icon = QSystemTrayIcon(self)
        self.tray_icon.setToolTip('RouterSight 路由视界 - 路由器监控')
        self._set_tray_icon()
        self._create_tray_menu()
        self.tray_icon.show()
        self.tray_icon.activated.connect(self.on_tray_icon_activated)

    def _set_tray_icon(self):
        try:
            icon_path = self.get_resource_path('logo.ico')
            if os.path.exists(icon_path):
                self.tray_icon.setIcon(QIcon(icon_path))
                return
            self.tray_icon.setIcon(QApplication.style().standardIcon(QApplication.style().SP_ComputerIcon))
            return
        except Exception:
            self.tray_icon.setIcon(QApplication.style().standardIcon(QApplication.style().SP_ComputerIcon))

    def app_theme(self):
        '''The palette the whole app should use right now (config 'theme').'''
        try:
            return SettingsDialog.THEME_DARK if self.config_manager.getint('theme', 1) == 1 else SettingsDialog.THEME_LIGHT
        except Exception:
            return SettingsDialog.THEME_DARK

    def _create_tray_menu(self):
        self._tray_menu = QMenu()
        self._tray_menu.setStyleSheet(build_menu_stylesheet(self.app_theme()))
        for text, slot in self._tray_actions():
            action = QAction(text, self)
            action.triggered.connect(slot)
            self._tray_menu.addAction(action)
        self.tray_icon.setContextMenu(self._tray_menu)

    def clean_exit(self):
        self._force_quit = True
        self.tray_icon.hide()
        self.tray_icon = None
        try:
            if self.timer:
                self.timer.stop()
        except Exception:
            pass
        self.close_router()
        try:
            self.router_executor.shutdown(wait=False)
        except Exception:
            pass
        QApplication.instance().quit()

    def _tray_actions(self):
        """托盘/右键菜单项。锁定/解锁与显示/隐藏已取消（靠边隐藏 + 鼠标穿透取代）。"""
        return [('显示 / 隐藏组件', self.toggle_widget_visible),
                ('✓ 鼠标穿透' if self.is_click_through() else '鼠标穿透', self.toggle_click_through),
                ('✓ 置顶' if self.is_stays_on_top else '置顶', self.toggle_stays_on_top),
                (self._get_auto_start_text(), self.toggle_auto_start),
                ('设置', self.open_settings), ('退出', self.clean_exit)]

    def _get_auto_start_text(self):
        return '✓ 开机启动' if self.config_manager.getboolean('auto_start') else '开机启动'

    def on_tray_icon_activated(self, reason):
        # 左键单击托盘图标：把靠边隐藏的卡片叫出来（没有再隐藏它的入口）
        if reason == QSystemTrayIcon.Trigger and self._edge_hidden:
            self._reveal_from_edge()

    def show_context_menu(self, position):
        context_menu = QMenu(self)
        context_menu.setStyleSheet(self._tray_menu.styleSheet())
        for text, slot in self._tray_actions():
            action = QAction(text, self)
            action.triggered.connect(slot)
            context_menu.addAction(action)
        context_menu.exec_(self.mapToGlobal(position))

    def setup_timer(self):
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.fetch_data)
        interval = self.get_refresh_interval()
        self.timer.start(interval * 1000)

    def get_data_source(self):
        return (self.config_manager.get('data_source') or 'router').strip().lower()

    def _router_settings_tuple(self):
        cfg = self.config_manager
        return (cfg.get('router_host'), cfg.get('router_port'), cfg.get('router_user'), cfg.get('router_password'), cfg.get('router_key'), cfg.get('net_interface'))

    def get_router(self):
        """Build (or rebuild after a settings change) the router SSH source."""
        settings = self._router_settings_tuple()
        if self.router is not None and settings == self.router_settings:
            return self.router
        if self.router is not None:
            try:
                self.router.close()
            except Exception:
                pass
        host, port, user, password, key, interface = settings
        try:
            port_num = int(port or 22)
        except (TypeError, ValueError):
            port_num = 22
        self.router = RouterStats(host=host, port=port_num, username=user, password=password, key_filename=key, interface=interface)
        self.router_settings = settings
        return self.router

    def close_router(self):
        if self.router is not None:
            try:
                self.router.close()
            except Exception:
                pass
            self.router = None

    def check_network_status(self):
        if self.get_data_source() == 'router':
            # Failures already surface through the SSH sample; never block the
            # GUI thread with a socket probe here.
            return True
        current_time = time.time()
        if current_time - self.last_network_check < self.network_check_interval:
            return self.is_online
        self.last_network_check = current_time
        api_url = self.config_manager.get('api_url')
        self.is_online = NetworkManager.check_api_connectivity(api_url)
        return self.is_online

    def fetch_data(self):
        if self.get_data_source() == 'router':
            self.fetch_router_data()
            return
        try:
            if not self.check_network_status():
                self.metrics_data = self._get_zero_data()
                self.update_display()
                return
            api_url = self.config_manager.get('api_url')
            if not api_url:
                self.metrics_data = self._get_zero_data()
                self.is_online = False
                self.update_display()
                return
            self._safe_cancel_request()
            request = QNetworkRequest(QUrl(api_url))
            request.setRawHeader(b'User-Agent', b'RouterSight/1.0')
            self.current_reply = self.network_manager.get(request)
            self.current_reply.finished.connect(self.on_network_reply)
            return
        except Exception:
            self._safe_cleanup_request()
            self.metrics_data = self._get_zero_data()
            self.is_online = False
            self.update_display()

    # 连续失败时的退避上限（秒）。第一次失败等 2 秒，之后倍增，最多 30 秒。
    ROUTER_BACKOFF_BASE = 2.0
    ROUTER_BACKOFF_MAX = 30.0

    def _router_backoff_delay(self, fails):
        delay = self.ROUTER_BACKOFF_BASE * (2 ** max(0, fails - 1))
        return min(delay, self.ROUTER_BACKOFF_MAX)

    def fetch_router_data(self):
        """Kick off one SSH sample on the worker thread (never blocks the GUI)."""
        if self.router_busy:
            return
        if time.monotonic() < self.router_retry_at:
            return
        self.router_busy = True
        try:
            router = self.get_router()
        except Exception as exc:
            self.router_busy = False
            self.last_error = str(exc)
            self.metrics_data = self._get_zero_data()
            self.is_online = False
            self.update_display()
            return
        try:
            self.router_executor.submit(self._router_worker, router)
        except Exception as exc:
            self.router_busy = False
            self.last_error = str(exc)
            self.metrics_data = self._get_zero_data()
            self.is_online = False
            self.update_display()

    def _router_worker(self, router):
        try:
            sample = router.sample()
            metrics = router.to_netdata_metrics(sample)
        except Exception as exc:
            self.router_sample_ready.emit(None, str(exc))
            return
        self.router_sample_ready.emit(metrics, '')

    def on_router_sample(self, metrics, error):
        self.router_busy = False
        if metrics:
            self.metrics_data = metrics
            self.cached_data = metrics
            self.is_online = True
            self.last_error = ''
            self.router_fail_count = 0
            self.router_retry_at = 0.0
        else:
            self.router_fail_count += 1
            delay = self._router_backoff_delay(self.router_fail_count)
            self.router_retry_at = time.monotonic() + delay
            self.last_error = '%s（%d 秒后重试）' % (error or '未知错误', int(delay))
            self.metrics_data = self._get_zero_data()
            self.is_online = False
        self.update_display()

    def _safe_cancel_request(self):
        if self.current_reply is not None:
            try:
                if hasattr(self.current_reply, 'isRunning') and self.current_reply.isRunning():
                    self.current_reply.abort()
                if hasattr(self.current_reply, 'deleteLater'):
                    self.current_reply.deleteLater()
            except Exception:
                pass
            self.current_reply = None

    def _safe_cleanup_request(self):
        try:
            if self.current_reply is not None:
                if hasattr(self.current_reply, 'deleteLater'):
                    self.current_reply.deleteLater()
                self.current_reply = None
                return
        except Exception:
            pass

    def on_network_reply(self):
        try:
            reply = self.current_reply
            if reply and reply.error() == QNetworkReply.NoError:
                data = reply.readAll().data()
                json_data = json.loads(data.decode('utf-8'))
                self.metrics_data = json_data
                self.cached_data = json_data
                self.is_online = True
            else:
                self.metrics_data = self._get_zero_data()
                self.is_online = False
        except Exception:
            self.metrics_data = self._get_zero_data()
            self.is_online = False
        finally:
            self._safe_cleanup_request()
            self.update_display()

    def _get_zero_data(self):
        if hasattr(self, '_zero_data_cache'):
            return self._zero_data_cache
        self._zero_data_cache = {'system.cpu': {'dimensions': {'user': {'value': 0}, 'system': {'value': 0}}}, 'system.ram': {'dimensions': {'used': {'value': 0}, 'free': {'value': 0}, 'cached': {'value': 0}, 'buffers': {'value': 0}}}, 'system.io': {'dimensions': {'in': {'value': 0}, 'out': {'value': 0}}}, 'system.net': {'dimensions': {'InOctets': {'value': 0}, 'OutOctets': {'value': 0}}}, 'ipv4.tcpsock': {'dimensions': {'CurrEstab': {'value': 0}}}, 'ipv4.sockstat_udp_sockets': {'dimensions': {'inuse': {'value': 0}}}, 'router': {'interface': None, 'interfaces': [], 'rx_kbps': 0.0, 'tx_kbps': 0.0, 'source': 'none'}}
        return self._zero_data_cache

    def update_display(self):
        if 'system.cpu' in self.metrics_data:
            cpu_dims = self.metrics_data['system.cpu'].get('dimensions', {})
            user = cpu_dims.get('user', {}).get('value', 0)
            system = cpu_dims.get('system', {}).get('value', 0)
            self.charts['cpu'].update_data(user + system)
        else:
            self.charts['cpu'].update_data(0)
        if 'system.ram' in self.metrics_data:
            ram_dims = self.metrics_data['system.ram'].get('dimensions', {})
            used = ram_dims.get('used', {}).get('value', 0)
            free = ram_dims.get('free', {}).get('value', 0)
            cached = ram_dims.get('cached', {}).get('value', 0)
            buffers = ram_dims.get('buffers', {}).get('value', 0)
            total = used + free + cached + buffers
            used_percent = used / total * 100 if total > 0 else 0
            self.charts['memory'].update_data(used_percent)
        else:
            self.charts['memory'].update_data(0)
        if 'system.io' in self.metrics_data:
            io_dims = self.metrics_data['system.io'].get('dimensions', {})
            disk_read = abs(io_dims.get('in', {}).get('value', 0))
            disk_write = abs(io_dims.get('out', {}).get('value', 0))
            self.charts['disk'].update_data(disk_read + disk_write)
        else:
            self.charts['disk'].update_data(0)
        if 'router' in self.metrics_data:
            # Router source: ONE interface, both directions kept apart.
            # (The old code added InOctets + OutOctets over every interface at
            #  once, which is why one LAN transfer showed up as 2x.)
            ns = self.metrics_data.get('router', {}) or {}
            down = abs(ns.get('rx_kbps', 0.0))
            up = abs(ns.get('tx_kbps', 0.0))
            self.charts['network'].update_data(down)
            if 'upload' in self.charts:
                self.charts['upload'].update_data(up)
        elif 'system.net' in self.metrics_data:
            net_dims = self.metrics_data['system.net'].get('dimensions', {})
            network_in = abs(net_dims.get('InOctets', {}).get('value', 0))
            network_out = abs(net_dims.get('OutOctets', {}).get('value', 0))
            self.charts['network'].update_data(network_in)
            if 'upload' in self.charts:
                self.charts['upload'].update_data(network_out)
        else:
            self.charts['network'].update_data(0)
            if 'upload' in self.charts:
                self.charts['upload'].update_data(0)
        tcp_connections, udp_connections = 0, 0
        if 'ipv4.tcpsock' in self.metrics_data:
            tcp_dims = self.metrics_data['ipv4.tcpsock'].get('dimensions', {})
            tcp_connections = tcp_dims.get('CurrEstab', {}).get('value', 0)
        if 'ipv4.sockstat_udp_sockets' in self.metrics_data:
            udp_dims = self.metrics_data['ipv4.sockstat_udp_sockets'].get('dimensions', {})
            udp_connections = udp_dims.get('inuse', {}).get('value', 0)
        self.charts['connections'].update_connections_data(tcp_connections, udp_connections)

    def toggle_click_through(self):
        """鼠标穿透开关。开启后卡片收不到鼠标事件，只能从托盘菜单关闭。"""
        enabled = not self.is_click_through()
        self.config_manager.set('click_through', enabled)
        self.config_manager.save_config()
        self._apply_click_through(enabled)
        self._create_tray_menu()

    def toggle_stays_on_top(self):
        self.is_stays_on_top = not self.is_stays_on_top
        if self.is_stays_on_top:
            self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)
        else:
            self.setWindowFlags(self.windowFlags() & ~Qt.WindowStaysOnTopHint)
        self.show()
        for button in self.shortcut_buttons:
            self._update_button_stays_on_top(button)
            button.show()
        self.config_manager.set('stays_on_top', self.is_stays_on_top)
        self.config_manager.save_config()
        self._save_widget_state()

    def open_settings(self):
        self.settings_dialog = SettingsDialog(self)
        self.settings_dialog.setModal(False)
        self.setContextMenuPolicy(Qt.NoContextMenu)
        self.settings_dialog.finished.connect(self.on_settings_dialog_closed)
        self.settings_dialog.settings_saved.connect(self.apply_settings)
        self.settings_dialog.show()

    def on_settings_dialog_closed(self):
        self.preview_config = None
        self._apply_all_settings()
        self.settings_dialog = None
        self.setContextMenuPolicy(Qt.CustomContextMenu)

    def apply_settings(self):
        self.config_manager.load_config()
        self.preview_config = None
        self._apply_all_settings()

    def _apply_all_settings(self):
        interval = self.get_refresh_interval()
        data_points = self.get_data_points()
        self.timer.setInterval(interval * 1000)
        for chart in self.charts.values():
            chart.update_data_points(data_points)
        self.is_stays_on_top = self.config_manager.getboolean('stays_on_top')
        self.setWindowFlags(self._window_flags())
        self._apply_click_through()
        self._dock_to_edge()
        self._apply_performance_settings()
        self.apply_theme()
        self.update_layout()
        self._update_charts_visibility()
        self._create_shortcut_buttons()
        self._save_current_position()
        self._save_widget_state()
        self.show()
        for chart in self.charts.values():
            chart.update()

    def _update_charts_visibility(self):
        chart_visibility = {'cpu': self.get_chart_visibility('show_cpu_chart'), 'memory': self.get_chart_visibility('show_memory_chart'), 'disk': self.get_chart_visibility('show_disk_chart'), 'network': self.get_chart_visibility('show_network_chart'), 'upload': self.get_chart_visibility('show_upload_chart'), 'connections': self.get_chart_visibility('show_connections_chart')}
        for chart_id, visible in chart_visibility.items():
            if chart_id in self.charts:
                self.charts[chart_id].setVisible(visible)

    def apply_preview_settings(self, preview_config):
        self.preview_config = preview_config
        self._apply_preview_settings()

    def _apply_preview_settings(self):
        self.setUpdatesEnabled(False)
        try:
            interval = self.get_refresh_interval()
            data_points = self.get_data_points()
            self.timer.setInterval(interval * 1000)
            for chart in self.charts.values():
                chart.update_data_points(data_points)
            if 'performance_mode' in self.preview_config:
                self.performance_optimizer.set_mode(self.preview_config['performance_mode'])
            if 'animation_enabled' in self.preview_config:
                for chart in self.charts.values():
                    chart.set_animation_enabled(self.preview_config['animation_enabled'])
            self.apply_theme()
            self.update_layout()
            self._update_charts_visibility()
            if 'shortcut_border_width' in self.preview_config:
                border_width = self.get_shortcut_border_width()
                for button in self.shortcut_buttons:
                    button.set_border_width(border_width)
                    button.update()
            if 'shortcut_button_radius' in self.preview_config:
                button_radius = self.get_shortcut_button_radius()
                for button in self.shortcut_buttons:
                    button.set_radius(button_radius)
                    button.update()
            if 'shortcut_button_size' in self.preview_config:
                button_size = self.get_shortcut_button_size()
                for button in self.shortcut_buttons:
                    button.set_size(button_size)
                    button.update()
            if 'shortcut_button_spacing' in self.preview_config:
                self._update_shortcut_buttons_position()
            if any((key in self.preview_config for key in ('shortcut_button_position', 'shortcut_button_alignment', 'shortcut_button_offset_x', 'shortcut_button_offset_y', 'shortcut_border_width'))):
                self._update_shortcut_buttons_position()
            for chart in self.charts.values():
                chart.update()
        finally:
            self.setUpdatesEnabled(True)
            self.update()

    def preview_shortcut_animation(self):
        if not self.shortcut_buttons:
            return
        self.preview_config = self.preview_config or {}
        self.preview_config['shortcut_display_mode'] = 'always'
        self._update_shortcut_buttons_visibility()
        animation_mode = self.get_shortcut_animation_mode()
        if animation_mode in ('default', 'fade', 'scale'):
            self._apply_button_animations(show=True)
            QTimer.singleShot(1000, (lambda: self._apply_button_animations(show=False)))
        QTimer.singleShot(2000, self._restore_preview_display_mode)

    def _restore_preview_display_mode(self):
        if self.preview_config and 'shortcut_display_mode' in self.preview_config:
            del self.preview_config['shortcut_display_mode']
        self._update_shortcut_buttons_visibility()

    def update_shortcut_button_from_dialog(self, row, link_data):
        '''关键修复：从对话框接收数据并更新对应的快捷按钮'''

        if 0 <= row < len(self.shortcut_buttons):
            button = self.shortcut_buttons[row]
            button.name = link_data.get('name', '')
            button.icon_char = link_data.get('icon_char')
            button.icon_image = link_data.get('icon_image')
            button.link = link_data.get('link', '')
            button.set_border_color(link_data.get('border_color', '#000000'), link_data.get('border_opacity', 100))
            button.update()

    def _update_main_window_shortcut_button(self, row):
        '''更新主窗口对应的快捷按钮预览'''

        if 0 <= row < len(self.shortcut_buttons):
            button = self.shortcut_buttons[row]
            button.update()

    def get_refresh_interval(self):
        return self._get_config_value('refresh_interval', int)

    def get_data_points(self):
        return self._get_config_value('data_points', int)

    def get_layout_option(self):
        return self._get_config_value('layout_option', int)

    def get_card_opacity(self):
        return self._get_config_value('card_opacity', int)

    def get_text_opacity(self):
        return self._get_config_value('text_opacity', int)

    def get_chart_opacity(self):
        return self._get_config_value('chart_opacity', int)

    def get_card_radius(self):
        return self._get_config_value('card_radius', int)

    def get_ui_scale(self):
        '''整体缩放系数（配置项 ui_scale，单位 %，0 表示自动）。

        桌面小部件不该像常规窗口那样整倍跟随系统缩放，否则高分屏上大得离谱；
        自动模式取桌面缩放比例的 70%，并限制在 100%~160% 之间。
        Windows 上恒为 1.0，保持原样。
        '''
        override = self._get_config_value('ui_scale', int, 0)
        if override and override > 0:
            return max(0.5, min(2.5, override / 100.0))
        if not is_linux():
            return 1.0
        try:
            screen = self.screen() or QApplication.primaryScreen()
            dpi = screen.logicalDotsPerInch() if screen is not None else 96.0
        except Exception:
            dpi = 96.0
        return max(1.0, min(1.6, (dpi / 96.0) * 0.7))

    def get_widget_width(self):
        return int(round(self._get_config_value('widget_width', int) * self.get_ui_scale()))

    def get_widget_height(self):
        return int(round(self._get_config_value('widget_height', int) * self.get_ui_scale()))

    def get_shortcut_button_size(self):
        return self._get_config_value('shortcut_button_size', int)

    def get_shortcut_button_radius(self):
        return self._get_config_value('shortcut_button_radius', int)

    def get_shortcut_border_width(self):
        return self._get_config_value('shortcut_border_width', int, 0)

    def get_shortcut_hover_scale(self):
        return self._get_config_value('shortcut_hover_scale', float, 1.2)

    def get_shortcut_button_position(self):
        return self._get_config_value('shortcut_button_position', str, 'bottom')

    def get_shortcut_button_alignment(self):
        return self._get_config_value('shortcut_button_alignment', str, 'left')

    def get_shortcut_display_mode(self):
        return self._get_config_value('shortcut_display_mode', str, 'none')

    def get_shortcut_animation_mode(self):
        return self._get_config_value('shortcut_animation_mode', str, 'default')

    def get_shortcut_button_offset_x(self):
        return self._get_config_value('shortcut_button_offset_x', int, 0)

    def get_shortcut_button_offset_y(self):
        return self._get_config_value('shortcut_button_offset_y', int, 0)

    def get_shortcut_border_opacity(self):
        return self._get_config_value('shortcut_border_opacity', int, 100)

    def get_shortcut_button_spacing(self):
        return self._get_config_value('shortcut_button_spacing', int, 5)

    def _get_config_value(self, key, value_type=str, default=None):
        if self.preview_config is not None and key in self.preview_config:
            return self.preview_config[key]
        if value_type == int:
            if default is not None:
                return self.config_manager.getint(key, default)
            return self.config_manager.getint(key, default if default is not None else 0)
        if value_type == float:
            if default is not None:
                return self.config_manager.getfloat(key, default)
            return self.config_manager.getfloat(key, default if default is not None else 0.0)
        return self.config_manager.get(key, default)

    # ------------------------------------------------------------ 鼠标穿透
    def is_click_through(self):
        if self.preview_config is not None:
            return bool(self.preview_config.get('click_through', False))
        return self.config_manager.getboolean('click_through', False)

    def _apply_click_through(self, enabled=None):
        '''给窗口加 WS_EX_TRANSPARENT，鼠标点击就穿透到下面的窗口。

        开启后卡片收不到任何鼠标事件（不能右键、不能拖动），
        所以关掉它的唯一入口是托盘图标右键菜单。
        '''
        if enabled is None:
            enabled = self.is_click_through()
        if is_linux():
            # Linux 用 Qt 的 WindowTransparentForInput 标志实现，需重建窗口才生效；
            # 重建会丢失位置，所以先记下几何信息再恢复。Wayland 下部分合成器不支持。
            try:
                was_visible = self.isVisible()
                geo = self.geometry()
                self.setWindowFlag(Qt.WindowTransparentForInput, bool(enabled))
                if was_visible:
                    self.setGeometry(geo)
                    self.show()
                    self.setGeometry(geo)
                self._click_through_applied = bool(enabled)
            except Exception:
                pass
            return
        if os.name != 'nt':
            return
        try:
            import ctypes
            hwnd = int(self.winId())
            user32 = ctypes.windll.user32
            GWL_EXSTYLE = -20
            WS_EX_TRANSPARENT = 0x00000020
            WS_EX_LAYERED = 0x00080000
            style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            if enabled:
                style |= WS_EX_TRANSPARENT | WS_EX_LAYERED
            else:
                style &= ~WS_EX_TRANSPARENT
            user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
        except Exception:
            pass

    # ---------------------------------------------------------- 靠边隐藏
    def _edge_hide_enabled(self):
        if self.preview_config is not None:
            return bool(self.preview_config.get('edge_hide', True))
        return self.config_manager.getboolean('edge_hide', True)

    def _screen_area_for(self, point=None):
        try:
            screen = QApplication.screenAt(point) if point is not None else None
            screen = screen or self.screen() or QApplication.primaryScreen()
            return screen.availableGeometry() if screen is not None else None
        except Exception:
            return None

    def _flush_position(self, edge, area):
        width, height = self.width(), self.height()
        if edge == 'left':
            return QPoint(area.left(), self.y())
        if edge == 'right':
            return QPoint(area.right() + 1 - width, self.y())
        if edge == 'top':
            return QPoint(self.x(), area.top())
        if edge == 'bottom':
            return QPoint(self.x(), area.bottom() + 1 - height)
        return self.pos()

    def _hidden_position(self, edge, area):
        width, height = self.width(), self.height()
        strip = EDGE_HIDE_STRIP
        if edge == 'left':
            return QPoint(area.left() - width + strip, self.y())
        if edge == 'right':
            return QPoint(area.right() + 1 - strip, self.y())
        if edge == 'top':
            return QPoint(self.x(), area.top() - height + strip)
        if edge == 'bottom':
            return QPoint(self.x(), area.bottom() + 1 - strip)
        return self.pos()

    def _detect_dock_edge(self, point=None):
        area = self._screen_area_for(point if point is not None else self.pos())
        if area is None:
            return None
        pos = point if point is not None else self.pos()
        width, height = self.width(), self.height()
        tol = EDGE_DOCK_TOLERANCE
        if abs(pos.x() - area.left()) <= tol:
            return 'left'
        if abs(pos.x() + width - (area.right() + 1)) <= tol:
            return 'right'
        if abs(pos.y() - area.top()) <= tol:
            return 'top'
        if abs(pos.y() + height - (area.bottom() + 1)) <= tol:
            return 'bottom'
        return None

    def _dock_to_edge(self):
        '''松手/设置变更后：贴边就记成停靠，否则解除停靠。'''
        edge = self._detect_dock_edge()
        if edge is None:
            self._dock_edge = None
            self._edge_hidden = False
            self._edge_timer.stop()
            return
        area = self._screen_area_for(self.pos())
        self._dock_edge = edge
        self._edge_hidden = False
        self._edge_armed = False
        self._edge_out_polls = 0
        if area is not None:
            self.move(self._flush_position(edge, area))
        if self._edge_hide_enabled():
            self._edge_timer.start(EDGE_POLL_MS)
        else:
            self._edge_timer.stop()

    def _hide_at_edge(self):
        edge = self._dock_edge
        area = self._screen_area_for(self.pos())
        if not edge or area is None:
            return
        self.move(self._hidden_position(edge, area))
        self._edge_hidden = True
        self._edge_armed = False
        self._edge_out_polls = 0
        self._update_shortcut_buttons_position()

    def _reveal_from_edge(self):
        edge = self._dock_edge
        area = self._screen_area_for(self.pos())
        if not edge or area is None:
            return
        self.move(self._flush_position(edge, area))
        self._edge_hidden = False
        self._edge_armed = False
        self._edge_out_polls = 0
        self.raise_()
        self._update_shortcut_buttons_position()

    def _poll_edge(self):
        '''靠边隐藏的驱动：轮询鼠标位置而不是 enterEvent，
        因为鼠标穿透时窗口收不到任何事件。'''
        if not self._dock_edge or not self._edge_hide_enabled() or not self.isVisible():
            self._edge_timer.stop()
            return
        if self._dragging:
            return
        try:
            cursor = QCursor.pos()
        except Exception:
            return
        inside = self.frameGeometry().contains(cursor)
        if self._edge_hidden:
            if not inside:
                self._edge_armed = True       # 光标离开过边缘才算「再来一次」
                return
            if self._edge_armed:
                self._reveal_from_edge()
            return
        if inside:
            self._edge_out_polls = 0
            return
        self._edge_out_polls += 1
        if self._edge_out_polls * EDGE_POLL_MS >= EDGE_HIDE_DELAY:
            self._hide_at_edge()

    # ------------------------------------------------------------ 拖拽
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            if self._edge_hidden:
                self._reveal_from_edge()
            self._dragging = True
            self.drag_position = event.globalPos() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.LeftButton:
            self.move(event.globalPos() - self.drag_position)
            event.accept()
            self._update_shortcut_buttons_position()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._dragging = False
            self._dock_to_edge()
            self._save_current_position()
            event.accept()

    def enterEvent(self, event):
        if self._edge_hidden:
            self._reveal_from_edge()
        if self.get_shortcut_display_mode() == 'hover':
            self.shortcut_hide_timer.stop()
            if not self.shortcut_buttons_visible:
                self.shortcut_buttons_visible = True
                self._apply_button_animations(show=True)
        event.accept()

    def leaveEvent(self, event):
        if self.get_shortcut_display_mode() == 'hover' and not self.underMouse():
            if all((not button.underMouse() for button in self.shortcut_buttons)):
                self.shortcut_hide_timer.start(5000)
        event.accept()

    def show_shortcut_buttons(self):
        if not self.shortcut_buttons_visible:
            self.shortcut_buttons_visible = True
            self._apply_button_animations(show=True)

    def hide_shortcut_buttons(self):
        if self.shortcut_buttons_visible:
            if self.get_shortcut_display_mode() == 'hover':
                if not self.underMouse():
                    if all((not button.underMouse() for button in self.shortcut_buttons)):
                        self.shortcut_buttons_visible = False
                        self._apply_button_animations(show=False)

    def toggle_auto_start(self):
        current_auto_start = self.config_manager.getboolean('auto_start')
        new_auto_start = not current_auto_start
        self.config_manager.set('auto_start', new_auto_start)
        self.config_manager.save_config()
        self.set_auto_start(new_auto_start)
        self._update_auto_start_menu_text(new_auto_start)
        self._save_widget_state()

    def _update_auto_start_menu_text(self, enabled):
        new_text = '✓ 开机启动' if enabled else '开机启动'
        if hasattr(self, '_tray_menu'):
            for action in self._tray_menu.actions():
                if '开机启动' in action.text():
                    action.setText(new_text)
                    return

    def _set_auto_start_linux(self, enabled):
        '''XDG 自启动：写 ~/.config/autostart/routersight.desktop，等价于 Windows 的 Run 键。'''
        autostart_dir = os.path.join(os.path.expanduser('~'), '.config', 'autostart')
        desktop_path = os.path.join(autostart_dir, 'routersight.desktop')
        try:
            if not enabled:
                if os.path.exists(desktop_path):
                    os.remove(desktop_path)
                return
            if getattr(sys, 'frozen', False):
                parts = [os.environ.get('APPIMAGE') or os.path.abspath(sys.executable)]
            else:
                parts = [os.path.abspath(sys.executable), os.path.abspath(sys.argv[0])]
            exec_line = ' '.join(('"%s"' % part) if ' ' in part else part for part in parts)
            os.makedirs(autostart_dir, exist_ok=True)
            content = ('[Desktop Entry]\n'
                       'Type=Application\n'
                       'Name=RouterSight\n'
                       'Comment=RouterSight 路由视界 桌面监控\n'
                       'Exec=%s\n'
                       'Icon=routersight\n'
                       'Terminal=false\n'
                       'StartupNotify=false\n'
                       'X-GNOME-Autostart-enabled=true\n' % exec_line)
            with open(desktop_path, 'w', encoding='utf-8') as handle:
                handle.write(content)
            os.chmod(desktop_path, 0o644)
        except Exception:
            pass

    def set_auto_start(self, enabled):
        if is_linux():
            self._set_auto_start_linux(enabled)
            return
        if sys.platform == 'win32':
            try:
                import winreg
                app_path = sys.executable if getattr(sys, 'frozen', False) else sys.executable + ' ' + os.path.abspath(sys.argv[0])
                key_path = 'Software\\Microsoft\\Windows\\CurrentVersion\\Run'
                if enabled:
                    key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE)
                    winreg.SetValueEx(key, 'RouterSight', 0, winreg.REG_SZ, app_path)
                    winreg.CloseKey(key)
                    return
                key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE)
                try:
                    winreg.DeleteValue(key, 'RouterSight')
                except FileNotFoundError:
                    pass
                else:
                    winreg.CloseKey(key)
            except Exception:
                return


def run_self_test():
    """--selftest: 采一次路由器数据并把报告写到 exe 同目录的 RouterSight_selftest.txt。

    用途：打包后没有控制台，靠这个文件确认 SSH 数据源是否正常；出问题时也方便排查。
    """
    lines = []

    def log(text=''):
        lines.append(str(text))

    log('RouterSight 自检报告 / self-test')
    log('时间: ' + time.strftime('%Y-%m-%d %H:%M:%S'))
    log('frozen: ' + str(getattr(sys, 'frozen', False)))
    log('executable: ' + sys.executable)
    base_dir = writable_base_dir()
    log('directory: ' + base_dir)
    rc = 1
    try:
        cfg = ConfigManager()
        log('配置文件: ' + cfg.config_file)
        log('数据源: ' + str(cfg.get('data_source', 'router')))
        log('路由器: %s@%s:%s  网卡=%s' % (cfg.get('router_user', 'root'), cfg.get('router_host', ''), cfg.get('router_port', '22'), cfg.get('net_interface', 'auto')))
        router = RouterStats(host=cfg.get('router_host', ''), port=cfg.getint('router_port', 22), username=cfg.get('router_user', 'root'), password=cfg.get('router_password', ''), key_filename=cfg.get('router_key', ''), interface=cfg.get('net_interface', 'auto'))
        ok, message = router.test_connection()
        log('连接测试: %s - %s' % (ok, message))
        if ok:
            router.sample()
            time.sleep(1.2)
            sample = router.sample()
            metrics = router.to_netdata_metrics(sample)
            extra = metrics['router']
            ram = metrics['system.ram']['dimensions']
            ram_total = sum((item['value'] for item in ram.values())) or 1
            log('网卡: %s' % extra['interface'])
            log('可用网卡: %s' % ', '.join(extra['interfaces']))
            log('CPU: %.1f%%' % metrics['system.cpu']['dimensions']['user']['value'])
            log('内存: %.1f%% (%d / %d kB)' % (ram['used']['value'] / ram_total * 100, ram['used']['value'], ram_total))
            log('磁盘: %.1f 读 / %.1f 写 KiB/s' % (metrics['system.io']['dimensions']['in']['value'], metrics['system.io']['dimensions']['out']['value']))
            log('下载: %.1f kb/s' % extra['rx_kbps'])
            log('上传: %.1f kb/s' % extra['tx_kbps'])
            log('TCP/UDP 连接: %s / %s' % (metrics['ipv4.tcpsock']['dimensions']['CurrEstab']['value'], metrics['ipv4.sockstat_udp_sockets']['dimensions']['inuse']['value']))
            log('说明: 下载/上传取自同一张网卡的两个方向，不跨网卡相加，所以不会翻倍。')
            rc = 0
        router.close()
    except Exception as exc:
        log('错误: %s: %s' % (type(exc).__name__, exc))
    log('')
    log('结果: ' + ('正常' if rc == 0 else '失败'))
    report = '\n'.join(lines)
    try:
        with open(os.path.join(base_dir, 'RouterSight_selftest.txt'), 'w', encoding='utf-8') as handle:
            handle.write(report)
    except Exception:
        pass
    try:
        print(report)
    except Exception:
        pass
    return rc


def main():
    if '--selftest' in sys.argv:
        sys.exit(run_self_test())
    os.environ['QT_LOGGING_RULES'] = 'qt.qpa.fonts=false'
    app = QApplication(sys.argv)
    app.setStyle('Fusion')  # consistent widget rendering for the themed settings dialog
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName('RouterSight')
    app.setApplicationVersion('2.1.1')
    try:
        base_path = getattr(sys, '_MEIPASS', os.path.abspath('.'))
        icon_path = os.path.join(base_path, 'logo.ico')
        if os.path.exists(icon_path):
            app.setWindowIcon(QIcon(icon_path))
    except Exception:
        pass
    widget = RouterWidget()
    if not QSystemTrayIcon.isSystemTrayAvailable():
        print('警告: 系统托盘不可用，应用将无法最小化到托盘。')
    sys.exit(app.exec_())

if __name__ == '__main__':
    main()
# WARNING: Decompyle incomplete
