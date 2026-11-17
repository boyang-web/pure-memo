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
4. `sw.js` 的 `CACHE` —— 升一位（`purememo-v10` → `purememo-v11`），否则已安装的客户端可能继续用旧缓存。
5. `release/PureMemo-vX.Y.Z.apk` —— 前端有任何改动就要重建，否则装出来的还是旧界面（见下文「Android APK」）。

## 发布

```bash
# 1. 本地自查
python scripts/check_references.py
node --check sw.js
python scripts/build_release.py v1.1.2      # 产出 dist/*.zip 与 SHA256SUMS.txt
python scripts/build_apk.py                 # 产出 release/PureMemo-v1.1.2.apk

# 2. 提交并打标签
git add -A && git commit -m "chore(release): v1.1.2"
git tag -a v1.1.2 -m "v1.1.2"
git push origin main --follow-tags
```

推送标签会触发 `.github/workflows/release.yml`：重新跑一遍校验 → 打包 `PureMemo-vX.Y.Z-web.zip` → 生成 `SHA256SUMS.txt` → 如果仓库里有 `release/PureMemo-vX.Y.Z.apk` 就一并带上 → 用 `docs/releases/vX.Y.Z.md` 作为正文创建 Release。

APK 不在 CI 里构建（Runner 上没有 Android SDK，也不该把签名私钥放进 Secrets），而是本地构建后随提交入库，工作流只负责按标签名取对应文件。标签没有对应的 APK 时会照常发 web 包，不报错。

也可以在 Actions 页面手动触发 `Release` 工作流，填一个已存在的标签重跑发布（例如补传产物）。

## 发布包内容

`scripts/build_release.py` 只打包运行时需要的文件：

```text
index.html  sw.js  manifest.webmanifest  LICENSE  assets/icons/*
```

zip 内使用固定的时间戳与权限，同一份源码多次打包字节一致，校验和才值得核对。`dist/` 已在 `.gitignore` 中，不进仓库。

## Android APK

壳的源码在 `android/`，构建脚本是 `scripts/build_apk.py`，只依赖 JDK 17 与 Android SDK（`build-tools` + `platforms;android-34`），不需要 Gradle。实现细节见 `docs/DEVELOPMENT.md`。

```bash
python scripts/build_apk.py            # 版本号取 index.html 的 app-version
```

产出：

- `release/PureMemo-vX.Y.Z.apk` —— 签名后的安装包（v1 + v2 + v3）
- `release/SHA256SUMS-vX.Y.Z.txt` —— 该 APK 的校验和

`versionCode` 由版本号算出（`MAJOR*10000 + MINOR*100 + PATCH`），只要版本号递增就不会回退。同一个版本号重复构建，**APK 字节完全一致**，因此校验和可以用来确认“这个包装的确实是我发的那份代码”。

注意：

- 前端改动必须重新构建 APK 才会同步进去，`assets/` 是构建时的快照。
- 签名密钥在 `android/keystore/`（已 gitignore）。**丢了私钥就无法发布能覆盖安装的更新**，请自行备份 `purememo-release.jks` 与 `keystore.properties`。
- 换密钥后旧版本无法覆盖安装，发布说明里必须写明“先卸载旧版”，并提醒卸载会清空 App 内数据。
- `validate.yml` 会检查 `release/PureMemo-v<app-version>.apk` 存在，版本号对不上会直接失败——这条能挡住“改了前端却忘了重建 APK”。

## 回滚

发布有问题时不要删除标签重打（会破坏已发出的校验和），改为发一个新的 PATCH 版本；确有需要时可把标签指向修复提交再强制推送标签，但要在发布说明里说明。
