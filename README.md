# RouterSight · 路由视界

面向 Windows 桌面的轻量级路由器监控组件，**无需部署 Netdata**。

组件通过 **SSH 直读 iStoreOS / OpenWrt 的 `/proc`** 采集指标，在桌面实时呈现 CPU 使用率、内存占用、磁盘 I/O、**下载 / 上传速率**与 TCP/UDP 连接数。

> 原版 NetSight 依赖路由器安装 iStoreOS 应用商店中的「NetData 系统监控」；本项目改为自行采集，路由器端**无需安装、无常驻进程**。

---

## 来源与致谢

| | |
|---|---|
| **改自** | [**酷友社论坛**](https://www.koolcenter.com/) 的 **NetSight v2.1.1**（原作者 **RtrBug**，原帖：<https://www.koolcenter.com/t/topic/7826>） |
| **反编译与重构** | **经 DeepSeek 优化**完成 —— 从 PyInstaller 打包的 exe 中还原出 Python 源码，改为 SSH 直读路由器，修正局域网测速翻倍的 bug，并重做整套 UI |
| **界面 / 交互** | 知影 |

原程序通过 REA 工具链从 `NetSight.exe`（PyInstaller + Python 3.13）提取并反编译，再在此基础上前端、数据层、打包脚本全部重写。原作者的署名与版权归 RtrBug 所有；本仓库仅作学习与个人使用。

---

## 截图

| 桌面挂件（暗黑） | 桌面挂件（明亮） |
|---|---|
| ![widget dark](docs/widget-dark.png) | ![widget light](docs/widget-light.png) |

| 设置窗口（暗黑） | 设置窗口（明亮） |
|---|---|
| ![settings dark](docs/settings-dark.png) | ![settings light](docs/settings-light.png) |

托盘菜单：

![tray menu](docs/tray-menu.png)

图标（16px 起可用）：

![icon](docs/icon-sheet.png)

---

## 功能

- **六张卡片**：CPU 使用率 · 内存使用 · 磁盘 I/O · 下载速度 · 上传速度 · TCP/UDP 连接
- **网速用 MB/s**，下载（青）/ 上传（紫）分开显示，互不相加
- **靠边隐藏**：拖到屏幕边缘自动停靠，鼠标离开 0.5 秒后只留 **4px** 在屏幕上；鼠标碰一下边缘就滑出来
- **鼠标穿透**：开启后挂件对鼠标完全透明，不挡桌面任何操作；只能从托盘菜单关掉（防止穿透后点不到自己）
- **双主题**：暗黑 / 明亮。明亮主题按 **Windows 11 (WinUI) 规范**配色（`#F3F3F3` 底 / `#FFFFFF` 卡片 / `#E5E5E5` 描边 / `#0067C0` 主色），字体走 Segoe UI → 微软雅黑
- 多显示器：吸附和穿透按**光标所在屏幕**判定，使用工作区（不会压住任务栏）
- 开机自启、窗口置顶、快捷方式按钮、无边框拖拽、托盘菜单
- `--selftest` 命令行自检，出问题一眼定位

---

## 为什么不再需要 Netdata

原版每 1 秒拉一次 `http://<路由器>:19999/api/v1/allmetrics?format=json`，取 `system.net` 的 `InOctets`/`OutOctets` 相加。

问题是 **Netdata 的 `system.net` 是所有网卡的汇总**：一次外网下载会同时出现在 `eth0.rx`、`eth1.tx`、`br-lan.tx` 上，相加后自然翻倍甚至更多。

实测（从路由器拉 500MB 数据的同时采样）：

| 统计方式 | 读数 |
|---|---|
| `eth1` 单网卡上传 | **464,549 kb/s** ← 真实值 |
| 原版「全接口 in + out」 | **928,501 kb/s** = 整 2.0 倍 |

现在的做法：**只统计用户指定的那一个网卡，且下载/上传分开**，从结构上就不存在翻倍。

---

## 工作原理

```
┌─────────────── Windows ───────────────┐        ┌──────── iStoreOS / OpenWrt ────────┐
│  RouterSight.exe (PyQt5)              │  SSH   │  sshd                              │
│   ├─ RouterStats ──── paramiko ───────┼───────▶│  sh -s  ← 只读脚本从 stdin 进入     │
│   │    采样 2 次算差分 → CPU%/速率     │  :22   │   ├─ /proc/stat      CPU          │
│   ├─ 6 张卡片 (QPainter 自绘)          │        │   ├─ /proc/meminfo   内存         │
│   └─ 靠边隐藏 / 鼠标穿透 (Win32 API)   │        │   ├─ /proc/net/dev   各网卡字节数 │
└───────────────────────────────────────┘        │   ├─ /sys/block + /proc/diskstats │
                                                  │   └─ /proc/net/{tcp,udp}*  连接数 │
                                                  └───────────────────────────────────┘
```

- 路由器上**不落任何文件**：脚本用 `sh -s` 从标准输入喂进去，纯 `busybox` 兼容语法，只读不写
- 一个长连接常驻（keepalive 15s），每 `refresh_interval` 秒跑一次
- CPU% 和网速都是**两次采样的差分**算出来的，所以第一次显示会略慢一拍
- 免密登录可选（SSH key），也支持密码

---

## 快速开始

1. 下载 `RouterSight_单文件版.exe`（或整个 `RouterSight` 文件夹版）
2. 双击运行 → 托盘出现图标，桌面出现挂件
3. 托盘右键 → **设置**，填：

   | 项 | 说明 |
   |---|---|
   | 地址 | 路由器 IP，如 `192.168.9.1` |
   | 端口 | SSH 端口，默认 `22` |
   | 用户 | 一般为 `root` |
   | 密码 | 路由器 root 密码（也可留空改用 SSH key） |
   | 网卡 | `自动（按默认路由选择）` = 走 WAN 口；想看局域网流量就选 `br-lan` / `eth1` |

4. 点 **测试连接**，出现「正常」即可
5. 「显示设置 → 窗口行为」勾上 **靠边隐藏**；需要挂件完全不挡操作时，从托盘菜单开 **鼠标穿透**

> 配置文件 `RouterSight_config.ini` 与 exe 同目录，保存时会自动留一份 `.bak`。
> 从旧版 NetSight 升级会自动复制 `NetSight_config.ini` → `RouterSight_config.ini`。

---

## 托盘菜单

```
鼠标穿透     ← 勾选后挂件对鼠标透明，只能在这里取消
置顶
开机启动
设置
退出
```

原版有「显示/隐藏」和「锁定/解锁」两项，本版**已移除**：靠边隐藏取代了手动隐藏，穿透状态由托盘独占控制，避免出现「穿透开着又点不到挂件」的死锁。

---

## 从源码运行 / 构建

```bash
# 依赖
pip install PyQt5==5.15.11 paramiko cryptography

# 直接跑
python RouterSight.py

# 自检（连接、采样、字段完整性）
python RouterSight.py --selftest

# 打包（--onefile / --onedir，默认两个都打）
python build.py
```

打包产物：

- `dist/RouterSight.exe` —— 单文件版（约 46 MB）
- `dirdist/RouterSight_dir/` —— 文件夹版（启动更快，推荐）

辅助脚本：

| 文件 | 用途 |
|---|---|
| `routersight_router.py` | SSH 数据层：`RouterStats`、`to_netdata_metrics`、`test_connection` |
| `make_icon.py` | 生成黑白图标（`assets/logo.png`、`assets/logo.ico` 及箭头 PNG） |
| `ui_preview.py` | 离屏渲染设置窗口（暗/亮两套）到 PNG |
| `render_widget.py` | 离屏渲染桌面挂件到 PNG |
| `menu_preview.py` | 离屏渲染托盘菜单到 PNG |
| `smoke_test.py` | 无界面冒烟测试：拉真实数据并打印每张卡片的显示文本 |
| `edge_test.py` | 靠边隐藏 / 鼠标穿透的单元测试（用 `WA_DontShowOnScreen`，不打扰桌面） |
| `lan_test.py` | 复现并验证「局域网传输测速翻倍」的对比脚本 |

> 离屏渲染需要 `QT_QPA_PLATFORM=offscreen` 和 `QT_QPA_FONTDIR=C:\Windows\Fonts`，否则文字是空白。

---

## 配置项速查

| 键 | 默认 | 说明 |
|---|---|---|
| `router_host` / `router_port` / `router_user` / `router_password` | `192.168.100.1` / `22` / `root` / 空 | SSH 连接 |
| `router_key` | 空 | 私钥路径，填了就用 key 登录 |
| `net_interface` | `auto` | `auto` = 默认路由网卡；或指定 `eth0` `br-lan` … |
| `refresh_interval` | `1` | 刷新秒数 |
| `data_points` | `50` | 曲线保留点数 |
| `layout_option` | `2` | 1 单行 / 2 每行两个 / 4 紧凑 |
| `theme` | `1` | 0 明亮 / 1 暗黑 |
| `card_opacity` `text_opacity` `chart_opacity` `card_radius` | `70` `50` `90` `5` | 外观 |
| `edge_hide` | `True` | 靠边隐藏 |
| `click_through` | `False` | 鼠标穿透 |
| `show_cpu_chart` … `show_connections_chart` | `True` | 六张卡片开关 |
| `widget_x` `widget_y` `widget_width` `widget_height` `widget_stays_on_top` | — | 位置与置顶 |

---

## 常见问题

**Q：状态一直是「离线」？**
先点设置里的「测试连接」。SSH 连不上时检查：路由器 sshd 是否开启、端口是否被改、密码是否正确、Windows 防火墙是否放行出站 22。

**Q：CPU / 网速第一秒是 0？**
正常。差分指标需要两次采样，第二次才有值。

**Q：数据明显不对 / 网速偶尔翻倍？**
多半是网卡选错了。`自动` 取默认路由网卡（一般是 WAN 口 `eth0`）。想在**局域网内部传输**时看到准确速率，请选实际承载流量的网卡（`br-lan` 或 `eth1`）—— 单网卡、分方向统计永远不翻倍。

**Q：穿透打开后点不到挂件了？**
这是设计如此。从**托盘图标**右键 → 取消「鼠标穿透」。

**Q：怎么排查启动问题？**
命令行跑 `RouterSight.exe --selftest`，会在 exe 同目录生成 `RouterSight_selftest.txt`，里面有连接、每条指标和错误信息。

---

## 已知限制

- 仅在 **iStoreOS 24.10（OpenWrt 系）** 上实测；其它发行版只要 `busybox` + `/proc` 标准布局即可，但未验证
- 只支持 **Windows 10/11 x64**
- 路由器密码以**明文**存在 `RouterSight_config.ini` 里（这是继承自原版的设计）。介意的话请改用 SSH key：`router_key` 填私钥路径、密码留空
- 曲线是单线条自绘，没有历史持久化，重启即清空
- 内存曲线上限固定按物理内存算，不随采样缩放

## 安全提示

程序只读 `/proc`，不写路由器、不改配置、不开端口。
但请注意：**路由器把 SSH(22)、LuCI(80/443)、AdGuardHome(3000)、ttyd(7681) 等端口暴露在局域网里**。ttyd 是网页终端，能登录就等于交出 root。建议关掉不用的服务或限源。

---

## 免责声明

本项目是个人学习用途的二次开发，与原程序作者 RtrBug 及酷友社论坛无隶属关系。
使用前请自行确认所在网络环境的合规性；因使用本程序造成的任何后果由使用者自行承担。

## 许可

原程序版权归 **RtrBug / 酷友社论坛** 所有。本仓库的修改部分可自由使用、修改、分发；转载请注明原出处与本仓库。
