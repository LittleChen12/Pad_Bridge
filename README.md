# PadBridge

通过 USB 或同一局域网 Wi-Fi，把 iPad 用作电脑的镜像屏或扩展屏。
支持 Ubuntu/Xorg；0.3.0 新增 Windows 11 x64 后端。
iPad 端使用 [OpenDisplay](https://apps.apple.com/app/id6780264891)（Philip Poloczek）。

[下载最新版本](https://github.com/LittleChen12/Pad_Bridge/releases/latest) ·
[Windows 11 使用说明](docs/windows.md) · [开发与构建](CONTRIBUTING.md) · [0.3.0 发布说明](docs/releases/v0.3.0.md)

本轮 Windows 迭代的改动、实现方式与实测数据见 [优化记录](docs/windows-optimization.md)；
切回 Ubuntu 接着开发见 [Linux 升级交接](docs/linux-upgrade.md)。0.3.0 当前为开发版本，
分支 CI 产物与已发布的 GitHub Release 分开；仅推送版本标签才发布正式安装包。

## Windows 11

便携包完整解压后双击 `PadBridge.exe`。源码开发运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\bootstrap.ps1
.\padbridge.cmd
```

默认镜像主屏；首次安装签名扩展组件后，可自动创建 iPad 副屏，断开后收回。
扩展模式可保存副屏默认位于左侧或右侧；命令行还可选择 Windows 已启用的物理或虚拟副屏。
使用 Windows Graphics Capture（GDI 回退）、低延迟 NVENC / x264 编码和独立后台进程，
支持 USB、Wi-Fi、触控和托盘。Qt 界面延续 Ubuntu 版的侧栏、卡片和配色。
NVENC 直接处理 BGRA，画面处理与网络发送并行；切换镜像/扩展时自动同步 iPad 的画面比例。
USB 需要 Apple 移动设备支持。安装、测试、构建与实机验收范围见 [Windows 文档](docs/windows.md)。
以下安装及系统依赖说明针对 Ubuntu。

## 安装与支持范围

首个安装包目标为 **Ubuntu 24.04、x86_64、Xorg 会话**。

从 Releases 下载 `.deb` 后，在文件所在目录运行：

```bash
sudo apt install ./padbridge_0.3.0_amd64.deb
```

安装后从应用菜单打开 **PadBridge**。安装包使用系统依赖，不包含设备 IP、用户设置或开发缓存。
不设置开机启动、不更改启动参数、显卡驱动或 sudoers。
Ubuntu 默认使用 Wayland 的电脑，需要在登录界面选择 **Ubuntu on Xorg**。
其他 Ubuntu / Debian 版本、ARM 和 macOS 未作为本包的支持目标；Windows 使用独立便携包。

- **镜像**：读取现有主屏，不创建虚拟输出，不改主屏分辨率、刷新率或布局。
- **扩展**：需要 Intel / AMD 驱动支持的空闲 HDMI 接口；不是所有电脑都具备这个条件。
  第一次启动时通过系统认证，仅临时授予本次开机的接口访问权限；用户需属于 plugdev 组。
- **编码**：有可用的 NVIDIA NVENC 时使用硬件编码，否则尝试 x264 软件编码。
  没有 NVIDIA 显卡也可尝试运行，但高分辨率和帧率下的 CPU 性能需要实测。
- 托盘需要系统支持 AppIndicator / StatusNotifier。Ubuntu 默认的 AppIndicators 扩展可用。

安装包结构与依赖可以检查；其他型号电脑的驱动、接口和性能尚未逐台实测。

## 使用

1. 在 iPad 上打开 OpenDisplay；USB 连接时按 iPad 提示信任电脑。
2. 在 PadBridge 选择 **扩展屏幕** 或 **镜像主屏**，以及 USB / Wi-Fi。
3. 点击 **连接 iPad**。修改模式或画面参数前，先点击 **断开连接**。

Wi-Fi 需要同一局域网，并允许 OpenDisplay 的“本地网络”权限。
可自动搜索；发现不到时，直接填写 iPad 的 IP 地址，默认接收端口为 9000。
自动发现使用 Avahi / Bonjour，不扫描整个网段；手动地址支持 IPv4、IPv6 和 .local。

**镜像必须在 PadBridge 中切换。系统设置里的“镜像”不是支持路径。**
扩展时可通过“排列屏幕”调整布局。镜像时保留电脑显示设置，iPad 按比例显示完整主屏，
屏幕比例不同时留黑边。iPad 旋转不会改变电脑主屏方向。

### 画面参数

“画面设置”提供预设 / 自定义分辨率、15～60 FPS、1～50 Mbps 或自动码率。
参数在下次连接时应用并保存。

- 自动原生：扩展使用 iPad 原生尺寸；镜像尽量使用主屏原始尺寸。
- 自定义分辨率按横屏填写，宽是 8 的倍数，高是偶数，范围 320～3840。
  扩展时设定虚拟屏大小；镜像时作为等比缩放的上限，不修改电脑主屏。
- 自动码率：USB 24 Mbps；Wi-Fi 10 Mbps。码率、帧率都是目标值，实际受内容和设备限制。
- 镜像会遵守接收端解码尺寸和吞吐上限；必要时只缩放传输的视频。
- 保持持续采集，不做静止画面自动降帧。

### 关闭与退出

- 点击窗口 **×**：隐藏到托盘，当前连接继续。
- 托盘 **显示窗口**：恢复界面；**断开连接**：停止串流。
- 托盘或窗口菜单 **退出 PadBridge**：先停止串流、收回属于本程序的虚拟屏，再结束整个软件。
- 镜像退出不会关闭电脑物理屏幕。
- 没有托盘宿主时，窗口不会直接隐藏失联，会提示启用托盘或使用菜单退出。
- 未连接时不运行采集、转换或编码，只有对应平台的界面、托盘和低频状态检查。

USB 拔线会收回扩展屏；Wi-Fi 连接不依赖数据线。正常连接中断时会尝试重连。
本版本修复了 XShm 截图与屏幕尺寸变化之间的特定 BadMatch 竞争：丢弃无效帧并重新采集。
每次启动或切换尺寸时，先发送视频配置，首帧发送后再同步一次真实光标状态，
让接收端及时更新视频显示区域；不会移动电脑鼠标，也不会持续增加关键帧。
这不代表系统显卡驱动的任意显示配置变更都已经兼容；不要通过系统设置强制镜像虚拟输出。

## 命令行

```bash
padbridge ui
padbridge start --display-mode mirror --transport usb
padbridge start --display-mode extend --transport wifi --address 192.168.8.123
padbridge start --resolution 1920x1440 --fps 30 --bitrate 8
padbridge stop
padbridge status
padbridge doctor
journalctl --user -u padbridge.service -f
```

未指定的启动参数使用上次保存设置。`--resolution native` 与 `--bitrate 0` 恢复自动选项。
用户设置位于 `~/.config/padbridge/connection.json`，缓存位于 `~/.cache/padbridge/`。
卸载使用 `sudo apt remove padbridge`；卸载前请从托盘退出。

## 开发与模块

仓库已包含固定版本的上游运行时代码，普通克隆即可，无需 Git 子模块。
源码运行 `./padbridge`。开发环境需要系统 GTK / GStreamer；`bootstrap.sh` 可下载并局部解压
部分缺失的运行库。发布包不捆绑这些开发运行库，通过 apt 安装标准依赖。

| 模块 | 职责 |
| --- | --- |
| `padbridge_app/cli.py` | 命令行入口 |
| `service.py`、`preferences.py` | 工作进程生命周期、状态、原子保存设置 |
| `worker.py` | 串流进程装配 |
| `displays.py` | 只读镜像、虚拟扩展屏创建与回收 |
| `encoding.py`、`x11_capture.py` | 编码、缩放、截图异常保护 |
| `network.py` | Bonjour 搜索、握手、TCP 缓冲 |
| `video.py` | 参数模型与边界校验 |
| `ui/application.py`、`ui/window.py` | 异步界面行为与窗口布局 |
| `ui/panels.py`、`ui/tray.py`、`ui/styles.css` | 控件、托盘、样式 |
| `enable_display.py` | 独立的最小权限辅助程序 |
| `windows/` | Windows 的采集、编码、设备、输入、工作进程和 Qt 界面，详见 [模块对应表](docs/linux-upgrade.md#模块对应表) |

界面不直接设置显示模式，也不启动编码器；用户连接后才创建独立工作进程，Linux 由 systemd 用户服务管理。
镜像适配器仅查询 RandR。输入与光标始终按原始采集区域映射，与视频缩放解耦。

```bash
./test.sh
python3 packaging/build_deb.py
```

无显示器 / iPad 的 CI 使用 `./test.sh --unit-only`；完整发布使用
`python3 packaging/build_release.py`，生成 `.deb`、对应提交的源码压缩包和 `SHA256SUMS`。
推送与源码版本一致的 `v*` 标签会在测试通过后自动发布到 GitHub Releases。

回归测试覆盖协议 / 会话、PRIME 接口匹配、授权范围、参数迁移、解码上限和主屏不被修改。
`tests/isolated_capture.py` 在离屏 Xephyr 中复现尺寸变化导致的截图错误，对照无保护与有保护的行为；
不调整真实显示器。额外实机检查包括镜像、扩展、参数应用、托盘退出和闲置占用。
构建输出为 `dist/padbridge_0.3.0_amd64.deb`。

## 已知边界与来源

当前不支持 Wayland、音频、剪贴板、Apple Pencil 压感或多 iPad 并行。
Wi-Fi 使用原生 OpenDisplay TCP 协议，当前不加密且没有身份认证，适用于可信局域网。
无云服务器或公网中转。

基于 [OpenDisplay for X11](https://github.com/cray2015/opendisplay-x11)，作者 Vibhanshu Biswas，
GPL-3.0-or-later，保留在 `vendor/opendisplay-x11/`，上游提交
`0301158192212c5aa7ad46d5901048251a46e936`。本地代码同样采用 GPL-3.0-or-later。
来源、保留范围和上游补丁见 [vendor/README.md](vendor/README.md)。
上游会话循环的局部扩展包括：连接套接字设置、按实际编码尺寸计算解码预算、首帧前的视频配置与首帧后的状态同步、发布视频尺寸和目标帧率。
接收端属于 [OpenDisplay](https://opendisplay.app/) 项目，单独通过 App Store 安装。
