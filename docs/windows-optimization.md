# Windows 0.3.0 适配与优化记录

整理日期：2026-10-31。基线为 Ubuntu 0.2.0（`4f9f9fb`），本轮开发分支为
`feature/windows11`。本文记录已经实现的行为、如何实现和验证范围；两端成果现已共同纳入 v0.3.0，
后续 Linux 实现见 [Linux 优化记录](linux-optimization.md)。

## 完成了什么，怎么实现

| 问题或需求 | 实现方式 | 主要代码 |
| --- | --- | --- |
| Linux 工程不能直接在 Windows 启动 | 公共入口按平台延迟导入；Windows 使用独立后台进程、原子状态文件和进程身份核验，替代 systemd；配置放入 AppData | `cli.py`、`paths.py`、`windows/service.py`、`windows/storage.py` |
| Windows 界面与 Ubuntu 差异较大 | 用 Qt 重现侧栏、连接/画面/关于三页、卡片和配色；连接任务在后台执行，错误保留在状态卡；关闭窗口进入托盘 | `windows/ui.py`、`windows/widgets.py`、`windows/styles.qss` |
| 系统识别 iPad，但 USB 串流不可用 | 连接 Apple Mobile Device Service 的 usbmux TCP 接口；明确区分 MTP 设备识别与可用的 USB 通信服务，补充诊断提示 | `windows/transport.py`、`windows/service.py` |
| Wi-Fi 发现或连接失败 | Windows 用 zeroconf 实现 Bonjour；支持手填地址，保留握手校验；提示排查单播可达性和 iPad 重新入网 | `windows/transport.py`、`network.py` |
| Windows 无法直接创建扩展屏 | 显式安装固定版本、校验摘要及签名的虚拟显示驱动；通过 Windows 显示配置 API 分离复制路径，匹配 iPad 尺寸 | `windows/driver_setup.py`、`windows/display_config.py`、`windows/virtual_display.py` |
| 未连接时系统仍显示两个屏幕 | 只在收到接收端握手后启用本程序拥有的设备；断线、退出和异常恢复时收回，开机清理异常关机遗留设备；固定权限辅助任务负责启停 | `windows/device_control.py`、`windows/display_control.ps1`、`windows/virtual_display.py` |
| 扩展页的屏幕来源选项多余 | GUI 扩展模式直接管理 iPad 副屏；已有副屏选择保留为命令行 `--monitor` | `windows/widgets.py`、`windows/ui.py` |
| 希望默认把副屏放左边或右边 | 保存 `display_position`；新连接按所选方向放在桌面外沿并与主屏顶部对齐，避免多屏重叠；当前连接中保留手动排列，重连再应用默认位置 | `preferences.py`、`windows/virtual_display.py` |
| 镜像切换到扩展必定出现黑边 | 新比例的视频配置和首帧先到达接收端，再仅重建一次视频连接；保留虚拟副屏和窗口位置，以兼容接收端残留的旧比例状态 | `windows/receiver_layout.py`、`windows/worker.py` |
| 原生分辨率下有周期性清晰度跳动 | NVENC 改用逐步帧内刷新，码率预算从一帧扩大到四帧；仍关闭 B 帧、前瞻及编码输出等待，接收端请求仍触发完整 IDR | `windows/encoding.py` |
| 逐帧 CPU 处理开销较高 | WGC 获取 BGRA 最新帧；PyAV 引用 NumPy 缓冲，NVENC 接收 BGRA 并在 GPU 完成颜色转换；保留 NVENC YUV 和 x264 兼容回退 | `windows/desktop.py`、`windows/encoding.py` |
| TCP 发送等待拖慢采集和编码 | 独立发送线程，最多两个视频帧占位；先申请占位再采集，避免拥堵时积累旧画面；视频与控制消息有序发送，保持 H.264 参考帧完整 | `windows/stream_sender.py`、`windows/worker.py` |
| 重连后帧率明显下降 | 每次采集会话重新枚举 DXGI 设备和输出，按唯一显示器名称匹配；避免 DXcam 全局缓存仍引用已销毁副屏，从而退回 GDI | `windows/desktop.py` |
| 平均 FPS 看起来正常但仍有卡顿 | 统计最近两秒发送帧率和帧间隔，增加采集、编码、发送及发送排队的平均/P95 耗时，并保留接收端上报统计 | `windows/stream_sender.py`、`windows/worker.py` |

表中的代码路径相对于 `padbridge_app/`。采集、编码、虚拟屏和 UI 的 Windows 实现均位于
`windows/`；固定版本的上游 `vendor/opendisplay-x11/` 在本轮没有改动。

## 帧率优化的边界

Windows 当前持续按目标帧率采集发送，没有按静止画面主动降帧的策略。
曾观察到静止画面时 NVIDIA GPU 降频，编码超过 60 FPS 的每帧 16.7 ms 预算。
本机在用户切换独显直连后，另外为实际运行的 `PadBridge.exe` 设置了应用专用的
“最高性能优先”，静止和活动画面的编码耗时才稳定下来。

这是显卡驱动的本机设置，按 EXE 路径生效，不是源码或便携包自带功能；换路径或电脑后
需要重新核验。应用专用设置与撤销方式见 [Windows 指南](windows.md#连接问题定位)。
源码开发时的 Python 进程也不会自动继承这个 EXE 的驱动配置。

发送线程有界并不意味着无线链路能保证 60 FPS。TCP 遇到重传或无线停顿仍会阻塞，
保留参考帧也意味着不能随意丢掉已经编码的 P 帧。
“自动码率”目前是按传输方式选择固定值：USB 24 Mbps、Wi-Fi 10 Mbps，尚未实现动态码率。
VBV 的四帧预算用于码率控制，不代表等待四帧后才输出视频。

## 本机实测结果

以下是同一台 Windows 11 NVIDIA 笔记本与同一台 iPad 的短时记录，iPad 原生
2224 × 1668、目标 60 FPS、NVENC P4/BGRA、WGC。USB 测试使用独显直连及上述应用专用
驱动设置；Wi-Fi 使用现有 2.4 GHz 802.11n 网络。这些数据不是其他硬件的性能保证。

每次约 189 秒，排除开始 5 秒，保留 185 次状态采样。发送 FPS 为相互重叠的两秒窗口，
表中的均值是这些采样窗口的平均值；接收端报告更新更慢，整数 FPS 不能表示完整的帧间隔分布。

| 场景 | 发送 FPS 均值 / 最低 | 最长观察帧间隔 | 平均编码耗时 | 结论 |
| --- | --- | --- | --- | --- |
| USB，自动 24 Mbps | 59.87 / 59.6 | 31.31 ms | 7.26 ms | 静止与活动阶段均接近目标，iPad 上报 59～60 FPS |
| Wi-Fi，自动 10 Mbps | 59.08 / 33.0 | 315.75 ms | 7.03 ms | 编码正常，但仍有传输停顿 |
| Wi-Fi，手动 6 Mbps | 59.60 / 46.5 | 212.39 ms | 6.96 ms | 本次短测有改善，不能视为消除了卡顿 |

后续恢复普通 6 Mbps 设置的约一分钟复测仍观察到约 1002 ms 的最长帧间隔。
所以不能把较低码率那一轮的结果解释为“Wi-Fi 已稳定锁定 60 FPS”。
临时尝试过 WLAN media streaming 模式和 DSCP 策略，未得到可靠改善，已撤销，未写入产品代码。
测试日志只保存在本机；仓库仅记录汇总，避免带入设备地址、标识和桌面内容。

## 验证范围

- 本轮功能完成后 Windows 测试为 **173 passed、11 subtests passed**，编码自检选中 `h264_nvenc`。
- 源码和便携包均通过原生虚拟屏回环测试：解码视频、断线回收、重连、停止后恢复主屏布局。
- 便携包左右布局各完成两次连接：左侧为 `(-2224, 0)`，右侧为 `(2560, 0)`；
  重连前后都使用 WGC，原有物理屏布局保持正常。这些坐标对应本次测试的屏幕尺寸。
- 镜像→扩展测试覆盖仅重建一次视频连接、保持同一副屏；真实 iPad 用户确认黑边消失。
- 真实 iPad 已验证 USB 镜像/扩展和 Wi-Fi 扩展的显示与操作。
- Ubuntu 和 Windows 的无设备测试、安装包检查由分支 CI 再次执行；每次提交结果以 Actions 为准。

后续仍需更多机器、长时间 Wi-Fi、弱信号、旋转和多 DPI 布局验证。
回环测试证明协议、解码和资源回收，不能代替真实 USB/Wi-Fi 链路测试。

## 后续优先项

1. Linux 先补齐同口径的阶段耗时、帧间隔和接收端统计，建立可比较的基线。
2. 依据测量减少 Linux GStreamer 颜色转换和排队成本，逐项验证，保持主屏保护和退出回收。
3. Wi-Fi 继续研究受拥堵约束的码率/分辨率调整；同时验证画质、恢复时间和参考帧连续性。
4. Linux 的副屏位置设置、会话比例兼容与 Windows 行为对齐前，先复现对应场景。
