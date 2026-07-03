# 练歌房 Android APK

这是离线优先的 Android 客户端。

APK 使用原 Web UI：构建时会把仓库根目录的 `templates/index.html` 和 `web_static/app.css` / `web_static/app.js` 打进 APK。Android 侧只负责本地缓存、在线代理和离线返回数据，不另写一套播放器界面。

## 工作方式

- APK 内置原 Web UI，不依赖手机浏览器打开网页。
- 首次安装后本地库为空。
- 在线时在原网页设置区域的 `APK 离线同步` 中填写飞牛后端地址并点击同步，例如：

```text
http://192.168.68.200:8502
```

- 同步会下载歌单、歌词和音频到 App 私有目录。
- 离线时可以播放已经同步过的歌曲。
- 没同步过的歌曲离线不可用。

## 云端配置

可以填写一个云端 JSON 地址，格式参考仓库根目录的 `app_config.example.json`。读取后会把飞牛后端地址写入同步设置。

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

当前本地也会复制一份到：

```text
dist/utapractice-original-ui-offline-debug.apk
```

这是 debug 签名包，适合自己安装测试；正式分发需要 release 签名。
