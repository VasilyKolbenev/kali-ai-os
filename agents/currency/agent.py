"""Currency agent — exchange rates and conversion via open.er-api.com (free, no key)."""

import logging
import os
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from agents._base.agent_base import BaseAgent
from kernel.sandbox.http_client import HttpRequest, SandboxHttpClient, SandboxHttpError

logger = logging.getLogger(__name__)

BASE_URL = "https://open.er-api.com/v6/latest"


class CurrencyAgent(BaseAgent):
    """Agent for fetching exchange rates and converting currencies."""

    def get_name(self) -> str:
        """Return agent name."""
        return "currency"

    def handle_action(self, action: str, args: dict[str, Any]) -> dict[str, Any]:
        """Dispatch action to appropriate handler.

        Args:
            action: Action name (get_rates, convert).
            args: Action arguments.

        Returns:
            Result dictionary.
        """
        if action == "get_rates":
            return self._get_rates(args.get("base", "USD"))
        elif action == "convert":
            return self._convert(
                args.get("amount", 1.0),
                args.get("from_currency", "USD"),
                args.get("to_currency", "RUB"),
            )
        else:
            raise ValueError(f"Unknown action: {action}")

    def _fetch_rates(self, base: str) -> dict[str, Any]:
        """Fetch exchange rates from the API.

        Routes egress through the SSRF/whitelist guard (private-IP block +
        redirect re-check). Whitelist is locked to open.er-api.com so a
        tampered BASE_URL cannot exfiltrate to an arbitrary host.

        Args:
            base: Base currency code (e.g. 'USD').

        Returns:
            Parsed API response, or dict with 'error' key on failure.
        """
        url = f"{BASE_URL}/{base.upper()}"
        client = SandboxHttpClient("currency", allowed_domains=["open.er-api.com"])
        try:
            resp = client.request(HttpRequest(url=url, method="GET", timeout=10.0))
            return resp.json()
        except SandboxHttpError as e:
            return {"error": str(e)}
        except Exception as e:
            return {"error": str(e)}

    def _get_rates(self, base: str = "USD") -> dict[str, Any]:
        """Get current exchange rates for a base currency.

        Args:
            base: Base currency code (default 'USD').

        Returns:
            Dict with base currency, rates dict, and last update time.
        """
        data = self._fetch_rates(base)
        if "error" in data:
            return data
        if data.get("result") != "success":
            return {"error": data.get("error-type", "API error")}
        rates = data.get("rates", {})
        # Return a useful subset of common currencies
        common = ["USD", "EUR", "RUB", "GBP", "CNY", "JPY", "TRY", "UAH", "KZT", "BYN"]
        filtered = {k: v for k, v in rates.items() if k in common}
        return {
            "base": data.get("base_code"),
            "rates": filtered,
            "all_rates_count": len(rates),
            "time_last_update": data.get("time_last_update_utc"),
        }

    def _convert(self, amount: float, from_currency: str, to_currency: str) -> dict[str, Any]:
        """Convert an amount between two currencies.

        Args:
            amount: Amount to convert.
            from_currency: Source currency code.
            to_currency: Target currency code.

        Returns:
            Dict with original amount, converted amount, and rate.
        """
        data = self._fetch_rates(from_currency)
        if "error" in data:
            return data
        if data.get("result") != "success":
            return {"error": data.get("error-type", "API error")}
        rates = data.get("rates", {})
        to_upper = to_currency.upper()
        if to_upper not in rates:
            return {"error": f"Currency not found: {to_currency}"}
        rate = rates[to_upper]
        converted = round(float(amount) * rate, 4)
        return {
            "from": from_currency.upper(),
            "to": to_upper,
            "amount": amount,
            "converted": converted,
            "rate": rate,
            "time_last_update": data.get("time_last_update_utc"),
        }


if __name__ == "__main__":
    CurrencyAgent().run()
