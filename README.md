# CourseRun

一个纯 GUI 的跨平台 BrowserSkill 课程自动播放器，使用 Python 3 + Tkinter 开发。

程序会自动识别 Windows、macOS、Linux，并选择对应的后台进程、浏览器激活、`bsk` 查找和数据目录逻辑。

## 界面功能

- 开始播放
- 暂停 / 继续
- 上一视频
- 下一视频
- 停止
- 环境检测
- 打开日志目录
- 实时状态、播放进度、视频序号和日志

快捷键：

- `←`：上一视频
- `→`：下一视频
- `Space`：暂停 / 继续
- `Ctrl+Enter`：开始播放

## 实时响应机制

GUI 内置单进程控制器，所有 BrowserSkill 操作在同一个线程中串行执行：

- 按钮点击后立即进入命令队列
- 不会与后台 Worker 抢占 BrowserSkill 会话
- 播放状态约每 `0.8` 秒检查一次
- 视频暂停后自动恢复
- 自动结束切换下一节
- 自动识别“已学完 / 已完成播放 / 已完成”的视频并跳过
- 记住上次课程、视频和时间
- 重新打开后自动恢复最新播放进度
- 多次恢复失败时自动尝试重载页面
- 自动关闭已知课程提示弹窗
- 浏览器窗口最小化或播放进度停滞时自动尝试恢复
- 本地进度与平台进度取较新位置，避免重新打开后倒退

## 环境要求

1. Python 3.10 或更高版本。
2. 已安装 BrowserSkill `bsk` CLI。
3. Edge 或 Chrome 已安装 BrowserSkill 扩展并保持连接。
4. 浏览器已登录课程平台。

安装 `bsk`：

Windows PowerShell：

```powershell
irm https://raw.githubusercontent.com/Tencent/BrowserSkill/main/install.ps1 | iex
```

macOS / Linux：

```bash
curl -fsSL https://raw.githubusercontent.com/Tencent/BrowserSkill/main/install.sh | sh
```

### Windows 网络排查

如果 `raw.githubusercontent.com` 无法访问，可使用项目提供的备用安装脚本，它会尝试 GitHub 官方 Release 和镜像，并校验官方 SHA256：

```powershell
.\scripts\install_bsk_windows.ps1
```

也可以手动下载官方 Windows x64 包：

`https://github.com/Tencent/BrowserSkill/releases/download/cli-v0.3.0/bsk-v0.3.0-x86_64-pc-windows-msvc.zip`

校验值：

```text
CD31665559D0FAAE2CFB79AB1C3CB6854BCE10B4FDE510BE015456E8370F629E
```

## 开发运行

macOS / Linux：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/python -m course_run.gui_main
```

Windows PowerShell：

```powershell
py -m venv .venv
.venv\Scripts\python -m pip install -e .
.venv\Scripts\python -m course_run.gui_main
```

## 打包

PyInstaller 需要在目标系统上执行。

macOS：

```bash
./scripts/build_macos.sh
```

Linux：

```bash
./scripts/build_linux.sh
```

Windows PowerShell：

```powershell
.\scripts\build_windows.ps1
```

默认只生成 GUI：

- macOS：`dist/CourseRun.app`
- Windows：`dist/CourseRun.exe`
- Linux：`dist/CourseRun`

## CI/CD

GitHub Actions 工作流位于 `.github/workflows/build.yml`。

- 推送 `main`：运行测试并构建 Windows x64 / macOS ARM64 制品，发布滚动 `nightly` 预发布。
- 推送 `v*` 标签：构建并创建正式 GitHub Release。
- Pull Request：运行测试和双平台构建，不发布 Release。
- 手动触发：可在 Actions 页面执行。

发布产物：

- `CourseRun.exe`：Windows x86_64 单文件程序
- `CourseRun-macOS-arm64.dmg`：macOS Apple Silicon 安装镜像

## 数据目录

- Windows：`%LOCALAPPDATA%\CourseRun`
- macOS：`~/Library/Application Support/CourseRun`
- Linux：`${XDG_DATA_HOME:-~/.local/share}/course-run`

可通过环境变量覆盖：

```bash
export COURSE_RUN_DATA_DIR=/path/to/data
```

## 测试

```bash
.venv/bin/python -m unittest discover -s tests -v
```

## 项目结构

```text
course-run/
├── src/course_run/
│   ├── gui.py                 # GUI 界面
│   ├── controller.py          # 实时串行浏览器控制器
│   ├── bsk.py                 # BrowserSkill CLI 封装
│   ├── expression.py          # 播放、上一节、下一节脚本
│   ├── config.py              # 配置与路径
│   └── platform_adapter.py    # 系统自动识别与平台差异处理
├── tests/                     # 单元测试
├── scripts/                   # 各平台打包脚本
└── build.py                   # PyInstaller 构建入口
```

## 注意

- 手动切换会跳过视频，平台可能不把被跳过的视频计入完成时长。
- 登录失效、验证码或未知人工确认弹窗仍需要用户处理。
- 建议最小化 CourseRun 窗口，而不要最小化 Edge Agent Window。
- 即使 Edge 被最小化，开启“浏览器最小化时自动恢复”后程序会尝试重新激活窗口并恢复播放。
- 需要保持电脑唤醒、浏览器打开且 BrowserSkill 扩展到在线状态。
- 本地记录和平台进度会取较新的有效位置；如果平台判定某个视频尚未完成，平台可能优先返回该视频继续播放。
