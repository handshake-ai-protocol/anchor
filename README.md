# handshake-anchor

Blockchain anchoring providers for Handshake tree-heads. Sovereign-tier
operators run a periodic job that publishes the latest signed tree-head
digest to a public ledger so any auditor can independently verify that the
Registry's transparency log was not rewritten.

## Install

```bash
pip install handshake-anchor
```

## The `BlockchainAnchorProvider` Protocol

Anchoring backends implement a single async method:

```python
class BlockchainAnchorProvider(Protocol):
    name: str

    async def anchor(self, req: AnchorRequest) -> AnchorRecord: ...
```

`AnchorRequest` carries the tree-head ID, root hash, tree size, and a
canonical SHA-256 digest. `AnchorRecord` is the receipt — chain, network,
mode (`STUB` / `LIVE`), txid, block height, explorer URL, and timestamp —
that gets persisted locally and POSTed back to the Registry's
`/v1/anchors` ingestion endpoint.

## Reference implementations

| Provider          | Module                  | Notes                                                                          |
| ----------------- | ----------------------- | ------------------------------------------------------------------------------ |
| `BitcoinOPReturn` | `handshake_anchor.bitcoin`  | OP_RETURN broadcast to a Blockstream-compatible REST endpoint; caller pre-signs the transaction. |
| `EthereumLog`     | `handshake_anchor.ethereum` | Calls a Sovereign-deployed `HandshakeAnchor.anchor(bytes32)` contract; caller pre-signs. |
| `NoopAnchor`      | `handshake_anchor.noop`     | Records a deterministic stub record without any network call. Demo-safe.       |

In both LIVE backends the provider only **broadcasts** — wallet and key
material live with the Sovereign customer. See each module's docstring
for the BYO-keystore flow.

## CLI

```bash
handshake-anchor --provider bitcoin --network testnet --mode stub
```

Wire it into `cron`, a systemd timer, a cloud scheduler, or any external
orchestrator.

## License

MIT — see `LICENSE`.
