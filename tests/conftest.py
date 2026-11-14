"""Safety net for the whole test suite: tests must NEVER reach Telegram, email, OpenAI, Tavily or any
other real service, even though sapsignal.config loads your real .env.

  * every secret is removed from the environment before each test (a test may set a fake one itself)
  * every real HTTP request is refused (tests that need HTTP replace requests.get/post with fakes)
  * SMTP connections are refused
"""
import smtplib

import pytest
import requests

SECRETS = ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "SMTP_USER", "SMTP_PASSWORD", "EMAIL_TO", "EMAIL_FROM",
           "OPENAI_API_KEY", "TAVILY_API_KEY", "APPROVAL_SECRET", "CLOUDFLARE_API_TOKEN", "GITHUB_TOKEN")


class NetworkBlocked(RuntimeError):
    pass


@pytest.fixture(autouse=True)
def no_real_outside_calls(monkeypatch):
    for key in SECRETS:
        monkeypatch.delenv(key, raising=False)

    def refuse(self, method, url, *args, **kwargs):
        raise NetworkBlocked(f"test tried a real network call: {method} {url}")
    monkeypatch.setattr(requests.sessions.Session, "request", refuse)

    def refuse_smtp(*args, **kwargs):
        raise NetworkBlocked("test tried to send a real email")
    monkeypatch.setattr(smtplib, "SMTP", refuse_smtp)
    monkeypatch.setattr(smtplib, "SMTP_SSL", refuse_smtp)
    yield


@pytest.fixture(autouse=True)
def _evening_update_enabled(monkeypatch):
    """Tests exercise the evening engine as if switched on, whatever config.yaml says today."""
    import main
    from sapsignal.config import get_config
    cfg = dict(get_config())
    cfg["second_run"] = {**(cfg.get("second_run") or {}), "enabled": True}
    monkeypatch.setattr(main, "get_config", lambda: cfg)
