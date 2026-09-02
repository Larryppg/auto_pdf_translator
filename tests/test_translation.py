import logging

import httpx

from pdf_translation_workflow.config import DocumentAnalysisConfig, TranslationConfig
from pdf_translation_workflow.models import Box, TextRegion
from pdf_translation_workflow.translation import (
    OpenAICompatibleTranslator,
    _Item,
    _batches,
    _extract_json,
)


def test_batching_never_drops_an_item() -> None:
    items = [_Item(str(index), "x" * 30) for index in range(8)]
    batches = list(_batches(items, maximum_characters=100))
    assert [item.id for batch in batches for item in batch] == [item.id for item in items]
    assert len(batches) > 1


def test_json_parser_accepts_fenced_response() -> None:
    parsed = _extract_json('```json\n{"items":[{"id":"a","text":"译文"}]}\n```')
    assert parsed["items"][0]["text"] == "译文"


def test_openai_compatible_backend_falls_back_when_json_mode_is_unsupported(
    monkeypatch,
) -> None:
    monkeypatch.setenv("TEST_TRANSLATION_KEY", "test-key")
    config = TranslationConfig(
        api_key_env="TEST_TRANSLATION_KEY",
        base_url="https://translator.invalid/v1",
        retry_attempts=2,
    )
    translator = OpenAICompatibleTranslator(
        config,
        DocumentAnalysisConfig(enabled=False),
    )
    requests: list[dict] = []

    def respond(request: httpx.Request) -> httpx.Response:
        payload = __import__("json").loads(request.content)
        requests.append(payload)
        if len(requests) == 1:
            return httpx.Response(
                400,
                json={"error": {"message": "response_format is unsupported"}},
            )
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"items":[{"id":"r1","text":"译文"}]}'}}]},
        )

    translator.client.close()
    translator.client = httpx.Client(
        base_url=config.base_url + "/",
        transport=httpx.MockTransport(respond),
    )
    region = TextRegion(
        id="r1",
        page_number=0,
        kind="pdf_text",
        box=Box(0, 0, 100, 20),
        source_text="source",
        font_size=10,
        color=(0, 0, 0),
    )
    translator.translate_regions([region])
    translator.client.close()

    assert "response_format" in requests[0]
    assert "response_format" not in requests[1]
    assert region.translated_text == "译文"


def test_document_analysis_is_injected_and_progress_is_logged(
    monkeypatch,
    caplog,
) -> None:
    monkeypatch.setenv("TEST_TRANSLATION_KEY", "test-key")
    config = TranslationConfig(
        api_key_env="TEST_TRANSLATION_KEY",
        base_url="https://translator.invalid/v1",
        model="deepseek-v4-flash",
        thinking_mode="disabled",
        retry_attempts=1,
    )
    translator = OpenAICompatibleTranslator(
        config,
        DocumentAnalysisConfig(enabled=True, sample_characters=2_000),
    )
    requests: list[dict] = []

    def respond(request: httpx.Request) -> httpx.Response:
        payload = __import__("json").loads(request.content)
        requests.append(payload)
        if len(requests) == 1:
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "content": """{"analysis":{"subject":"Human anatomy",
                                "domain":"anatomy","summary":"An introductory lecture",
                                "keywords":["anatomy","homeostasis"],
                                "entities":[{"source":"homeostasis","type":"term",
                                "recommended_translation":"稳态"}],
                                "ambiguities":[{"source":"plane",
                                "meaning_in_document":"anatomical plane",
                                "recommended_translation":"平面",
                                "avoid_translation":"飞机"}],
                                "style_notes":"concise textbook style"}}"""
                            }
                        }
                    ]
                },
            )
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": '{"items":[{"id":"r1","text":"稳态"}]}'}}
                ]
            },
        )

    translator.client.close()
    translator.client = httpx.Client(
        base_url=config.base_url + "/",
        transport=httpx.MockTransport(respond),
    )
    region = TextRegion(
        id="r1",
        page_number=0,
        kind="pdf_text",
        box=Box(0, 0, 100, 20),
        source_text="Homeostasis",
        font_size=10,
        color=(0, 0, 0),
    )

    with caplog.at_level(logging.INFO):
        analysis = translator.translate_regions([region])
    translator.client.close()

    assert len(requests) == 2
    assert requests[0]["thinking"] == {"type": "disabled"}
    assert requests[1]["thinking"] == {"type": "disabled"}
    translation_system = requests[1]["messages"][0]["content"]
    assert "Human anatomy" in translation_system
    assert "homeostasis" in translation_system
    assert analysis and analysis["status"] == "completed"
    assert analysis["ambiguities"][0]["avoid_translation"] == "飞机"
    assert region.translated_text == "稳态"
    assert "Translation batch 1/1 completed" in caplog.text
    assert "ETA" in caplog.text
