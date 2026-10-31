# 切回 Linux 后的升级交接

> 这是 Windows 迭代结束时的交接快照。后续移植已在 `feature/linux-upgrade` 实施；
> 当前代码、测试结果和仍有差异的项目见 [Linux 优化记录](linux-optimization.md)。
> 下文的“暂不支持/待迁移”描述对应原 `feature/windows11`，不代表 Linux 升级分支现状。

本轮 Windows 工作基于 Ubuntu 0.2.0（`4f9f9fb`），保存在 `feature/windows11`。
当前共享版本号为 0.3.0，尚未通过版本标签发布；此分支可作为下一轮 Linux 开发起点。
已完成的实现和实测数据见 [Windows 优化记录](windows-optimization.md)。

## 获取本轮代码

在原 Linux 工程目录先运行 `git status`。若有本地修改，先自行提交或备份，再切换分支。
从远端 Windows 迭代分支建立独立的 Linux 开发分支：

```bash
git fetch origin
git switch -c feature/linux-upgrade origin/feature/windows11
```

若这台机器还没有仓库：

```bash
git clone git@github.com:LittleChen12/Pad_Bridge.git
cd Pad_Bridge
git switch -c feature/linux-upgrade origin/feature/windows11
```

如果 `feature/linux-upgrade` 已经存在，先切回该分支并检查自己的提交，再决定如何合入；
不要用重置命令覆盖已有工作。Windows 的 `.venv`、`runtime`、AppData 配置和驱动配置不需要复制到 Linux。

## 本轮对 Linux 的实际影响

Linux 仍使用 GTK、Xorg/RandR、GStreamer、usbmuxd/Avahi 和 systemd 用户服务，
默认模式仍为扩展。Windows 的 PySide6、PyAV、DXcam、驱动和 PowerShell 辅助程序按平台隔离，
Linux 无需安装 `requirements-windows*.txt`。

共享部分的变更只有这些：

- `app.py` 和 `cli.py` 按平台选择入口，避免 Windows 导入 GTK/X11。
- `paths.py` 分离 AppData 与原来的 XDG 路径；Linux 配置和缓存目录保持原来的位置。
- `preferences.py` 明确使用 UTF-8，并兼容旧配置，新增字段有默认值。
- 等比缩放/解码预算计算移至 `video.py`；`displays.py` 继续导入，原导入路径仍可用。
- TCP 配置增加 `TCP_NODELAY`；Wi-Fi 超时提示补充重新入网的排查方法。
- 版本、文档与构建 CI 增加 Windows 支持；上游固定代码本轮未改动。

**本轮没有把 Windows 的流媒体优化自动移植到 Linux。**
Linux 当前仍走原有 GStreamer 管线；“副屏位置”左右选择和视频连接比例重置也暂时只在
Windows 实现。`--display-position` 的帮助文字明确标记为 Windows 参数，不能据此认定 Linux 已支持。

## 模块对应表

下表路径相对于 `padbridge_app/`，用于定位可复用逻辑和必须分别实现的系统接口。

| 职责 | Linux | Windows |
| --- | --- | --- |
| 界面 | `ui/`，GTK | `windows/ui.py`、`widgets.py`、`styles.qss`，Qt |
| 后台生命周期 | `service.py`，systemd | `windows/service.py`、`storage.py`，独立进程 |
| 会话装配 | `worker.py`、上游 `odx11/daemon.py` | `windows/worker.py` |
| 屏幕与回收 | `displays.py`、`enable_display.py`，RandR/DRM | `windows/virtual_display.py`、`display_config.py`、`device_control.py` |
| 采集 | `encoding.py` 的 ximagesrc、`x11_capture.py` | `windows/desktop.py`，WGC/GDI |
| 编码 | `encoding.py`，GStreamer NVENC/x264 | `windows/encoding.py`，PyAV NVENC/x264 |
| 发送和统计 | 上游 `odx11` 的会话与管线 | `windows/stream_sender.py` |
| 比例同步 | 首帧前配置、首帧后状态同步 | 上述同步加 `windows/receiver_layout.py` 的一次连接重置 |
| 参数、端点和协议 | `video.py`、`preferences.py`、`network.py` 与固定上游协议，两个平台共用 | 同左 |

## 建立 Linux 基线

目标仍为 Ubuntu 24.04 amd64 的 Xorg 会话。先运行不连接设备的回归检查：

```bash
sudo apt install python3-gi python3-xlib python3-pytest desktop-file-utils
./test.sh --unit-only
python3 packaging/build_deb.py
python3 packaging/check_deb.py dist/padbridge_0.3.0_amd64.deb
```

桌面运行依赖见 `packaging/build_deb.py`；安装生成的包时由 apt 处理：

```bash
sudo apt install ./dist/padbridge_0.3.0_amd64.deb
./test.sh
./padbridge doctor
./padbridge
```

Windows 电脑没有可用的 WSL Linux 环境，本轮 Linux 自动检查交给 Ubuntu CI。
CI 不连接 iPad，也不测量 Linux 桌面串流性能；回到 Linux 后仍需真实桌面与设备验收。

## 建议的升级顺序与验收

1. **先记录当前表现。** 使用相同原生尺寸、60 FPS，USB 24 Mbps 和 Wi-Fi 10/6 Mbps 分开测；
   每轮交替静止桌面和持续滚动，记录至少三分钟，保留平均值、P95 和最长帧间隔。
   记录采集/编码/发送后端与 GPU 电源状态，避免把平台或功耗差异归因于单个代码改动。
2. **先补可观测性。** 对齐 Windows 的最近两秒发送 FPS、采集/编码/发送/排队耗时以及接收端统计。
   区分启动阶段、静止阶段和活动阶段；不能只比较 OpenDisplay 的一个整数 FPS。
3. **按瓶颈调整管线。** 当前 Linux 管线包含 CPU `videoconvert`，检查实际开销后再评估 GPU 转换。
   Windows 的 BGRA 输入参数不等同于 GStreamer 插件参数，应查询本机插件能力并实际编码验证。
   保持无 B 帧、无前瞻、有限排队；允许丢弃未编码的旧采集帧，不能随意丢弃编码后的参考帧。
4. **对齐扩展体验。** 为 GTK 增加左右位置选择，将偏好传给 RandR 布局；复用 Windows 的验收约束：
   主屏不变、新连接应用默认侧、已有多屏不重叠、当前会话保留手动排列、断线仅回收本程序拥有的输出。
5. **复测比例切换。** 连续执行镜像→扩展→镜像，并在扩展中断线重连，检查是否有残留黑边。
   只有确认接收端需要时才引入一次视频连接重置，保持副屏和窗口位置，避免无限重连。
6. **独立处理 Wi-Fi 尖峰。** 固定码率下先分离采集/编码和传输瓶颈；动态码率是后续功能，
   需要单独设计变化速度、下限和恢复策略，不能把当前“自动”称为自适应码率。

每次变更后检查镜像不改主屏、扩展创建与回收、USB 拔线/Wi-Fi 重连、旋转、托盘退出和闲置资源。
XShm 尺寸变化的保护继续用 `tests/isolated_capture.py` 在离屏 Xephyr 验证，不能通过强制镜像真实屏幕来复现。
上游修改需同步 `vendor/opendisplay-x11.patch` 和来源说明。

## 交付约定

`main`、`feature/**` 的推送及 PR 会触发 Ubuntu 和 Windows 测试、构建、包检查。
继续保留这两条 CI；Linux 共享模块的改动也必须避免破坏 Windows。
开发分支仅生成 Actions 产物；确认实机验收并准备正式发布后，才推送与源码版本一致的 `v*` 标签。
