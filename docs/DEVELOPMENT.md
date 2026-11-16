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
├── scripts/generate_icons.py   # 用 Python 标准库生成 PNG 图标
├── scripts/check_references.py # 本地资源引用校验
├── release/                    # 构建产物（APK）
├── docs/                       # 文档
└── .github/workflows/          # CI 校验
```

## 数据模型

存储键与结构：

| 键 | 类型 | 说明 |
| --- | --- | --- |
| `purememo.cards.v1` | `Card[]` | 看板卡片 |
| `purememo.draft.v1` | `{ text: string, editingId: string \| null }` | 输入面板草稿 |
| `purememo.settings.v1` | `Settings` | 排序、视图、主题、当前留存页 |
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
};

type Settings = {
  sort: 'desc' | 'asc';
  view: 'grid' | 'list';
  theme: 'dark' | 'light' | null; // null 表示跟随系统
  page: 0 | 1 | 2;
};
```

`load()` 会过滤掉缺少字符串 `text` 的非法卡片，并补齐默认字段。旧版 `purememo.archive.v1` 只在首次读取时迁移到 `purememo.pages.v1` 的第 1 页，迁移后旧键保留但不删除，避免误丢数据。

`read()` / `write()` 包装了 `localStorage` 访问：当浏览器禁用存储或配额不足时，会降级到内存对象 `memoryFallback`，并在启动后提示「本地存储不可用」。

## 自动保存与生命周期

输入面板（composer）中的每次 `input` 事件都会把文本写入 `state.draft` 并持久化，**不是**在关闭时才读取 DOM。以下事件会调用幂等的 `flushDraftToCard()`：

- `visibilitychange` 变为 `hidden`
- `pagehide`
- `beforeunload`

这样多个生命周期事件连续触发时也只会生成一张卡片。切回前台时，如果当前在看板面板，会重新自动打开输入面板；如果停留在长期留存面板，则不打断编辑。

长期留存文本通过 `archiveEditor` 的 `input` 事件即时写入 `state.pages[state.page]`，并在切后台时再兜底同步一次（处理输入法组合态尚未触发 `input` 的情况）。

## 看板与交互

- **分组**：置顶卡片单独成组；其余按创建日期分组为「今天 / 昨天 / 具体日期」。
- **排序**：`desc` 最新在前，`asc` 最早在前；置顶组按 `pinnedAt` 排序。
- **视图**：`grid` 双列，`list` 单列，仅改变 CSS 网格与文本行数。
- **就地菜单**：`.popover` 根据锚点元素的 `getBoundingClientRect()` 定位；下方空间不足时翻到上方，右侧空间不足时右对齐。打开时不给页面加遮罩，点击外部、滚动看板、按 `Esc`、切换面板或切后台都会关闭。
- **长按**：`pointerdown` 启动 480ms 计时器；移动超过 10px 或触发 `pointercancel` 时取消。计时器触发后设置 `longPressFired`，在 `pointerup` 时用捕获阶段的 `click` 监听吞掉系统补发的合成 click，避免菜单刚打开就被同一手势关闭。`contextmenu` 在已打开本卡菜单时直接返回，避免二次触发。
- **撤销**：`showToast(msg, '撤销', fn)` 提供约 5.2 秒的撤销窗口。转存到长期留存的撤销只在目标页文本未被后续编辑时回滚，避免覆盖用户新输入的内容。

## Service Worker 策略

`sw.js` 的缓存名为 `purememo-v2`：

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
3. 置顶、排序、双列/单列切换正常。
4. 长按卡片与点击 ⋯ 都能打开就地菜单，且不会闪动。
5. 删除、清空、转存后点击「撤销」能恢复。
6. 三个留存页分别输入，刷新后内容与当前页保持。
7. 深色/浅色主题切换及跟随系统正常。
8. 断网后重新打开页面仍可使用（需先在线访问一次）。

## APK 构建说明

APK 采用离线 WebView 壳，而不是 `file://` 直接加载，以保证 `localStorage` 有稳定的 origin：

- `MainActivity` 通过 `shouldInterceptRequest` 把 `https://appassets.androidplatform.net/*` 映射到 APK 的 `assets/`。
- 由于该 origin 下不存在 `sw.js`，页面中的 Service Worker 注册会失败并被空 `catch` 忽略。
- 主文档加载失败时回退到 `file:///android_asset/index.html`。
- `onPause` 中派发 `pagehide`，确保草稿落卡。
- 必须开启 `setDomStorageEnabled(true)`。

构建链路（工具链未纳入仓库，成品位于 `release/`）：

1. `aapt2 compile` / `aapt2 link` 生成资源与基础 APK；
2. `javac -source 8 -target 8` 编译壳代码；
3. `d8` 生成 `classes.dex`；
4. 用 Python `zipfile` 将 `classes.dex` 与前端 `assets/` 注入 APK；
5. `zipalign` 对齐；
6. `keytool` 生成 PKCS12 密钥，`apksigner` 签名并校验（v2 + v3）。

注意事项：

- `d8.jar` 没有 `Main-Class`，需使用 `java -cp d8.jar com.android.tools.r8.D8`。
- `aapt2 link` 不会打包 `assets/`，必须在 link 之后手动注入。
- 修改前端后需要重新构建 APK 才能同步到安装包；当前 `release/` 中的 v1.0 对应 2026-11-07 的代码。

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
- APK 为自签名，需要允许未知来源；最低 Android 7.0。
- CI 只做静态资源与语法校验，浏览器交互仍需手动冒烟测试。
