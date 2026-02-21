# ETHbox

Delegation-aware Ethereum transaction simulator. Validates the feasibility of delegated trading on Ethereum using MetaMask's Delegation Framework.

**Status:** Phase 0 — Proof of Concept

## Overview

ETHbox forks Ethereum mainnet using Anvil, executes real swaps through Uniswap V3, and maps delegation intents to concrete MetaMask CaveatBuilder constraints. The Phase 0 POC validates three core assumptions (~200 lines of Python, no frontend, no LLM):

1. **Anvil fork pipeline** — Fork mainnet at a historical block, execute a USDC→WETH swap through the real Uniswap V3 SwapRouter02.
2. **Price puppeteering** — Move Uniswap pool reserves via large swaps to match a target price, then validate the result.
3. **Caveat resolution mapping** — Map a delegation intent ("allow USDC→WETH swap") to concrete MetaMask CaveatBuilder caveats (AllowedTargets, AllowedMethods, ERC20TransferAmount).

## Project Structure

```
ETHbox/
├── poc/                              # Phase 0 proof of concept
│   ├── main.py                       # Entry point — orchestrates the 4-step flow
│   ├── fork.py                       # Anvil lifecycle & account funding
│   ├── swap.py                       # USDC→WETH swap execution via Uniswap V3
│   ├── price.py                      # Price reading, manipulation, validation
│   ├── caveats.py                    # Delegation intent → MetaMask caveat mapping
│   └── constants.py                  # Mainnet contract addresses & ABIs
├── tests/                            # Layered test suite
│   ├── conftest.py                   # Shared pytest fixtures (Anvil lifecycle)
│   ├── test_caveats_unit.py          # Pure function tests (no EVM)
│   ├── test_caveats_local.py         # Local Anvil tests (no mainnet fork)
│   └── test_integration_fork.py      # Mainnet fork integration tests
├── docs/
│   └── caveat-testing-assessment.md  # Testing strategy & recommendations
├── pyproject.toml
├── requirements.txt
└── LICENSE                           # Apache 2.0
```

## Prerequisites

- Python 3.10+
- [Foundry](https://getfoundry.sh/) (`anvil` must be on PATH)
- A mainnet RPC URL (Alchemy, Infura, etc.)

## Installation

```bash
pip install -r requirements.txt
```

Dependencies: `web3>=6.0,<7` and `pytest>=7.0`.

## Usage

Run the Phase 0 POC:

```bash
python -m poc.main \
  --rpc-url https://eth-mainnet.g.alchemy.com/v2/YOUR_KEY \
  --block 19000000
```

| Flag | Required | Description |
|------|----------|-------------|
| `--rpc-url` | Yes | Ethereum mainnet RPC endpoint |
| `--block` | No | Fork block number (default: `19000000`, ~Jan 2024, ETH ~$2,400) |

## How It Works

The script executes a 4-step validation flow:

1. **Read baseline prices** — Fetches the current ETH/USD price from the Uniswap V3 USDC/WETH pool and the Chainlink ETH/USD oracle.
2. **Fund & swap** — Injects USDC and ETH into a test account via Anvil storage manipulation, then executes a 10,000 USDC → WETH swap through SwapRouter02.
3. **Price puppeteering** — Iteratively executes large swaps to move the pool price toward a target ($2,600). Validates the result is within 10% of the target.
4. **Caveat resolution** — Maps the swap intent to a MetaMask caveat structure containing AllowedTargets, AllowedMethods, ERC20TransferAmount, and SwapConstraints.

### GO / NO-GO Verdict

The script prints a final verdict:

- **GO** — Swap executed successfully, price puppet within tolerance. Proceed to Phase 1.
- **NO-GO** — Something failed. Investigate before continuing.

## Contracts Used

ETHbox interacts with existing mainnet contracts (no custom contracts deployed):

| Contract | Address | Role |
|----------|---------|------|
| USDC | `0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48` | Input token (6 decimals) |
| WETH | `0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2` | Output token (18 decimals) |
| Uniswap V3 SwapRouter02 | `0x68b3465833fb72A70ecDF485E0e4C7bD8665Fc45` | Swap execution |
| USDC/WETH 0.3% Pool | `0x8ad599c3A0ff1De082011EFDDc58f1908eb6e6D8` | Price source & liquidity |
| Chainlink ETH/USD | `0x5f4eC3Df9cbd43714FE2740f5E3616155c5b8419` | Price oracle reference |

## Testing

The test suite uses a layered approach:

```bash
# Unit tests — pure function tests, no dependencies, fast
pytest tests/test_caveats_unit.py -v

# Local EVM tests — requires anvil, no RPC needed
pytest tests/test_caveats_local.py -v

# Integration tests — requires anvil and a mainnet RPC URL
RPC_URL=https://eth-mainnet.g.alchemy.com/v2/YOUR_KEY \
  pytest tests/test_integration_fork.py -v

# All tests
RPC_URL=https://eth-mainnet.g.alchemy.com/v2/YOUR_KEY \
  pytest tests/ -v
```

| Layer | File | What it tests | Requirements |
|-------|------|---------------|--------------|
| Unit | `test_caveats_unit.py` | Caveat dict structure, selectors, parameter propagation | None |
| Local | `test_caveats_local.py` | Selectors against mock ERC-20 on local Anvil | Foundry |
| Integration | `test_integration_fork.py` | Full flow against real Uniswap V3 & Chainlink on mainnet fork | Foundry + `RPC_URL` |

Integration tests are automatically skipped if `RPC_URL` is not set.

## License

Apache 2.0 — see [LICENSE](LICENSE).
