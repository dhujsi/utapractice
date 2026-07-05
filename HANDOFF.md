# HANDOFF

## 当前状态

- APK 打包共享 Web UI，Android 侧只负责 WebView 资源和 `/api` 拦截。
- APK 离线同步入口仍只在 `window.UtaPracticeAndroid` 存在时显示，普通网页端不会出现。
- 本次重点修复了 APK 本地音频 Range、歌词点击 seek ready 保护、公共移动端侧栏滑动。
- 工作页 ruby 生成任务完成后，可从任务列表重新打开工作源、预览生成结果并发布为正式歌词；旧版转换任务仍会直接写入正式歌词。
- 普通网页端不再使用 safe-area 顶部/底部空隙；只有 APK 桥接环境会给根节点加 `android-shell` 并启用安全区。
- 歌库上传区现在需要先选择文件再点上传；音频可选择一个“已有歌词但无音频”的目标，把任意文件名音频保存为目标歌词同名音频。

## 验证

- 已通过：`node --test tests/app_behavior.test.js`
- 已通过：`node --check web_static/app.js`
- 已通过：`python3 -m py_compile web_app.py`
- 已通过：静态 HTTP + Playwright 手机宽度检查上传区控件可见，网页 `--safe-top` 为 `0px`，生成页输入框不会被横滑逻辑忽略。
- 未完成：本机 Python 缺少 Flask/OpenAI/librosa/soundfile，未能启动 Flask 做真接口 test client 验证。
- 未完成：`bash ./gradlew assembleDebug`，当前机器没有 `java` 且 `JAVA_HOME` 未设置。

## 后续建议

- 在有 JDK/Android SDK 的环境中运行 `cd android && bash ./gradlew assembleDebug`，再安装 APK 实机验证歌词点击跳转、切歌速度和侧栏滑动。
