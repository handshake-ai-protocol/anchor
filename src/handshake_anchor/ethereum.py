"""``EthereumLog`` — anchor a tree-head digest as a contract event.

Ethereum's ``LOG`` opcode lets a contract emit indexed events
into the receipt trie. Anchoring a 32-byte digest as a single
event topic gives the same tamper-evidence as Bitcoin OP_RETURN
with cheaper per-tx cost on L2s. The Sovereign customer deploys
their own ``HandshakeAnchor`` contract (one-line Solidity) and
configures its address; the provider sends a transaction calling
``anchor(bytes32 digest)``.

Two modes:

* :attr:`Mode.STUB` — deterministic ``stub-eth-<sha256 of digest>``
  txid, no network calls. Demo-safe.
* :attr:`Mode.LIVE` — calls ``eth_sendRawTransaction`` against an
  Infura/Alchemy endpoint. Like the Bitcoin provider, we do NOT
  hold the signing key — the caller pre-signs and passes the raw
  tx hex via ``ETH_RAW_TX_HEX``. ``ETH_RPC_URL`` selects the
  endpoint (defaults to Sepolia testnet via Infura).

Network defaults to ``sepolia`` (Ethereum testnet). Mainnet is
configurable for Sovereign customers willing to pay mainnet gas.
"""

from __future__ import annotations

import hashlib
import os
import time
from typing import Any

import httpx

from .provider import AnchorRecord, AnchorRequest, BlockchainAnchorProvider, Mode

DEFAULT_RPC = {
    "sepolia": "https://rpc.sepolia.org",
    "mainnet": "https://cloudflare-eth.com",
}


def _explorer_url(network: str, txid: str) -> str:
    if network == "mainnet":
        return f"https://etherscan.io/tx/{txid}"
    return f"https://sepolia.etherscan.io/tx/{txid}"


class EthereumLog(BlockchainAnchorProvider):
    name = "ethereum"

    def __init__(
        self,
        *,
        mode: Mode = Mode.STUB,
        network: str = "sepolia",
        rpc_url: str | None = None,
    ) -> None:
        self.mode = mode
        self.network = network
        self._rpc_url = rpc_url

    def _endpoint(self) -> str:
        return self._rpc_url or DEFAULT_RPC.get(
            self.network, DEFAULT_RPC["sepolia"]
        )

    async def anchor(self, req: AnchorRequest) -> AnchorRecord:
        digest = req.digest()
        if self.mode == Mode.STUB:
            txid = "0xstub-eth-" + hashlib.sha256(digest.encode()).hexdigest()
            return AnchorRecord(
                chain="ethereum",
                network="stub",
                mode=Mode.STUB,
                digest_hex=digest,
                txid=txid,
                block_height=0,
                explorer_url=f"stub://ethereum/{txid}",
                anchored_at_ms=int(time.time() * 1000),
                extra={"event": "Anchor(bytes32)"},
            )
        raw_hex = os.environ.get("ETH_RAW_TX_HEX")
        if not raw_hex:
            raise RuntimeError(
                "EthereumLog LIVE mode requires ETH_RAW_TX_HEX "
                "(pre-signed tx hex from caller's keystore); see "
                "docs/integrations/byo_anchor.md for the wallet flow."
            )
        if not raw_hex.startswith("0x"):
            raw_hex = "0x" + raw_hex
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                self._endpoint(),
                json={
                    "jsonrpc": "2.0",
                    "method": "eth_sendRawTransaction",
                    "params": [raw_hex],
                    "id": 1,
                },
                headers={"content-type": "application/json"},
            )
            if resp.status_code != 200:
                raise RuntimeError(
                    f"ethereum broadcast failed {resp.status_code}: "
                    f"{resp.text[:300]}"
                )
            body: dict[str, Any] = resp.json()
            if "error" in body:
                raise RuntimeError(
                    f"ethereum rpc error: {body['error']}"
                )
            txid = str(body.get("result", ""))
            if not txid:
                raise RuntimeError(
                    f"ethereum rpc returned no txid: {body!r}"
                )
        return AnchorRecord(
            chain="ethereum",
            network=self.network,
            mode=Mode.LIVE,
            digest_hex=digest,
            txid=txid,
            block_height=None,
            explorer_url=_explorer_url(self.network, txid),
            anchored_at_ms=int(time.time() * 1000),
            extra={"rpc_endpoint": self._endpoint()},
        )
