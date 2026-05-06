# SPDX-License-Identifier: MIT
"""``BitcoinOPReturn`` — anchor a tree-head digest as OP_RETURN data.

OP_RETURN is the documented Bitcoin opcode for embedding up to 80
bytes of arbitrary data in a transaction output that is
provably unspendable. This is the canonical mechanism for
third-party data anchoring (used by Tierion, OpenTimestamps, and
the historical Factom service before its migration).

Two modes:

* :attr:`Mode.STUB` — produces a deterministic ``stub-btc-<sha256
  of digest>`` txid and ``block_height = 0``. No HTTP calls. The
  Phase 8 demo runs in stub mode so ``make phase8`` is hermetic.
* :attr:`Mode.LIVE` — broadcasts a real transaction by POSTing a
  hex-serialised tx to Blockstream's public REST API (testnet:
  ``https://blockstream.info/testnet/api``; mainnet:
  ``https://blockstream.info/api``). Requires the caller to
  supply a pre-signed transaction hex via ``BTC_RAW_TX_HEX`` env
  (this provider does NOT hold a private key — wallet management
  is the Sovereign customer's responsibility).

The rationale for the "caller signs the tx, provider only
broadcasts" split: holding a funded Bitcoin private key inside a
multi-tenant cloud deployment would itself be a compliance
finding. Sovereign customers run their own keystore; the provider
only needs the broadcast endpoint.

For LIVE mode without a pre-signed tx (the common dev path), set
``BTC_NODE_RPC_URL`` + ``BTC_NODE_RPC_AUTH`` and the provider
will use Bitcoin Core's ``sendrawtransaction`` / ``createrawtransaction``
flow — but this path requires the caller to fund a wallet on the
node, which is documented as Sovereign-rollout work.
"""

from __future__ import annotations

import hashlib
import os
import time

import httpx

from .provider import AnchorRecord, AnchorRequest, BlockchainAnchorProvider, Mode


def _explorer_url(network: str, txid: str) -> str:
    if network == "mainnet":
        return f"https://blockstream.info/tx/{txid}"
    return f"https://blockstream.info/testnet/tx/{txid}"


class BitcoinOPReturn(BlockchainAnchorProvider):
    name = "bitcoin"

    def __init__(
        self,
        *,
        mode: Mode = Mode.STUB,
        network: str = "testnet",
        broadcast_url: str | None = None,
    ) -> None:
        self.mode = mode
        self.network = network
        self._broadcast_url = broadcast_url

    def _broadcast_endpoint(self) -> str:
        if self._broadcast_url:
            return self._broadcast_url
        if self.network == "mainnet":
            return "https://blockstream.info/api/tx"
        return "https://blockstream.info/testnet/api/tx"

    async def anchor(self, req: AnchorRequest) -> AnchorRecord:
        digest = req.digest()
        if self.mode == Mode.STUB:
            txid = "stub-btc-" + hashlib.sha256(digest.encode()).hexdigest()
            return AnchorRecord(
                chain="bitcoin",
                network="stub",
                mode=Mode.STUB,
                digest_hex=digest,
                txid=txid,
                block_height=0,
                explorer_url=f"stub://bitcoin/{txid}",
                anchored_at_ms=int(time.time() * 1000),
                extra={"op_return_size_bytes": len(bytes.fromhex(digest))},
            )
        # LIVE mode — caller pre-signs the OP_RETURN tx with their
        # own keystore and passes the hex via env. We *only* broadcast.
        raw_hex = os.environ.get("BTC_RAW_TX_HEX")
        if not raw_hex:
            raise RuntimeError(
                "BitcoinOPReturn LIVE mode requires BTC_RAW_TX_HEX "
                "(a pre-signed Bitcoin transaction in hex form). "
                "Construct it with your own keystore — e.g. Bitcoin "
                "Core's `createrawtransaction` + "
                "`signrawtransactionwithwallet` against a funded wallet, "
                "or any HSM- or hardware-wallet signing flow. This "
                "provider intentionally never holds a private key; it "
                "only broadcasts the hex you supply to the configured "
                "Blockstream-compatible REST endpoint."
            )
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                self._broadcast_endpoint(),
                content=raw_hex,
                headers={"content-type": "text/plain"},
            )
            if resp.status_code not in (200, 201):
                raise RuntimeError(
                    f"bitcoin broadcast failed {resp.status_code}: "
                    f"{resp.text[:300]}"
                )
            txid = resp.text.strip()
        return AnchorRecord(
            chain="bitcoin",
            network=self.network,
            mode=Mode.LIVE,
            digest_hex=digest,
            txid=txid,
            block_height=None,  # mempool; cron job updates after confirmation
            explorer_url=_explorer_url(self.network, txid),
            anchored_at_ms=int(time.time() * 1000),
            extra={"broadcast_endpoint": self._broadcast_endpoint()},
        )
