# ETHbox

Delegation-aware Ethereum transaction simulator. Validates the feasibility of delegated trading on Ethereum using MetaMask's Delegation Framework.

**Status:** Phase 1 in progress — Delegation Enforcement

## Overview

ETHbox forks Ethereum mainnet using Anvil, executes real swaps through Uniswap V3, and maps delegation intents to concrete MetaMask CaveatBuilder constraints. The Phase 0 POC validates three core assumptions (~200 lines of Python, no frontend, no LLM):

1. **Anvil fork pipeline** — Fork mainnet at a historical block, execute a USDC→WETH swap through the real Uniswap V3 SwapRouter02.
2. **Price puppeteering** — Move Uniswap pool reserves via large swaps to match a target price, then validate the result.
3. **Caveat resolution mapping** — Map a delegation intent ("allow USDC→WETH swap") to concrete MetaMask CaveatBuilder caveats (AllowedTargets, AllowedMethods, ERC20TransferAmount).

## Project Structure

```
ETHbox/
├── poc/                              # Core Python modules
│   ├── main.py                       # Phase 0 entry point — 4-step validation flow
│   ├── fork.py                       # Anvil lifecycle & account funding
│   ├── swap.py                       # Token swap execution via Uniswap V3
│   ├── price.py                      # Price reading, manipulation, validation
│   ├── caveats.py                    # Delegation intent → MetaMask caveat mapping
│   ├── constants.py                  # Token/pair registry, addresses, ABIs
│   ├── delegation.py                 # Phase 1: delegation enforcement logic
│   └── enforcers.py                  # Phase 1: on-chain enforcer contracts (EVM bytecode)
├── contracts/                        # Solidity reference implementations
│   ├── AllowedTargetsEnforcer.sol    # Target address whitelist enforcer
│   ├── AllowedMethodsEnforcer.sol    # Function selector whitelist enforcer
│   └── ValueLimitEnforcer.sol        # Spending cap enforcer
├── tests/                            # Layered test suite
│   ├── conftest.py                   # Shared pytest fixtures (Anvil lifecycle)
│   ├── test_caveats_unit.py          # Pure function tests (no EVM)
│   ├── test_caveats_local.py         # Local Anvil tests (no mainnet fork)
│   ├── test_delegation_unit.py       # Phase 1: delegation enforcement unit tests
│   ├── test_delegation_local.py      # Phase 1: on-chain enforcer tests (local Anvil)
│   ├── test_multitoken_unit.py       # Multi-token registry and caveat tests
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

## Roadmap

### Phase 0 — Proof of Concept (complete)

Validated core assumptions: Anvil fork pipeline, Uniswap swap execution, price puppeteering, and caveat resolution mapping. Verdict: **GO**.

### Phase 1 — Delegation Enforcement (in progress)

- [x] Delegation data model (`Delegation`, `Caveat` dataclasses)
- [x] Off-chain enforcement engine (AllowedTargets, AllowedMethods, ERC20TransferAmount)
- [x] On-chain enforcer contracts (hand-assembled EVM bytecode, deployed on Anvil)
- [x] Violation testing — assert reverts for wrong target, wrong method, and over-cap
- [x] Delegated call execution via Anvil account impersonation
- [x] Bridge from Phase 0 caveat maps to Phase 1 delegation objects
- [ ] Deploy MetaMask's [`DelegationManager`](https://github.com/MetaMask/delegation-framework) + full `CaveatEnforcer` contracts
- [ ] Frontend for constructing and visualizing delegation intents
- [ ] LLM-powered intent parsing (natural language → caveat structure)
- [x] Multi-token support (Token/SwapPair registry, generic swap_caveats, DAI/USDT/WBTC)

## Contracts

### Mainnet contracts (used via fork)

| Contract | Address | Role |
|----------|---------|------|
| USDC | `0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48` | Stablecoin (6 decimals) |
| WETH | `0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2` | Wrapped ETH (18 decimals) |
| DAI | `0x6B175474E89094C44Da98b954EedeAC495271d0F` | Stablecoin (18 decimals) |
| USDT | `0xdAC17F958D2ee523a2206206994597C13D831ec7` | Stablecoin (6 decimals) |
| WBTC | `0x2260FAC5E5542a773Aa44fBCfeDf7C193bc2C599` | Wrapped BTC (8 decimals) |
| Uniswap V3 SwapRouter02 | `0x68b3465833fb72A70ecDF485E0e4C7bD8665Fc45` | Swap execution |
| USDC/WETH 0.3% Pool | `0x8ad599c3A0ff1De082011EFDDc58f1908eb6e6D8` | Liquidity pool |
| DAI/WETH 0.3% Pool | `0xC2e9F25Be6257c210d7Adf0D4Cd6E3E881ba25f8` | Liquidity pool |
| WBTC/WETH 0.3% Pool | `0xCBCdF9626bC03E24f779434178A73a0B4bad62eD` | Liquidity pool |
| USDT/WETH 0.3% Pool | `0x4e68Ccd3E89f51C3074ca5072bbAC773960dFa36` | Liquidity pool |
| Chainlink ETH/USD | `0x5f4eC3Df9cbd43714FE2740f5E3616155c5b8419` | Price oracle reference |

### Enforcer contracts (Phase 1 — deployed on Anvil)

| Contract | Source | Role |
|----------|--------|------|
| AllowedTargetsEnforcer | `contracts/AllowedTargetsEnforcer.sol` | Whitelist target addresses |
| AllowedMethodsEnforcer | `contracts/AllowedMethodsEnforcer.sol` | Whitelist function selectors |
| ValueLimitEnforcer | `contracts/ValueLimitEnforcer.sol` | Cap spending amounts |

The enforcer contracts are deployed as hand-assembled EVM bytecode via `poc/enforcers.py`. The Solidity files in `contracts/` are reference implementations documenting the intended behavior.

## Testing

The test suite uses a layered approach:

```bash
# Unit tests — pure function tests, no dependencies, fast
pytest tests/test_caveats_unit.py tests/test_delegation_unit.py tests/test_multitoken_unit.py -v

# Local EVM tests — requires anvil, no RPC needed
pytest tests/test_caveats_local.py tests/test_delegation_local.py -v

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
| Unit | `test_delegation_unit.py` | Delegation enforcement logic, violation scenarios | None |
| Unit | `test_multitoken_unit.py` | Token/pair registry, generic caveats, multi-token enforcement | None |
| Local | `test_caveats_local.py` | Selectors against mock ERC-20 on local Anvil | Foundry |
| Local | `test_delegation_local.py` | On-chain enforcers, delegated call execution | Foundry |
| Integration | `test_integration_fork.py` | Full flow against real Uniswap V3 & Chainlink on mainnet fork | Foundry + `RPC_URL` |

Integration tests are automatically skipped if `RPC_URL` is not set.
Local EVM tests are automatically skipped if `anvil` is not on PATH.

## License

Apache 2.0 — see [LICENSE](LICENSE).
