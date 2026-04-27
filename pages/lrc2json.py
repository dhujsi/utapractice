import json
import os
import re
from pathlib import Path

import streamlit as st
from openai import OpenAI

SONG_DIR = "songs"
os.makedirs(SONG_DIR, exist_ok=True)


def parse_lrc_title(lrc_text: str) -> str:
    """从LRC元信息中解析标题，优先 [ti:xxx]。"""
    m = re.search(r"\[ti:(.*?)\]", lrc_text, flags=re.IGNORECASE)
    if m and m.group(1).strip():
        return m.group(1).strip()
    return ""


def extract_json_from_text(text: str):
    """容错提取 JSON 数组。"""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)

    # 先尝试整体解析
    try:
        return json.loads(text)
    except Exception:
        pass

    # 再尝试抓第一个数组
    start = text.find("[")
    end = text.rfind("]")
    if start != -1 and end != -1 and end > start:
        return json.loads(text[start : end + 1])

    raise ValueError("模型输出中未找到可解析的 JSON 数组")


def normalize_lyrics_items(data):
    """规范化输出结构，兼容 app.py 的读取逻辑。"""
    if not isinstance(data, list):
        raise ValueError("JSON 根节点必须是数组")

    normalized = []
    for i, item in enumerate(data):
        if not isinstance(item, dict):
            raise ValueError(f"第 {i+1} 行不是对象")

        if "time" not in item or "original_html" not in item:
            raise ValueError(f"第 {i+1} 行缺少 time 或 original_html")

        try:
            t = round(float(item["time"]), 3)
        except Exception as e:
            raise ValueError(f"第 {i+1} 行 time 不是数字: {e}")

        normalized.append(
            {
                "time": t,
                "original_html": str(item.get("original_html", "")).strip(),
                "translation": str(item.get("translation", "")).strip(),
            }
        )

    normalized.sort(key=lambda x: x["time"])
    return normalized


def call_ark_model(lyrics_with_furigana_or_jyutping: str, lrc_or_timed_text: str):
    api_key = os.getenv("ARK_API_KEY")
    if not api_key:
        raise RuntimeError("未检测到环境变量 ARK_API_KEY，请先在系统或启动命令中设置。")

    client = OpenAI(
        base_url="https://ark.cn-beijing.volces.com/api/v3",
        api_key=api_key,
    )

    system_prompt = (
        "你是歌词对齐与格式化助手。"
        "请严格输出 JSON 数组，不要输出任何解释、不要输出 markdown 代码块。"
        "JSON 每一项必须包含字段: time(number), original_html(string), translation(string)。"
        "其中 original_html 必须使用 HTML，可包含 <ruby><rt></rt></ruby> 与 <br>。"
        "如果输入1包含日语假名或粤语注音，必须转写为 ruby 格式。"
        "禁止把注音保留成括号、空格后缀或纯文本标注，必须写进 <rt>。"
        "例如：'你(nei5)' 必须输出为 '<ruby>你<rt>nei5</rt></ruby>'。"
        "translation 若未知可填空字符串。"
        "time 必须来自带时间轴文本，不要虚构时间。"
        "行数尽量与时间轴歌词逐行对应。"
    )

    user_prompt = f"""
任务：根据两份输入合成播放器可用 JSON。

输入1（带粤语注音或日语假名歌词文本）：
{lyrics_with_furigana_or_jyutping}

输入2（带时间轴的 lrc 或文本）：
{lrc_or_timed_text}

输出要求：
1) 仅输出 JSON 数组；
2) 每项格式：{{"time": 12.345, "original_html": "...", "translation": "..."}}；
3) original_html 使用输入1中的内容，必要换行用 <br>；
4) 日语假名注音与粤语注音都必须写入 ruby/rt：
    - 例：君(きみ) -> <ruby>君<rt>きみ</rt></ruby>
    - 例：你(nei5) -> <ruby>你<rt>nei5</rt></ruby>
    - 不允许输出 "你(nei5)" 这种括号注音形式；
5) translation 可空字符串；
6) 不要漏字段。
"""

    completion = client.chat.completions.create(
        model="ep-20260208224806-h8zp7",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.2,
    )

    return completion.choices[0].message.content or ""


st.set_page_config(page_title="LRC2JSON", layout="wide")
st.title("🎼 LRC2JSON（AI 辅助）")
st.caption("把“注音歌词文本 + 时间轴歌词”合成为当前应用可直接使用的 JSON。")

with st.expander("使用说明", expanded=False):
    st.markdown(
        """
- 输入1：粘贴带粤语注音或日语假名的歌词文本（可含 ruby）。
- 输入2：粘贴或上传 `.lrc/.txt` 时间轴歌词。
- 点击“生成 JSON”后，先看预览效果，再保存到 `songs/`。
- 保存文件名优先使用 LRC 的 `[ti:xxx]`，否则用你输入的名称。
        """
    )

col_left, col_right = st.columns(2)

with col_left:
    st.subheader("1) 注音歌词文本")
    input1 = st.text_area(
        "粘贴带注音的歌词文本",
        height=320,
        placeholder="例如包含日语假名注音或粤语注音的歌词...",
    )

with col_right:
    st.subheader("2) 时间轴歌词（LRC/TXT）")
    uploaded_timed = st.file_uploader("上传 .lrc 或 .txt", type=["lrc", "txt"])
    timed_text = st.text_area(
        "或直接粘贴时间轴文本",
        height=260,
        placeholder="例如: [00:12.34]歌词...",
    )

    if uploaded_timed is not None:
        try:
            file_text = uploaded_timed.read().decode("utf-8")
        except UnicodeDecodeError:
            file_text = uploaded_timed.read().decode("utf-8", errors="ignore")

        if not timed_text.strip():
            timed_text = file_text
            st.success("已使用上传文件内容填充时间轴文本。")

name_col1, name_col2 = st.columns([2, 1])
with name_col1:
    suggested_name = parse_lrc_title(timed_text) if timed_text.strip() else ""
    song_name = st.text_input(
        "歌曲名（保存为 songs/<歌曲名>.json）",
        value=suggested_name,
        placeholder="若留空，生成后会提示你填写",
    )
with name_col2:
    st.write("")
    st.write("")
    do_generate = st.button("🚀 生成 JSON", type="primary", use_container_width=True)

if do_generate:
    if not input1.strip() or not timed_text.strip():
        st.error("请先提供输入1和输入2。")
    else:
        with st.spinner("AI 正在对齐歌词并生成 JSON..."):
            model_output = ""
            try:
                model_output = call_ark_model(input1.strip(), timed_text.strip())
                raw_data = extract_json_from_text(model_output)
                parsed = normalize_lyrics_items(raw_data)

                st.session_state["lrc2json_result"] = parsed
                st.session_state["lrc2json_raw"] = model_output
                if song_name.strip():
                    st.session_state["lrc2json_song_name"] = song_name.strip()
                elif suggested_name:
                    st.session_state["lrc2json_song_name"] = suggested_name
                else:
                    st.session_state["lrc2json_song_name"] = ""

                st.success(f"生成完成，共 {len(parsed)} 行。请先检查预览后再保存。")
            except Exception as e:
                st.error(f"生成失败：{e}")
                if model_output:
                    st.session_state["lrc2json_raw"] = model_output
                    with st.expander("模型原始返回（调试）", expanded=True):
                        st.text_area(
                            "请把这段内容发给我排查",
                            value=model_output,
                            height=260,
                            key="lrc2json_raw_error_view",
                        )

if "lrc2json_result" in st.session_state:
    result = st.session_state["lrc2json_result"]

    st.divider()
    st.subheader("🔍 预览效果（防止出错）")

    preview_mode = st.selectbox("预览模式", ["原文 + 译文", "仅原文", "仅译文"], index=0)

    # 简单效果预览（与主应用展示逻辑一致）
    preview_lines = []
    for item in result:
        original = item.get("original_html", "")
        trans = item.get("translation", "")

        if preview_mode == "仅原文":
            text = original
        elif preview_mode == "仅译文":
            text = trans
        else:
            text = f"{original}<br><small style='color:#999'>{trans}</small>"

        preview_lines.append(
            f"<div style='padding:8px 12px;margin:4px 0;border-radius:8px;background:#11111108;line-height:1.9'>"
            f"<span style='color:#888;font-size:12px'>[{item['time']:.3f}]</span> {text}</div>"
        )

    st.markdown(
        """
<style>
ruby rt { font-size: 0.7em; color: #B0B0B0; }
</style>
""",
        unsafe_allow_html=True,
    )
    st.markdown("".join(preview_lines), unsafe_allow_html=True)

    st.subheader("🧾 JSON 结果")
    st.code(json.dumps(result, ensure_ascii=False, indent=2), language="json")

    dl_col, save_col = st.columns(2)

    with dl_col:
        download_name = (st.session_state.get("lrc2json_song_name") or "lyrics") + ".json"
        st.download_button(
            "下载 JSON",
            data=json.dumps(result, ensure_ascii=False, indent=2).encode("utf-8"),
            file_name=download_name,
            mime="application/json",
            use_container_width=True,
        )

    with save_col:
        save_name = st.text_input(
            "确认保存文件名",
            value=st.session_state.get("lrc2json_song_name", ""),
            key="lrc2json_save_name_input",
            placeholder="例如：トゲナシトゲアリ - 雑踏、僕らの街",
        )

        if st.button("💾 保存到 songs", use_container_width=True):
            final_name = (save_name or "").strip()
            if not final_name:
                st.error("请先填写歌曲名再保存。")
            else:
                safe_name = re.sub(r'[\\/*?:"<>|]', "_", final_name)
                output_path = Path(SONG_DIR) / f"{safe_name}.json"
                with open(output_path, "w", encoding="utf-8") as f:
                    json.dump(result, f, ensure_ascii=False, indent=2)
                st.success(f"已保存：{output_path}")

if "lrc2json_raw" in st.session_state:
    with st.expander("最近一次模型原始返回", expanded=False):
        st.text_area(
            "原始文本（用于排查 JSON 解析失败）",
            value=st.session_state.get("lrc2json_raw", ""),
            height=220,
            key="lrc2json_raw_latest",
        )
