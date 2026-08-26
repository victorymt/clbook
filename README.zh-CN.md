# book

[English](README.md)

`book` 用于将散落的学习文档整理为本地书籍，并在浏览器中阅读。添加文档时会归档副本，因此移动或删除原始文件后，已收集的内容仍可继续阅读。

## 安装

```bash
python -m pip install -e .
```

资料库默认位于 `$XDG_DATA_HOME/book`；若未配置 XDG，则位于 `~/.local/share/book`。可设置 `BOOK_DATA_DIR`，或在单次命令前添加 `--data-dir PATH`，将资料库放到其他位置。

## 创建书籍

```bash
book add "线性代数" --description "课程笔记与参考资料"
book doc add "线性代数" ~/notes/vectors.md
book doc add "线性代数" ~/downloads/matrices.html
book doc list "线性代数"
book doc move 2 1
```

添加文档会复制源文件，以及它引用的本地图片、样式表、字体和媒体资源。原始文件不会被修改或删除。

原始文档更新后，使用以下命令重新归档并更新搜索内容：

```bash
book doc refresh 1
```

## 阅读与搜索

```bash
book open "线性代数"
book serve --open
book search determinant --book "线性代数"
```

`book open` 会在 `127.0.0.1:8765` 启动本地服务并打开指定书籍；按下 `Ctrl-C` 可停止服务。阅读器提供章节目录、拖动排序、上一章和下一章、本地全文搜索、浅色和深色主题，以及阅读位置恢复。

端口被占用时，可以指定其他端口：

```bash
book open "线性代数" --port 8989
```

## 安全与归档

HTML 文档会在隔离页面中保留归档后的样式。脚本、表单、插件和远程资源的自动加载会被阻止；已归档的本地资源仍可正常使用。

删除书籍或文档只会删除 `book` 创建的归档副本，不会删除原始文件。
