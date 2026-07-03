package com.utapractice.app;

import android.annotation.SuppressLint;
import android.app.Activity;
import android.content.Context;
import android.content.SharedPreferences;
import android.net.Uri;
import android.os.Bundle;
import android.util.Base64;
import android.webkit.JavascriptInterface;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;

public class MainActivity extends Activity {
    private static final String APP_ORIGIN = "https://utapractice.local";
    private static final String DEFAULT_SERVER_URL = "http://192.168.68.200:8502";
    private static final String PREFS_NAME = "utapractice_apk";
    private static final String KEY_SERVER_URL = "server_url";
    private static final String KEY_CLOUD_CONFIG_URL = "cloud_config_url";
    private static final String KEY_LAST_SYNC = "last_sync";

    private WebView webView;
    private SharedPreferences prefs;

    @SuppressLint({"SetJavaScriptEnabled", "AddJavascriptInterface"})
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        prefs = getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE);

        webView = new WebView(this);
        setContentView(webView);

        WebSettings settings = webView.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setDatabaseEnabled(true);
        settings.setMediaPlaybackRequiresUserGesture(false);
        settings.setAllowFileAccess(false);
        settings.setAllowContentAccess(false);
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_ALWAYS_ALLOW);

        webView.addJavascriptInterface(new AndroidBridge(), "UtaPracticeAndroid");
        webView.setWebChromeClient(new WebChromeClient());
        webView.setWebViewClient(new AppWebViewClient());
        webView.loadUrl(APP_ORIGIN + "/");
    }

    private class AppWebViewClient extends WebViewClient {
        @Override
        public WebResourceResponse shouldInterceptRequest(WebView view, WebResourceRequest request) {
            Uri uri = request.getUrl();
            if (!APP_ORIGIN.equals(uri.getScheme() + "://" + uri.getHost())) {
                return super.shouldInterceptRequest(view, request);
            }

            String path = uri.getPath() == null ? "/" : uri.getPath();
            if ("/".equals(path) || "/index.html".equals(path)) {
                return assetResponse("text/html", "webapp/index.html");
            }
            if ("/manifest.webmanifest".equals(path)) {
                return assetResponse("application/manifest+json", "webapp/web_static/manifest.webmanifest");
            }
            if (path.startsWith("/web_static/")) {
                return assetResponse(mimeForPath(path), "webapp" + path);
            }
            if (path.startsWith("/api/")) {
                return handleApiRequest(request);
            }
            return super.shouldInterceptRequest(view, request);
        }
    }

    private WebResourceResponse handleApiRequest(WebResourceRequest request) {
        Uri uri = request.getUrl();
        String method = request.getMethod() == null ? "GET" : request.getMethod().toUpperCase();
        String pathAndQuery = uri.getEncodedPath() + (uri.getEncodedQuery() == null ? "" : "?" + uri.getEncodedQuery());
        if (!"GET".equals(method)) {
            return jsonResponse(503, "{\"error\":\"APK 离线壳暂不支持这个写操作；请在网页端执行\"}");
        }

        try {
            WebResourceResponse cachedAudio = cachedAudioResponse(uri);
            if (cachedAudio != null) {
                return cachedAudio;
            }

            byte[] remote = httpGetBytes(serverUrl() + pathAndQuery);
            cacheGetResponse(uri, remote);
            return bytesResponse(mimeForPath(uri.getPath()), remote);
        } catch (Exception ignored) {
            return cachedApiResponse(uri);
        }
    }

    private void cacheGetResponse(Uri uri, byte[] bytes) throws Exception {
        String path = uri.getPath();
        if ("/api/songs".equals(path)) {
            writeFile(songsListFile(), bytes);
            return;
        }

        String prefix = "/api/songs/";
        if (path != null && path.startsWith(prefix) && !path.endsWith("/audio")) {
            String name = Uri.decode(path.substring(prefix.length()));
            writeFile(songJsonFile(name), bytes);
        }
    }

    private WebResourceResponse cachedApiResponse(Uri uri) {
        String path = uri.getPath();
        try {
            if ("/api/songs".equals(path) && songsListFile().exists()) {
                return fileResponse("application/json", songsListFile());
            }
            if ("/api/settings".equals(path)) {
                return jsonResponse(200, "{\"base_url\":\"\",\"model\":\"\",\"has_api_key\":false}");
            }
            if ("/api/convert-jobs".equals(path)) {
                return jsonResponse(200, "[]");
            }
            if ("/api/app/health".equals(path)) {
                return jsonResponse(200, "{\"ok\":true,\"name\":\"utapractice-apk\",\"offline\":true}");
            }

            String audioPrefix = "/api/songs/";
            if (path != null && path.startsWith(audioPrefix) && path.endsWith("/audio")) {
                String name = Uri.decode(path.substring(audioPrefix.length(), path.length() - "/audio".length()));
                File audio = audioFile(name);
                if (audio.exists()) return fileResponse(audioMimeFile(name), audio);
                return jsonResponse(404, "{\"error\":\"这首歌没有离线音频，请先同步\"}");
            }

            if (path != null && path.startsWith(audioPrefix)) {
                String name = Uri.decode(path.substring(audioPrefix.length()));
                File song = songJsonFile(name);
                if (song.exists()) return fileResponse("application/json", song);
                return jsonResponse(404, "{\"error\":\"这首歌没有离线缓存，请先同步\"}");
            }
        } catch (Exception error) {
            return jsonResponse(500, "{\"error\":\"读取 APK 离线缓存失败\"}");
        }
        return jsonResponse(503, "{\"error\":\"离线模式不支持这个接口\"}");
    }

    private WebResourceResponse cachedAudioResponse(Uri uri) throws IOException {
        String path = uri.getPath();
        if (path == null || !path.startsWith("/api/songs/") || !path.endsWith("/audio")) return null;
        String name = Uri.decode(path.substring("/api/songs/".length(), path.length() - "/audio".length()));
        File audio = audioFile(name);
        if (!audio.exists()) return null;
        return fileResponse(audioMimeFile(name), audio);
    }

    private class AndroidBridge {
        @JavascriptInterface
        public String getServerUrl() {
            return serverUrl();
        }

        @JavascriptInterface
        public void setServerUrl(String value) {
            prefs.edit().putString(KEY_SERVER_URL, cleanUrl(value)).apply();
        }

        @JavascriptInterface
        public String getCloudConfigUrl() {
            return prefs.getString(KEY_CLOUD_CONFIG_URL, "");
        }

        @JavascriptInterface
        public void loadCloudConfig(String value) {
            prefs.edit().putString(KEY_CLOUD_CONFIG_URL, cleanUrl(value)).apply();
            new Thread(() -> {
                try {
                    emit("cloud", "reading", 0, "正在读取云端配置");
                    String raw = new String(httpGetBytes(cleanUrl(value)), StandardCharsets.UTF_8);
                    JSONObject config = new JSONObject(raw);
                    String nextServer = cleanUrl(config.optString("default_base_url", config.optString("defaultBaseUrl", "")));
                    JSONArray servers = config.optJSONArray("servers");
                    if (nextServer.isEmpty() && servers != null && servers.length() > 0) {
                        JSONObject first = servers.optJSONObject(0);
                        if (first != null) nextServer = cleanUrl(first.optString("base_url", first.optString("baseUrl", first.optString("url", ""))));
                    }
                    if (nextServer.isEmpty()) throw new IOException("云端配置没有服务器地址");
                    prefs.edit().putString(KEY_SERVER_URL, nextServer).apply();
                    emit("cloud", "done", 100, nextServer);
                } catch (Exception error) {
                    emit("cloud", "failed", 0, "云端配置失败：" + error.getMessage());
                }
            }).start();
        }

        @JavascriptInterface
        public void syncAll() {
            new Thread(() -> {
                try {
                    emit("sync", "running", 0, "正在读取远端歌库");
                    byte[] listBytes = httpGetBytes(serverUrl() + "/api/songs");
                    writeFile(songsListFile(), listBytes);
                    JSONArray songs = new JSONArray(new String(listBytes, StandardCharsets.UTF_8));
                    int failed = 0;
                    for (int index = 0; index < songs.length(); index++) {
                        JSONObject summary = songs.optJSONObject(index);
                        if (summary == null) continue;
                        String name = summary.optString("name", "");
                        if (name.isEmpty()) continue;
                        int progress = Math.round(index * 100f / Math.max(songs.length(), 1));
                        emit("sync", "running", progress, "同步 " + (index + 1) + "/" + songs.length() + "：" + name);
                        try {
                            syncSong(name);
                        } catch (Exception error) {
                            failed += 1;
                        }
                    }
                    prefs.edit().putString(KEY_LAST_SYNC, String.valueOf(System.currentTimeMillis())).apply();
                    emit("sync", "done", 100, failed == 0 ? "同步完成；刷新歌库后可离线使用" : "同步完成，失败 " + failed + " 首；其余可离线使用");
                } catch (Exception error) {
                    emit("sync", "failed", 0, "同步失败：" + error.getMessage());
                }
            }).start();
        }
    }

    private void syncSong(String name) throws Exception {
        String encodedName = URLEncoder.encode(name, "UTF-8").replace("+", "%20");
        byte[] songBytes = httpGetBytes(serverUrl() + "/api/songs/" + encodedName);
        writeFile(songJsonFile(name), songBytes);

        JSONObject song = new JSONObject(new String(songBytes, StandardCharsets.UTF_8));
        if (!song.optBoolean("has_audio", false)) return;
        int key = song.optInt("saved_key", 0);
        HttpResult audio = httpGet(serverUrl() + "/api/songs/" + encodedName + "/audio?key=" + key);
        writeFile(audioFile(name), audio.bytes);
        writeText(audioMimeSidecar(name), audio.contentType == null ? "audio/mpeg" : audio.contentType);
    }

    private void emit(String channel, String status, int progress, String message) {
        try {
            JSONObject detail = new JSONObject();
            detail.put("channel", channel);
            detail.put("status", status);
            detail.put("progress", progress);
            detail.put("message", message);
            if ("cloud".equals(channel) && "done".equals(status)) detail.put("serverUrl", message);
            String script = "window.dispatchEvent(new CustomEvent('utapractice-android', { detail: " + detail + " }));";
            runOnUiThread(() -> webView.evaluateJavascript(script, null));
        } catch (Exception ignored) {
        }
    }

    private String serverUrl() {
        return cleanUrl(prefs.getString(KEY_SERVER_URL, DEFAULT_SERVER_URL));
    }

    private String cleanUrl(String value) {
        String text = value == null ? "" : value.trim();
        while (text.endsWith("/")) text = text.substring(0, text.length() - 1);
        return text.isEmpty() ? DEFAULT_SERVER_URL : text;
    }

    private HttpResult httpGet(String urlText) throws IOException {
        HttpURLConnection connection = (HttpURLConnection) new URL(urlText).openConnection();
        connection.setConnectTimeout(5000);
        connection.setReadTimeout(20000);
        connection.setRequestProperty("User-Agent", "utapractice-android");
        int status = connection.getResponseCode();
        if (status < 200 || status >= 300) throw new IOException("HTTP " + status);
        String contentType = connection.getContentType();
        try (InputStream input = connection.getInputStream()) {
            return new HttpResult(readAll(input), contentType);
        } finally {
            connection.disconnect();
        }
    }

    private byte[] httpGetBytes(String urlText) throws IOException {
        return httpGet(urlText).bytes;
    }

    private byte[] readAll(InputStream input) throws IOException {
        ByteArrayOutputStream output = new ByteArrayOutputStream();
        byte[] buffer = new byte[8192];
        int count;
        while ((count = input.read(buffer)) != -1) output.write(buffer, 0, count);
        return output.toByteArray();
    }

    private WebResourceResponse assetResponse(String mimeType, String assetPath) {
        try {
            return new WebResourceResponse(mimeType, "UTF-8", getAssets().open(assetPath));
        } catch (IOException error) {
            return jsonResponse(404, "{\"error\":\"asset not found\"}");
        }
    }

    private WebResourceResponse bytesResponse(String mimeType, byte[] bytes) {
        return new WebResourceResponse(mimeType, "UTF-8", new ByteArrayInputStream(bytes));
    }

    private WebResourceResponse fileResponse(String mimeType, File file) throws IOException {
        return new WebResourceResponse(mimeType, "UTF-8", new FileInputStream(file));
    }

    private WebResourceResponse jsonResponse(int status, String json) {
        WebResourceResponse response = bytesResponse("application/json", json.getBytes(StandardCharsets.UTF_8));
        response.setStatusCodeAndReasonPhrase(status, status == 200 ? "OK" : "Error");
        return response;
    }

    private String mimeForPath(String path) {
        if (path == null) return "application/octet-stream";
        if (path.endsWith(".html")) return "text/html";
        if (path.endsWith(".css")) return "text/css";
        if (path.endsWith(".js")) return "text/javascript";
        if (path.endsWith(".json") || path.startsWith("/api/")) return "application/json";
        if (path.endsWith(".webmanifest")) return "application/manifest+json";
        return "application/octet-stream";
    }

    private File cacheDir(String name) {
        File dir = new File(getFilesDir(), name);
        if (!dir.exists()) dir.mkdirs();
        return dir;
    }

    private File songsListFile() {
        return new File(cacheDir("cache"), "songs.json");
    }

    private File songJsonFile(String name) {
        return new File(cacheDir("songs"), safeName(name) + ".json");
    }

    private File audioFile(String name) {
        return new File(cacheDir("audio"), safeName(name) + ".bin");
    }

    private File audioMimeSidecar(String name) {
        return new File(cacheDir("audio"), safeName(name) + ".mime");
    }

    private String audioMimeFile(String name) {
        File sidecar = audioMimeSidecar(name);
        if (!sidecar.exists()) return "audio/mpeg";
        try (InputStream input = new FileInputStream(sidecar)) {
            return new String(readAll(input), StandardCharsets.UTF_8).trim();
        } catch (IOException error) {
            return "audio/mpeg";
        }
    }

    private String safeName(String value) {
        return Base64.encodeToString(value.getBytes(StandardCharsets.UTF_8), Base64.URL_SAFE | Base64.NO_WRAP);
    }

    private void writeFile(File file, byte[] bytes) throws IOException {
        File parent = file.getParentFile();
        if (parent != null && !parent.exists()) parent.mkdirs();
        try (FileOutputStream output = new FileOutputStream(file)) {
            output.write(bytes);
        }
    }

    private void writeText(File file, String value) throws IOException {
        writeFile(file, value.getBytes(StandardCharsets.UTF_8));
    }

    @Override
    public void onBackPressed() {
        if (webView != null && webView.canGoBack()) {
            webView.goBack();
            return;
        }
        super.onBackPressed();
    }

    private static class HttpResult {
        final byte[] bytes;
        final String contentType;

        HttpResult(byte[] bytes, String contentType) {
            this.bytes = bytes;
            this.contentType = contentType;
        }
    }
}
