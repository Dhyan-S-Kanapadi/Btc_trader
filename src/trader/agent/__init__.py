"""Bounded investigator core; it has no worker, broker, or risk imports."""

from .investigator import InvestigationResult, investigate

__all__ = ["InvestigationResult", "investigate"]
