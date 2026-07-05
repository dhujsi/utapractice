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
  assert.match(indexHtml, /id="lyricsUploadButton"/);
  assert.match(indexHtml, /id="audioUploadStatus"/);
  assert.match(indexHtml, /id="lyricsUploadStatus"/);
  assert.match(appJs, /audioTargetSongSelect/);
  assert.match(appJs, /audioUploadButton/);
  assert.match(appJs, /lyricsUploadButton/);
  assert.match(appJs, /target_song/);
  assert.match(appJs, /has_lyrics && !song\.has_audio/);
});

test("audio upload endpoint can attach one arbitrary-named file to a lyric-only song", () => {
  assert.match(webApp, /target_song = sanitize_filename\(request\.form\.get\("target_song", ""\)\.strip\(\)\)/);
  assert.match(webApp, /if target_song and len\(files\) != 1:/);
  assert.match(webApp, /if not song\["lyrics_path"\]:/);
  assert.match(webApp, /if song\["audio_path"\]:/);
  assert.match(webApp, /target = SONG_DIR \/ f"\{target_song\}\{suffix\}"/);
});

test("main web page has exactly one shared audio element", () => {
  assert.equal((indexHtml.match(/id="audio"/g) || []).length, 1);
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
