# ETHbox

Delegation-aware Ethereum transaction simulator.

## Phase 0 — Proof of Concept

Validates three core assumptions (~200 lines of Python, no frontend, no LLM):

1. **Anvil fork pipeline** — Fork mainnet at a historical block, execute a USDC→WETH swap through the real Uniswap V3 SwapRouter02.
2. **Price puppeteering** — Move Uniswap pool reserves via large swaps to match a target price, then validate the result.
3. **Caveat resolution mapping** — Map a delegation intent ("allow USDC→WETH swap") to concrete MetaMask CaveatBuilder caveats (AllowedTargets, AllowedMethods, ERC20TransferAmount).

### Prerequisites

- Python 3.10+
- [Foundry](https://getfoundry.sh/) (`anvil` on PATH)
- A mainnet RPC URL (Alchemy, Infura, etc.)

### Run

```bash
pip install -r requirements.txt
python -m poc.main --rpc-url https://eth-mainnet.g.alchemy.com/v2/YOUR_KEY --block 19000000
```

### GO / NO-GO gate

The script prints a verdict:
- **GO** — swap executed, price puppet within 10% of target. Proceed to Phase 1.
- **NO-GO** — something is off. Investigate before continuing.
