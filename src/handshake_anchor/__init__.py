"""``handshake-anchor`` — BYO blockchain anchor providers.

The :class:`~handshake_anchor.provider.BlockchainAnchorProvider`
Protocol abstracts the act of anchoring a signed tree-head into
an external blockchain so that even a Registry compromise cannot
rewrite history. Sovereign-tier customers configure one of:

* :class:`~handshake_anchor.bitcoin.BitcoinOPReturn` — OP_RETURN
  data carriers on Bitcoin (testnet by default; mainnet via
  configuration). Uses Blockstream's public REST API to broadcast
  in STUB mode and Bitcoin Core RPC in LIVE mode.
* :class:`~handshake_anchor.ethereum.EthereumLog` — emits a
  contract event whose data field is the tree-head digest. Uses
  Infura/Alchemy JSON-RPC.
* :class:`~handshake_anchor.noop.NoopAnchor` — default for
  non-Sovereign tenants; records anchor requests in the local
  store for replay but never broadcasts.
"""

from .bitcoin import BitcoinOPReturn  # noqa: F401
from .ethereum import EthereumLog  # noqa: F401
from .noop import NoopAnchor  # noqa: F401
from .provider import (  # noqa: F401
    AnchorRecord,
    AnchorRequest,
    BlockchainAnchorProvider,
    Mode,
)
from .store import AnchorStore  # noqa: F401
