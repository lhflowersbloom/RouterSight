# Linux / AppImage 打包说明

把 RouterSight 打成单文件 AppImage，双击即用，不需要用户装 Python、PyQt5 或 Paramiko。

## 产物

| 文件 | 说明 |
|---|---|
| `dist_linux/RouterSight-<版本>-x86_64.AppImage` | 单文件，`chmod +x` 后可直接运行 |
| `dist_linux/RouterSight.AppDir/` | 中间产物（AppDir 目录结构），排查问题时可直接跑 `./AppRun` |

体积约 **58 MB**（strip 掉调试符号后；不打 strip 会到 250 MB+，因为 python-build-standalone 的 `libpython` 自带完整调试信息）。

## 构建

```bash
# 1. 干净环境（建议 3.10+，实测 3.13）
python3 -m venv .venv-linux
. .venv-linux/bin/activate
pip install pyinstaller PyQt5 paramiko

# 2. 一条命令出包
python linux/build_appimage.py
```

可选参数：

| 参数 | 作用 |
|---|---|
| `--version 1.1` | 写进文件名和 AppStream 元数据 |
| `--skip-pyinstaller` | 复用 `dist_linux/RouterSight/`，只重新组装 AppDir 和 AppImage（改图标/desktop 时很快） |
| `--appdir-only` | 只生成 AppDir，不压 AppImage |

`appimagetool` 会自动下载到 `.tools/` 并以 `--appimage-extract` 方式解包运行，**不依赖 FUSE**，CI 容器里也能构建。离线环境用 `APPIMAGETOOL=/path/to/squashfs-root/AppRun` 指定。

> 构建要在**较老的发行版**上做兼容性最好。本包是在 Fedora 44 上用 python-build-standalone 的 Python 3.13 构建的，Python 与 Qt 的 glibc 基线都是 **2.17**，所以老系统也能跑。如果你用发行版自带的 Python（比如 Ubuntu 24.04 的 3.12）构建，产物会继承那个系统的 glibc，只能在同等或更新的系统上运行。

## 使用

```bash
chmod +x RouterSight-1.0-x86_64.AppImage
./RouterSight-1.0-x86_64.AppImage            # 启动组件
./RouterSight-1.0-x86_64.AppImage --selftest # 无界面自检，报告写到 AppImage 同目录
```

放进应用菜单（可选）：

```bash
mkdir -p ~/Applications
mv RouterSight-1.0-x86_64.AppImage ~/Applications/
# 首次运行后若想加进菜单：
cp ~/Applications/RouterSight-1.0-x86_64.AppImage ~/Applications/  # 保持可执行
```

## 配置文件位置

| 场景 | 位置 |
|---|---|
| AppImage | **`.AppImage` 文件所在目录**下的 `RouterSight_config.ini`（绿色版行为，和 Windows 单文件版一致） |
| 该目录不可写（如放在 `/opt`） | 自动回退到 `~/.config/RouterSight/RouterSight_config.ini` |
| 源码运行 | 脚本所在目录 |

AppImage 运行时 `sys.executable` 指向只读挂载点（`/tmp/.mount_*/usr/bin`），所以代码里用 `$APPIMAGE` 反推真实目录，避免"设置保存后重启就丢"。

## 与 Windows 版的差异

| 功能 | Linux 实现 | 备注 |
|---|---|---|
| 数据采集（SSH 读 `/proc`） | 完全一致 | 与本机系统无关 |
| 界面 / 主题 / 图表 | 完全一致 | 字体自动换成本机 CJK 字体（Noto Sans CJK SC 优先） |
| HiDPI / 桌面缩放 | 组件尺寸跟随桌面缩放的 **70%**（限制 100%~160%），可在「显示设置 → 界面缩放」手动覆盖（0% = 自动） | 小部件不像常规窗口那样整倍跟随系统缩放，否则高分屏上会大得离谱；字号按卡片高度等比推算，放大组件时文字跟着变大。曲线统一画在文字下方 |
| 靠边隐藏 | 可用 | **需要 X11**；Wayland 不允许客户端设置窗口绝对坐标，会退化为不平移 |
| 鼠标穿透 | 可用 | 用 `Qt.WindowTransparentForInput` 实现，切换时窗口会重建一次 |
| 开机启动 | 写 `~/.config/autostart/routersight.desktop` | 等价于 Windows 的 `Run` 注册表项 |
| 托盘图标 | `QSystemTrayIcon`（StatusNotifier） | GNOME 需装 AppIndicator 扩展；KDE/XFCE/Cinnamon 开箱可用 |
| 关闭 / 任务栏 | 关闭窗口缩到托盘继续运行；组件用 `Qt.Tool`，默认不进任务栏、不参与 Alt+Tab | 两个都能在「显示设置 → 托盘 / 任务栏」里关掉；托盘不可用时关闭即退出，不会变成无界面后台进程 |
| 快捷方式按钮 | `xdg-open` / 直接 exec | 原 Windows 路径已按平台分流 |

启动脚本默认在有 X11 时强制 `QT_QPA_PLATFORM=xcb`，因为"贴边停靠"依赖窗口绝对定位。想用 Wayland 原生：

```bash
ROUTERSIGHT_KEEP_QT_PLATFORM=1 ./RouterSight-1.0-x86_64.AppImage
```

## 兼容性

- 架构：x86_64
- glibc：**>= 2.17**（CentOS 7 / Ubuntu 16.04 / Debian 9 及以上）
- 需要系统提供（不打包，避免 glibc 冲突）：`libX11`、`libGL`、`libfontconfig`、`libfreetype`、`libdbus`、以及 Qt xcb 平台插件的一堆 `libxcb-*`
- 缺失 xcb 依赖时，`AppRun` 会先做 `ldd` 预检并直接打印对应发行版的安装命令，而不是甩一段 Qt 的英文报错

## 常见问题

**启动报 `Cannot mount AppImage` / `fusermount` 缺失**
装 `libfuse2`（Ubuntu 22.04+：`sudo apt install libfuse2`）；或临时用 `./RouterSight-*.AppImage --appimage-extract-and-run`。

**没反应，日志里是 `Could not load the Qt platform plugin "xcb"`**
按 `AppRun` 提示补装 xcb 相关包。GNOME/Wayland 上先用 `ROUTERSIGHT_KEEP_QT_PLATFORM=1` 确认是不是平台插件问题。

**托盘图标不显示**
GNOME 默认不显示托盘，装 `gnome-shell-extension-appindicator` 并启用。

**中文变成方块**
装任一中文字体：`sudo apt install fonts-noto-cjk`（Debian/Ubuntu）或 `sudo dnf install google-noto-sans-cjk-fonts`（Fedora）。
