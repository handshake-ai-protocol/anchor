# SPDX-License-Identifier: MIT
"""``BlockchainAnchorProvider`` Protocol + shared data types.

Each provider implementation takes a signed Registry tree-head
(the same shape :class:`handshake_registry.db.models.TreeHead` is
serialised to: ``log_id``, ``tree_size``, ``root_hash`` (hex),
``timestamp_ms``, ``signature`` (b64u), ``registry_did``) and
writes a digest of it onto a chain. The returned
:class:`AnchorRecord` is what the Registry's anchor verification
endpoint surfaces.

Two modes per provider, mirroring the Phase 7 integrations
pattern:

* :attr:`Mode.STUB` — deterministic, no network. The provider
  fabricates a believable txid (sha256 of the digest) and
  ``block_height = 0`` and returns immediately. Used by the demo
  and tests so ``make phase8`` is hermetic.
* :attr:`Mode.LIVE` — real network call. Bitcoin uses Blockstream
  ``POST /tx`` (testnet) or Bitcoin Core RPC; Ethereum uses
  ``eth_sendRawTransaction`` against Infura/Alchemy. Live mode
  requires per-vendor credentials in env (Bitcoin: funded WIF
  private key + endpoint; Ethereum: keystore + Infura project
  id).

The provider deliberately has zero awareness of the Registry's
key material — the tree-head it receives is *already* signed.
What this layer adds is independent third-party tamper evidence:
even if every Registry replica is compromised tomorrow, the
historical tree-head digests on Bitcoin / Ethereum cannot be
rewritten without breaking SHA-256 / re-mining the chain.
"""

from __future__ import annotations

import hashlib
from enum import Enum
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field


class Mode(str, Enum):
    STUB = "stub"
    LIVE = "live"


class AnchorRequest(BaseModel):
    """Input to :py:meth:`BlockchainAnchorProvider.anchor`.

    The shape mirrors a Registry-signed tree-head row. Hex-encoded
    bytes everywhere so the JSON envelope is portable.
    """

    model_config = ConfigDict(extra="forbid")

    tenant_slug: str
    log_id: int
    tree_size: int
    root_hash_hex: str
    timestamp_ms: int
    registry_did: str
    signature_b64u: str

    def digest(self) -> str:
        """SHA-256 over the canonical anchor input.

        This is what actually goes on chain (32 bytes -> 64 hex).
        Including the ``registry_did`` and signature in the digest
        binds the anchor to a specific Registry signing identity:
        anchoring the same root hash signed by a different DID
        produces a different on-chain digest, so the anchor commits
        to *who* signed the head, not just the bytes of the head.
        """

        h = hashlib.sha256()
        h.update(self.tenant_slug.encode())
        h.update(b"|")
        h.update(str(self.log_id).encode())
        h.update(b"|")
        h.update(str(self.tree_size).encode())
        h.update(b"|")
        h.update(self.root_hash_hex.encode())
        h.update(b"|")
        h.update(str(self.timestamp_ms).encode())
        h.update(b"|")
        h.update(self.registry_did.encode())
        h.update(b"|")
        h.update(self.signature_b64u.encode())
        return h.hexdigest()


class AnchorRecord(BaseModel):
    """Result of a successful anchoring operation.

    ``explorer_url`` is the public block-explorer link an operator
    can share with a customer's auditor to *visually* confirm the
    digest landed on chain. STUB mode produces a placeholder URL
    that begins with ``stub://`` so it never points at a real
    site (and is easy to grep out of demo output).
    """

    model_config = ConfigDict(extra="forbid")

    chain: str  # "bitcoin" | "ethereum" | "noop"
    network: str  # "mainnet" | "testnet" | "sepolia" | "stub"
    mode: Mode
    digest_hex: str
    txid: str
    block_height: int | None = None
    explorer_url: str
    anchored_at_ms: int
    extra: dict[str, Any] = Field(default_factory=dict)


class BlockchainAnchorProvider(Protocol):
    """Single-method anchoring interface."""

    name: str  # "bitcoin" | "ethereum" | "noop"
    mode: Mode

    async def anchor(self, req: AnchorRequest) -> AnchorRecord:
        ...
