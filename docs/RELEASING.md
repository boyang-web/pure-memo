# 发版流程

版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)：`vMAJOR.MINOR.PATCH`。

| 变动类型 | 版本位 | 例子 |
| --- | --- | --- |
| 破坏性改动（数据结构不兼容、必须手动迁移） | MAJOR | `v2.0.0` |
| 新增功能、交互调整 | MINOR | `v1.1.0` |
| 只修 bug、措辞或样式微调 | PATCH | `v1.1.1` |

## 一次发布要动的东西

1. `index.html` 的 `<meta name="app-version">` —— 打包脚本会拿它和标签比对，不一致直接报错。
2. `docs/CHANGELOG.md` —— 把 `## [Unreleased]` 下的条目归到新的 `## [vX.Y.Z] — YYYY-MM-DD`，并更新文件末尾的对比链接。
3. `docs/releases/vX.Y.Z.md` —— 发布说明，会原样作为 GitHub Release 的正文。
4. `sw.js` 的 `CACHE` —— 升一位（`purememo-v9` → `purememo-v10`），否则已安装的客户端可能继续用旧缓存。

## 发布

```bash
# 1. 本地自查
python scripts/check_references.py
node --check sw.js
python scripts/build_release.py v1.1.0      # 产出 dist/*.zip 与 SHA256SUMS.txt

# 2. 提交并打标签
git add -A && git commit -m "chore(release): v1.1.0"
git tag -a v1.1.0 -m "v1.1.0"
git push origin main --follow-tags
```

推送标签会触发 `.github/workflows/release.yml`：重新跑一遍校验 → 打包 `PureMemo-vX.Y.Z-web.zip` → 生成 `SHA256SUMS.txt` → 用 `docs/releases/vX.Y.Z.md` 作为正文创建 Release 并附上这两个文件。

也可以在 Actions 页面手动触发 `Release` 工作流，填一个已存在的标签重跑发布（例如补传产物）。

## 发布包内容

`scripts/build_release.py` 只打包运行时需要的文件：

```text
index.html  sw.js  manifest.webmanifest  LICENSE  assets/icons/*
```

zip 内使用固定的时间戳与权限，同一份源码多次打包字节一致，校验和才值得核对。`dist/` 已在 `.gitignore` 中，不进仓库。

## 关于 Android APK

`release/PureMemo-v1.0.apk` 是用本机 Android 工具链（`aapt2` / `d8` / `apksigner`）手工构建的 WebView 壳，工具链不在仓库内，CI 无法重建。因此：

- 前端发布不影响 APK；APK 里的 `assets/` 是发布时的快照。
- 重新构建 APK 后，把新包放进 `release/` 并在发布说明里写清楚对应版本，再按上面的流程发版。
- 在重建之前，发布说明中要明确写出「APK 版本落后于网页版」。

## 回滚

发布有问题时不要删除标签重打（会破坏已发出的校验和），改为发一个新的 PATCH 版本；确有需要时可把标签指向修复提交再强制推送标签，但要在发布说明里说明。
