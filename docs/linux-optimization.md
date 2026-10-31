# Linux 优化记录

2026-10-31，基于 `feature/windows11` 的 `50c213a`，开发分支为 `feature/linux-upgrade`。
目标为 Ubuntu 24.04 amd64 / Xorg，继续使用 GTK、GStreamer、RandR 和 systemd。
本轮未改 Windows 采集/编码实现，保留两平台 CI；成果已与 Windows 后端一起纳入 v0.3.0。

## 迁移内容

- **GPU 转色与缩放**：`encoding_profiles.py` 定义 GStreamer 1.24 实际支持的参数。
  优先 `cudaupload → cudaconvertscale → nvcudah264enc`，将 X11 原始 BGRx 上传一次，
  在 CUDA 内存中转成 NV12 并编码。启动时用真实帧验证整个转换/编码组合；失败后尝试
  CPU 转色加旧版 `nvh264enc`，再尝试 `x264enc`。`settings.toml` 的 `convert="cpu"`
  可以排除 CUDA 路径，默认 `auto`。镜像缩放仍只影响传输画面，不改变主屏或触控坐标。
- **有限排队**：编码前申请帧名额，最多两帧包括正在转换、编码、排队和发送的帧。
  名额不足时丢弃尚未编码的原始帧；编码后的参考帧按顺序发送。GStreamer 的非丢弃输出队列
  将编码与交付分开，`stream_sender.py` 的单写线程按序发送控制消息和视频。
  GLib 不再在 `sendall()` 上等待；队列满或发送失败会结束当前连接，不会无限堆积。
  关闭先中断套接字、唤醒等待者，再停止管线，避免退出卡住。
- **NVENC 参数**：CUDA 编码使用 P4、ultra-low-latency、无 B 帧/前瞻、CBR、四帧 VBV。
  USB/Wi-Fi 的周期 IDR 分别保持两秒/十秒；接收端请求的 IDR 已验证。
- **统计**：`stream_metrics.py` 以有界容器和锁匹配帧时间戳，发布最近两秒的完成发送 FPS、
  各阶段平均/P95、帧间隔 P95/最大值、跳过的原始帧，以及有界的接收端统计。
  串流期间每秒更新状态；GTK 显示实际 FPS，仍清楚标注目标码率。
- **左右位置**：`display_layout.py` 在整个桌面的左/右外侧放置副屏，与主屏顶部对齐。
  X11 不允许负坐标，左侧扩展会整体平移桌面原点；物理输出只设置位置，不更改模式、刷新率或方向。
  自动排列中的旋转重新计算原点，避免宽度变更后重叠；当前会话检测到手动排列后保留其位置。
  所有权记录原子写入，退出仅在物理布局仍与记录一致时撤销自己的平移，尊重之后的手动调整。
  崩溃时 systemd 的 `ExecStopPost` 使用同一记录回收副屏。
- **界面**：GTK 增加左右选择，保存偏好；连接失败保留在状态卡中，不再弹阻塞式错误窗口。
  托盘行为、持续采集、分辨率/帧率/码率选项保持可用。

## 与 Windows 的区别

Ubuntu 24.04 的 GStreamer 1.24 插件没有 Windows/PyAV 使用的 `intra-refresh` 属性，
因此本轮没有宣称实现逐步帧内刷新，也没有为此升级系统显卡驱动或安装另一套视频运行时。
仍使用原有的长 GOP 与接收端主动请求 IDR。

Linux 继续使用首帧前配置、首帧成功发送后 100 ms 重放真实光标状态的比例同步。
真实 iPad 日志验证镜像的 `2560×1600 / layer 1112×695` 在切回扩展后自动变成
`2224×1668 / layer 1112×834`。本轮无需移植 Windows 的额外视频连接重置。
验证过程没有用程序移动电脑鼠标。

自动码率仍为 USB 24 / Wi-Fi 10 Mbps 固定预设，不是网络自适应；静止画面继续采集、编码。
没有修改全局 GPU 电源策略。GPU 转色降低 CPU 工作量，不代表整机功耗一定降低。

## 实机性能

测试机：i7-13700HX、RTX 4080 Laptop、NVIDIA 580.126.09、GStreamer 1.24.2；
iPad Air 3 / iPadOS 17.2 / OpenDisplay。原生 2224×1668，目标 60 FPS。
Wi-Fi 为同局域网 2.4 GHz（2422 MHz），非有线 USB 隧道。

每轮 185 秒，副屏内 1200×950 合成文本画布每 30 秒交替静止内容/滚动内容，持续重绘。
前 10 秒作为预热，统计剩余 176 个每秒快照。CPU 为串流进程占一个逻辑核的百分比，
不含 Xorg、桌面合成器、测试画布，也不是整机 CPU 百分比。
基线保留 `50c213a` 的 CPU 转色、旧 NVENC 参数和同步发送，只增加同口径测量探针。

| 指标 | 原 Linux USB 24 Mbps | 新 Linux USB 24 Mbps | 新 Linux Wi-Fi 10 Mbps |
| --- | ---: | ---: | ---: |
| 平均发送 FPS（两秒窗口） | 59.75 | 59.72 | 59.63 |
| 最低窗口 FPS | 59.5 | 59.5 | 53.6 |
| 串流 CPU，单核口径 | 41.99% | 17.31% | 17.60% |
| 转换/缩放平均耗时 | 2.68 ms | 1.57 ms | 1.57 ms |
| 编码平均耗时 | 4.21 ms | 3.53 ms | 3.54 ms |
| 发送平均耗时 | 0.07 ms | 0.04 ms | 0.12 ms |
| 各窗口帧间隔 P95 的均值 | 19.43 ms | 19.19 ms | 19.19 ms |
| 观测到的最长帧间隔 | 29.67 ms | 34.07 ms | 179.87 ms |
| 整卡功耗均值（nvidia-smi） | 38.61 W | 38.90 W | 38.90 W |

主要收益是串流进程 CPU 约降低 59%，转换/编码更快；USB 本来就接近 60 FPS，
不能称为帧率大幅提升，新版的最长帧间隔也并非每项更优。三轮 GPU 均处于 P0，
功耗是整卡采样，不能单独归因于应用。Wi-Fi 仍出现约 180 ms 的尖峰，不能保证无线锁定 60 FPS。
这些短测不能代替不同显卡、网络或长时间使用的验证；本轮没有重测 Wi-Fi 6 Mbps。

`capture` 测量源帧从时间戳到产出的年龄，包含采集及调度等待，不是纯 XShm 调用耗时。
`convert` 包括上传/缩放，`send` 是写入本机套接字的耗时，不是 iPad 呈现延迟。
接收端 e2e 依赖时钟同步，未用其作为本表结论。表内 P95 均值不是全部帧合并后的 P95。

早期测试窗口曾因副屏未就绪被窗口管理器放到主屏，该轮滚动数据不用于以上结论。
已改成等待串流和非主屏几何匹配后再显示画布，逐秒验证位置，布局变化时关闭测试窗口；
上表为修正后重测数据。

## 验证与复现

- Linux 40 项单元测试、143 项上游协议/会话测试通过。
- CUDA 真正出帧、强制 IDR、软件 x264 回退通过；80 ms 人工慢发送下出现原始帧跳过，
  仍发送有效 H.264 及请求的 IDR，关闭可完成。
- 离屏 Xephyr 复现 XShm BadMatch：无保护版本退出/超时，有保护版本恢复并继续发送，
  竖向 `240×320` 与横向 `320×240` 的 GPU 缩放均正确。没有用真实主屏强制镜像复现崩溃。
- 真机 USB 镜像→右侧扩展→镜像→左侧扩展，物理主屏模式、方向和主屏身份保持不变；
  正常退出与强制结束串流进程后副屏被回收，桌面原点恢复。
- 左侧扩展在真实 Xorg 中按横屏→竖屏→横屏重排，主屏原点依次为 2224→1668→2224，
  没有重叠，退出恢复为 0。用户随后确认新版 Wi-Fi 的画面和 iPad 横竖旋转均正常。
- GTK 的隐藏与托盘退出路径在扩展、镜像中均完成回收；未连接的隐藏界面 25 秒测得
  CPU 0.0%、RSS 约 61 MiB、PSS 约 31 MiB，未导入 GStreamer，没有串流工作进程。
- `.deb` 构建、源码一致性、桌面入口和 CLI 检查通过。Windows 实机由前轮验证，
  本轮保留 Windows CI，未在这台 Ubuntu 机器宣称复测 Windows 硬件。

单元检查：`./test.sh --unit-only`。显式实机检查使用与启动器一致的环境：

```bash
export PYTHONPATH="$PWD:$PWD/vendor/opendisplay-x11:$PWD/runtime/usr/lib/python3/dist-packages"
export LD_LIBRARY_PATH="$PWD/runtime/usr/lib/x86_64-linux-gnu${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export GST_PLUGIN_PATH="$PWD/gst-plugins${GST_PLUGIN_PATH:+:$GST_PLUGIN_PATH}"
export GI_TYPELIB_PATH="$PWD/runtime/usr/lib/x86_64-linux-gnu/girepository-1.0${GI_TYPELIB_PATH:+:$GI_TYPELIB_PATH}"
/usr/bin/python3 tests/smoke_capture.py --slow-send
/usr/bin/python3 tests/smoke_capture.py --encoder x264enc
/usr/bin/python3 tests/isolated_capture.py
```

性能测试需事先连接扩展屏：

```bash
./padbridge start --transport usb --display-mode extend --resolution native --fps 60 --bitrate 24
/usr/bin/python3 tests/benchmark_stream.py --output validation/usb.json --duration 185
./padbridge stop
```

画布只显示在已就绪的非主屏中；不保存屏幕像素。原始状态/设备日志仅保留在本机忽略的
`validation/` 中，不随源码或安装包上传。上游改动记录在 `vendor/opendisplay-x11.patch`。
