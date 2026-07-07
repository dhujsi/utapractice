const { readFileSync } = require("node:fs");
const { test } = require("node:test");
const assert = require("node:assert/strict");

const androidMain = readFileSync("android/app/src/main/java/com/utapractice/app/MainActivity.java", "utf8");
const appJs = readFileSync("web_static/app.js", "utf8");
const appCss = readFileSync("web_static/app.css", "utf8");
const indexHtml = readFileSync("templates/index.html", "utf8");
const webApp = readFileSync("web_app.py", "utf8");

test("APK local audio responses implement HTTP Range semantics", () => {
  assert.match(androidMain, /getRequestHeaders\(\)\.get\("Range"\)/);
  assert.match(androidMain, /parseRangeHeader\(/);
  assert.match(androidMain, /206,\s*"Partial Content"/);
  assert.match(androidMain, /"Accept-Ranges",\s*"bytes"/);
  assert.match(androidMain, /"Content-Range"/);
  assert.match(androidMain, /"Content-Length"/);
  assert.match(androidMain, /new BoundedInputStream\(/);
});

test("lyric click seeks after audio metadata is ready", () => {
  assert.match(appJs, /function seekAudioTo\(/);
  assert.match(appJs, /loadedmetadata/);
  assert.match(appJs, /canplay/);
  assert.match(appJs, /seekAudioTo\(Number\(line\.time \|\| 0\), \{ play: true \}\)/);
  assert.doesNotMatch(appJs, /els\.audio\.currentTime = Number\(line\.time \|\| 0\);\n\s*els\.audio\.play/);
});

test("mobile sidebar swipe is implemented in the shared web UI", () => {
  assert.match(appJs, /document\.addEventListener\("touchstart", onSidebarSwipeStart/);
  assert.match(appJs, /document\.addEventListener\("touchmove", onSidebarSwipeMove/);
  assert.match(appJs, /document\.addEventListener\("touchend", onSidebarSwipeEnd/);
  assert.match(appJs, /EDGE_SWIPE_WIDTH/);
});

test("mobile sidebar swipe can start on generator form controls", () => {
  const ignoreFunction = appJs.match(/function shouldIgnoreSidebarSwipe\(target\) \{[\s\S]*?\n\}/)?.[0] || "";
  assert.ok(ignoreFunction);
  assert.doesNotMatch(ignoreFunction, /button|input|textarea|select/);
});

test("web safe-area spacing is only enabled inside the APK shell", () => {
  assert.match(appCss, /--safe-top:\s*0px/);
  assert.match(appCss, /:root\.android-shell\s*\{[\s\S]*--safe-top:\s*env\(safe-area-inset-top,\s*0px\)/);
  assert.match(appJs, /document\.documentElement\.classList\.add\("android-shell"\)/);
});

test("library upload UI exposes statuses and manual audio target binding", () => {
  assert.match(indexHtml, /id="audioTargetSongSelect"/);
  assert.match(indexHtml, /id="audioUploadButton"/);
  assert.match(indexHtml, /id="lyricsTargetSongSelect"/);
  assert.match(indexHtml, /id="lyricsSongNameInput"/);
  assert.match(indexHtml, /id="lyricsTextType"/);
  assert.match(indexHtml, /id="lyricsTextInput"/);
  assert.match(indexHtml, /id="saveLyricsText"/);
  assert.match(indexHtml, /id="lyricsUploadButton"/);
  assert.match(indexHtml, /id="audioUploadStatus"/);
  assert.match(indexHtml, /id="lyricsUploadStatus"/);
  assert.match(appJs, /audioTargetSongSelect/);
  assert.match(appJs, /audioUploadButton/);
  assert.match(appJs, /lyricsTargetSongSelect/);
  assert.match(appJs, /lyricsSongNameInput/);
  assert.match(appJs, /lyricsTextType/);
  assert.match(appJs, /lyricsTextInput/);
  assert.match(appJs, /saveLyricsText/);
  assert.match(appJs, /lyricsUploadButton/);
  assert.match(appJs, /target_song/);
  assert.match(appJs, /has_lyrics && !song\.has_audio/);
  assert.match(appJs, /song\.has_audio && !song\.has_lyrics/);
});

test("audio upload endpoint can attach one arbitrary-named file to a lyric-only song", () => {
  assert.match(webApp, /target_song = sanitize_filename\(request\.form\.get\("target_song", ""\)\.strip\(\)\)/);
  assert.match(webApp, /if target_song and len\(files\) != 1:/);
  assert.match(webApp, /if not song\["lyrics_path"\]:/);
  assert.match(webApp, /if song\["audio_path"\]:/);
  assert.match(webApp, /target = SONG_DIR \/ f"\{target_song\}\{suffix\}"/);
});

test("lyrics upload and typed lyrics can attach to an audio-only song", () => {
  assert.match(webApp, /@app\.post\("\/api\/upload\/lyrics-text"\)/);
  assert.match(webApp, /target_song = sanitize_filename\(request\.form\.get\("target_song", ""\)\.strip\(\)\)/);
  assert.match(webApp, /payload\.get\("target_song"/);
  assert.match(webApp, /lyrics_type = str\(payload\.get\("lyrics_type", "lrc"\)\)/);
  assert.match(webApp, /parse_lrc\(lyrics_text\)/);
  assert.match(webApp, /json\.loads\(lyrics_text\)/);
  assert.match(webApp, /Target song already has lyrics/);
  assert.match(appJs, /\/api\/upload\/lyrics-text/);
  assert.match(appJs, /renderLyricsTargetOptions/);
});

test("mobile sidebar stays open when switching side pages", () => {
  const setPageFunction = appJs.match(/function setPage\(page\) \{[\s\S]*?\n\}/)?.[0] || "";
  assert.ok(setPageFunction);
  assert.doesNotMatch(setPageFunction, /classList\.remove\("open"\)/);
  assert.match(appJs, /function closeSidebarOnMobile\(\)/);
  assert.match(appJs, /els\.libraryLoadSong\.addEventListener\("click",[\s\S]*closeSidebarOnMobile\(\)/);
});

test("mobile sidebar uses a backdrop so player controls do not receive outside taps", () => {
  assert.match(indexHtml, /id="sidebarBackdrop"/);
  assert.match(appJs, /sidebarBackdrop: document\.getElementById\("sidebarBackdrop"\)/);
  assert.match(appJs, /function openSidebarOnMobile\(\)/);
  assert.match(appJs, /function closeSidebar\(\)/);
  assert.match(appJs, /els\.appShell\.classList\.toggle\("sidebar-open"/);
  assert.match(appJs, /els\.sidebarBackdrop\.addEventListener\("click", closeSidebar\)/);
  assert.match(appCss, /\.sidebar-backdrop/);
  assert.match(appCss, /\.app-shell\.sidebar-open \.sidebar-backdrop/);
});

test("toast and touch button feedback do not block immediate follow-up taps", () => {
  const toastCss = appCss.match(/\.toast\s*\{[\s\S]*?\n\}/)?.[0] || "";
  assert.match(toastCss, /pointer-events:\s*none/);
  assert.match(appCss, /@media \(hover: hover\) and \(pointer: fine\)/);
  assert.match(appCss, /button:disabled/);
});

test("main web page has exactly one shared audio element", () => {
  assert.equal((indexHtml.match(/id="audio"/g) || []).length, 1);
});

test("lyrics display has a separate ruby toggle and no translation-only mode", () => {
  assert.doesNotMatch(indexHtml, /value="translation"/);
  assert.doesNotMatch(indexHtml, /仅译文/);
  assert.match(indexHtml, /id="rubyToggle"/);
  assert.match(indexHtml, /假名标注/);
  assert.match(indexHtml, />备注<\/span>/);
  assert.match(appJs, /showRuby: true/);
  assert.match(appJs, /function stripRubyMarkup\(/);
  assert.match(appJs, /els\.rubyToggle\.addEventListener\("change"/);
  assert.doesNotMatch(appJs, /state\.displayMode === "translation"/);
});

test("APK optional sync panel does not expose cloud config loading", () => {
  assert.doesNotMatch(indexHtml, /apkCloudUrl/);
  assert.doesNotMatch(indexHtml, /apkLoadCloud/);
  assert.doesNotMatch(indexHtml, /读取云端/);
  assert.doesNotMatch(appJs, /loadCloudConfig/);
  assert.doesNotMatch(androidMain, /loadCloudConfig/);
  assert.match(indexHtml, /可选同步后端地址/);
  assert.match(indexHtml, /id="apkSyncAll"/);
});

test("completed workspace jobs can reopen generated lyrics for preview and publishing", () => {
  assert.match(appJs, /function workspaceJobReadyForPublish\(job\)/);
  assert.match(appJs, /async function openWorkspaceJob\(job\)/);
  assert.match(appJs, /setPage\("generator"\)/);
  assert.match(appJs, /await loadWorkspace\(job\.song_name\)/);
  assert.match(appJs, /await previewGenerated\(\{ refreshWorkspace: true \}\)/);
  assert.match(appJs, /button\.textContent = "打开工作源"/);
  assert.match(appJs, /button\.textContent = "发布正式歌词"/);
});

test("legacy lyric conversion jobs are labeled as already published", () => {
  assert.match(appJs, /旧版任务已直接写入正式歌词/);
  assert.match(appJs, /job\.type !== "generate_ruby_from_rows"/);
});

test("APK implements local-first JSON write API through Android bridge", () => {
  assert.match(androidMain, /apiRequest\(String method, String path, String body\)/);
  assert.match(androidMain, /handleLocalPost\(/);
  assert.match(androidMain, /handleMetaPost\(/);
  assert.match(androidMain, /handleLyricsPost\(/);
  assert.match(androidMain, /handleLyricsTextPost\(/);
  assert.match(androidMain, /localSongsListJson\(/);
  assert.match(androidMain, /upsertLocalSong\(/);
  assert.doesNotMatch(androidMain, /APK 离线壳暂不支持这个写操作；请在网页端执行/);
  assert.match(appJs, /androidBridgeRequestJson\(/);
  assert.match(appJs, /window\.UtaPracticeAndroid\.apiRequest/);
});

test("APK exposes Android file import bridge for local audio and lyrics", () => {
  assert.match(androidMain, /chooseAudioForSong\(String songName\)/);
  assert.match(androidMain, /chooseLyricsForSong\(String songName\)/);
  assert.match(androidMain, /ACTION_OPEN_DOCUMENT/);
  assert.match(androidMain, /handlePickedImportFile\(/);
  assert.match(appJs, /importAndroidAudioFile\(/);
  assert.match(appJs, /importAndroidLyricsFile\(/);
  assert.match(appJs, /chooseAudioForSong/);
  assert.match(appJs, /chooseLyricsForSong/);
});

test("APK stores AI settings locally instead of proxying them to the sync server", () => {
  assert.match(androidMain, /settingsFile\(\)/);
  assert.match(androidMain, /localSettingsJson\(/);
  assert.match(androidMain, /handleSettingsPost\(/);
  assert.match(androidMain, /handleSettingsTestPost\(/);
  assert.match(androidMain, /openAiChatCompletionsUrl\(/);
  assert.match(androidMain, /"\/api\/settings"\.equals\(path\)/);
  assert.match(androidMain, /"\/api\/settings\/test"\.equals\(path\)/);
  assert.match(appJs, /requestJson\("\/api\/settings"/);
  assert.match(appJs, /requestJson\("\/api\/settings\/test"/);
});

test("APK does not use a hard-coded sync server as an implicit backend", () => {
  assert.doesNotMatch(androidMain, /192\.168\.68\.200:8502/);
  assert.doesNotMatch(indexHtml, /192\.168\.68\.200:8502/);
  assert.match(androidMain, /private static final String DEFAULT_SERVER_URL = ""/);
  assert.match(androidMain, /return text;/);
  assert.match(androidMain, /if \(baseUrl\.isEmpty\(\)\) throw new IOException\("请先填写同步服务器地址"\)/);
  assert.match(androidMain, /if \(baseUrl\.isEmpty\(\)\) throw new IOException\("这个功能需要先配置可选后端"\)/);
});

test("APK startup GET APIs are answered locally before any optional sync backend", () => {
  const cachedFirst = androidMain.match(/private WebResourceResponse cachedFirstResponse\(WebResourceRequest request\)[\s\S]*?\n    private void cacheGetResponse/)?.[0] || "";
  assert.match(cachedFirst, /"\/api\/songs"\.equals\(path\)/);
  assert.match(cachedFirst, /"\/api\/settings"\.equals\(path\)/);
  assert.match(cachedFirst, /"\/api\/convert-jobs"\.equals\(path\)/);
  assert.match(cachedFirst, /"\/api\/app\/health"\.equals\(path\)/);
  assert.match(cachedFirst, /return jsonResponse\(404, "\{\\"error\\":\\"本地歌库没有这首歌\\"\}"\)/);
  assert.match(cachedFirst, /return jsonResponse\(404, "\{\\"error\\":\\"这首歌没有本地音频，请先导入或同步\\"\}"\)/);
});

test("APK generator workspace APIs are local and do not require the optional sync backend", () => {
  assert.match(androidMain, /workspaceFile\(String name\)/);
  assert.match(androidMain, /jobsFile\(\)/);
  assert.match(androidMain, /handleWorkspaceSavePost\(/);
  assert.match(androidMain, /handleWorkspacePublishPost\(/);
  assert.match(androidMain, /handleConvertJobPost\(/);
  assert.match(androidMain, /runLocalRubyJob\(/);
  assert.match(androidMain, /performLocalRubyGeneration\(/);
  assert.match(androidMain, /localJobsListJson\(/);
  assert.match(androidMain, /path\.startsWith\("\/api\/lyrics-workspace\/"\)/);
  assert.match(androidMain, /"\/api\/convert-jobs"\.equals\(path\)/);
  assert.match(androidMain, /startLocalRubyJob\(jobId, songName/);
  assert.match(androidMain, /openAiChatCompletionsUrl\(settings\.optString\("base_url", ""\)\)/);
  assert.match(androidMain, /unsupportedJsonMode\(/);
  assert.match(androidMain, /request\.remove\("response_format"\)/);
  assert.match(androidMain, /httpRequest\(method, urlText, body, extraHeaders, 10000, 120000\)/);
  assert.match(androidMain, /setReadTimeout\(readTimeoutMs\)/);
});

test("APK can search and preview LRCLIB without the optional sync backend", () => {
  assert.match(androidMain, /handleLyricsSearchPost\(/);
  assert.match(androidMain, /handleLyricsPreviewPost\(/);
  assert.match(androidMain, /searchLrclib\(/);
  assert.match(androidMain, /previewLrclib\(/);
  assert.match(androidMain, /https:\/\/lrclib\.net\/api\/search/);
  assert.match(androidMain, /https:\/\/lrclib\.net\/api\/get\//);
});

test("web lyric search uses resilient provider calls instead of hanging on slow or broken sources", () => {
  assert.match(webApp, /SEARCH_PROVIDER_TIMEOUT_SECONDS\s*=\s*6/);
  assert.match(webApp, /SEARCH_AGGREGATE_TIMEOUT_SECONDS\s*=\s*7/);
  assert.match(webApp, /SEARCH_HTTP_TIMEOUT_SECONDS\s*=\s*6/);
  assert.match(webApp, /def search_lrclib\(song_name, artist="", album=""\):[\s\S]*"q": broad_query/);
  assert.match(webApp, /def merge_search_results\(/);
  assert.match(webApp, /def search_qq\(song_name, artist="", album=""\):[\s\S]*smartbox_new\.fcg/);
  assert.doesNotMatch(webApp, /client_search_cp\?/);
  assert.match(webApp, /as_completed\(futures\.values\(\), timeout=SEARCH_AGGREGATE_TIMEOUT_SECONDS\)/);
  assert.match(webApp, /for provider_name, future in futures\.items\(\):[\s\S]*future\.cancel\(\)/);
  assert.match(webApp, /executor\.shutdown\(wait=False, cancel_futures=True\)/);
});

test("lyrics and audio library mutations reload the affected song before playback continues", () => {
  assert.match(appJs, /async function refreshSongsAfterLibraryMutation\(affectedName = ""\)/);
  assert.match(appJs, /await loadSong\(reloadName\)/);
  assert.match(appJs, /refreshSongsAfterLibraryMutation\(result\.song_name \|\| formFields\.target_song \|\| formFields\.song_name\)/);
  assert.match(appJs, /refreshSongsAfterLibraryMutation\(result\.song_name \|\| target_song \|\| song_name\)/);
  assert.match(appJs, /const previousCurrent = state\.current\?\.name \|\| ""/);
  assert.match(appJs, /refreshSongsAfterLibraryMutation\(detail\.song_name \|\| previousCurrent\)/);
});

test("APK lyric search can use QQ locally without the optional sync backend", () => {
  assert.match(androidMain, /SEARCH_TIMEOUT_MS = 6000/);
  assert.match(androidMain, /appendQuery\(broad, "q", \(songName \+ " " \+ artist\)\.trim\(\)\)/);
  assert.match(androidMain, /private JSONArray searchQq\(/);
  assert.match(androidMain, /private JSONObject previewQq\(/);
  assert.match(androidMain, /smartbox_new\.fcg/);
  assert.match(androidMain, /fcg_query_lyric_new\.fcg/);
  assert.match(androidMain, /mergeSearchResults\(/);
  assert.match(androidMain, /"qq"\.equals\(provider\)/);
  assert.doesNotMatch(androidMain, /暂只支持 LRCLIB/);
});
