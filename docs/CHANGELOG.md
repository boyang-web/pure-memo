# 变更记录

本项目从 v1.0 开始记录版本变更，结构参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)。

## [Unreleased] — 2026-11-16

### 变更

- 仓库结构标准化：图标归档到 `assets/icons/`，图标生成脚本移至 `scripts/`，APK 移至 `release/`。
- 同步更新 `index.html`、`manifest.webmanifest`、`sw.js` 中的资源路径；Service Worker 缓存版本升至 `purememo-v2`。
- 新增 `README.md`、MIT `LICENSE`、`.gitignore`、`.gitattributes`、`.editorconfig`。
- 新增 `scripts/check_references.py` 与 GitHub Actions 校验工作流。
- 新增 `docs/DEVELOPMENT.md`，并将原有开发记录整理为本文档。

### 说明

- 应用功能与交互无变化。

## [v1.0] — 2026-11-07

### 新增

- 单页 PWA：原生 HTML / CSS / JavaScript，无框架、无构建步骤。
- 卡片看板：按「置顶 / 今天 / 昨天 / 日期」分组，支持最新/最早排序、双列/单列视图。
- 输入面板：启动或回到前台自动弹出并居中显示；输入实时保存草稿，切后台或退出时自动落成卡片。
- 卡片操作：置顶、编辑、复制、删除；删除后约 5 秒内可撤销。
- 就地浮层菜单：锚定卡片或顶栏按钮，无全屏遮罩；支持点击 ⋯ 与长按卡片唤出。
- 长期留存：三个独立分页的纯文本区，输入即存；卡片可转存到指定页；支持复制/清空当前页，转存可撤销。
- 深浅主题：默认跟随系统，可手动切换。
- PWA 能力：Web App Manifest、Service Worker 离线缓存、iOS/Android 添加到主屏幕。
- Android APK `PureMemo-v1.0.apk`：WebView 壳，包名 `com.baiyang.purememo`，minSdk 24 / targetSdk 35，自签名。

### 变更

- 输入面板从底部弹层改为屏幕中部居中显示。
- 大幅精简界面文案，操作按钮改为图标化。
- 移除备份导出/导入、复制备份、导出留存文本等功能；数据仅保存在本机 `localStorage`。
- 卡片菜单从全屏 sheet 改为就地 popover；顶栏菜单按当前面板动态生成。

### 修复

- 撤销回调被 `hideToast()` 提前清空，导致「撤销」失效。
- 切后台时只保存数据而未刷新看板 DOM，系统后台快照显示旧内容。
- 长按卡片后误触发卡片点击编辑。
- `visibilitychange` / `pagehide` / `beforeunload` 多次触发导致重复落卡。
- Android 上长按唤出菜单后，系统补发的 click 与 `contextmenu` 导致菜单闪动或自动关闭。

### 已知限制

- 无账号、无云端同步，数据仅存在当前浏览器或 App 内。
- 无导出/导入功能；清除站点数据、使用无痕模式或卸载 APK 都会丢失内容。
- APK 为自签名，需要允许「安装未知来源应用」；最低 Android 7.0；竖屏锁定。
