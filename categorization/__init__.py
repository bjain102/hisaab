"""Categorization pipeline (ADR-009). Phase 4.

Public surface grows over the phase:
  - 4.1: normalize() — the pure description-cleaning function (this task).
  - 4.2: v7 merchants/aliases schema + precedence backfill.
  - 4.3: review queue + trust meter.

Later, for the dashboard's behaviour lens:
  - classify_channel() — UPI-on-credit-card vs card auth, derived from the
    same leading-token peel normalize() uses.
"""
from .channel import classify_channel
from .normalize import leading_instrument_tokens, normalize

__all__ = ["normalize", "leading_instrument_tokens", "classify_channel"]
