# HANDOFF

## 当前状态

- APK 仍使用原 Web UI，Android 侧只负责 WebView 资源和 `/api` 拦截。
- APK 离线同步入口仍只在 `window.UtaPracticeAndroid` 存在时显示，普通网页端不会出现。
- 本次重点修复了 APK 本地音频 Range、歌词点击 seek ready 保护、公共移动端侧栏滑动。

## 验证

- 已通过：`node --test tests/app_behavior.test.js`
- 已通过：`node --check web_static/app.js`
- 未完成：`bash ./gradlew assembleDebug`，当前机器没有 `java` 且 `JAVA_HOME` 未设置。

## 后续建议

- 在有 JDK/Android SDK 的环境中运行 `cd android && bash ./gradlew assembleDebug`，再安装 APK 实机验证歌词点击跳转、切歌速度和侧栏滑动。
