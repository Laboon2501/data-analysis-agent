"""Static Web UI composer availability tests."""

from __future__ import annotations

from pathlib import Path

WEB_ROOT = Path(__file__).resolve().parents[1] / "examples" / "web"


def test_web_ui_message_input_has_central_enabled_disabled_logic() -> None:
    """Textarea should not stay disabled after session creation or human approval."""

    text = (WEB_ROOT / "app.js").read_text(encoding="utf-8")

    assert "function updateComposerAvailability" in text
    assert "const inputDisabled = !hasSession || backendUnavailable || state.isSubmitting" in text
    assert "const sendDisabled = inputDisabled || state.isBusy" in text
    assert '$("message-input").disabled = inputDisabled' in text
    assert "state.isSubmitting = true" in text
    assert "state.isSubmitting = false" in text
    assert "updateComposerAvailability" in text


def test_web_ui_enter_shift_enter_contract_is_preserved() -> None:
    """Enter should send while Shift+Enter remains a newline."""

    text = (WEB_ROOT / "app.js").read_text(encoding="utf-8")

    assert 'event.key === "Enter" && !event.shiftKey' in text
    assert "event.preventDefault()" in text
    assert "sendChat()" in text
