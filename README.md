# CourseRun

一个使用 Python 3 + Tkinter 编写的跨平台 BrowserSkill 课程自动播放小程序。

程序会自动识别当前系统：

- Windows
- macOS
- Linux

然后选择对应的数据目录、后台进程启动方式、进程结束方式、浏览器打开方式和 `bsk` 查找路径。

## 功能

- 图形化桌面界面，无需命令行操作
- 自动调用本机 BrowserSkill `bsk`
- 创建独立 Agent Window 播放课程
- 自动展开多级课程目录
- 视频自然结束后切换下一节
- 自动恢复暂停视频
- 一键切换到下一个视频
- 自动处理“须学习完课程的视频才可获得学时”提示
- 后台进程与终端/界面分离
- 支持状态、进度和日志查看
- 支持 Windows、macOS、Linux
- 无第三方运行依赖，PyInstaller 仅用于打包

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

## 开发运行

```bash
cd /Users/lixinchen/PycharmProjects/course-run
python3 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/course-run
```

Windows PowerShell：

```powershell
py -m venv .venv
.venv\Scripts\python -m pip install -e .
.venv\Scripts\course-run.exe
```

不传参数时会直接打开 Tkinter 图形界面。

## 命令行

```bash
course-run gui
course-run start --url "https://example.com/course"
course-run status
course-run logs
course-run next
course-run stop
course-run doctor
course-run open-logs
```

## 数据目录

- Windows：`%LOCALAPPDATA%\CourseRun`
- macOS：`~/Library/Application Support/CourseRun`
- Linux：`${XDG_DATA_HOME:-~/.local/share}/course-run`

可通过环境变量覆盖：

```bash
export COURSE_RUN_DATA_DIR=/path/to/data
```

## 打包

PyInstaller 需要在目标系统上执行，通常不能在 macOS 上直接生成 Windows exe。

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

也可以直接运行：

```bash
python3 build.py
```

生成结果位于：

- `dist/CourseRun.app` 或 GUI 可执行文件
- `dist/course-run-cli` 或 `course-run-cli.exe`

## 测试

```bash
.venv/bin/python -m unittest discover -s tests -v
```

## 项目结构

```text
course-run/
├── src/course_run/
│   ├── cli.py                 # 命令行入口
│   ├── gui.py                 # Tkinter 图形界面
│   ├── manager.py             # 启动、停止、切下一节、状态管理
│   ├── worker.py              # 后台播放循环
│   ├── bsk.py                 # BrowserSkill CLI 封装
│   ├── expression.py          # 浏览器自动播放脚本
│   ├── config.py              # 配置、状态、日志路径
│   └── platform_adapter.py    # 系统识别与平台差异处理
├── tests/                     # 单元测试
├── scripts/                   # 各平台打包脚本
└── build.py                   # PyInstaller 构建入口
```

## 注意

- 课程平台最终是否记为“已完成”取决于平台自身规则。
- 登录失效、验证码、未知人工确认弹窗仍可能需要用户处理。
- 需要保持电脑唤醒、浏览器打开且 BrowserSkill 扩展在线。
