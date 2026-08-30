# book

[English](README.md)

`book` 用于将散落的学习文档整理为本地书籍，并在浏览器中阅读。添加文档时会归档副本，因此移动或删除原始文件后，已收集的内容仍可继续阅读。

## 环境要求

Python 3.10 或更高版本。运行时只使用 Python 标准库。推荐使用
[uv](https://docs.astral.sh/uv/) 安装。

## 安装

在项目目录中将 `book` 安装为独立的命令行工具：

```bash
uv tool install .
```

安装后可运行 `book --help` 检查命令是否可用。项目代码更新后，可使用
`uv tool install --force .` 重新安装。

也可以使用 pip 将其安装到当前 Python 环境：

```bash
python -m pip install .
```

资料库默认位于 `$XDG_DATA_HOME/book`；若未配置 XDG，则位于 `~/.local/share/book`。可设置 `BOOK_DATA_DIR`，或在单次命令前添加 `--data-dir PATH`，将资料库放到其他位置。

创建新的资料库目录时，可以先显式初始化：

```bash
book init
```

## 创建书籍

```bash
book add "线性代数" --description "课程笔记与参考资料"
book doc add "线性代数" ~/notes/vectors.md
book doc add "线性代数" ~/downloads/matrices.html
book doc list "线性代数"
book doc move 2 1
book doc add "线性代数" ~/notes --recursive
book edit "线性代数" --description "更新后的参考资料"
```

导入器支持 HTML（`.html`/`.htm`）、Markdown（`.md`/`.markdown`）和纯文本（`.txt`）。其他扩展名会按文本导入。

添加文档会复制源文件，以及它引用的本地图片、样式表、字体和媒体资源。原始文件不会被修改或删除。

原始文档更新后，使用以下命令重新归档并更新搜索内容：

```bash
book doc refresh 1
book doc rename 1 "向量与矩阵"
```

## 阅读与搜索

```bash
book open "线性代数"
book serve --open
book search determinant --book "线性代数"
```

`book open` 会在 `127.0.0.1:8765` 启动本地服务并打开指定书籍；按下 `Ctrl-C` 可停止服务。阅读器提供章节目录、拖动排序、上一章和下一章、本地全文搜索、浅色和深色主题，以及阅读位置恢复。

主题选择会应用于 Markdown/文本页面，也会注入到归档的 HTML 页面中。

阅读器支持常见的 Markdown 表格、嵌套列表、任务列表、删除线和引用式链接。同一本书中的文档链接会路由到对应章节。

`book serve` 用于打开书架；添加 `--open` 可自动启动默认浏览器。`book open BOOK` 可以直接打开指定书籍。

端口被占用时，可以指定其他端口：

```bash
book open "线性代数" --port 8989
```

## 安全与归档

HTML 文档会在隔离页面中保留归档后的样式。脚本、表单、插件和远程资源的自动加载会被阻止；已归档的本地资源仍可正常使用。

可以使用 `book export PATH` 创建可迁移的 ZIP 备份，再用 `book restore PATH` 恢复。只有在明确要覆盖现有资料库时才使用 `--replace`。

出于安全考虑，只会归档源文件所在目录树内的资源；指向目录树外的引用会保持原样，不会被复制。

删除书籍或文档只会删除 `book` 创建的归档副本，不会删除原始文件。

## 开发

项目使用 `uv` 管理开发依赖和运行测试：

```bash
uv sync
uv run pytest -q
uv build
```
