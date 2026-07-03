# 练歌房 Android APK

这是离线优先的 Android 客户端。

## 工作方式

- APK 内置页面，不依赖手机浏览器打开网页。
- 首次安装后本地库为空。
- 在线时填写飞牛后端地址并点击同步，例如：

```text
http://192.168.68.200:8502
```

- 同步会下载歌单、歌词和音频到手机本地 IndexedDB。
- 离线时可以播放已经同步过的歌曲。
- 没同步过的歌曲离线不可用。

## 云端配置

可以填写一个云端 JSON 地址，格式参考仓库根目录的 `app_config.example.json`。读取后会把服务器列表显示在 APK 内。

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
dist/utapractice-offline-debug.apk
```

这是 debug 签名包，适合自己安装测试；正式分发需要 release 签名。
