"""Rewards rules engine (ADR-008). Phase 5.

Public surface grows over the phase:
  - 5.1: v8 schema (migrations/m008_reward_rules.py) — done.
  - 5.2: seed_all() / seed_card() — turn ccyamls/*.yaml into rows — done.
  - 5.3: rebuild_all() / evaluate_bonuses() — the accrual engine (this task).
  - 5.4: effective rates + reconciliation reports.
"""
from .engine import evaluate_bonuses, rebuild_all
from .seed import seed_all, seed_card

__all__ = ["seed_all", "seed_card", "rebuild_all", "evaluate_bonuses"]
