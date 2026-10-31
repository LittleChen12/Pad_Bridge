# 架构与模块边界

PadBridge 的公共入口按操作系统延迟导入后端。界面只管理设置、状态与生命周期；
连接后才启动采集/编码工作进程。Linux 使用 systemd 用户服务，Windows 使用独立后台进程。
未连接时不会初始化采集器或视频编码器。

## 共享部分

- `app.py`、`padbridge_app/cli.py`：命令行和桌面入口，按平台选择实现。
- `paths.py`、`preferences.py`、`video.py`：平台路径、原子设置保存、分辨率与码率校验。
- `network.py`：端点解析、接收端握手和套接字配置；发现机制按平台选择。
- `vendor/opendisplay-x11/odx11/protocol.py`、`annexb.py`：OpenDisplay 控制/视频协议与 H.264 帧处理。

## 平台实现

以下路径相对于 `padbridge_app/`。

| 职责 | Ubuntu / Xorg | Windows 11 |
| --- | --- | --- |
| 界面与托盘 | `ui/`：GTK、AppIndicator | `windows/ui.py`、`widgets.py`、`styles.qss`：Qt |
| 后台生命周期 | `service.py`：systemd 用户服务 | `windows/service.py`、`storage.py`：独立工作进程 |
| 会话装配 | `worker.py`、固定上游 `odx11/daemon.py` | `windows/worker.py` |
| 物理屏读取与虚拟副屏 | `displays.py`、`display_layout.py`、根目录 `enable_display.py` | `windows/virtual_display.py`、`display_config.py`、`device_control.py` |
| 采集 | `encoding.py` 的 ximagesrc、`x11_capture.py` | `windows/desktop.py`：WGC、GDI 回退 |
| 转色、缩放与编码 | `encoding.py`、`encoding_profiles.py`：GStreamer CUDA/NVENC、CPU/x264 回退 | `windows/encoding.py`：PyAV NVENC、x264 回退 |
| 有界发送与统计 | `stream_sender.py`、`stream_metrics.py` | `windows/stream_sender.py` |
| 接收端比例同步 | 首帧配置与首帧后的真实光标状态同步 | 同步逻辑加 `windows/receiver_layout.py` 的一次连接重置 |

## 生命周期与所有权

1. 界面保存经过验证的参数，将本次连接的配置快照交给工作进程。
2. 工作进程与接收端握手。镜像只读取主屏；扩展只管理自己创建的输出。
3. 根据接收端能力限制编码尺寸/帧率，启动采集、转换、编码及顺序发送。
4. 发送受阻时限制在途帧数，跳过未编码的旧帧；编码后的参考帧按顺序发送。
5. 断开或退出时先解除网络等待，再释放管线和拥有的副屏。镜像不会停用物理主屏。

原始采集坐标用于输入和光标，编码尺寸只控制传输画面。布局、管线与发送职责分开，
不在界面层调用显示驱动，也不在协议层加入平台界面依赖。
原始帧、等待帧与统计容器均有上限；静止画面仍持续采集，不自动降帧。

## 源码、测试与发布

- `tests/`：Linux 适配器、布局、发送、参数和显式实机测试；`tests/windows/`：Windows 后端测试。
- `vendor/`：固定版本的上游代码、许可证及可复现的本地补丁；不运行上游安装器。
- `packaging/`：Linux 包、Windows 安装器/便携包与源码发布构建；不保存本机运行库或用户配置。
- `windows/components.py`：安装器专用的系统组件检测、配置与结果报告；日常启动不下载或安装组件。
- `.github/workflows/build.yml`：Ubuntu/Windows 检查与构建；版本标签在两端通过后发布。
- `docs/`：当前使用指南、架构、实测与版本说明；已完成的交接待办通过 Git 历史查阅。
- `.cache/`、`runtime/`、`validation/`、`dist/`、`build/` 为本地忽略目录，不纳入源码发布。

测试和发布命令见 [开发说明](../CONTRIBUTING.md)。
