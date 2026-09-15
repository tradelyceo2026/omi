from decimal import Decimal
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

from main import _parse_amount, app


def test_parse_amount_valid():
    assert _parse_amount(50) == Decimal("50")
    assert _parse_amount("19.95") == Decimal("19.95")
    assert _parse_amount(0.01) == Decimal(str(0.01))


def test_parse_amount_zero_and_negative():
    with pytest.raises(ValueError, match="amount must be greater than 0"):
        _parse_amount(0)

    with pytest.raises(ValueError, match="amount must be greater than 0"):
        _parse_amount(-1)

    with pytest.raises(ValueError, match="amount must be greater than 0"):
        _parse_amount("-50.25")


def test_parse_amount_invalid_text():
    with pytest.raises(ValueError, match="amount must be a number"):
        _parse_amount("not-a-number")


def test_parse_amount_non_finite_rejected():
    non_finite_values = [
        "NaN",
        "nan",
        "sNaN",
        "-NaN",
        "Infinity",
        "+Infinity",
        "-Infinity",
        "inf",
        "-inf",
        float("nan"),
        float("inf"),
        float("-inf"),
    ]
    for val in non_finite_values:
        with pytest.raises(ValueError, match="amount must be a finite number"):
            _parse_amount(val)


def test_convert_currency_rejects_non_finite_amounts_without_500():
    client = TestClient(app)

    for bad_amount in ["NaN", "sNaN", "Infinity", "-Infinity"]:
        resp = client.post(
            "/tools/convert_currency",
            json={
                "amount": bad_amount,
                "from_currency": "USD",
                "to_currencies": ["EUR"],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["result"] is None
        assert "amount must be a finite number" in data["error"]


def test_convert_currency_valid_amount_success():
    client = TestClient(app)

    mock_rates = {
        "amount": 50.0,
        "base": "USD",
        "date": "2026-09-09",
        "rates": {"EUR": 45.5, "GBP": 39.2},
    }

    with patch("main._request_json", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = mock_rates
        resp = client.post(
            "/tools/convert_currency",
            json={
                "amount": 50,
                "from_currency": "USD",
                "to_currencies": ["EUR", "GBP"],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["error"] is None
        assert "50 USD on 2026-09-09:" in data["result"]
        assert "- EUR: 45.5" in data["result"]
        assert "- GBP: 39.2" in data["result"]


# --- Regression tests for the api.frankfurter.app -> api.frankfurter.dev/v1 move ---
#
# api.frankfurter.app now 301-redirects every request to api.frankfurter.dev/v1.
# httpx does not follow redirects by default, so with the old base URL every tool
# returned "Redirect response '301 Moved Permanently'". These tests exercise the
# real request path through the lifespan client against an in-memory transport.

import main as main_module


def _mock_transport(handler):
    return httpx.MockTransport(handler)


def _install_client(monkeypatch, handler, **client_kwargs):
    """Use a MockTransport-backed AsyncClient as app.state.http_client."""

    client = httpx.AsyncClient(transport=_mock_transport(handler), **client_kwargs)
    monkeypatch.setattr(app.state, "http_client", client, raising=False)
    return client


def test_base_url_is_current_frankfurter_host():
    assert main_module.FRANKFURTER_BASE_URL == "https://api.frankfurter.dev/v1"


def test_lifespan_client_follows_redirects():
    with TestClient(app):
        assert app.state.http_client.follow_redirects is True


def test_convert_currency_hits_v1_host(monkeypatch):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return httpx.Response(
            200,
            json={"amount": 100.0, "base": "USD", "date": "2026-09-15", "rates": {"EUR": 86.66}},
        )

    _install_client(monkeypatch, handler)
    resp = TestClient(app).post(
        "/tools/convert_currency",
        json={"amount": 100, "from_currency": "USD", "to_currencies": ["EUR"]},
    )
    data = resp.json()
    assert data["error"] is None, data
    assert "- EUR: 86.66" in data["result"]
    assert seen["url"].startswith("https://api.frankfurter.dev/v1/latest?")


def test_legacy_host_redirect_is_followed(monkeypatch):
    """Even if the base URL is pointed back at the legacy host, the client must follow the 301."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.frankfurter.app":
            target = str(request.url).replace("https://api.frankfurter.app/", "https://api.frankfurter.dev/v1/")
            return httpx.Response(301, headers={"location": target})
        return httpx.Response(200, json={"EUR": "Euro", "USD": "United States Dollar"})

    monkeypatch.setattr(main_module, "FRANKFURTER_BASE_URL", "https://api.frankfurter.app")
    _install_client(monkeypatch, handler, follow_redirects=True)
    data = TestClient(app).post("/tools/list_supported_currencies").json()
    assert data["error"] is None, data
    assert "- EUR: Euro" in data["result"]


def test_api_error_message_is_surfaced(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, json={"message": "bad currency pair"})

    _install_client(monkeypatch, handler)
    data = TestClient(app).post(
        "/tools/convert_currency",
        json={"amount": 1, "from_currency": "USD", "to_currencies": ["USD"]},
    )
    data = data.json()
    assert data["result"] is None
    assert data["error"] == "currency conversion failed: Frankfurter API error: bad currency pair"


def test_list_currencies_api_error_does_not_500(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="upstream unavailable")

    _install_client(monkeypatch, handler)
    resp = TestClient(app).post("/tools/list_supported_currencies")
    assert resp.status_code == 200
    data = resp.json()
    assert data["result"] is None
    assert data["error"] == "currency list request failed: Frankfurter API returned HTTP 503"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
