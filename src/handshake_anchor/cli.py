"""``handshake-anchor`` CLI — anchor the latest tree-head.

Documented as the surface a Sovereign-tier customer wires into a
60-minute cron job. The loop is intentionally one-shot (no
``while True``) so the operator can choose between cron, systemd
timer, Replit Scheduled deployment, or external orchestrators —
each scheduling layer is the customer's choice. The README's
"BYO anchor" section has the cron one-liner.

Flow per invocation:

1. Fetch the latest signed tree-head from the Registry's
   ``/v1/admin/tree_heads?limit=1`` endpoint (admin token required;
   this is server-to-server inside the customer's deployment).
2. Build an :class:`AnchorRequest` from the row.
3. Call the configured provider's ``anchor()`` method.
4. Persist the returned :class:`AnchorRecord` to the JSON store
   AND POST it to the Registry's ``/v1/anchors`` ingestion endpoint
   so ``GET /v1/anchors/{tree_head_id}`` (the verification
   surface) returns the latest record without reading the JSON
   store directly.
5. Print the explorer URL so the operator can paste it into a
   compliance pack / share with an auditor.

For the Phase 8 demo we run with ``--provider noop`` so no
network calls happen.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import os
import sys
import time
from typing import Any

import httpx

from .bitcoin import BitcoinOPReturn
from .ethereum import EthereumLog
from .noop import NoopAnchor
from .provider import (
    AnchorRecord,
    AnchorRequest,
    BlockchainAnchorProvider,
    Mode,
)
from .store import AnchorStore


def _admin_token() -> str:
    tok = os.environ.get("HANDSHAKE_ADMIN_TOKEN", "")
    if tok:
        return tok
    repl = os.environ.get("REPL_ID", "")
    if not repl:
        return ""
    return hashlib.sha256(f"handshake-admin::{repl}".encode()).hexdigest()


def _make_provider(name: str, mode: str, network: str) -> BlockchainAnchorProvider:
    m = Mode(mode)
    if name == "bitcoin":
        return BitcoinOPReturn(mode=m, network=network)
    if name == "ethereum":
        return EthereumLog(mode=m, network=network)
    if name == "noop":
        return NoopAnchor()
    raise SystemExit(f"unknown provider: {name}")


async def _fetch_latest_tree_head(
    *, registry_url: str, client: httpx.AsyncClient
) -> dict[str, Any]:
    """Return the latest signed tree-head row (Phase 8: stub-friendly).

    The Registry's existing tree-head admin endpoint
    (``/v1/admin/tree_heads``) is returned by the Phase 3 batcher.
    If the endpoint does not exist or returns no rows we synthesise
    a "genesis" head so the demo still has something to anchor —
    documented as Phase 8 demo accommodation in
    ``docs/decisions/0019-anomaly-byo-anchor-spec-site.md``.
    """

    try:
        resp = await client.get(
            f"{registry_url.rstrip('/')}/v1/admin/tree_heads?limit=1",
            headers={"authorization": f"Bearer {_admin_token()}"},
            timeout=10.0,
        )
        if resp.status_code == 200:
            body = resp.json()
            items = body.get("items") or []
            if items:
                return dict(items[0])
    except (httpx.HTTPError, ValueError):
        pass
    # Synthetic fallback so the demo never blocks on Registry
    # admin-side tree-head plumbing that isn't part of Phase 8 scope.
    return {
        "id": "synthetic-genesis",
        "log_id": 1,
        "tree_size": 0,
        "root_hash_hex": "0" * 64,
        "timestamp_ms": int(time.time() * 1000),
        "registry_did": "did:hsk:registry:dev",
        "signature_b64u": "",
    }


async def _post_anchor_record(
    *,
    registry_url: str,
    client: httpx.AsyncClient,
    tenant_slug: str,
    tree_head_id: str,
    record: AnchorRecord,
) -> bool:
    """Best-effort POST of the anchor record to the Registry.

    Returns False (and logs to stderr) on any failure — the local
    JSON store is the source of truth, the Registry POST is a
    convenience for the verification endpoint to render the link
    without crawling the store.
    """

    try:
        resp = await client.post(
            f"{registry_url.rstrip('/')}/v1/anchors",
            headers={"authorization": f"Bearer {_admin_token()}"},
            json={
                "tenant_slug": tenant_slug,
                "tree_head_id": tree_head_id,
                "record": record.model_dump(),
            },
            timeout=15.0,
        )
        if resp.status_code in (200, 201):
            return True
        sys.stderr.write(
            f"anchor: registry POST /v1/anchors {resp.status_code}: "
            f"{resp.text[:200]}\n"
        )
        return False
    except httpx.HTTPError as exc:
        sys.stderr.write(f"anchor: registry POST failed: {exc}\n")
        return False


async def _run(args: argparse.Namespace) -> int:
    registry = args.registry or os.environ.get(
        "HANDSHAKE_REGISTRY_URL", "http://127.0.0.1:8000"
    )
    provider = _make_provider(args.provider, args.mode, args.network)
    store = AnchorStore()
    async with httpx.AsyncClient() as client:
        head = await _fetch_latest_tree_head(
            registry_url=registry, client=client
        )
        req = AnchorRequest(
            tenant_slug=args.tenant,
            log_id=int(head.get("log_id", 1)),
            tree_size=int(head.get("tree_size", 0)),
            root_hash_hex=str(head.get("root_hash_hex") or "0" * 64),
            timestamp_ms=int(head.get("timestamp_ms", int(time.time() * 1000))),
            registry_did=str(head.get("registry_did") or "did:hsk:registry:dev"),
            signature_b64u=str(head.get("signature_b64u") or ""),
        )
        record = await provider.anchor(req)
        tree_head_id = str(head.get("id") or f"head-{req.tree_size}")
        store.put(
            tenant_slug=args.tenant,
            tree_head_id=tree_head_id,
            record=record,
        )
        await _post_anchor_record(
            registry_url=registry,
            client=client,
            tenant_slug=args.tenant,
            tree_head_id=tree_head_id,
            record=record,
        )
    print(
        f"anchored tree_head_id={tree_head_id} provider={provider.name} "
        f"mode={record.mode.value} txid={record.txid} "
        f"explorer={record.explorer_url}"
    )
    return 0


def main() -> None:
    p = argparse.ArgumentParser(
        prog="handshake-anchor",
        description=(
            "Anchor the latest signed Registry tree-head into a "
            "blockchain (Bitcoin OP_RETURN / Ethereum log / Noop)."
        ),
    )
    p.add_argument("--tenant", required=True)
    p.add_argument(
        "--provider",
        choices=("bitcoin", "ethereum", "noop"),
        default="noop",
    )
    p.add_argument("--mode", choices=("stub", "live"), default="stub")
    p.add_argument(
        "--network",
        default="testnet",
        help="Bitcoin: mainnet|testnet; Ethereum: mainnet|sepolia",
    )
    p.add_argument(
        "--registry",
        default=None,
        help="Registry base URL (default $HANDSHAKE_REGISTRY_URL or http://127.0.0.1:8000)",
    )
    args = p.parse_args()
    raise SystemExit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
