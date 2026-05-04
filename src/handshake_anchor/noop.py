# SPDX-License-Identifier: MIT
"""``NoopAnchor`` — default provider for non-Sovereign tenants.

Records what *would* have been anchored without making a network
call. The returned :class:`AnchorRecord` carries the digest so
:class:`~handshake_anchor.store.AnchorStore` can still surface
"we computed this digest at this time" to operators, and so a
later switch from Noop → Bitcoin / Ethereum has a clean replay
path (the digest is reproducible from the same
:class:`AnchorRequest`).

The txid is set to ``noop:<digest_hex>`` so it's lexically
distinct from a real chain txid and never accidentally
mistaken for one.
"""

from __future__ import annotations

import time

from .provider import AnchorRecord, AnchorRequest, BlockchainAnchorProvider, Mode


class NoopAnchor(BlockchainAnchorProvider):
    name = "noop"

    def __init__(self) -> None:
        self.mode = Mode.STUB

    async def anchor(self, req: AnchorRequest) -> AnchorRecord:
        digest = req.digest()
        return AnchorRecord(
            chain="noop",
            network="stub",
            mode=Mode.STUB,
            digest_hex=digest,
            txid=f"noop:{digest}",
            block_height=None,
            explorer_url=f"stub://noop/{digest}",
            anchored_at_ms=int(time.time() * 1000),
            extra={"reason": "non_sovereign_tenant"},
        )
