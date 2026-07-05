const { readFileSync } = require("node:fs");
const { test } = require("node:test");
const assert = require("node:assert/strict");

const androidMain = readFileSync("android/app/src/main/java/com/utapractice/app/MainActivity.java", "utf8");
const appJs = readFileSync("web_static/app.js", "utf8");

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
