"""Read-only market data. This adapter has no brokerage/order endpoints."""
import time
from datetime import datetime, timedelta, timezone
import httpx


class ProviderError(Exception):
    pass


class AlpacaProvider:
    def __init__(self, settings, transport=None):
        self.settings = settings
        self.transport = transport

    def fetch(self, symbols):
        if not self.settings.alpaca_key.get_secret_value() or not self.settings.alpaca_secret.get_secret_value():
            raise ProviderError("Add AXIOM_ALPACA_KEY and AXIOM_ALPACA_SECRET to .env, then restart.")
        headers = {"APCA-API-KEY-ID": self.settings.alpaca_key.get_secret_value(),
                   "APCA-API-SECRET-KEY": self.settings.alpaca_secret.get_secret_value()}
        with httpx.Client(base_url="https://data.alpaca.markets", headers=headers,
                          timeout=15, transport=self.transport) as client:
            def get(path, params):
                for attempt in range(3):
                    try:
                        result = client.get(path, params=params)
                        if result.status_code == 429 or result.status_code >= 500:
                            if attempt < 2:
                                time.sleep(.25 * 2**attempt)
                                continue
                        result.raise_for_status()
                        payload = result.json()
                        if not isinstance(payload, dict):
                            raise ValueError('Expected object')
                        return payload
                    except httpx.HTTPStatusError as exc:
                        raise ProviderError(f"Alpaca returned HTTP {exc.response.status_code}; check credentials, feed access or rate limits.") from None
                    except (httpx.TransportError, ValueError):
                        if attempt == 2:
                            raise ProviderError("Alpaca could not be reached or returned invalid data.") from None
                        time.sleep(.25 * 2**attempt)
            news, token = [], None
            # Bounded catch-up per cycle; overlap and URL dedupe make repeated polling safe.
            for _ in range(4):
                params = {"symbols": ','.join(symbols), "limit": 50, "include_content": "true",
                          "start": (datetime.now(timezone.utc)-timedelta(days=2)).isoformat(), "sort": "desc"}
                if token:
                    params['page_token'] = token
                page = get("/v1beta1/news", params)
                items = page.get('news', [])
                if not isinstance(items, list):
                    raise ProviderError('Alpaca returned an unexpected news format.')
                news.extend(items)
                token = page.get('next_page_token')
                if not token:
                    break
            bars = get("/v2/stocks/bars/latest", {"symbols": ','.join(symbols), "feed": self.settings.alpaca_feed})
            values = bars.get('bars', {})
            if not isinstance(values, dict):
                raise ProviderError('Alpaca returned an unexpected bars format.')
            return news, values, bool(token)
