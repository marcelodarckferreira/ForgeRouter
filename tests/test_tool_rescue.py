from app.tool_rescue import rescue_tool_calls

TOOLS = [{"type": "function", "function": {"name": "get_weather", "parameters": {}}}]


def test_rescues_plain_json_object_naming_a_requested_tool():
    body = {"choices": [{"message": {"role": "assistant", "content": '{"name": "get_weather", "arguments": {"city": "Rio"}}'}}]}

    assert rescue_tool_calls(body, TOOLS) is True
    message = body["choices"][0]["message"]
    assert message["content"] is None
    assert len(message["tool_calls"]) == 1
    call = message["tool_calls"][0]
    assert call["type"] == "function"
    assert call["function"]["name"] == "get_weather"
    assert call["function"]["arguments"] == '{"city": "Rio"}'
    assert body["choices"][0]["finish_reason"] == "tool_calls"


def test_rescues_json_wrapped_in_a_markdown_fence():
    content = 'Sure, let me check.\n```json\n{"name": "get_weather", "arguments": {"city": "Rio"}}\n```'
    body = {"choices": [{"message": {"content": content}}]}

    assert rescue_tool_calls(body, TOOLS) is True
    assert body["choices"][0]["message"]["tool_calls"][0]["function"]["name"] == "get_weather"


def test_rescues_parallel_calls_from_a_json_array():
    content = '[{"name": "get_weather", "arguments": {"city": "Rio"}}, {"name": "get_weather", "arguments": {"city": "SP"}}]'
    body = {"choices": [{"message": {"content": content}}]}

    assert rescue_tool_calls(body, TOOLS) is True
    calls = body["choices"][0]["message"]["tool_calls"]
    assert len(calls) == 2


def test_ignores_ordinary_prose_that_is_not_json():
    body = {"choices": [{"message": {"content": "The weather in Rio is sunny today."}}]}

    assert rescue_tool_calls(body, TOOLS) is False
    assert body["choices"][0]["message"]["content"] == "The weather in Rio is sunny today."


def test_ignores_json_that_does_not_name_a_requested_tool():
    # A legitimate JSON answer to the user's question must never be
    # reinterpreted as a tool call just because it happens to parse as JSON.
    body = {"choices": [{"message": {"content": '{"city": "Rio", "forecast": "sunny"}'}}]}

    assert rescue_tool_calls(body, TOOLS) is False


def test_skips_when_tool_calls_already_structured():
    body = {"choices": [{"message": {"content": None, "tool_calls": [{"id": "call_1", "type": "function", "function": {"name": "get_weather", "arguments": "{}"}}]}}]}

    assert rescue_tool_calls(body, TOOLS) is False


def test_no_op_when_tools_were_not_requested():
    body = {"choices": [{"message": {"content": '{"name": "get_weather", "arguments": {}}'}}]}

    assert rescue_tool_calls(body, None) is False
    assert rescue_tool_calls(body, []) is False
