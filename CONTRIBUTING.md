# 开发说明

开发与发布目标为 Ubuntu 24.04 amd64 / Xorg，以及 Windows 11 x64。
Windows 环境、测试、安装器和便携构建见 [Windows 开发说明](docs/windows.md)。
下文命令用于 Ubuntu；Windows 平台实现集中在 `padbridge_app/windows/`，不得在公共入口导入 X11/GTK。
本轮实现与实测结论见 [Windows 优化记录](docs/windows-optimization.md) 和
[Linux 优化记录](docs/linux-optimization.md)。跨平台共享改动应同时检查两套测试。
代码分层与平台边界见 [架构说明](docs/architecture.md)。

## 获取源码

```bash
git clone https://github.com/LittleChen12/Pad_Bridge.git
cd Pad_Bridge
```

上游运行时代码已随仓库固定版本保存，无需初始化 Git 子模块。

## 测试与运行

只运行单元和协议测试所需的依赖：

```bash
sudo apt install python3-gi python3-xlib python3-pytest desktop-file-utils
./test.sh --unit-only
```

桌面运行依赖列在 `packaging/build_deb.py`。可以先构建并通过 apt 安装生成的
`.deb`，由 apt 补全依赖，再在源码目录运行 `./padbridge`。
`bootstrap.sh` 仅用于本地下载、解压部分缺失库，不是完整的系统安装器。

`./test.sh` 在单元测试后额外执行编码器自检，需要可工作的 GStreamer 环境。
`tests/smoke_capture.py` 和 `tests/isolated_capture.py` 是显式执行的实机测试；
后者需要 Xephyr，仅修改离屏测试显示器。普通 CI 不控制真实屏幕或连接 iPad。
`smoke_capture.py --slow-send` 验证发送阻塞时只跳过原始帧，仍能发送请求的 IDR；
`--encoder x264enc` 可明确测试软件回退。测试用的延迟不影响普通运行路径。

## 构建与发布

```bash
python3 packaging/build_deb.py
python3 packaging/build_release.py
```

完整发布包必须从干净的 Git 提交构建。输出在 `dist/`：`.deb`、对应提交的源码
压缩包和 `SHA256SUMS`。`SOURCE_DATE_EPOCH` 默认使用提交时间，以便重复构建。

版本号位于 `padbridge_app/__init__.py`，发布说明位于 `docs/releases/v<版本>.md`。
推送与版本号一致的 `v<版本>` 标签后，GitHub Actions 先测试、构建和检查包，
再创建 GitHub Release 并附上产物。`main`、`feature/**` 分支推送和 PR 都运行 Ubuntu/Windows
无设备测试与构建检查；分支推送只上传 CI 产物，不创建 Release。

正式发布时，先确认各功能分支的提交都包含在发布候选中，再合入 `main`。
在干净提交上构建、核对版本与发布说明，并确认 Ubuntu/Windows 检查通过。
先推送 `main`，再单独推送指向同一提交的附注版本标签；标签流程通过后会发布
`.deb`、Windows 安装 EXE/便携 ZIP、对应源码和两份 SHA-256 文件。
发布后从 Releases 下载产物核对校验值。已发布的标签和包不覆盖，有修正则递增版本。

Windows 构建先运行 `packaging/bootstrap_inno.ps1` 准备固定版本的便携编译器，再运行
`packaging/build_windows.py` 同时生成安装 EXE 和 ZIP。`packaging/windows.iss` 的 AppId
须跨版本保持不变，以便 Windows 正确识别升级和卸载；安装/卸载仅管理应用自己的文件。
更新 Windows 运行入口时保留 `windows/installation.py` 的进程存活标记，避免运行中覆盖文件。
0.3.2 的 EXE 默认通过 `windows/components.py` 检测并配置 USB 与扩展组件；
`driver_setup.py` 使用内置签名驱动，Apple USB MSI 仅在客户端缺少服务时从官方获取。
更新依赖版本时同时更新固定校验值和 `packaging/licenses/` 中的对应许可。
Windows 包中的 `source.zip` 从 Git 跟踪文件构建，本地新增文件需先 `git add`；
安装器在准备阶段验证组件，失败必须返回非零状态，不得跳过后宣布安装成功。

## 代码边界

- 界面通过 `service.py` 控制工作进程，不直接操作显示接口。
- 镜像适配器只读取物理屏幕，扩展适配器只管理自己创建的虚拟输出。
- 只有开始连接才初始化采集、转换与编码。
- 退出、断线、布局变化应回收各自持有的资源。
- 上游修改保留来源及许可证，更新 `vendor/opendisplay-x11.patch`。
- 不提交设备标识、真实地址、屏幕截图、日志、缓存或本机解压的运行库。
- `main` 仅保留当前运行代码、构建脚本、测试和有效文档；已完成的临时交接通过 Git 历史查阅。
- 上游快照仅保留被使用的模块；删减时核对导入关系，并在 `vendor/README.md` 记录范围。

提交前运行与改动对应的检查；修改显示或生命周期逻辑还需要实机验证。
