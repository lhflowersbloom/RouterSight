# 更新日志

## v1.1 — 2026-10-29

**首个 Linux 版本，同时修复若干高分屏下的界面问题。**

### 新增

- **Linux / AppImage 支持**：单文件 `RouterSight-1.1-x86_64.AppImage`，双击即用，不需要用户自备 Python、PyQt5 或 Paramiko。
  构建脚本、`AppRun` 与说明见 `linux/` 目录（`python linux/build_appimage.py` 一条命令出包）。
  - glibc 基线 **2.17**（CentOS 7 / Ubuntu 16.04 / Debian 9 及以上均可运行）
  - 配置写在 `.AppImage` 同目录，保持绿色版体验；目录不可写时回退到 `~/.config/RouterSight`
  - 启动前自动检测 Qt xcb 依赖，缺失时直接打印对应发行版的安装命令
- **界面缩放**：显示设置新增「界面缩放」。默认 `自动`，组件尺寸跟随桌面缩放的 **70%**（限制 100%~160%）——
  桌面小部件不该像常规窗口那样整倍放大。也可手动填 50%~250%。
- **关闭时缩到托盘**：关闭窗口不再退出，监控继续在托盘里跑，首次缩回会弹一次提示。
  托盘菜单补回「显示 / 隐藏组件」。
- **不在任务栏显示**：组件默认使用 `Qt.Tool`，不占任务栏、不参与 Alt+Tab；可在设置里关掉。
- **开机自启（Linux）**：写入 `~/.config/autostart/routersight.desktop`，等价于 Windows 的 Run 注册表项。
- **鼠标穿透（Linux）**：用 `Qt.WindowTransparentForInput` 实现，切换时窗口会重建一次。

### 修复

- **高分屏下卡片文字重叠**：标题与数值原来用固定像素基线（10 / 22）配点字号，DPI 一高字号变大而基线不动，两行字就压在一起。
  现改为按卡片高度推算字号、用 `QFontMetrics` 量真实行高排布，任何 DPI / 字体下都不会重叠。
- **曲线盖住数值**：绘制顺序改为先曲线后文字；曲线顶部留白跟随文字实际高度，矮卡片上文字先回缩而不是挤压曲线。
- **设置窗口在 1366×768 上按钮出屏**：内容改为可滚动、底部按钮固定，同时按可用屏幕收敛初始高度。
- **Linux 字体**：界面字体不再写死「微软雅黑」，按可用性依次选择 Noto Sans CJK SC / Source Han Sans SC / 文泉驿等。

### 其他

- 预览与冒烟测试脚本（`smoke_test.py` / `ui_preview.py` 等）的 `QT_QPA_FONTDIR` 改为仅在 Windows 下设置，Linux 交给 fontconfig。
- `.gitignore` 补充 Linux 打包产物（`dist_linux/`、`.tools/`、`*.AppImage`）。

### 下载

| 文件 | 平台 | 说明 |
|---|---|---|
| `RouterSight-1.1-x86_64.AppImage` | Linux x86_64 | 单文件，`chmod +x` 后运行 |
| `RouterSight-1.0-single.exe` | Windows | 单文件版 |
| `RouterSight-1.0-portable.zip` | Windows | 文件夹版 |

Windows 版功能未变，仍为 v1.0 的构建。
