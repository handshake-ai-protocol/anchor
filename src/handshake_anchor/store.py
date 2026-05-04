# SPDX-License-Identifier: MIT
"""Tenant-scoped JSON store for :class:`AnchorRecord` rows.

We deliberately do NOT add a Postgres table in Phase 8 — the
Sovereign-tier storage decision (separate tenant DBs vs. a single
shared anchors table with RLS) is part of Phase 9. The JSON store
matches the pattern used by Phase 7 integrations and the Phase 8
anomaly detector, so a Sovereign customer's tree-head anchor
history is recoverable without a database.

Shape on disk:

    {
      "<tenant_slug>": {
        "<tree_head_id>": [AnchorRecord, ...],
        ...
      },
      ...
    }

Multiple records per tree-head id support re-anchoring (for
example, anchor the same tree head to both Bitcoin and Ethereum
for redundancy, or re-anchor on a different network when a
mainnet rollout happens).
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from .provider import AnchorRecord

DEFAULT_STORE_PATH = Path(
    os.environ.get("HANDSHAKE_ANCHOR_STORE", "state/handshake-anchors.json")
)


class AnchorStore:
    def __init__(self, path: Path = DEFAULT_STORE_PATH) -> None:
        self.path = path
        self._cache: dict[str, dict[str, list[dict[str, Any]]]] = {}
        self._loaded = False

    def _load(self) -> None:
        if self._loaded:
            return
        if self.path.exists():
            try:
                raw = json.loads(self.path.read_text())
                if isinstance(raw, dict):
                    self._cache = raw
            except (OSError, json.JSONDecodeError):
                self._cache = {}
        self._loaded = True

    def _flush(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(
            prefix=self.path.name + ".",
            dir=str(self.path.parent),
        )
        try:
            with os.fdopen(fd, "w") as fh:
                json.dump(self._cache, fh, indent=2, sort_keys=True)
            os.replace(tmp, self.path)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def put(
        self,
        *,
        tenant_slug: str,
        tree_head_id: str,
        record: AnchorRecord,
    ) -> None:
        if not tenant_slug:
            raise ValueError("tenant_slug required")
        if not tree_head_id:
            raise ValueError("tree_head_id required")
        self._load()
        sub = self._cache.setdefault(tenant_slug, {})
        per_head = sub.setdefault(tree_head_id, [])
        per_head.append(record.model_dump())
        self._flush()

    def list_for(
        self, *, tenant_slug: str, tree_head_id: str
    ) -> list[AnchorRecord]:
        self._load()
        sub = self._cache.get(tenant_slug, {})
        rows = sub.get(tree_head_id, [])
        return [AnchorRecord.model_validate(r) for r in rows]

    def all_for_tenant(
        self, *, tenant_slug: str
    ) -> dict[str, list[AnchorRecord]]:
        self._load()
        sub = self._cache.get(tenant_slug, {})
        return {
            head: [AnchorRecord.model_validate(r) for r in rows]
            for head, rows in sub.items()
        }

    def reset(self) -> None:
        self._cache = {}
        self._loaded = False
