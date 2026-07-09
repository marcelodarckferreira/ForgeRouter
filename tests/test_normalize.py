from app.normalize import count_tokens, normalize_messages


def test_normalize_strips_trailing_whitespace_and_collapses_blank_lines():
    messages = [{"role": "user", "content": "line one   \nline two\t\n\n\n\nline three\n"}]

    normalized = normalize_messages(messages)

    assert normalized[0]["content"] == "line one\nline two\n\nline three\n"


def test_normalize_minifies_json_tool_results():
    messages = [
        {
            "role": "tool",
            "tool_call_id": "call_1",
            "content": '{\n  "result": "ok",\n  "items": [\n    1,\n    2\n  ]\n}',
        }
    ]

    normalized = normalize_messages(messages)

    assert normalized[0]["content"] == '{"result":"ok","items":[1,2]}'


def test_normalize_leaves_non_json_tool_content_alone_except_whitespace():
    messages = [{"role": "tool", "tool_call_id": "call_1", "content": "plain text   \nwith trailing spaces"}]

    normalized = normalize_messages(messages)

    assert normalized[0]["content"] == "plain text\nwith trailing spaces"


def test_normalize_does_not_minify_json_in_non_tool_messages():
    raw = '{\n  "a": 1\n}'
    messages = [{"role": "user", "content": raw}]

    normalized = normalize_messages(messages)

    # Only whitespace normalization applies to non-tool roles: no trailing
    # whitespace and no 3+ blank line runs here, so the content is unchanged.
    assert normalized[0]["content"] == raw


def test_normalize_handles_list_content_parts():
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "hello   \nworld\n\n\n\n!"},
                {"type": "image_url", "image_url": {"url": "http://example.com/x.png"}},
            ],
        }
    ]

    normalized = normalize_messages(messages)

    assert normalized[0]["content"][0]["text"] == "hello\nworld\n\n!"
    assert normalized[0]["content"][1] == {"type": "image_url", "image_url": {"url": "http://example.com/x.png"}}


def test_normalize_preserves_messages_without_string_or_list_content():
    messages = [{"role": "assistant", "content": None, "tool_calls": [{"id": "call_1"}]}]

    normalized = normalize_messages(messages)

    assert normalized == messages


def test_count_tokens_reflects_compaction_savings():
    padded = [{"role": "user", "content": "hello   \nworld\n\n\n\n!"}]
    compact = normalize_messages(padded)

    raw_tokens = count_tokens(padded)
    compact_tokens = count_tokens(compact)

    if raw_tokens is None or compact_tokens is None:
        return  # tiktoken encoding unavailable in this environment — degrade gracefully
    assert compact_tokens < raw_tokens
