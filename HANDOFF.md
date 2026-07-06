# HANDOFF

## 当前状态

- APK 打包共享 Web UI，Android 侧只负责 WebView 资源和 `/api` 拦截。
- APK 方向已调整为本地完备应用：共享 Web UI 不分叉，Android 侧实现核心 `/api/...` 本地后端；服务器同步只是附加能力。
- 架构约束记录在 `docs/apk-local-backend.md`：以后新增功能应先定义 API 合约，再分别补 Flask 后端和 APK 本地后端；文件选择、权限和本机复制走 Android Bridge。
- APK 本地歌库可以从空库启动，`/api/songs` 无服务器时返回本机列表或 `[]`，不再把默认服务器当作隐式依赖。
- APK 已移除默认同步服务器地址：`getServerUrl()` 初始为空；未填写可选同步后端时不会隐式访问用户内网服务器。
- APK JSON 写请求通过 `window.UtaPracticeAndroid.apiRequest()` 进入 Android，本地支持 `/api/songs/<name>/meta`、`/api/songs/<name>/lyrics`、`/api/upload/lyrics-text` 和 `/api/songs/<name>/delete`。
- APK 接口设置已本地化：`/api/settings` 读写 App 私有目录的 `settings.local.json`，`/api/settings/test` 直接测试 OpenAI 兼容接口，不再代理到同步服务器。
- APK 音频/歌词文件导入通过 `chooseAudioForSong()` / `chooseLyricsForSong()` 打开 Android 文件选择器并复制到 App 私有目录。
- APK 离线同步入口仍只在 `window.UtaPracticeAndroid` 存在时显示，普通网页端不会出现。
- 本次重点修复了 APK 本地音频 Range、歌词点击 seek ready 保护、公共移动端侧栏滑动。
- 工作页 ruby 生成任务完成后，可从任务列表重新打开工作源、预览生成结果并发布为正式歌词；旧版转换任务仍会直接写入正式歌词。
- 普通网页端不再使用 safe-area 顶部/底部空隙；只有 APK 桥接环境会给根节点加 `android-shell` 并启用安全区。
- 歌库上传区现在需要先选择文件再点上传；音频可选择一个“已有歌词但无音频”的目标，把任意文件名音频保存为目标歌词同名音频。
- 歌库歌词区支持两条入库路径：文件上传或直接粘贴 LRC/JSON；两者都可以匹配“已有音频但无歌词”的歌曲。
- 移动端侧栏切换页面时保持打开，只有从歌库点击“载入练习”进入主播放区时主动收回。

## 验证

- 已通过：`node --test tests/app_behavior.test.js`，17 个行为测试通过，覆盖 APK 本地 JSON 写入桥、Android 文件导入桥、本地接口设置和无硬编码同步服务器。
- 已通过：`node --check web_static/app.js`
- 已通过：`python3 -m py_compile web_app.py`
- 已通过：`cd android && ANDROID_HOME=/home/er/android-sdk bash ./gradlew assembleDebug`
- 已通过：`unzip -p dist/utapractice-local-backend-debug.apk assets/webapp/web_static/app.js | rg "apiRequest|/api/settings|/api/settings/test|chooseAudioForSong"`
- 已通过：`strings dist/utapractice-local-backend-debug.apk | rg "192\\.168\\.68\\.200:8502" || true` 无输出。
- APK 输出：`dist/utapractice-local-backend-debug.apk`
- 已通过：静态 HTTP + Playwright 手机宽度检查上传区控件可见，网页 `--safe-top` 为 `0px`，生成页输入框不会被横滑逻辑忽略。
- 已通过：fnOS 部署后 `POST /api/upload/lyrics-text` 写入临时 LRC 成功，随后删除临时文件。
- 未完成：本机 Python 缺少 Flask/OpenAI/librosa/soundfile，未能启动 Flask 做真接口 test client 验证。

## 后续建议

- 安装 `dist/utapractice-local-backend-debug.apk` 实机验证：空库启动、导入音频、导入歌词、粘贴歌词、保存备注/Key/已学会、可选同步。
