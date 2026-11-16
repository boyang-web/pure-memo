# 变更记录

本项目从 v1.0 开始记录版本变更，结构参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)。

## [Unreleased]

## [v1.1.1] — 2026-11-16

### 新增

- Android 壳工程源码入库（`android/`）：`MainActivity` 把 `assets/` 映射为 `https://appassets.androidplatform.net/`，给出稳定 origin，`localStorage` 行为与浏览器一致；主文档加载失败回退 `file:///android_asset/index.html`；切到后台时派发 `pagehide`，保证草稿落卡。
- 状态栏跟随页面主题：壳在页面加载后注入一小段脚本，监听 `meta[name="theme-color"]` 的 `content` 变化，同步状态栏 / 导航栏底色与图标明暗（深色主题浅图标，浅色主题深图标）。
- `scripts/build_apk.py`：不依赖 Gradle，直接调用 `aapt2` / `javac` / `d8` / `zipalign` / `apksigner` 构建签名 APK。版本号取自 `index.html` 的 `app-version`，`versionCode` 按 `MAJOR*10000 + MINOR*100 + PATCH` 计算；未签名包内时间戳固定为 1980-01-01，同一份源码两次构建字节一致。

### 变更

- APK 重新构建为 v1.1.1（`release/PureMemo-v1.1.1.apk`，versionCode 10101，113 KB），内含 v1.1 的拖拽排序、顶部内联编辑与动画重做。v1.0 的 APK 与源码脱节，不再作为发布产物。
- 签名密钥换新（v1.0 的私钥没有入库），**新包无法覆盖安装 v1.0，需先卸载**。
- APK 内不再打包 `sw.js`：壳里资源随包分发、不会热更新，Service Worker 无意义，`/sw.js` 直接返回 404，页面里的注册静默失败。
- Service Worker 缓存版本升至 `purememo-v10`。

## [v1.1.0] — 2026-11-16

### 新增

- 拖拽排序：按住卡片约 0.3 秒即可拖动换序；拖进「置顶」分区即置顶，从置顶分区往下拖出即取消置顶；拖拽时靠近上下边缘自动滚动，落点实时预览置顶状态。
- 卡片数据新增 `order` 字段，旧数据在首次读取时按创建时间（新的在前）自动补齐。

### 修复

- 单列视图下拖拽换序不对：落点判定沿用了双列的规则，用手指横坐标决定「插到这张卡前面还是后面」。单列每行只有一张卡，横向位置没有意义——手指停在左半边时卡片永远只能往上挪、往下拖到第二张就卡住；停在右半边时又会提前一整格跳过去。改为单列只按纵向中线判定（`drag.cols` 在起拖时记一次列数）。
- 拖拽换序时卡片完全没有动画：`.card` 的入场动画 `cardIn` 用了 `animation-fill-mode: both`，`to` 帧里的 `transform:none` 在播完后永久生效，而 CSS 动画优先级高于脚本动画，把 FLIP 的 `translate3d` 整个压掉了。改为 `backwards`。
- 拖拽卡顿：
  - `updateSlot()` 不再逐帧 `getBoundingClientRect()`，改用 `drag.geom` 几何缓存（同一组操作下强制布局从 510 次降到 30 次以内）。
  - 落点判定合并进幽灵跟随的 rAF，`pointermove` 只记录坐标。
  - 换序动画的关键帧从 23 帧降到 2 帧，缓动改由 `cubic-bezier(.32,.72,.24,1)` 表达。
  - 拖拽期间关闭卡片 `backdrop-filter`（改用 `--glass-solid` 实色），并移除全卡 `will-change:transform`。
  - 背景光斑动画去掉 `scale`，只保留平移，避免模糊图层反复重新栅格化；拖拽时暂停背景动画。
- 换序动画被打断时会先跳回格子位置再重新出发：`reorder()` 改为先量视觉位置、再停动画，从当前所在处接着走（实测打断瞬间位移 0px）。
- 松手后幽灵落位偏慢：`settleGhost()` 时长改为按剩余距离自适应（110–200ms，原来固定 230ms）。
- 拖拽把卡片移出置顶后，空的「置顶」分组头没有删除，会残留一个没有卡片的分组标题。

### 变更

- Service Worker 缓存版本升至 `purememo-v9`；`index.html` 增加 `app-version` 元信息，与发布标签保持一致。
- 发布流程标准化：打 `vX.Y.Z` 标签触发 GitHub Actions，自动校验、打包 `PureMemo-vX.Y.Z-web.zip`、生成 `SHA256SUMS.txt` 并创建 Release（见 `docs/RELEASING.md`）。
- 同一次换序里所有卡片共用一个时长（按最大位移计算），一起出发一起停住，避免每张卡各走各的时长显得零碎。
- `render()` 改为复用节点：按新顺序移动已有卡片与分组头，只增删变化的部分，不再整板重建（点卡片编辑、保存、置顶不再重建所有卡片）。
- 拖拽落位后不再调用 `render()`，改由 `settleTempHeads()` 收尾分组头。
- 入场动画只在冷启动播放一次，其余场景不再重播。
- 拖拽手感重做：卡片被按住后浮起（放大、加深阴影），跟随指针时带一点延迟与速度倾斜；其余卡片换位改用带轻微回弹的位移动画（FLIP），松手后卡片收拢落回格子。
- 移除顶栏「排序」按钮：顺序只由拖拽决定，新建卡片仍进入所在组最前。
- 长按手势改为拖拽排序（此前用于唤出菜单，该能力已在上一轮移除）。
- Service Worker 缓存版本升至 `purememo-v6`。
- 交互调整：编辑不再使用居中弹层，改为在看板顶部（置顶分组上方）展开一张整行大卡片就地编写，取消不改动原文。
- 移除长按卡片唤出菜单的能力，卡片操作统一走右上角 ⋯ 按钮。
- 卡片菜单去掉「编辑」项（点击卡片本身即为编辑）。
- 移除输入弹层相关的结构、样式与脚本（遮罩、composer、键盘居中补偿）；Service Worker 缓存版本升至 `purememo-v3`。
- 仓库结构标准化：图标归档到 `assets/icons/`，图标生成脚本移至 `scripts/`，APK 移至 `release/`。
- 同步更新 `index.html`、`manifest.webmanifest`、`sw.js` 中的资源路径；Service Worker 缓存版本升至 `purememo-v2`。
- 新增 `README.md`、MIT `LICENSE`、`.gitignore`、`.gitattributes`、`.editorconfig`。
- 新增 `scripts/check_references.py` 与 GitHub Actions 校验工作流。
- 新增 `docs/DEVELOPMENT.md`，并将原有开发记录整理为本文档。

### 说明

- 仓库结构标准化本身不改变应用行为；上面的交互调整属于同一版本内的功能改动。

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

[Unreleased]: https://github.com/boyang-web/pure-memo/compare/v1.1.1...HEAD
[v1.1.1]: https://github.com/boyang-web/pure-memo/releases/tag/v1.1.1
[v1.1.0]: https://github.com/boyang-web/pure-memo/releases/tag/v1.1.0
