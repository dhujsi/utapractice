# 练歌房 Android APK

这是本地优先的 Android 客户端。

APK 使用原 Web UI：构建时会把仓库根目录的 `templates/index.html` 和 `web_static/app.css` / `web_static/app.js` 打进 APK。Android 侧提供本地后端、文件导入、在线代理和可选同步，不另写一套播放器界面。

## 工作方式

- APK 内置原 Web UI，不依赖手机浏览器打开网页。
- 首次安装后本地库为空。
- 没有服务器时也可以直接在歌库页导入音频、导入歌词、输入歌词、编辑歌词、保存练习状态。
- Web UI 仍然调用 `/api/...`；APK 内部用本地文件实现核心读写接口。
- 在线时可以在原网页设置区域的 `APK 离线同步` 中填写可选同步后端地址并点击同步，例如：

```text
http://your-server.local:8502
```

- 同步先读取轻量歌库索引，只拉取新增或发生变化的歌曲 JSON；音频按 `audio_version` 增量下载，并发执行，未变化的音频不会重复传输。
- 同步是附加能力：同步失败不会影响本地歌库读写。
- AI 生成和歌词搜索需要联网，但直接由 APK 本地后端调用对应服务，不依赖可选同步服务器。

## 本地能力

- `/api/songs` 返回本机歌库，空库返回 `[]`。
- `/api/songs/<name>/meta` 本地保存已学会、音域备注和默认 Key。
- `/api/songs/<name>/lyrics` 本地保存 JSON 歌词编辑结果。
- `/api/songs/<name>/rename` 同步重命名本地歌词、音频、草稿和任务记录。
- `/api/upload/lyrics-text` 本地保存粘贴的 LRC/JSON 歌词。
- `/api/settings` 本地保存 OpenAI 兼容 Base URL、模型和 API Key 状态。
- `/api/settings/test` 直接用本地保存的 OpenAI 兼容配置测试连接，不经过同步服务器。
- 音频和歌词文件导入通过 Android 文件选择器复制到 App 私有目录。
- `/api/songs/<name>/audio` 从本机音频缓存返回并支持 HTTP Range。
- 导入或粘贴的 LRC 会立即转换为同名正式 JSON；AI 完成后也直接覆盖该 JSON。

## 构建

在仓库根目录执行：

```powershell
cd android
.\gradlew.bat assembleDebug
```

产物：

```text
android/app/build/outputs/apk/debug/app-debug.apk
```

这是 debug 签名包，适合自己安装测试；正式分发需要 release 签名。
