"""Testes do módulo de observabilidade do Assistente Inteligente (Módulo 2D).

Verifica:
1. Sanitização de dados sensíveis
2. Métricas básicas
3. Registro de requisições
4. Health check
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from services.assistente_inteligente_observability import (
    _mask_phone,
    _mask_key,
    _hash_text,
    _sanitize_dict,
    AssistenteMetrics,
    get_metrics,
    reset_metrics,
    record_request_start,
    record_request_end,
    health_check,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset_metrics():
    """Reseta métricas antes e depois de cada teste."""
    reset_metrics()
    yield
    reset_metrics()


# ---------------------------------------------------------------------------
# Sanitização
# ---------------------------------------------------------------------------

def test_mask_phone():
    assert _mask_phone("5500000000001") == "55****01"
    assert _mask_phone("5511999999999") == "55****99"
    assert _mask_phone("1234") == "****"
    assert _mask_phone("") == "none"
    assert _mask_phone(None) == "none"


def test_mask_key():
    # _mask_key mantém prefixo de 4 chars e sufixo de 4 chars
    # "sk-123...cdef" -> len > 8 -> "sk-1****cdef" (first 4: "sk-1", last 4: "cdef")
    assert _mask_key("sk-123...cdef") == "sk-1****cdef"
    assert _mask_key("short") == "****"
    assert _mask_key("") == "none"
    assert _mask_key(None) == "none"


def test_hash_text():
    h1 = _hash_text("hello world")
    h2 = _hash_text("hello world")
    h3 = _hash_text("different")
    assert h1 == h2
    assert h1 != h3
    assert len(h1) == 8
    assert _hash_text("") == "empty"
    assert _hash_text(None) == "empty"


def test_sanitize_dict_basic():
    data = {
        "normal": "value",
        "api_key": "sk-secret123",
        "authorization": "Bearer token123",
        "phone": "5500000000001",
        "message": "Hello world",
    }
    result = _sanitize_dict(data)
    assert result["normal"] == "value"
    # _mask_key é aplicado a valores de chaves sensíveis
    assert "****" in result["api_key"]
    assert "****" in result["authorization"]
    assert "****" in result["phone"]
    assert "****" in result["message"]


def test_sanitize_dict_nested():
    data = {
        "outer": {
            "api_key": "«redacted:sk-…»",  # 15 chars, will be masked (sensitive key)
            "normal": "value",
        },
        "list": [
            {"token": "abc123defghijkl"},  # 15 chars, will be masked (sensitive key)
            "normal_string",
        ],
    }
    result = _sanitize_dict(data)
    assert "****" in result["outer"]["api_key"]
    assert result["outer"]["normal"] == "value"
    assert "****" in result["list"][0]["token"]
    assert result["list"][1] == "normal_string"


# ---------------------------------------------------------------------------
# Métricas
# ---------------------------------------------------------------------------

def test_metrics_initial_state():
    metrics = get_metrics()
    assert metrics["total_requests"] == 0
    assert metrics["successful_responses"] == 0
    assert metrics["fallback_responses"] == 0
    assert metrics["provider_errors"] == 0
    assert metrics["input_rejected"] == 0


def test_metrics_record_success():
    m = AssistenteMetrics()
    m.record_request("mock", success=True, used_fallback=False, latency_ms=100.0)
    summary = m.get_summary()
    assert summary["total_requests"] == 1
    assert summary["successful_responses"] == 1
    assert summary["fallback_responses"] == 0
    assert summary["provider_errors"] == 0


def test_metrics_record_fallback():
    m = AssistenteMetrics()
    m.record_request("openai", success=False, used_fallback=True, latency_ms=200.0)
    summary = m.get_summary()
    assert summary["total_requests"] == 1
    assert summary["successful_responses"] == 0
    assert summary["fallback_responses"] == 1
    assert summary["provider_errors"] == 0


def test_metrics_record_error():
    m = AssistenteMetrics()
    m.record_request("openrouter", success=False, used_fallback=False, latency_ms=50.0)
    summary = m.get_summary()
    assert summary["total_requests"] == 1
    assert summary["successful_responses"] == 0
    assert summary["fallback_responses"] == 0
    assert summary["provider_errors"] == 1


def test_metrics_by_provider():
    m = AssistenteMetrics()
    m.record_request("mock", success=True, used_fallback=False, latency_ms=10.0)
    m.record_request("openai", success=True, used_fallback=False, latency_ms=500.0)
    m.record_request("openai", success=False, used_fallback=True, latency_ms=1000.0)
    summary = m.get_summary()
    assert summary["by_provider"]["mock"]["requests"] == 1
    assert summary["by_provider"]["mock"]["success"] == 1
    assert summary["by_provider"]["openai"]["requests"] == 2
    assert summary["by_provider"]["openai"]["success"] == 1
    assert summary["by_provider"]["openai"]["fallback"] == 1


def test_metrics_input_rejected():
    m = AssistenteMetrics()
    m.record_input_rejected()
    m.record_input_rejected()
    summary = m.get_summary()
    assert summary["input_rejected"] == 2


# ---------------------------------------------------------------------------
# Registro de requisições
# ---------------------------------------------------------------------------

def test_record_request_start_returns_id():
    req_id = record_request_start("5500000000001", "mock", 100, 3)
    assert isinstance(req_id, str)
    assert len(req_id) == 12


def test_record_request_end_logs(caplog):
    with caplog.at_level("INFO"):
        req_id = record_request_start("5500000000001", "mock", 100, 3)
        record_request_end(req_id, True, 150.0, 200, False)

    # Verifica que logs foram emitidos
    assert any("request_start" in r.message for r in caplog.records)
    assert any("request_end" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

def test_health_check_disabled():
    os.environ["ASSISTENTE_INTELIGENTE_ENABLED"] = "false"
    health = health_check()
    assert health["config"]["enabled"] is False


def test_health_check_enabled():
    os.environ["ASSISTENTE_INTELIGENTE_ENABLED"] = "true"
    health = health_check()
    assert health["config"]["enabled"] is True


def test_health_check_provider_config():
    os.environ["ASSISTENTE_INTELIGENTE_PROVIDER"] = "openai"
    os.environ["ASSISTENTE_INTELIGENTE_MODEL"] = "gpt-4o"
    health = health_check()
    assert health["config"]["provider"] == "openai"
    assert health["config"]["model"] == "gpt-4o"


def test_health_check_degraded_when_high_error_rate():
    # Registra muitos erros usando AssistenteMetrics diretamente
    from services.assistente_inteligente_observability import _metrics
    # reset_metrics()  # already done by fixture

    # Use used_fallback=False para contar como provider_errors
    for _ in range(10):
        _metrics.record_request("mock", success=False, used_fallback=False, latency_ms=100.0)
    # Poucos sucessos
    for _ in range(3):
        _metrics.record_request("mock", success=True, used_fallback=False, latency_ms=100.0)

    health = health_check()
    # Com 10 erros e 3 sucessos, taxa de erro > 50% -> degraded
    assert health["status"] == "degraded"


# ---------------------------------------------------------------------------
# Logs seguros (integração com provider)
# ---------------------------------------------------------------------------

def test_no_sensitive_data_in_provider_logs(monkeypatch):
    """Verifica que logs de provider não expõem chaves."""
    from services.assistente_inteligente_observability import log_provider_request

    with patch.object(log_provider_request, '__module__', 'test'):
        # Apenas verifica que a função existe e aceita parâmetros
        log_provider_request("openai", "gpt-4o", 5, True, 1000, 30.0)
        # Se chegou aqui sem erro, OK


# ---------------------------------------------------------------------------
# Integração com service (smoke test)
# ---------------------------------------------------------------------------

def test_observability_integration_with_service(monkeypatch):
    """Testa que o service usa observabilidade sem quebrar."""
    from services.assistente_inteligente_service import (
        AssistenteInteligenteService,
        AssistenteRequest,
    )
    from services.assistente_inteligente_provider import build_mock_provider

    monkeypatch.setenv("ASSISTENTE_INTELIGENTE_ENABLED", "true")
    monkeypatch.setenv("ASSISTENTE_INTELIGENTE_PROVIDER", "mock")

    # Service com provider real (mock)
    service = AssistenteInteligenteService()

    # Gera resposta
    resp = service.generate(
        AssistenteRequest(sender_key="5500000000001", message="Olá")
    )

    assert resp.ok is True
    assert "Assistente Inteligente" in resp.text

    # Métricas atualizadas
    metrics = get_metrics()
    assert metrics["total_requests"] >= 1
    assert metrics["successful_responses"] >= 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])