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

`book doc add` 一次可以接收多个文件和目录。默认只扫描目录的第一层；添加 `--recursive` 可包含嵌套文件。导入单个文件时可以使用 `--title`。如果文档需要引用共享父目录中的资源，可以用 `--resource-root` 指定允许的资源根目录：

```bash
book doc add "线性代数" ~/course/chapters/intro.html \
  --resource-root ~/course
```

多文件导入默认是原子的：如果其中一个源文件失败，同一命令此前已导入的文档会回滚。需要保留部分成功结果时可添加 `--continue-on-error`；命令仍会返回失败状态，并列出无法导入的文件。

导入器支持 HTML（`.html`/`.htm`）、Markdown（`.md`/`.markdown`）和纯文本（`.txt`）。文档引用 CSS、Web App Manifest、图片、字体或媒体时，这些资源会被复制并重写为本地资源。其他文档扩展名会按文本导入。

添加文档会复制源文件，以及它引用的本地图片、样式表、字体和媒体资源。原始文件不会被修改或删除。

原始文档更新后，使用以下命令重新归档并更新搜索内容：

```bash
book doc refresh 1
book doc rename 1 "向量与矩阵"
book doc info 1
```

`book doc info` 会显示源文件路径、归档位置，以及自上次导入后源文件是否发生变化。刷新会重新归档源文件和本地资源，但不会删除原始文件；初次导入时设置的 `--resource-root` 会自动复用。

## 阅读与搜索

```bash
book open "线性代数"
book serve --open
book search determinant --book "线性代数"
```

`book open` 会在 `127.0.0.1:8765` 启动本地服务并打开指定书籍；按下 `Ctrl-C` 可停止服务。阅读器提供章节目录、拖动排序、上一章和下一章、本地全文搜索、浅色和深色主题、阅读位置恢复，以及整本书平均进度。阅读器中还可以新建、编辑或删除书籍，重命名、刷新或删除章节；也可以在目录中勾选多个章节，通过批量操作下拉菜单一次刷新或删除。批量结果会返回请求数量、成功文档元数据，以及带错误详情的失败 ID；删除章节只会删除归档副本，不会触碰原始文件，并可通过浏览器历史返回书架。

主题选择会应用于 Markdown/文本页面，也会注入到归档的 HTML 页面中。

语言下拉菜单可在英文（`en`）和中文（`zh-CN`）界面之间切换，默认使用英文。选择结果会以 `localStorage` 的 `book.locale` 键保存在浏览器中，重新加载阅读器后会自动恢复；主题选项和其他界面文案会随语言切换。

阅读器支持常见的 Markdown 表格、嵌套列表、任务列表、删除线和引用式链接。搜索会在书名、章节标题和提取出的正文中进行不区分大小写的子串匹配；结果会分批加载，并明确提示是否还有更多匹配。同一本书中的文档链接会路由到对应章节内容。

本地服务在 `/api` 下提供 JSON 接口，可供书架集成使用。接口支持列出和搜索书籍、新建/编辑/删除书籍、导入或移除文档、刷新文档、调整章节顺序，以及保存阅读状态和进度。批量章节管理接口为 `POST /api/books/{book_id}/documents/batch`，请求体示例为 `{"action":"refresh","document_ids":[1,2]}`；将 `action` 设为 `delete` 即可删除选中章节的归档副本。响应包含 `action`、`requested`、`succeeded` 和 `failed` 字段，客户端可据此查看部分成功结果。文档导入接口接收本机文件路径，因此只应在可信机器上使用本地服务。

`book serve` 用于启动书架；添加 `--open` 可自动启动默认浏览器。`book open BOOK` 可以直接打开指定书籍。两个命令都只监听本机回环地址。

端口被占用时，可以指定其他端口：

```bash
book open "线性代数" --port 8989
book serve --port 8989
```

## 安全与归档

HTML 文档会在隔离页面中保留归档后的样式。脚本、表单、插件和远程资源的自动加载会被阻止；已归档的本地资源仍可正常使用。

可以使用 `book export PATH` 创建可迁移的 ZIP 备份，再用 `book restore PATH` 恢复。导出不会覆盖已有目标文件；恢复时如果目标资料库非空，必须显式使用 `--replace`。替换恢复会先暂存并原子切换，解压前还会校验 ZIP 中是否包含不安全路径。

出于安全考虑，只会归档源文件所在目录树内的资源；指向目录树外的引用会保持原样，不会被复制。

删除书籍或文档只会删除 `book` 创建的归档副本，不会删除原始文件。

## 开发

项目使用 `uv` 管理开发依赖和运行测试：

```bash
uv sync
uv run pytest -q
uv build
```

测试套件覆盖文档导入与刷新、资源清理、Markdown 渲染、搜索、阅读状态、管理 API，以及备份/恢复行为。
