"""Append-only, hash-chained provenance ledger (specs §21, M0)."""

from fandea.ledger.hashchain import HashChainLedger, LedgerVerificationError

__all__ = ["HashChainLedger", "LedgerVerificationError"]
