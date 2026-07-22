"""Observabilidade segura do Assistente Inteligente Ciclus (Módulo 2D).

Este módulo fornece:
- Logging estruturado sem expor dados sensíveis (telefone, chaves, tokens, conteúdo de mensagens)
- Métricas básicas (contadores de sucesso, erro, fallback, latência)
- Sanitização de payloads para logs
- Contexto de rastreamento por requisição

NENHUM dado sensível é logado:
- Telefones (mascarados)
- Chaves de API (ocultas)
- Conteúdo de mensagens do usuário (apenas hash/metadados)
- Stack traces completos (apenas tipo de erro)
"""

from __future__ import annotations

import hashlib
import logging
import os
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Generator, Optional

# Configuração de logging estruturado
logger = logging.getLogger("assistente_inteligente")
logger.setLevel(logging.INFO)

# Formato JSON-like para parsing facilitado
_LOG_FORMAT = (
    '{"timestamp": "%(asctime)s", "level": "%(levelname)s", '
    '"logger": "%(name)s", "event": "%(message)s"}'
)

if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(_LOG_FORMAT, datefmt="%Y-%m-%dT%H:%M:%S"))
    logger.addHandler(handler)
    logger.propagate = False


# ---------------------------------------------------------------------------
# Sanitização de dados sensíveis
# ---------------------------------------------------------------------------

def _mask_phone(phone: Optional[str]) -> str:
    """Mascarar telefone mantendo apenas prefixo e sufixo."""
    if not phone:
        return "none"
    s = str(phone).strip()
    if len(s) <= 4:
        return "****"
    return f"{s[:2]}****{s[-2:]}"


def _mask_key(key: Optional[str]) -> str:
    """Mascarar chave/API key."""
    if not key:
        return "none"
    s = str(key).strip()
    if len(s) <= 8:
        return "****"
    return f"{s[:4]}****{s[-4:]}"


def _hash_text(text: Optional[str], length: int = 8) -> str:
    """Hash curto do texto para correlação sem expor conteúdo."""
    if not text:
        return "empty"
    h = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return h[:length]


def _sanitize_dict(data: Dict[str, Any], sensitive_keys: Optional[set] = None) -> Dict[str, Any]:
    """Sanitizar dicionário removendo/mascarando chaves sensíveis."""
    if sensitive_keys is None:
        sensitive_keys = {
            "api_key", "apikey", "api-key", "authorization", "token",
            "access_token", "refresh_token", "secret", "password",
            "phone", "telefone", "whatsapp_id", "wa_id", "from",
            "message", "text", "content", "body", "media_url",
            "openrouter_api_key", "openai_api_key", "OPENAI_API_KEY",
            "OPENROUTER_API_KEY", "WHATSAPP_ACCESS_TOKEN",
        }

    result = {}
    for k, v in data.items():
        kl = str(k).lower()
        if any(sk in kl for sk in sensitive_keys):
            if isinstance(v, str) and len(v) > 10:
                result[k] = _mask_key(v)
            else:
                result[k] = "***REDACTED***"
        elif isinstance(v, dict):
            result[k] = _sanitize_dict(v, sensitive_keys)
        elif isinstance(v, list):
            result[k] = [
                _sanitize_dict(i, sensitive_keys) if isinstance(i, dict) else
                _mask_key(i) if isinstance(i, str) and any(sk in kl for sk in sensitive_keys) else i
                for i in v
            ]
        else:
            result[k] = v
    return result


# ---------------------------------------------------------------------------
# Métricas em memória (para MVP; em produção usar Prometheus/StatsD)
# ---------------------------------------------------------------------------

@dataclass
class AssistenteMetrics:
    """Contadores simples de métricas do assistente."""
    total_requests: int = 0
    successful_responses: int = 0
    fallback_responses: int = 0
    provider_errors: int = 0
    input_rejected: int = 0
    total_latency_ms: float = 0.0
    provider_latency_ms: float = 0.0
    by_provider: Dict[str, Dict[str, int]] = field(default_factory=dict)

    def record_request(self, provider: str, success: bool, used_fallback: bool, latency_ms: float, provider_latency_ms: float = 0.0):
        self.total_requests += 1
        self.total_latency_ms += latency_ms
        self.provider_latency_ms += provider_latency_ms

        if provider not in self.by_provider:
            self.by_provider[provider] = {"requests": 0, "success": 0, "fallback": 0, "errors": 0}

        self.by_provider[provider]["requests"] += 1
        if success:
            self.successful_responses += 1
            self.by_provider[provider]["success"] += 1
        else:
            if used_fallback:
                self.fallback_responses += 1
                self.by_provider[provider]["fallback"] += 1
            else:
                self.provider_errors += 1
                self.by_provider[provider]["errors"] += 1

    def record_input_rejected(self):
        self.input_rejected += 1

    def get_summary(self) -> Dict[str, Any]:
        avg_latency = self.total_latency_ms / self.total_requests if self.total_requests > 0 else 0
        avg_provider_latency = self.provider_latency_ms / self.total_requests if self.total_requests > 0 else 0
        return {
            "total_requests": self.total_requests,
            "successful_responses": self.successful_responses,
            "fallback_responses": self.fallback_responses,
            "provider_errors": self.provider_errors,
            "input_rejected": self.input_rejected,
            "avg_latency_ms": round(avg_latency, 2),
            "avg_provider_latency_ms": round(avg_provider_latency, 2),
            "by_provider": self.by_provider,
        }


# Instância global de métricas (thread-safe para MVP simples)
_metrics = AssistenteMetrics()


def get_metrics() -> Dict[str, Any]:
    """Retorna snapshot das métricas atuais."""
    return _metrics.get_summary()


def reset_metrics() -> None:
    """Reseta contadores (útil para testes)."""
    global _metrics
    _metrics = AssistenteMetrics()


# ---------------------------------------------------------------------------
# Contexto de rastreamento por requisição
# ---------------------------------------------------------------------------

@dataclass
class RequestContext:
    """Contexto de uma única requisição do assistente."""
    request_id: str
    sender_key_hash: str  # hash do telefone, não o telefone real
    provider: str
    start_time: float = field(default_factory=time.perf_counter)
    provider_start_time: Optional[float] = None
    provider_end_time: Optional[float] = None
    input_chars: int = 0
    history_turns: int = 0
    success: bool = False
    used_fallback: bool = False
    error_type: Optional[str] = None
    error_message: str = ""

    def mark_provider_start(self):
        self.provider_start_time = time.perf_counter()

    def mark_provider_end(self):
        self.provider_end_time = time.perf_counter()

    def total_latency_ms(self) -> float:
        return (time.perf_counter() - self.start_time) * 1000

    def provider_latency_ms(self) -> float:
        if self.provider_start_time and self.provider_end_time:
            return (self.provider_end_time - self.provider_start_time) * 1000
        return 0.0


# Armazenamento de contexto ativo (em produção usar contextvars)
_active_context: Optional[RequestContext] = None


def get_current_context() -> Optional[RequestContext]:
    return _active_context


@contextmanager
def track_request(
    sender_key: str,
    provider: str,
    input_text: str,
    history_turns: int = 0
) -> Generator[RequestContext, None, None]:
    """Context manager para rastrear uma requisição completa."""
    global _active_context
    request_id = uuid.uuid4().hex[:12]
    ctx = RequestContext(
        request_id=request_id,
        sender_key_hash=_hash_text(sender_key),
        provider=provider,
        input_chars=len(input_text or ""),
        history_turns=history_turns,
    )
    _active_context = ctx

    # Log de entrada (sanitizado)
    logger.info(
        'request_start request_id="%s" sender_hash="%s" provider="%s" input_chars=%d history_turns=%d',
        request_id, ctx.sender_key_hash, provider, ctx.input_chars, history_turns
    )

    try:
        yield ctx
    except Exception as e:
        ctx.success = False
        ctx.error_type = type(e).__name__
        ctx.error_message = str(e)[:200]
        logger.warning(
            'request_error request_id="%s" sender_hash="%s" provider="%s" error_type="%s"',
            request_id, ctx.sender_key_hash, provider, ctx.error_type
        )
        raise
    finally:
        # Log de saída com métricas
        total_ms = ctx.total_latency_ms()
        provider_ms = ctx.provider_latency_ms()

        logger.info(
            'request_end request_id="%s" sender_hash="%s" provider="%s" '
            'success=%s used_fallback=%s total_latency_ms=%.2f provider_latency_ms=%.2f '
            'input_chars=%d history_turns=%d error_type="%s"',
            request_id, ctx.sender_key_hash, provider,
            ctx.success, ctx.used_fallback, total_ms, provider_ms,
            ctx.input_chars, ctx.history_turns, ctx.error_type or "none"
        )

        # Atualiza métricas globais
        _metrics.record_request(
            provider=provider,
            success=ctx.success,
            used_fallback=ctx.used_fallback,
            latency_ms=total_ms,
            provider_latency_ms=provider_ms,
        )

        _active_context = None


# ---------------------------------------------------------------------------
# Helpers para logging seguro de payloads de provider
# ---------------------------------------------------------------------------

def log_provider_request(
    provider: str,
    model: str,
    messages_count: int,
    has_system_prompt: bool,
    input_chars: int,
    timeout_seconds: float
) -> None:
    """Log seguro da requisição ao provider (sem conteúdo real)."""
    logger.info(
        'provider_request provider="%s" model="%s" messages_count=%d '
        'has_system_prompt=%s input_chars=%d timeout_s=%.1f',
        provider, model, messages_count, has_system_prompt, input_chars, timeout_seconds
    )


def log_provider_response(
    provider: str,
    success: bool,
    output_chars: int,
    latency_ms: float,
    used_fallback: bool,
    error_type: Optional[str] = None,
    error_message: str = ""
) -> None:
    """Log seguro da resposta do provider."""
    if success:
        logger.info(
            'provider_response provider="%s" success=true output_chars=%d '
            'latency_ms=%.2f used_fallback=%s',
            provider, output_chars, latency_ms, used_fallback
        )
    else:
        logger.warning(
            'provider_response provider="%s" success=false latency_ms=%.2f '
            'used_fallback=%s error_type="%s" error_preview="%s"',
            provider, latency_ms, used_fallback,
            error_type or "unknown", error_message[:100] if error_message else ""
        )


def sanitize_provider_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Sanitiza payload do provider para logging seguro."""
    return _sanitize_dict(payload, sensitive_keys={
        "api_key", "authorization", "token", "key", "secret",
        "messages", "content", "prompt", "input"
    })


# ---------------------------------------------------------------------------
# Health check simples
# ---------------------------------------------------------------------------

def health_check() -> Dict[str, Any]:
    """Retorna status de saúde do assistente."""
    metrics = get_metrics()
    return {
        "status": "healthy" if metrics["provider_errors"] < metrics["total_requests"] * 0.5 else "degraded",
        "metrics": metrics,
        "config": {
            "provider": os.getenv("ASSISTENTE_INTELIGENTE_PROVIDER", "mock"),
            "model": os.getenv("ASSISTENTE_INTELIGENTE_MODEL", "gpt-5.4-mini"),
            "enabled": os.getenv("ASSISTENTE_INTELIGENTE_ENABLED", "false").lower() == "true",
        }
    }


# ---------------------------------------------------------------------------
# Funções de registro de requisições (compatibilidade com service)
# ---------------------------------------------------------------------------

def record_request_start(
    sender_key: str,
    provider: str,
    input_chars: int,
    history_turns: int
) -> str:
    """Registra início de requisição e retorna request_id."""
    import uuid
    request_id = uuid.uuid4().hex[:12]
    sender_hash = _hash_text(sender_key)

    logger.info(
        'request_start request_id="%s" sender_hash="%s" provider="%s" input_chars=%d history_turns=%d',
        request_id, sender_hash, provider, input_chars, history_turns
    )
    return request_id


def record_request_end(
    request_id: str,
    success: bool,
    latency_ms: float,
    output_chars: int,
    used_fallback: bool,
    error_type: Optional[str] = None,
    error_message: str = ""
) -> None:
    """Registra fim de requisição com métricas."""
    logger.info(
        'request_end request_id="%s" success=%s used_fallback=%s '
        'total_latency_ms=%.2f output_chars=%d error_type="%s"',
        request_id, success, used_fallback, latency_ms, output_chars, error_type or "none"
    )

    # Atualiza métricas globais
    _metrics.record_request(
        provider="unknown",  # provider não disponível aqui, mas métricas globais ainda úteis
        success=success,
        used_fallback=used_fallback,
        latency_ms=latency_ms,
    )