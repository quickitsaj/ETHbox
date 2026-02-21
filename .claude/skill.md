# ETHbox — Delegation-Aware Ethereum Transaction Simulator

## Project Overview

ETHbox simulates Ethereum transactions in a forked mainnet environment, with a focus on **delegation-aware** execution using the MetaMask Delegation Framework. The core workflow: fork mainnet at a historical block via Anvil, execute real DeFi operations (swaps, price manipulation), and map high-level delegation intents to concrete on-chain caveats.

**License:** Apache 2.0

## Architecture

### Phased Development

- **Phase 0 (current):** Proof of concept (~200 lines Python, no frontend, no LLM). Validates three core assumptions: Anvil fork pipeline, price puppeteering, and caveat resolution mapping. Gated by a GO/NO-GO verdict.
- **Phase 1+:** To be defined after Phase 0 passes. Expected to add frontend, LLM-powered intent parsing, and multi-token/multi-protocol support.

### Module Layout

```
poc/
  main.py       — Entry point. Orchestrates the 4-step POC pipeline.
  fork.py       — Anvil lifecycle (start/stop), web3 connection, balance injection via storage slot overwrite.
  swap.py       — USDC→WETH swap execution through Uniswap V3 SwapRouter02.
  price.py      — Read Uniswap pool and Chainlink oracle prices. Manipulate pool price via large directional swaps.
  caveats.py    — Map delegation intents to MetaMask CaveatBuilder caveat structures.
  constants.py  — Mainnet contract addresses, minimal ABIs, storage slot indices.
```

### POC Pipeline (main.py)

1. **Read baseline prices** — Uniswap V3 pool slot0 + Chainlink ETH/USD oracle
2. **Fund & swap** — Inject USDC via storage slot, execute USDC→WETH through SwapRouter02
3. **Price puppeteering** — Push pool price toward a target via iterative large swaps
4. **Caveat resolution** — Map "allow USDC→WETH swap" intent to AllowedTargets, AllowedMethods, ERC20TransferAmount caveats
5. **GO/NO-GO** — Pass if swap succeeded AND price puppet landed within 10% of target

## Key Domain Concepts

### Uniswap V3 Price Math

The USDC/WETH 0.3% pool (`0x8ad599c3...`) has token0=USDC, token1=WETH. The pool stores `sqrtPriceX96 = sqrt(token1/token0) * 2^96`. To convert to ETH/USD:

```
price_raw = (sqrtPriceX96 / 2^96)^2       # token1/token0 ratio
eth_price_usd = (1 / price_raw) * 10^12   # invert and adjust for decimal difference (18-6)
```

To compute a target sqrtPriceX96 from a desired ETH/USD price:
```
price = 1 / (eth_price_usd * 10^12)
sqrtPriceX96 = int(sqrt(price) * 2^96)
```

### Storage Slot Manipulation (Anvil)

Anvil's `anvil_setStorageAt` RPC lets us directly set ERC-20 balances without needing to acquire tokens. The balance slot for a mapping `mapping(address => uint256)` at storage slot `N` for address `A` is:
```
keccak256(abi.encode(uint256(A), uint256(N)))
```

Known slots:
- **USDC** balance mapping: slot **9**
- **WETH** balance mapping: slot **3**

### MetaMask Delegation Framework Caveats

The project maps high-level intents to CaveatBuilder-compatible structures:
- **AllowedTargets** — Contract addresses the delegate can call (e.g., USDC, SwapRouter02)
- **AllowedMethods** — Function selectors permitted (e.g., `approve`, `exactInputSingle`)
- **ERC20TransferAmount** — Cap on token spend
- **SwapConstraints** — Token pair, fee tier, recipient constraints

### Contract Addresses (Ethereum Mainnet)

| Contract | Address |
|---|---|
| USDC | `0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48` |
| WETH | `0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2` |
| Uniswap V3 SwapRouter02 | `0x68b3465833fb72A70ecDF485E0e4C7bD8665Fc45` |
| USDC/WETH 0.3% Pool | `0x8ad599c3A0ff1De082011EFDDc58f1908eb6e6D8` |
| Chainlink ETH/USD | `0x5f4eC3Df9cbd43714FE2740f5E3616155c5b8419` |

## Development

### Prerequisites

- Python 3.10+
- [Foundry](https://getfoundry.sh/) installed (`anvil` must be on PATH)
- A mainnet RPC URL (Alchemy, Infura, etc.) — store in `.env` as `RPC_URL`, never commit

### Setup & Run

```bash
pip install -r requirements.txt
python -m poc.main --rpc-url "$RPC_URL" --block 19000000
```

The default fork block is **19,000,000** (~Jan 2024, ETH ~$2,400).

### Security Rules

- **Never commit RPC URLs, API keys, or private keys.** The `.gitignore` already excludes `.env`.
- The POC uses Anvil's pre-funded accounts (`w3.eth.accounts[0]`) — no real private keys are involved.
- `amountOutMinimum: 0` is acceptable in a forked simulation but must never be used in production code.

### Testing

No test suite exists yet. When adding tests:
- Use `pytest` as the test runner
- Each test should spin up its own Anvil instance on a unique port to avoid collisions
- Mock RPC URLs are not feasible — tests require a real mainnet RPC for forking
- Consider a shared fixture that starts/stops Anvil per test session

### Code Conventions

- Type hints on all public function signatures
- Minimal ABIs in `constants.py` — only include the functions actually called
- Raw units everywhere (6-decimal for USDC, 18-decimal for WETH/ETH) — never pass float dollar amounts to on-chain calls
- Module imports use relative paths (`from .constants import ...`)

## Common Tasks

### Adding a New Token Pair

1. Add token address and relevant pool address to `constants.py`
2. Look up the pool's token0/token1 ordering — this affects price math direction
3. Find the token's balance storage slot (use `forge inspect <Contract> storageLayout` or brute-force with Anvil)
4. Add a fund function in `fork.py`
5. Add swap function in `swap.py`, reusing the SwapRouter02 ABI
6. Update price math in `price.py` for the new decimal difference

### Adding a New Caveat Type

1. Define the caveat structure in `caveats.py`
2. Compute any new function selectors via `Web3.keccak(text="functionSignature")`
3. Add to the returned dict in the intent-mapping function

### Changing the Fork Block

Pass `--block <number>` to the CLI. Be aware:
- Contract deployments must exist at the chosen block
- Pool liquidity and price will differ — tolerance thresholds may need adjustment
- Chainlink oracle answers are block-dependent
