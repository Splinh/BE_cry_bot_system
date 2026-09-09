"""
LLM Client - Provider-agnostic interface cho cac LLM API.

Provider hien tai: OmniRouter (self-hosted tren VPS).
- Base URL: http://localhost:20128/v1 (khi bot chay cung VPS) hoac http://139.99.89.215:20128/v1
- Auth: Authorization: Bearer <OMNIROUTER_API_KEY> (key dang sk-...)
- Chat: POST /v1/chat/completions - OpenAI-compatible response (choices[0].message.content)
- LUU Y: phai gui "stream": false - mac dinh server tra SSE stream neu khong khai bao
- Model auto: "auto/best-chat" (smart routing), "auto/best-reasoning", "auto/best-coding",
  "auto/best-vision", "auto/cheap"... - tu chon model phu hop; response tra ve model th dung.

Phase sau: chi can them class moi ke thua BaseLLMProvider va dang ky vao PROVIDER_REGISTRY.
Khong them dependency moi - dung httpx (co san trong requirements.txt).
"""
import asyncio
from typing import Optional

import httpx
from loguru import logger

from core.config import Config


class LLMError(Exception):
    """Loi chung khi goi LLM (timeout, 429, 5xx, sai API key...)."""

    def __init__(self, message: str, status: Optional[int] = None):
        super().__init__(message)
        self.status = status


class BaseLLMProvider:
    """Interface chung cho tat ca LLM provider."""

    name: str = "base"

    async def complete(self, messages: list[dict], model: Optional[str] = None,
                       max_tokens: int = 1500, temperature: float = 0.4) -> str:
        raise NotImplementedError

    def is_configured(self) -> bool:
        raise NotImplementedError


class OmniRouterProvider(BaseLLMProvider):
    """
    OmniRouter - unified API gateway (self-hosted).

    Endpoint: POST {BASE_URL}/chat/completions
    Response: OpenAI-compatible {"choices": [{"message": {"content": ...}}], "model": ..., "usage": ...}
    """

    name = "omnirouter"

    def __init__(self):
        self.api_key = Config.OMNIROUTER_API_KEY
        self.base_url = Config.OMNIROUTER_BASE_URL.rstrip("/")
        self.default_model = Config.OMNIROUTER_MODEL

    def is_configured(self) -> bool:
        return bool(self.api_key)

    async def complete(self, messages: list[dict], model: Optional[str] = None,
                       max_tokens: int = 1500, temperature: float = 0.4) -> str:
        if not self.api_key:
            raise LLMError("OMNIROUTER_API_KEY chua cau hinh trong .env")

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model or self.default_model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            # Bat buoc: mac dinh server tra SSE stream neu khong khai bao
            "stream": False,
        }

        timeout = httpx.Timeout(Config.LLM_TIMEOUT)
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                f"{self.base_url}/chat/completions",
                headers=headers, json=payload,
            )

        if resp.status_code == 429:
            raise LLMError("Rate limit OmniRouter (429) - thu lai sau", status=429)
        if resp.status_code == 401:
            raise LLMError("API key OmniRouter khong hop le (401)", status=401)
        if resp.status_code == 402:
            raise LLMError("Het credit OmniRouter (402) - can nap them", status=402)
        if resp.status_code >= 500:
            raise LLMError(f"OmniRouter loi server ({resp.status_code})", status=resp.status_code)
        if resp.status_code != 200:
            raise LLMError(f"OmniRouter loi ({resp.status_code}): {resp.text[:200]}", status=resp.status_code)

        try:
            data = resp.json()
        except Exception as e:
            raise LLMError(f"OmniRouter response khong phai JSON: {e}")

        # Mot so gateway tra HTTP 200 nhung body chua error -> kiem tra truoc
        if isinstance(data, dict) and data.get("error"):
            err = data["error"]
            raise LLMError(f"OmniRouter error: {err.get('message', str(err)[:200])}")

        try:
            content = data["choices"][0]["message"]["content"]
            if not content or not content.strip():
                raise KeyError("content rong")
            return content.strip()
        except (KeyError, IndexError, TypeError, AttributeError) as e:
            logger.warning(f"OmniRouter response khong dung format: {e} | raw={str(data)[:300]}")
            raise LLMError("OmniRouter response khong dung format")


PROVIDER_REGISTRY: dict[str, BaseLLMProvider] = {
    OmniRouterProvider.name: OmniRouterProvider,
}


class LLMClient:
    """
    Facade chon provider theo Config.LLM_PROVIDER.
    Co retry (backoff) cho loi tam thoi: 429 / 5xx / network error.
    """

    RETRY_DELAYS = (1, 3)  # giay - lan 1 cho 1s, lan 2 cho 3s

    def __init__(self):
        self.provider_name = Config.LLM_PROVIDER.lower()
        self._provider: Optional[BaseLLMProvider] = None
        self.request_count = 0
        self.error_count = 0

    def _get_provider(self) -> BaseLLMProvider:
        if self._provider is None:
            cls = PROVIDER_REGISTRY.get(self.provider_name)
            if cls is None:
                raise LLMError(f"Provider '{self.provider_name}' khong ton tai. Co: {list(PROVIDER_REGISTRY.keys())}")
            self._provider = cls()
        return self._provider

    def get_model(self) -> str:
        return Config.OMNIROUTER_MODEL

    def set_model(self, model: str) -> None:
        """Doi model runtime (khong can restart)."""
        Config.OMNIROUTER_MODEL = model

    def is_ready(self) -> bool:
        """True neu provider da duoc cau hinh (co API key...)."""
        try:
            return self._get_provider().is_configured()
        except LLMError:
            return False

    def status(self) -> dict:
        return {
            "provider": self.provider_name,
            "model": self.get_model(),
            "configured": self.is_ready(),
            "request_count": self.request_count,
            "error_count": self.error_count,
        }

    async def complete(self, messages: list[dict], model: Optional[str] = None,
                       max_tokens: int = 1500, temperature: float = 0.4) -> str:
        provider = self._get_provider()
        last_error: Optional[Exception] = None

        for attempt in range(len(self.RETRY_DELAYS) + 1):
            try:
                self.request_count += 1
                return await provider.complete(
                    messages, model=model,
                    max_tokens=max_tokens, temperature=temperature,
                )
            except LLMError as e:
                self.error_count += 1
                last_error = e
                # Chi retry khi loi tam thoi (429/5xx), khong retry khi sai key hay sai format
                if e.status in (429,) or (e.status or 0) >= 500:
                    if attempt < len(self.RETRY_DELAYS):
                        delay = self.RETRY_DELAYS[attempt]
                        logger.warning(f"LLM loi {e.status}, retry lan {attempt + 1} sau {delay}s...")
                        await asyncio.sleep(delay)
                        continue
                raise
            except (httpx.TimeoutException, httpx.TransportError) as e:
                self.error_count += 1
                last_error = e
                if attempt < len(self.RETRY_DELAYS):
                    delay = self.RETRY_DELAYS[attempt]
                    logger.warning(f"LLM network/timeout: {type(e).__name__}, retry lan {attempt + 1} sau {delay}s...")
                    await asyncio.sleep(delay)
                    continue
                raise LLMError(f"LLM timeout hoac loi mang: {type(e).__name__}")

        raise LLMError(f"LLM that bai sau {len(self.RETRY_DELAYS) + 1} lan thu: {last_error}")


# Singleton dung chung toan bo he thong
llm_client = LLMClient()
