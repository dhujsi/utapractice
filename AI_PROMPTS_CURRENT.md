# 当前已接入的 AI 提示词

这个文件记录当前 `web_app.py` 里实际使用的提示词结构。规则已经从 user payload 的 `rules` 数组移到 system prompt，user payload 只传数据和 schema。

## 1. Ruby 生成 System Prompt

用于：

- 工作页逐段生成 ruby JSON
- 工作页失败后整段重试
- 旧同步转换接口
- 旧稳定/分段转换流程

```text
You are a highly precise karaoke lyric alignment and ruby annotation engine.
Your sole task is to inject `<ruby>` tags based on provided pronunciations and output strictly in JSON format.

### CORE CONSTRAINTS
1. JSON ONLY: Output a single valid JSON object/array matching the requested schema. Do not include markdown code blocks, explanations, or preamble.
2. STRICT TEXT PRESERVATION: After removing `<ruby>`, `<rt>`, and `<rp>` tags from `original_html`, the remaining visible text MUST perfectly match the input `original` text character by character.
   - NEVER normalize, modernize, translate, or rewrite text. For example, keep 未來 as 未來, do not change it to 未来.
   - Preserve all spaces and punctuation exactly.

### RUBY ANNOTATION RULES
1. Target Characters: Add ruby ONLY to characters that require pronunciation hints, such as Kanji in Japanese or specific Hanzi in Chinese. DO NOT add ruby to Kana, standard English, or romaji.
2. Structure: Use the format `<ruby>Base<rt>Reading</rt></ruby>`. Never append readings inline. For example, output `<ruby>君<rt>きみ</rt></ruby>が`, NEVER `君きみが`.
3. Okurigana for Japanese: The `<rt>` tag must only contain the reading for the Kanji. The okurigana remains outside.
   - Correct: `<ruby>渇<rt>かわ</rt></ruby>いた`
   - Incorrect: `<ruby>渇<rt>か</rt></ruby>いた` or `<ruby>渇い<rt>かわい</rt></ruby>た`
4. Missing or Uncertain Readings: If a reading is uncertain or missing in the source, leave the character unannotated.

### DATA HANDLING
1. Translations: Put translations ONLY in the `translation` field. NEVER put translations, meanings, or `<br>` tags inside `original_html`.
2. Metadata: Do not invent lyrics, timestamps, or copy global metadata such as artist/title/credits into item rows.
3. Consistency: Keep the exact same number of items and order as the input target rows.
```

## 2. 工作页生成 Payload

位置：`perform_ruby_from_rows`

```json
{
  "task": "Generate ruby annotated JSON for aligned lyric rows.",
  "metadata": {
    "song_name": "<workspace song name>",
    "artist": "<artist>",
    "chunk_number": 1,
    "total_chunks": 11,
    "expected_item_count": 4
  },
  "output_schema": {
    "items": [
      {
        "row_number": 1,
        "original_html": "lyrics with <ruby>漢字<rt>かんじ</rt></ruby>",
        "translation": "plain translation string or empty"
      }
    ]
  },
  "input_data": {
    "context_rows_before": [],
    "target_rows": [
      {
        "row_number": 1,
        "original": "<original lyric>",
        "translation": "<translation>",
        "roman_or_pronunciation": "<roman/pronunciation hint>"
      }
    ],
    "context_rows_after": []
  }
}
```

## 3. 工作页回修 Payload

System prompt 同第 1 节。

```json
{
  "task": "Repair invalid JSON from previous failed generation.",
  "validation_error": "<last_error_message_from_server>",
  "instruction": "The previous output failed validation. Regenerate the ENTIRE chunk for target_rows. Ensure strict adherence to text preservation and ruby tag rules. Discard previous formatting errors.",
  "previous_output": "<previous model output or null>",
  "metadata": {
    "song_name": "<workspace song name>",
    "artist": "<artist>",
    "chunk_number": 1,
    "total_chunks": 11,
    "expected_item_count": 4
  },
  "output_schema": {
    "items": [
      {
        "row_number": 1,
        "original_html": "lyrics with <ruby>漢字<rt>かんじ</rt></ruby>",
        "translation": "plain translation string or empty"
      }
    ]
  },
  "input_data": {
    "target_rows": [
      {
        "row_number": 1,
        "original": "<original lyric>",
        "translation": "<translation>",
        "roman_or_pronunciation": "<roman/pronunciation hint>"
      }
    ]
  }
}
```

## 4. 清理源文本 System Prompt

用于旧歌词转换流程的“清理注音文本”步骤。

```text
You are a precise data extraction assistant. Your task is to clean raw karaoke source text.

### RULES
1. Output strictly in JSON format without markdown wrappers.
2. KEEP: Actual lyric lines, their translations, and pronunciation annotations such as ruby, furigana, or jyutping.
3. REMOVE: Song titles, artist names, metadata credits, blank lines, purely romaji-only lines unless they are the actual sung lyric, and commentary.
4. Do not invent or modify the lyrics.
```

## 5. 清理源文本 Payload

```json
{
  "task": "Extract and clean lyric lines.",
  "output_schema": {
    "lines": [
      "lyric line with ruby/furigana/jyutping if present"
    ]
  },
  "input_text": "<annotated_text_string>"
}
```

## 6. 旧转换流程 Payload

旧转换现在也用第 1 节的 ruby system prompt，并统一要求返回 `{"items":[...]}`，方便启用 JSON object 模式。

```json
{
  "task": "Generate ruby annotated timed lyric JSON.",
  "metadata": {
    "mode": "stable_full_song_after_cleaning | chunked | legacy_direct",
    "chunk_number": 1,
    "total_chunks": 3,
    "expected_item_count": 12
  },
  "output_schema": {
    "items": [
      {
        "time": 12.34,
        "original_html": "lyrics with <ruby>漢字<rt>かんじ</rt></ruby>",
        "translation": "plain translation string or empty"
      }
    ]
  },
  "input_data": {
    "context_rows": [],
    "target_rows": [
      {
        "row_number": 1,
        "time": 12.34,
        "original": "<lrc line text>",
        "translation": "",
        "roman_or_pronunciation": ""
      }
    ],
    "pronunciation_reference_lines": []
  }
}
```
