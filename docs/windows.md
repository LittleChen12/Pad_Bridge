# Windows 11 使用与开发

0.3.2 把 Windows 11 x64 主程序、USB 通信与扩展屏幕组件整合进一个安装流程。

## 启动

推荐下载 `padbridge-0.3.2-windows-x64-setup.exe`，双击打开简体中文/英文安装向导。
默认安装到 `%LOCALAPPDATA%\Programs\PadBridge`，自动创建开始菜单入口，桌面快捷方式可选。
Python、Qt、编码库和签名虚拟显示驱动已经包含在安装包中。
向导自动检查 USB 与扩展组件；缺少 USB 支持时自动从 Apple 官方下载并安装通信组件（约 39 MB）。
无需另外寻找安装包或运行命令，不依赖 WinGet、Microsoft Store 或 iTunes。
首次补齐系统组件需联网并允许管理员确认，Windows 可能另行要求确认驱动发布者。
已有可用组件直接复用，单独更新主程序无需管理员权限。
组件准备失败时，向导会显示错误并提供重试；需要重启时会提示，不强制重启。

新版安装包会沿用原安装目录，保留 AppData 中的连接、画面和副屏位置设置。
更新或卸载前请从托盘或窗口菜单选择“退出 PadBridge”，关闭窗口的 × 只会隐藏到托盘。
界面或后台工作进程仍运行时，安装器会要求先退出，避免覆盖正在使用的文件。
可从 Windows“设置 → 应用 → 已安装的应用 → PadBridge”卸载；卸载保留用户设置和用户自行添加的文件。
Apple 通信组件、虚拟显示驱动以及显卡程序配置属于单独管理的组件，不随主应用卸载。

便携使用可下载 `padbridge-0.3.2-windows-x64.zip`，适合已经配置组件的电脑。
完整解压后双击 `PadBridge/PadBridge.exe`，保留同目录 `_internal` 文件夹。
首次使用推荐 EXE；ZIP 用户可以直接改用安装版，设置继续共用；旧目录不会自动删除。
安装版程序位置与便携版不同，已有 NVIDIA 程序电源设置需指向新 EXE 路径。
应用安装器尚未做 Authenticode 代码签名，Windows 可能显示未知发布者；虚拟显示驱动有独立签名。

源码开发：安装 Python 3.12～3.14 x64，在项目目录运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\bootstrap.ps1
.\padbridge.cmd
```

也可传入 `bootstrap.ps1 -Python C:\路径\python.exe`；项目内已有
`runtime/python/python.exe` 时优先使用它。脚本只创建 `.venv` 并安装项目依赖，
不修改全局执行策略、不注册系统服务或启动项。

## 连接

1. iPad 打开 OpenDisplay。
2. 选择“镜像主屏”或“扩展屏幕”。安装版已经配置扩展组件；扩展模式会自动管理 iPad 副屏。
   “副屏位置”可选左侧或右侧，选择会保存并在下次连接时应用；旧配置默认右侧。
3. USB：连接数据线，在 iPad 上信任此电脑。安装版已经配置 Apple USB 通信服务。
4. Wi-Fi：设备在同一局域网，允许 OpenDisplay 本地网络权限；可搜索或填写 `IP:9000`。
5. 点击“连接 iPad”。修改参数前断开。

Windows USB 使用 Apple 本机 usbmux TCP 服务 `127.0.0.1:27015`；Wi-Fi 不依赖 Apple 软件。
若组件被外部卸载或服务异常，重新运行 PadBridge 安装器即可自动检测并尝试修复。
安装日志位于 `%LOCALAPPDATA%\PadBridge\setup-logs`，主安装日志位于用户临时目录。
便携 / 源码用户也可以使用安装器完成首次组件配置；界面的“安装扩展组件”保留为高级修复入口。

仅在设备管理器里看到 iPad（照片/MTP）不代表 USB 串流组件已经安装。
Bonjour 发现由 Python zeroconf 实现，不依赖 Avahi / D-Bus。网络阻止 mDNS 时可手动填写地址。
本机软件不自动修改 Windows 防火墙规则。

## 功能范围

| 功能 | Windows 0.3.2 |
| --- | --- |
| 主屏镜像 | 支持，不修改分辨率/布局 |
| 已有扩展桌面 | 命令行通过 `--monitor` 选择已启用的非主屏，含可被 GDI 采集的虚拟屏 |
| 无副屏时自动创建扩展屏 | EXE 自动配置签名扩展组件；按 iPad 原生尺寸选择模式，断开后从系统显示列表移除 |
| USB / Wi-Fi / 重连 | 协议及重连已测试；USB 镜像/扩展、Wi-Fi 原生扩展已实机验证 |
| H.264 | 优先实际探测 NVENC，不可用时回退 libx264；禁用 B 帧、前瞻和额外输出等待帧 |
| 高 DPI / 负坐标副屏 | 使用物理像素，采集区域与编码缩放分离 |
| 鼠标与触控 | 视频内含真实光标；支持点击、拖动、长按右键和滚动 |
| 界面 | 延续 Ubuntu 的侧栏、连接/画面/关于三页、卡片与紫色配色，由 Qt 实现 |
| 托盘 | × 隐藏；托盘恢复、断开、退出；无托盘时保留窗口并提示菜单退出 |

扩展组件使用 [VirtualDrivers Virtual Display Driver 25.7.23](https://github.com/VirtualDrivers/Virtual-Display-Driver/releases/tag/25.7.23)
的 x64 驱动包，随 Windows 包内置，安装时固定 SHA-256 并校验 Authenticode 签名。
源码运行且未打包时，显式安装命令仍可从同一固定官方地址下载。
首次安装需要管理员权限及 Windows 发布者确认，不导入证书或修改签名策略。
安装时配置 `\PadBridgeDisplayControl\Enable`、`Disable` 两个专用计划任务，
只启停本程序安装并记录的 `Root\MttVDD` 设备；每次操作重新校验设备实例与硬件标识。
辅助脚本和设备记录存放在 `%ProgramFiles%\PadBridge\DisplayControl`，仅管理员和 SYSTEM 可写，
普通权限的 PadBridge 可运行这两个固定任务，日常连接无需再次提权。任务不执行项目目录中的代码。
已有旧版扩展组件需以管理员身份重新点击一次“安装扩展组件”，更新启停功能，无需重装驱动。
程序通过 Windows 显示配置 API 将虚拟目标从默认复制状态拆分为独立副屏，保留物理屏模式。
新建副屏按所选方向放在电脑桌面左侧或右侧，与主屏顶部对齐；已有多屏时放在对应侧外沿，避免重叠。
连接期间通过“排列屏幕”手动调整的位置会保留；断开重建时再应用保存的默认位置。
空闲时停用虚拟显示设备，使其从 Windows“系统 → 屏幕”列表消失；收到 iPad 握手后再启用。
主动断开、USB/Wi-Fi 连接中断和退出会移除副屏；重连时重新创建。停用状态跨重启保留，
开机任务也会清理上一次异常关机遗留的虚拟设备。
使用已有副屏时只采集，不修改其模式或在断开时停用。自行改为主屏的虚拟屏也会保留。
虚拟屏创建记录写入本程序状态目录；进程被强制结束后，下次打开界面、启动连接或运行 `stop` 会回收对应副屏。
驱动文件和屏幕模式列表位于 `%ProgramData%\PadBridge\VirtualDisplayDriver`。
首次安装提供常见 iPad 横竖屏和视频预设尺寸；自定义尺寸未包含时选择最接近的同宽高比模式。
其他虚拟显示软件已有的驱动配置不会被覆盖；可通过命令行 `--monitor` 选择对应副屏。
移除扩展组件时，先断开 PadBridge，再在设备管理器卸载 **Virtual Display Driver**。
同时可在任务计划程序中删除 `PadBridgeDisplayControl` 文件夹下的两个任务。
Windows 虚拟显示的驱动接口参见 [Microsoft IDD 文档](https://learn.microsoft.com/en-us/windows-hardware/drivers/display/indirect-display-driver-model-overview)。

优先使用 Windows Graphics Capture（含光标），仅处理最新帧；接口不可用时回退 GDI。
每次建立采集会话时重新枚举图形适配器和显示输出，避免断线重建虚拟屏后使用旧设备列表而退回慢速采集。
采集的 BGRA 缓冲直接交给 NVENC，由 GPU 转换为接收端兼容的 H.264 4:2:0，
减少逐帧 CPU 复制和颜色转换；不支持该输入格式时先回退 NVENC 的 YUV 路径，再尝试 x264。
NVENC 使用 P4、逐步帧内刷新和四帧码率预算，避免原生分辨率下周期性关键帧画质跳动。
码率预算不增加排队帧：B 帧、前瞻及编码输出等待均关闭；接收端请求仍触发完整 IDR。
采集/编码与 TCP 发送分线程执行，最多一帧正在发送、一帧正在处理或等待。
发送拥堵时先等待再采集，避免积累旧画面；视频和控制消息保持顺序，不丢弃正在使用的 H.264 参考帧。
镜像切换到扩展等明显比例变化时，先让接收端识别新尺寸，再自动重建一次视频连接，
兼容旧版 iPad 接收端保留上一画面比例的问题。这个过程保留 Windows 副屏和窗口位置，
同一比例下的正常连接不重复执行，也不需要手动再断开一次。
采集当前交互桌面；锁屏、安全桌面、受保护视频及某些远程/虚拟显示驱动可能无法采集。
触控不能控制高于 PadBridge 权限等级的窗口。缩放及兼容编码路径仍使用 CPU；
15～60 FPS 是目标值，高分辨率性能取决于机器。音频、剪贴板、键盘输入、Pencil 压感尚未实现。
OpenDisplay TCP 协议没有加密或认证，只用于可信局域网。

## 命令与数据

```powershell
.\padbridge.cmd doctor
.\padbridge.cmd monitors
.\padbridge.cmd discover
.\padbridge.cmd encoder-test
.\padbridge.cmd install-display-driver --interactive
.\padbridge.cmd start --display-mode mirror --transport wifi --address 192.168.1.20 --resolution 1920x1080 --fps 30
.\padbridge.cmd start --display-mode extend --monitor '\\.\DISPLAY2' --transport usb
.\padbridge.cmd start --display-mode extend --monitor auto --transport usb --display-position left
.\padbridge.cmd status
.\padbridge.cmd stop
```

便携包可将 `.\padbridge.cmd` 替换为 `.\PadBridge.exe`；安装版在其安装目录中使用同样命令。
`run` 为前台调试命令，Ctrl+C 停止；
`start` 创建独立后台进程。仅连接时初始化采集和编码。停止使用每次运行的唯一标识、进程
创建时间及命令行核验，避免误结束复用旧 PID 的其他进程。

- 设置：`%APPDATA%\PadBridge\connection.json`，UTF-8 原子写入。
- 状态与锁：`%LOCALAPPDATA%\PadBridge\runtime\`。
- 轮转日志：`%LOCALAPPDATA%\PadBridge\padbridge.log`，每份 2 MiB，最多保留两个备份。
- 控制器启动/连接错误：同目录 `controller.log`；错误也会保留在连接页状态卡中。
- 不将本机设置、地址、日志、截图或运行库提交到仓库。

## 测试与构建

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-windows-dev.txt
powershell -NoProfile -ExecutionPolicy Bypass -File .\test.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\test.ps1 -Smoke
powershell -NoProfile -ExecutionPolicy Bypass -File .\packaging\bootstrap_inno.ps1
.\.venv\Scripts\python.exe packaging\build_windows.py
.\.venv\Scripts\python.exe tests\windows\smoke_installer.py
.\.venv\Scripts\python.exe tests\windows\smoke_stream.py --executable dist\PadBridge\PadBridge.exe
.\.venv\Scripts\python.exe tests\windows\smoke_stream.py --virtual --executable dist\PadBridge\PadBridge.exe
.\.venv\Scripts\python.exe tests\windows\smoke_stream.py --virtual --require-graphics --executable dist\PadBridge\PadBridge.exe
.\.venv\Scripts\python.exe tests\windows\smoke_stream.py --virtual --require-graphics --display-position left --executable dist\PadBridge\PadBridge.exe
.\.venv\Scripts\python.exe tests\windows\smoke_modes.py --executable dist\PadBridge\PadBridge.exe
```

`-Smoke` 显式采集当前桌面到本地回环模拟接收端，解码后检查尺寸、关键帧、重连、停止和
显示布局；不保存截图、不向外部设备发送画面，使用临时用户配置目录。
无桌面 CI 执行协议、Windows 后端单元测试及编码自检，不执行桌面 smoke。
`--virtual` 额外要求扩展组件已安装且处于空闲状态，会真实创建副屏，验证原生尺寸解码、
掉线期间从 Windows 显示目标列表移除、重连再次创建及最终恢复主屏布局。
`--require-graphics` 额外验证断线重连前后都保持 Windows Graphics Capture，用于排查重连后的帧率回退。
`--display-position left` 验证左侧负坐标、重连后位置和物理屏布局；省略时验证默认右侧。
`smoke_modes.py` 验证镜像到原生扩展的尺寸切换、仅执行一次比例同步，以及同步期间保持同一副屏。

构建输出为 `dist/PadBridge/PadBridge.exe`、Windows ZIP、`*-windows-x64-setup.exe` 和
包含 ZIP/安装器校验值的 `SHA256SUMS-windows`。安装器使用固定的 Inno Setup 7.1.1，
引导脚本核对官方文件的 SHA-256 与签名后，仅在项目 `.cache` 中以便携模式解包编译器。
包中包含构建使用的项目源码 `source.zip`、依赖版本、许可证和应用图标；源码只收集 Git 跟踪文件。
本地构建前先 `git add` 新增源码；正式发布仍须从干净提交构建。Windows Actions 上传两个发行产物。

`smoke_installer.py` 会在临时目录中实际安装旧版本号的测试包，再运行当前安装器升级，
检查应用登记、中文路径、开始菜单、已运行进程保护、编码自检、卸载和用户文件保留。
使用当前用户的卸载登记，因此检测到已经安装 PadBridge 时会拒绝执行，应改用干净测试账户。
测试不会自动启动桌面串流；普通用户安装时无需运行这些开发测试。

已实机验证 USB 镜像、USB/Wi-Fi 原生尺寸扩展串流、Wi-Fi 端正常显示和操作，
以及断开后收回副屏、保留主屏布局。
实机验收仍需：更多 USB 拔线场景、Wi-Fi 长时间/弱信号/旋转场景、多 DPI 布局变化。
自动化回环测试通过不等同于这些设备场景已通过。

## 连接问题定位

- **USB 系统能看到 iPad，但 PadBridge 无法连接**：可重新运行安装器检查 / 修复 Apple 通信服务；
  MTP/照片设备识别不等同于 OpenDisplay 所需的 usbmux 接口已可用。
- **Wi-Fi 能搜索到，但连接超时**：mDNS 广播可达不保证 TCP 单播可达。用
  `Test-NetConnection <iPad-IP> -Port 9000` 检查；若系统也失败，应检查来宾网络、AP 客户端隔离、
  设备地址及 VPN/路由。保持 OpenDisplay 前台运行。PadBridge 不自动更改防火墙或路由器设置。
  若地址正确、邻居解析和 TCP 都失败，先在 iPad“设置 → Wi-Fi”关闭再打开 Wi-Fi，
  重新连接同一个网络，然后返回 OpenDisplay。实机曾出现广播可达、单播不可达，重新入网后恢复；
  这说明连接状态可能异常，不能仅凭此现象断定路由器开启了 AP 隔离。
- **延迟**：`status` 显示实际帧率、采集后端、采集/编码/发送平均耗时和接收端统计。
  实际发送帧率采用最近两秒窗口，排除启动耗时；`send_queue` 是编码后等待发送的平均毫秒数。
  `capture_p95` / `encode_p95` / `send_p95` / `send_queue_p95` 显示最近采样中 95% 的耗时上限；
  `frame_interval_p95` 和 `frame_interval_max` 显示最近两秒实际发帧间隔，便于发现平均值掩盖的卡顿。
  接收端延迟是软件上报值，不能替代相机测量的物理端到端延迟。
- **Wi-Fi 大部分时间接近 60 FPS，但偶发卡顿**：如果采集、编码耗时保持正常，而 `send`、
  `send_queue` 或最长帧间隔同时升高，应继续检查传输链路。当前“自动”选择 Wi-Fi 10 Mbps / USB 24 Mbps，
  尚未根据网络状况动态调整码率。可用相同分辨率、帧率和测试画面对比 Wi-Fi 6 Mbps；
  较低码率会减少运动细节，也不能保证消除无线延迟尖峰。应同时观察 iPad 上报帧率和帧间隔，
  不能只凭电脑端平均帧率判断是否流畅。
- **静止时约 50 FPS、活动时接近 60 FPS**：Windows 发送端当前没有按画面静止主动降帧的策略。
  若采集和 USB 发送很快，但编码随 NVIDIA GPU 进入低功耗状态而超过 16.7 ms，
  可在 NVIDIA 控制面板的“管理 3D 设置 → 程序设置”中选择实际运行的 `PadBridge.exe`，
  将该程序的“电源管理模式”设为“最高性能优先”，重新启动 PadBridge 后再对照测试。
  这是应用程序专用的驱动设置，不属于 ZIP 内的配置；移动 EXE 或换电脑后需要重新选择对应路径。
  它会增加串流期间的显卡功耗。恢复该程序的默认电源管理设置即可撤销。
  用 `nvidia-smi` 的频率、功耗及上述耗时确认原因，不要仅凭 59/60 的整数显示判断丢帧。
