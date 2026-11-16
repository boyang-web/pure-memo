# 开发说明

本文档记录纯粹备忘录的架构、数据模型、运行机制与开发约定。

## 概览

纯粹备忘录是一个零后端、离线优先的极简备忘录：

- 应用主体是单文件 `index.html`（HTML + CSS + JS 全部内联），没有构建步骤，也没有运行时依赖。
- 数据保存在浏览器 `localStorage`，不上传服务器。
- `manifest.webmanifest` + `sw.js` 提供 PWA 安装与离线缓存。
- `release/PureMemo-v1.0.apk` 是 Android WebView 壳的成品，内部加载同一份前端资源。

单文件设计是刻意选择：离线缓存只需处理少量资源，部署简单，也便于嵌入 WebView。

## 目录结构

```text
.
├── index.html                  # 应用主体（结构 / 样式 / 逻辑）
├── manifest.webmanifest        # PWA 清单
├── sw.js                       # Service Worker
├── assets/icons/               # SVG 与 PNG 图标
├── android/                    # WebView 壳源码（清单 / 资源 / MainActivity）
│   └── keystore/               # 签名密钥（gitignore，务必自行备份）
├── scripts/generate_icons.py   # 用 Python 标准库生成 PNG 图标
├── scripts/check_references.py # 本地资源引用校验
├── scripts/build_release.py    # 打包 web 版 zip + SHA256
├── scripts/build_apk.py        # 构建签名 APK（aapt2 / d8 / apksigner）
├── release/                    # 构建产物（APK）
├── docs/                       # 文档
└── .github/workflows/          # CI 校验与发布
```

## 数据模型

存储键与结构：

| 键 | 类型 | 说明 |
| --- | --- | --- |
| `purememo.cards.v1` | `Card[]` | 看板卡片 |
| `purememo.draft.v1` | `{ text: string, editingId: string \| null }` | 输入面板草稿 |
| `purememo.settings.v1` | `Settings` | 视图、主题、当前留存页 |
| `purememo.pages.v1` | `[string, string, string]` | 三页长期留存文本 |
| `purememo.archive.v1` | `string` | 旧版单页留存，仅用于迁移 |

```ts
type Card = {
  id: string;
  text: string;
  createdAt: number;   // 毫秒时间戳
  updatedAt: number;
  pinned: boolean;
  pinnedAt: number | null;
  order: number;       // 组内手工顺序，越小越靠前
};

type Settings = {
  view: 'grid' | 'list';
  theme: 'dark' | 'light' | null; // null 表示跟随系统
  page: 0 | 1 | 2;
};
```

`load()` 会过滤掉缺少字符串 `text` 的非法卡片，并补齐默认字段。旧版 `purememo.archive.v1` 只在首次读取时迁移到 `purememo.pages.v1` 的第 1 页，迁移后旧键保留但不删除，避免误丢数据。

`order` 是排序的唯一依据：组内按 `order` 升序，相同时退回 `createdAt`。旧数据没有 `order` 时，`load()` 会按创建时间（新的在前）调 `resetOrderByTime()` 补一份并立刻落盘。分组仍是「置顶组 + 按 `createdAt` 的日期组」，日期组按新的在前排列，`order` 只组内比较——日期由 `createdAt` 决定，不属于可拖拽的自由维度，因此跨组拖拽只允许发生在「置顶」与它自己的日期组之间。

`read()` / `write()` 包装了 `localStorage` 访问：当浏览器禁用存储或配额不足时，会降级到内存对象 `memoryFallback`，并在启动后提示「本地存储不可用」。

## 自动保存与生命周期

输入大卡（看板顶部的内联编辑卡）中的每次 `input` 事件都会把文本写入 `state.draft` 并持久化，**不是**在关闭时才读取 DOM。以下事件会调用幂等的 `flushDraftToCard()`：

- `visibilitychange` 变为 `hidden`
- `pagehide`
- `beforeunload`

这样多个生命周期事件连续触发时也只会生成一张卡片。切回前台时，如果当前在看板面板，会重新展开输入大卡；如果停留在长期留存面板，则不打断编辑。

## 内联编辑

编辑不弹层、不遮罩：`ensureEditCard()` 只创建一次 `.card.card-editing` 节点（`grid-column:1/-1` 占满整行），需要时由 `render()` 插到 `boardInner` 的最前面，所以它永远出现在「置顶」分组上方。

- 点卡片 → `openEditor({mode:'edit', id})`，`state.draft = { text, editingId }`，被编辑的卡片在列表里暂时隐藏，避免同一内容出现两份。
- 点 FAB / 启动 / 回到前台 → `openEditor({mode:'new'})`，草稿为空时不会继承 `editingId`。
- 输入只更新 `state.draft` 并落盘，不触发 `render()`；`render()` 会记住并还原选区，避免重新挂载丢焦点。
- 保存（✓、⌘/Ctrl+Enter）→ `commitDraft()`：有 `editingId` 就更新该卡片，否则新建。
- 取消（✕、Esc）→ 编辑已有卡片时丢弃本次改动；新建时保留草稿，FAB 上显示草稿点。
- 切到别的卡片、点 FAB、切到留存面板前都会先 `stowEditing()` 静默落卡，防止丢字。

长期留存文本通过 `archiveEditor` 的 `input` 事件即时写入 `state.pages[state.page]`，并在切后台时再兜底同步一次（处理输入法组合态尚未触发 `input` 的情况）。

## 看板与交互

- **分组**：置顶卡片单独成组；其余按创建日期分组为「今天 / 昨天 / 具体日期」。
- **排序**：组内按 `order` 升序，新建卡片进入所在组的最前面。顶栏**没有排序按钮**——顺序只由拖拽决定，不再提供「按时间重排」的入口。
- **视图**：`grid` 双列，`list` 单列，仅改变 CSS 网格与文本行数。
- **就地菜单**：`.popover` 根据锚点元素的 `getBoundingClientRect()` 定位；下方空间不足时翻到上方，右侧空间不足时右对齐。打开时不给页面加遮罩，点击外部、滚动看板、按 `Esc`、切换面板或切后台都会关闭。菜单项为「置顶 / 留存 / 复制 / 删除」，**没有「编辑」**——点卡片本身就是编辑。
- **长按 = 拖拽**：长按不再唤出菜单，而是拖拽排序，见下节。
- **撤销**：`showToast(msg, '撤销', fn)` 提供约 5.2 秒的撤销窗口。转存到长期留存的撤销只在目标页文本未被后续编辑时回滚，避免覆盖用户新输入的内容。

## 拖拽排序

按住卡片 300ms 进入拖拽（短按仍是打开编辑）；鼠标按住移动超过 6px 立刻起拖，不用等长按。触摸时按下后移动超过 8px 视为滚动并放弃拖拽。

| 阶段 | 做的事 |
| --- | --- |
| `beginDrag()` | 克隆一张 `.drag-ghost` 浮起来跟随指针（`position:fixed`，不受页面滚动影响），原卡加 `.drag-source` 变成虚线占位；`ensureDragZones()` 补出落点分组，同时把全盘几何量进 `drag.geom` |
| `updateSlot()` | 只用 `drag.geom` 做算术，算出分组与组内插入点，**直接移动占位卡 DOM**，让占位卡就是最终落点；其他卡片的位移交给 `reorder() → animateShift()` 补动画 |
| `endDrag()` | `commitDrop()` 按看板当下的 DOM 顺序重写 `order`、同步 `pinned`，`settleTempHeads()` 收尾分组头，最后 `settleGhost()` 让幽灵落进格子 |

关键细节：

- **浮动**：幽灵的位移由 `startGhostLoop()` 逐帧插值（每帧向目标靠拢 34%），比手指慢半拍才有惯性；倾斜角来自水平滞后量（上限 ±4.5°），停下时自然回正；起拖 200ms 内放大到 1.038 倍并加深阴影（`.lifted`），形成"被拿起来"的层次。
- **换序动画**：`reorder()` 用 FLIP——先量视觉位置、再停动画、再插入、最后量布局位置，把差值做成 `translate3d` 回落到 0 的动画。**只给两个端点关键帧**，加减速交给 `cubic-bezier(.32,.72,.24,1)`；同一次换序里所有卡片共用一个时长（`200 + maxDist * 0.45`，封顶 340ms），一起出发一起停住，才有"整块被挤开"的整体感。
- **不跳**：`reorder()` 里量 `before` 必须在 `freezeShifts()` **之前**。`getBoundingClientRect` 包含 transform，所以停动画前量到的是卡片此刻真正的屏幕位置；拿它和插入后的布局位置相减，被下一次换序打断的动画就能从当前位置接着走。顺序反了的话（先停再量），动画会先跳回格子位置再重新出发。落点判定读 `drag.geom`，不依赖这些中间帧。
- **落点判定分单双列**：双列时同一行并排两张卡，指针落在卡片左半边就插到它前面、右半边插到它后面（`sameRow ? x < 卡片中线 : cy < 卡片中线`）；单列每行只有一张卡，横向坐标没有意义，必须只比纵向中线。`beginDrag()` 时把列数记进 `drag.cols`，`updateSlot()` 据此走两套规则——否则单列下会出现"手指在左半边时卡片永远只能往上挪、往下拖一格就卡住，在右半边又会整格跳过头"。
- **落位**：`settleGhost()` 让幽灵收拢到格子位置并淡出，时长只跟"还差多远"有关（`90 + dd * 0.24`，110–200ms），手指基本就在格子上时立刻收住；同时占位卡从 0.34 淡入。
- 落点只允许「置顶组」和卡片自己的日期组，落在别的日期组时保持上一次有效位置。
- 没有置顶卡片时，`ensureDragZones()` 会临时插一个 `.group-head.drag-temp` 的「置顶」组当落点；卡片原本置顶、自己的日期组又空了时，也会临时补一个日期组，否则拖不出来。
- 移动过程中会给卡片加/去 `.pinned` 类，实时预览"放到这里会置顶/取消置顶"。
- 拖拽期间 `touchmove` 被 `preventDefault()` 吃掉，避免页面跟着手指滚；靠近看板上下边缘 58px 时用 `requestAnimationFrame` 自动滚动。
- `dragEndAt` 记录落位时间，420ms 内补发的 `click` 不再当作"打开编辑"。
- 拖拽中途触发 `blur`（指针在窗口外松开）会走 `cancelDrag()`，不会把拖拽卡死。

## 渲染与动画性能

界面大量使用半透明与模糊，性能上做了几处针对性取舍，改动时别把它们改回去：

- **背景光斑只平移，不缩放**：`.blob` 是 `filter:blur(56px)` 的大图层。模糊半径在元素自身坐标系里计算，一旦 `scale` 变化，整个模糊层必须重新栅格化——三个上百 px 的图层每帧重算会直接压垮合成器。`float1..3` 只保留 `translate3d`，图层栅格化一次后持续复用；拖拽时 `body.dragging .blob{animation-play-state:paused}` 再把背景冻住。
- **拖拽期间关掉毛玻璃**：`body.dragging .board-inner .card` 把 `backdrop-filter` 换成 `--glass-solid` 实色。移动或换位的元素每帧都要重新采样并模糊背后的整块画面，是手机上最贵的合成操作。
- **不全卡 `will-change`**：只有幽灵 `.drag-ghost` 保留，其余交给动画自身提升图层。
- **几何缓存**：`drag.geom` 存的是**看板内容坐标**（`t + scrollTop`），所以滚动时不必重测，判断落点时把指针 `y` 换算成内容坐标即可。只有 `beginDrag()` 和每次 `reorder()` 之后才测量布局。
- **pointermove 合并进 rAF**：`pointermove` 只更新 `drag.lastX/lastY` 并置 `slotDirty`，真正的落点计算在幽灵跟随的同一帧里做一次。事件频率再高也只有一帧一次算术。
- **render 复用节点**：`render()` 不再 `textContent=''` 重建，而是把现有的卡片与分组头收进 pool，用 `applyOrder()` 按新顺序 `appendChild` 移动，只增删变化的部分；内容变化走 `updateCard()` 局部更新。点卡片编辑、保存、置顶这些高频操作因此不会重新栅格化整板卡片层。
- **入场动画只在冷启动播**：`state.noAnim` 默认 `true`，只在启动时置 `false`；此后新增卡片用 `.fresh` 单独高亮。
- **`.card` 的 `cardIn` 必须用 `animation-fill-mode: backwards`，不能用 `both`**：`cardIn` 的 `to` 帧里写了 `transform:none`，`both`/`forwards` 会让这条 CSS 动画在播完后**永久**生效；而 CSS 动画在层叠里优先于脚本创建的动画（Web Animations API），于是 `animateShift()` 的 `translate3d` 会被整个压掉——表现就是"拖拽换序时卡片一动不动"。改回 `both` 会立刻复现，别改。
- **落位不重绘**：`endDrag()` 结束时 DOM 已经是最终顺序和分组，只调 `settleTempHeads()`，不调 `render()`。

`settleTempHeads()` 会把名下还有卡片的临时分组头"转正"、空掉的删掉。因为落位不再走 `render()`，置顶组和日期组的增删必须在这一步补上——早期版本漏了"把卡片从置顶拖出去后空掉的分组头"，会留下一个没有卡片的分组标题。

验证方式：Chrome DevTools Protocol 里 `Performance.getMetrics` 取差值，配合页面内 `requestAnimationFrame` 采样。60 次连续换序的极端场景下，`LayoutCount` 增量约 120 次、主线程占用约 10%，帧率稳定在 60fps 以上且没有超过 32ms 的长帧。

## Service Worker 策略

`sw.js` 的缓存名为 `purememo-v5`：

- **install**：预缓存 `ASSETS` 列表（应用入口、manifest 与图标），单个资源失败不会中断安装；随后 `skipWaiting()`。
- **activate**：删除非当前版本的缓存，随后 `clients.claim()`。
- **页面导航**：网络优先，成功后把 `index.html` 写回缓存；断网时回退缓存的 `index.html` 或 `./`。这样在线时能及时拿到新版本。
- **其他同源 GET**：缓存优先，未命中则请求网络，并把成功响应写入缓存。

**修改缓存资源或发布新版本时，必须递增 `CACHE` 版本号**，否则已安装的客户端可能继续使用旧缓存。

Service Worker 仅在非 `file://` 环境注册。`localhost` 与 HTTPS 满足要求，因此本地预览请使用静态服务器。

## 图标生成

`scripts/generate_icons.py` 只使用 Python 标准库（`math` / `struct` / `zlib`）逐像素绘制并编码 PNG，不依赖 Pillow：

```bash
python scripts/generate_icons.py
```

脚本会输出 `assets/icons/icon-180.png`、`icon-192.png`、`icon-512.png`，使用超采样抗锯齿。`assets/icons/icon.svg` 为矢量版本，手写维护。

修改图标后，请同步更新 `manifest.webmanifest` 与 `sw.js` 中的引用（文件名不变时无需改动），并递增 Service Worker 缓存版本。

## 本地预览与校验

```bash
# 静态服务器（Service Worker 需要 localhost 或 HTTPS）
python -m http.server 8000

# 校验 HTML、manifest、Service Worker 中引用的本地资源是否存在
python scripts/check_references.py
```

建议的手动冒烟检查：

1. 新建卡片后刷新，内容仍在。
2. 输入草稿后切到后台再回来，草稿已落成卡片且没有重复。
3. 置顶、双列/单列切换正常。
4. 按住卡片拖动可换序；拖进「置顶」变成置顶，往下拖出来取消置顶；松手后不误开编辑；换序时邻卡有滑动动画、松手后卡片落回格子。
5. 点击卡片在顶部展开整行编辑大卡，文字一致；点 ✕ 后原文不变，点 ✓ 后保存并回到列表。
6. 删除、清空、转存后点击「撤销」能恢复。
7. 三个留存页分别输入，刷新后内容与当前页保持。
8. 深色/浅色主题切换及跟随系统正常。
9. 断网后重新打开页面仍可使用（需先在线访问一次）。

## 发布

版本号、需要同步修改的文件、标签与自动发布流程见 [`RELEASING.md`](RELEASING.md)。要点：

- 版本号写在 `index.html` 的 `<meta name="app-version">`，打包脚本会用它和标签比对，不一致直接失败。
- `python scripts/build_release.py vX.Y.Z` 产出 `dist/PureMemo-vX.Y.Z-web.zip` 与 `dist/SHA256SUMS.txt`；zip 内时间戳与权限固定，同源码可复现。
- 推送 `vX.Y.Z` 标签触发 `.github/workflows/release.yml`，校验通过后自动创建 Release 并上传产物，正文取自 `docs/releases/vX.Y.Z.md`。
- `dist/` 不进仓库；`release/` 里只有手工构建的 APK。

## Android 壳（APK）

壳的源码在 `android/`，只是一个 Activity，没有 Gradle 工程，也没有第三方依赖。

### 为什么不用 `file://`

`file:///android_asset/index.html` 的 origin 是 opaque 的，`localStorage`、`crypto.randomUUID` 这类能力行为不稳定。壳把资源映射成 `https://appassets.androidplatform.net/`，origin 是正常的 `https`，与浏览器里访问时一致，数据也就不会因为换加载方式而消失。

### 实现要点

| 位置 | 做法 |
| --- | --- |
| `shouldInterceptRequest` | 把 `appassets.androidplatform.net` 下的请求映射到 APK 的 `assets/`，按扩展名给 MIME，文本给 `utf-8`、图片给 `null`，并带 `Cache-Control: no-store`。 |
| `/sw.js` | 直接回 404。壳里资源随包分发、不会热更新，Service Worker 没有意义。页面对注册失败已经是空 `catch`，不受影响。 |
| 主文档失败 | `onReceivedError` 里回退到 `file:///android_asset/index.html`，保证最坏情况下还能打开。 |
| `onPause` | 派发一次 `pagehide`，触发页面的 `flushDraftToCard()`，切后台不会丢正在写的草稿。 |
| `setDomStorageEnabled(true)` | 必须开，否则 `localStorage` 不可用，卡片写不进去。 |
| 状态栏 | 页面加载完后注入一段只读脚本，观察 `meta[name="theme-color"]` 的 `content`，经 `PureMemoShell.setBarColor()` 同步状态栏 / 导航栏底色，并按亮度切换图标明暗。 |
| 深色自动适配 | 关掉 `FORCE_DARK` 与 `setAlgorithmicDarkeningAllowed`，主题完全由页面控制，避免二次压暗。 |

`targetSdk` 取 34（不要求 edge-to-edge），窗口底色与页面深色背景同为 `#080B13`，冷启动不闪白；不需要 `safe-area-inset`，页面自带的 `env()` 取 0 也不会顶到状态栏。

### 构建

前置只有 JDK 17 与 Android SDK（`build-tools` + `platforms;android-34`），不需要 Gradle：

```bash
python scripts/build_apk.py          # 产出 release/PureMemo-vX.Y.Z.apk
python scripts/build_apk.py --skip-sign   # 只出未签名包，排查打包问题
```

脚本内部链路：

1. `aapt2 compile` 编译 `android/res`；
2. `aapt2 link` 生成基础 APK，`-A` 直接把 `assets/` 打进去，`--version-code` / `--version-name` 由 `index.html` 的 `app-version` 推出（`MAJOR*10000 + MINOR*100 + PATCH`）；
3. `javac -source 8 -target 8` 编译壳代码；
4. `d8 --release --min-api 24` 生成 `classes.dex`；
5. 用 Python `zipfile` 把 `classes.dex` 合并进 APK，**所有条目时间戳固定为 1980-01-01**，同一份源码两次构建哈希一致；
6. `zipalign -f -p 4` 对齐；
7. `apksigner` 签名（v1 + v2 + v3，v4 的 `.idsig` 不随包发布）。

### 签名

- 密钥在 `android/keystore/purememo-release.jks`，口令在 `android/keystore/keystore.properties`，两者都已 `.gitignore`。
- 首次运行脚本会自动 `keytool -genkeypair` 生成，口令随机并存进 `keystore.properties`。
- **务必备份这两个文件**：私钥丢了就无法再发布可覆盖安装的更新；口令丢了等于私钥不可用。
- v1.0 的旧私钥没有入库，所以 v1.1.1 的包签名与 v1.0 不同，**装过 v1.0 的设备要先卸载**。

### 注意事项

- `aapt2 link` 的 `-A` 只打包目录内容，改前端后必须重新构建 APK 才会同步进安装包。
- `build-tools` 里的 `d8` / `apksigner` 是 shell 包装脚本，靠 `JAVA_HOME` 或 `PATH` 找 `java`；脚本会自己导出这两个变量。
- XML 注释里不能出现 `--`（例如写成 `--bg`），`aapt2 compile` 会直接报 `not well-formed`。

## 开发约定

- 保持零依赖、零构建；不要引入打包器或框架，除非有明确必要。
- 资源使用相对路径（`./`），确保部署在子路径（如 GitHub Pages 项目页）时仍可用。
- 文本文件统一使用 UTF-8 与 LF 换行。
- 修改 `sw.js` 的资源列表或发布新版本时，递增 `CACHE`。
- 界面文案使用简体中文；代码标识符与注释风格保持现有写法。
- 新增本地资源后，更新 `scripts/check_references.py` 可识别的引用位置，并运行校验。

## 已知限制

- 数据只存在本机，没有云同步；清除站点数据或卸载 APK 会丢失内容。
- 当前版本没有导出/导入功能，也没有自动备份。
- APK 为自签名，需要允许未知来源；最低 Android 7.0；targetSdk 34，不跟随系统字体缩放（避免布局错位）。
- 壳内的数据与浏览器里的数据互不相通：网页版和 APK 各自一份 `localStorage`。
- CI 只做静态资源与语法校验，浏览器交互仍需手动冒烟测试。
