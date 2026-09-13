# AI 注音生成合约

本文件描述当前唯一的 AI 歌词流程。提示词的可执行真源位于 `web_app.py` 的
`RUBY_GENERATION_SYSTEM_PROMPT`；APK 在本地后端中实现相同的数据约束。

## 输入

“歌词制作”页先把原文、翻译和读音来源对齐为草稿行。生成任务只接受
`generate_ruby_from_rows` 类型，并按段提交以下数据：

```json
{
  "task": "Generate ruby annotated JSON for aligned lyric rows.",
  "metadata": {
    "song_name": "歌曲名",
    "artist": "歌手",
    "chunk_number": 1,
    "total_chunks": 8,
    "expected_item_count": 8
  },
  "output_schema": {
    "items": [
      {
        "row_number": 1,
        "original_html": "<ruby>歌<rt>うた</rt></ruby>",
        "translation": "翻译"
      }
    ]
  },
  "input_data": {
    "context_rows_before": [],
    "target_rows": [
      {
        "row_number": 1,
        "original": "歌",
        "translation": "翻译",
        "roman_or_pronunciation": "uta"
      }
    ],
    "context_rows_after": []
  }
}
```

## 服务端校验

- 返回值必须是 JSON 数组，或包含 `items` 数组的 JSON 对象。
- 行数、顺序和 `row_number` 必须与目标行一致。
- 去掉 ruby 标签后的正文必须逐字等于输入原文。
- 只允许 `<ruby>`、`<rt>`、`<rp>`；属性和其他 HTML 会被移除或转义。
- 翻译和罗马音必须是纯文本，时间戳沿用对齐后的原始时间轴。
- 日文汉字或中文汉字的注音覆盖不足会触发整段重试；达到重试上限则任务失败，不会写入半成品。

## 输出与失败语义

全部分段通过校验后，服务端一次性替换 `songs/<存储键>.json` SongDocument 的 `lyrics` 字段，并保留歌曲的 `title`、`artists`、`album`、`source`。草稿只承担搜索结果校对、
对齐和任务过程记录，不存在“发布正式歌词”步骤，也没有旧的整首/分段转换接口。

失败任务保留日志和原始 payload，可在歌词制作页重试；旧流程的历史任务只可查看或删除，
不能重新排队。
