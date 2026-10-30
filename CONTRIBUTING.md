# 开发说明

当前开发与发布目标是 Ubuntu 24.04 amd64，桌面运行需要 Xorg。
Windows 版本尚未实现。

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

## 构建与发布

```bash
python3 packaging/build_deb.py
python3 packaging/build_release.py
```

完整发布包必须从干净的 Git 提交构建。输出在 `dist/`：`.deb`、对应提交的源码
压缩包和 `SHA256SUMS`。`SOURCE_DATE_EPOCH` 默认使用提交时间，以便重复构建。

版本号位于 `padbridge_app/__init__.py`，发布说明位于 `docs/releases/v<版本>.md`。
推送与版本号一致的 `v<版本>` 标签后，GitHub Actions 先测试、构建和检查包，
再创建 GitHub Release 并附上产物。日常分支与 PR 运行相同的无设备测试和构建检查。

## 代码边界

- 界面通过 `service.py` 控制工作进程，不直接操作显示接口。
- 镜像适配器只读取物理屏幕，扩展适配器只管理自己创建的虚拟输出。
- 只有开始连接才初始化采集、转换与编码。
- 退出、断线、布局变化应回收各自持有的资源。
- 上游修改保留来源及许可证，更新 `vendor/opendisplay-x11.patch`。
- 不提交设备标识、真实地址、屏幕截图、日志、缓存或本机解压的运行库。

提交前运行与改动对应的检查；修改显示或生命周期逻辑还需要实机验证。
