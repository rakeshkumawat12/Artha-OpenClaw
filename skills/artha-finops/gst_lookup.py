"""
gst_lookup.py — GST Rate Lookup via Web Search
Searches the internet to find the correct GST rate for a given product/service.
Falls back to 18% if the rate cannot be determined.
"""

import re
import urllib.request
import urllib.parse
import json
from typing import Optional, Tuple

# ---------------------------------------------------------------------------
# Hardcoded fast-path table (common items, avoids unnecessary web calls)
# Source: GST council rate schedule
# ---------------------------------------------------------------------------
KNOWN_RATES: dict[str, tuple[float, str]] = {
    # 0%
    "milk": (0.0, "GST exempt — fresh milk"),
    "eggs": (0.0, "GST exempt — eggs"),
    "vegetables": (0.0, "GST exempt — fresh vegetables"),
    "fruits": (0.0, "GST exempt — fresh fruits"),
    "rice": (0.0, "GST exempt — rice"),
    "wheat": (0.0, "GST exempt — wheat"),
    "bread": (0.0, "GST exempt — bread"),
    "salt": (0.0, "GST exempt — salt"),
    # 5%
    "sugar": (0.05, "GST Schedule I — 5%"),
    "tea": (0.05, "GST Schedule I — 5%"),
    "coffee": (0.05, "GST Schedule I — 5%"),
    "edible oil": (0.05, "GST Schedule I — 5%"),
    "coal": (0.05, "GST Schedule I — 5%"),
    "transport": (0.05, "GST Schedule I — passenger transport 5%"),
    "medicine": (0.05, "GST Schedule I — medicines 5%"),
    "medicines": (0.05, "GST Schedule I — medicines 5%"),
    "pharmaceutical": (0.05, "GST Schedule I — pharma 5%"),
    "fertilizer": (0.05, "GST Schedule I — fertilizers 5%"),
    # 12%
    "mobile phone": (0.12, "GST Schedule II — mobile phones 12%"),
    "mobile": (0.12, "GST Schedule II — mobile phones 12%"),
    "phone": (0.12, "GST Schedule II — mobile phones 12%"),
    "smartphone": (0.12, "GST Schedule II — mobile phones 12%"),
    "butter": (0.12, "GST Schedule II — 12%"),
    "ghee": (0.12, "GST Schedule II — 12%"),
    "fruit juice": (0.12, "GST Schedule II — 12%"),
    "processed food": (0.12, "GST Schedule II — 12%"),
    "printing": (0.12, "GST Schedule II — printing services 12%"),
    "hotel": (0.12, "GST — hotel room tariff < ₹7500, 12%"),
    # 18%
    "software": (0.18, "GST Schedule III — IT services 18%"),
    "saas": (0.18, "GST Schedule III — software/SaaS 18%"),
    "website": (0.18, "GST Schedule III — IT/web services 18%"),
    "web design": (0.18, "GST Schedule III — IT services 18%"),
    "web development": (0.18, "GST Schedule III — IT services 18%"),
    "app development": (0.18, "GST Schedule III — IT services 18%"),
    "mobile app": (0.18, "GST Schedule III — IT services 18%"),
    "consulting": (0.18, "GST Schedule III — professional services 18%"),
    "design": (0.18, "GST Schedule III — design services 18%"),
    "logo design": (0.18, "GST Schedule III — design services 18%"),
    "graphic design": (0.18, "GST Schedule III — design services 18%"),
    "marketing": (0.18, "GST Schedule III — marketing services 18%"),
    "advertising": (0.18, "GST Schedule III — advertising 18%"),
    "it services": (0.18, "GST Schedule III — IT services 18%"),
    "cloud": (0.18, "GST Schedule III — cloud/hosting services 18%"),
    "hosting": (0.18, "GST Schedule III — hosting services 18%"),
    "aws": (0.18, "GST Schedule III — cloud services 18%"),
    "azure": (0.18, "GST Schedule III — cloud services 18%"),
    "figma": (0.18, "GST Schedule III — SaaS subscription 18%"),
    "subscription": (0.18, "GST Schedule III — software subscription 18%"),
    "legal": (0.18, "GST Schedule III — legal services 18%"),
    "accounting": (0.18, "GST Schedule III — accounting services 18%"),
    "financial": (0.18, "GST Schedule III — financial services 18%"),
    "restaurant": (0.18, "GST — restaurant (AC) 18%"),
    "air conditioned": (0.18, "GST — AC restaurant 18%"),
    "paint": (0.18, "GST Schedule III — paints 18%"),
    "cement": (0.18, "GST Schedule III — cement 18%"),
    "iron": (0.18, "GST Schedule III — iron/steel 18%"),
    "steel": (0.18, "GST Schedule III — iron/steel 18%"),
    # 28%
    "car": (0.28, "GST Schedule IV — motor vehicles 28%"),
    "automobile": (0.28, "GST Schedule IV — automobiles 28%"),
    "tobacco": (0.28, "GST Schedule IV — tobacco 28%"),
    "cigarette": (0.28, "GST Schedule IV — tobacco 28%"),
    "aerated": (0.28, "GST Schedule IV — aerated drinks 28%"),
    "cold drink": (0.28, "GST Schedule IV — aerated drinks 28%"),
    "luxury": (0.28, "GST Schedule IV — luxury goods 28%"),
    "washing machine": (0.28, "GST Schedule IV — white goods 28%"),
    "refrigerator": (0.28, "GST Schedule IV — white goods 28%"),
    "air conditioner": (0.28, "GST Schedule IV — AC units 28%"),
    "ac unit": (0.28, "GST Schedule IV — AC units 28%"),
    "television": (0.28, "GST Schedule IV — large TVs 28%"),
    "casino": (0.28, "GST Schedule IV — casino/betting 28%"),
    "betting": (0.28, "GST Schedule IV — gambling 28%"),
}

DEFAULT_RATE = 0.18
DEFAULT_SOURCE = "Default GST rate (18%) — could not determine product-specific rate"


def _match_known(description: str) -> Optional[Tuple[float, str]]:
    """Check description against the local fast-path table."""
    lower = description.lower()
    # Longer keys first so "web design" beats "design"
    for key in sorted(KNOWN_RATES.keys(), key=len, reverse=True):
        if key in lower:
            return KNOWN_RATES[key]
    return None


def _web_search_gst(description: str) -> Optional[Tuple[float, str]]:
    """
    Search DuckDuckGo Instant Answer API for GST rate.
    Returns (rate, source_text) or None if not found.
    """
    query = f"GST rate India {description} percent"
    encoded = urllib.parse.quote(query)
    url = f"https://api.duckduckgo.com/?q={encoded}&format=json&no_redirect=1&no_html=1"

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "ArthaFinOps/1.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())

        # Try Abstract text
        text = data.get("AbstractText", "") or data.get("Answer", "")
        if text:
            rate = _extract_rate_from_text(text)
            if rate is not None:
                return rate, f"Web: {text[:120]}"

        # Try related topics
        for topic in data.get("RelatedTopics", []):
            snippet = topic.get("Text", "")
            if "gst" in snippet.lower() or "%" in snippet:
                rate = _extract_rate_from_text(snippet)
                if rate is not None:
                    return rate, f"Web: {snippet[:120]}"

    except Exception:
        pass  # Network error or timeout — fall through to default

    return None


def _extract_rate_from_text(text: str) -> Optional[float]:
    """
    Extract a GST percentage from free text.
    Looks for patterns like: 18%, 12 percent, GST of 5%
    Only returns valid Indian GST slab values: 0, 5, 12, 18, 28.
    """
    VALID_SLABS = {0, 5, 12, 18, 28}

    # Pattern: "18%" or "18 percent" near GST context
    patterns = [
        r'gst\s+(?:rate\s+)?(?:is\s+|of\s+)?(\d+)\s*%',
        r'(\d+)\s*%\s+gst',
        r'gst.*?(\d+)\s*(?:%|percent)',
        r'(\d+)\s*(?:%|percent).*?gst',
        r'(\d+)\s*%',  # last resort: any percentage
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            val = int(match.group(1))
            if val in VALID_SLABS:
                return val / 100.0

    return None


def lookup_gst_rate(description: str) -> dict:
    """
    Main entry point. Given a product/service description, return the GST rate.

    Returns:
        {
            "gst_rate": float,          # e.g. 0.18
            "gst_percent": int,         # e.g. 18
            "source": str,              # how the rate was determined
            "lookup_method": str,       # "local_table" | "web_search" | "default"
        }
    """
    # 1. Fast-path: local table
    match = _match_known(description)
    if match:
        rate, source = match
        return {
            "gst_rate": rate,
            "gst_percent": int(rate * 100),
            "source": source,
            "lookup_method": "local_table",
        }

    # 2. Web search
    web_match = _web_search_gst(description)
    if web_match:
        rate, source = web_match
        return {
            "gst_rate": rate,
            "gst_percent": int(rate * 100),
            "source": source,
            "lookup_method": "web_search",
        }

    # 3. Default fallback
    return {
        "gst_rate": DEFAULT_RATE,
        "gst_percent": int(DEFAULT_RATE * 100),
        "source": DEFAULT_SOURCE,
        "lookup_method": "default",
    }


if __name__ == "__main__":
    test_cases = [
        "website design",
        "mobile phone",
        "rice and wheat",
        "car purchase",
        "AWS hosting charges",
        "Figma subscription",
        "office supplies",
        "logo design",
        "consulting services",
    ]
    for desc in test_cases:
        result = lookup_gst_rate(desc)
        print(f"  {desc:<30} → {result['gst_percent']}%  [{result['lookup_method']}]  {result['source'][:60]}")
