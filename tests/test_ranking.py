from app.ranking import intelligence_score, is_free_model


def test_known_families_are_ordered_by_intelligence():
    assert intelligence_score("openrouter/deepseek-r1:free") > intelligence_score("groq/llama-3.1-8b-instant")
    assert intelligence_score("llama-3.3-70b-versatile") > intelligence_score("llama-3.2-1b")
    assert intelligence_score("qwen2.5:1.5b") > intelligence_score("qwen2.5:0.5b")


def test_claude_code_models_are_ordered_by_tier():
    assert intelligence_score("claude-code/claude-opus-4-8") > intelligence_score("claude-code/claude-sonnet-4-6-20251114")
    assert intelligence_score("claude-code/claude-sonnet-4-6-20251114") > intelligence_score("claude-code/claude-sonnet-4-5-20250929")
    assert intelligence_score("claude-code/claude-sonnet-4-5-20250929") > intelligence_score("claude-code/claude-haiku-4-5-20251001")


def test_gemini_lite_variants_score_below_their_full_siblings():
    assert intelligence_score("antigravity/gemini-3-pro-preview") > intelligence_score("antigravity/gemini-2.5-pro")
    assert intelligence_score("antigravity/gemini-2.5-pro") > intelligence_score("antigravity/gemini-2.5-flash")
    assert intelligence_score("antigravity/gemini-2.5-flash") > intelligence_score("antigravity/gemini-2.5-flash-lite")
    assert intelligence_score("antigravity/gemini-3.1-flash-lite-preview") > intelligence_score("antigravity/gemini-2.5-flash-lite")


def test_unknown_model_falls_back_to_parameter_size():
    assert intelligence_score("mystery-model-70b") == 40
    assert intelligence_score("mystery-model-1b") == 10
    assert intelligence_score("totally-unknown") == 20


def test_free_detection_from_pricing():
    assert is_free_model({"id": "m", "pricing": {"prompt": "0", "completion": "0"}}, "https://x/v1") is True
    assert is_free_model({"id": "m", "pricing": {"prompt": "0.001"}}, "https://x/v1") is False


def test_free_detection_from_suffix_and_local():
    assert is_free_model({"id": "meta-llama/llama-3.2-3b-instruct:free"}, "https://openrouter.ai/api/v1") is True
    assert is_free_model({"id": "qwen2.5:1.5b"}, "http://127.0.0.1:11434/v1") is True
    assert is_free_model({"id": "some-model"}, "https://api.groq.com/openai/v1") is None


def test_auto_router_models_are_excluded():
    from app.ranking import is_auto_router_model

    assert is_auto_router_model("openrouter/auto") is True
    assert is_auto_router_model("openrouter/auto-beta") is True
    assert is_auto_router_model("kilo-auto/free") is True
    assert is_auto_router_model("openrouter/free") is True
    assert is_auto_router_model("openrouter/bodybuilder") is True
    assert is_auto_router_model("openrouter/fusion") is True
    assert is_auto_router_model("openrouter/pareto-code") is True
    assert is_auto_router_model("meta-llama/llama-3.3-70b-instruct:free") is False

    # is_free_model excludes auto router models even if pricing is 0 or suffix is :free
    assert is_free_model({"id": "openrouter/auto"}, "https://openrouter.ai/api/v1") is False
    assert is_free_model({"id": "kilo-auto/free"}, "https://api.kilo.ai/v1") is False

