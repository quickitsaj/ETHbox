# ETHbox Documentation Summary

## Project Overview

**ETHbox** is a delegation-aware Ethereum transaction simulator. It is currently at
**Phase 0 — Proof of Concept** (v0.0.1), consisting of ~200 lines of Python with no
frontend and no LLM integration. The project is licensed under Apache 2.0.

## What Phase 0 Validates

The POC tests three core assumptions before the project proceeds to Phase 1:

### 1. Anvil Fork Pipeline (`poc/fork.py`)

Forks Ethereum mainnet at a historical block using Foundry's `anvil` and executes
real Uniswap V3 swaps against the forked state. Key capabilities:

- **`start_anvil`** — Launches an `anvil` process forking mainnet at a specified block
  number, waits for the RPC to become ready (up to ~9 seconds).
- **`stop_anvil`** — Gracefully terminates the anvil process via SIGTERM.
- **`connect`** — Returns a `web3.Web3` instance connected to the local anvil RPC.
- **`fund_usdc` / `fund_eth`** — Injects arbitrary USDC and ETH balances into test
  accounts by directly writing to contract storage slots (`anvil_setStorageAt`) or
  using `anvil_setBalance`.

### 2. Price Puppeteering (`poc/price.py`)

Manipulates Uniswap V3 pool reserves via large swaps to hit a target ETH/USD price,
then validates the result against tolerance bounds.

- **`read_pool_price`** — Reads `sqrtPriceX96` from the USDC/WETH 0.3% pool's
  `slot0` and converts it to a human-readable ETH/USD price.
- **`read_chainlink_price`** — Fetches the ETH/USD price from Chainlink's on-chain
  oracle (8-decimal precision) as an independent reference.
- **`move_pool_price`** — Pushes the pool price toward a target by executing
  iterative large swaps (up to 10 rounds of 5M USDC or 2000 WETH chunks).
- **`validate_price`** — Checks whether the actual price is within a fractional
  tolerance (default 5%) of the expected price.

### 3. Caveat Resolution Mapping (`poc/caveats.py`)

Maps a high-level delegation intent (e.g., "allow USDC→WETH swap up to N USDC") to
concrete MetaMask Delegation Toolkit caveats:

| Caveat Type          | Value                                           |
|----------------------|-------------------------------------------------|
| AllowedTargets       | USDC contract, SwapRouter02                     |
| AllowedMethods       | `approve(address,uint256)`, `exactInputSingle(...)` |
| ERC20TransferAmount  | Cap on USDC spend (token address + max amount)  |
| SwapConstraints      | tokenIn, tokenOut, fee tier, recipient          |

## Module Reference

| File               | Purpose                                              |
|--------------------|------------------------------------------------------|
| `poc/main.py`      | CLI entry point; orchestrates the full POC pipeline   |
| `poc/fork.py`      | Anvil process lifecycle and account funding           |
| `poc/swap.py`      | USDC→WETH swap execution via Uniswap V3 SwapRouter02 |
| `poc/price.py`     | Pool price reading, manipulation, and validation      |
| `poc/caveats.py`   | Delegation intent → caveat resolution mapping         |
| `poc/constants.py` | Mainnet addresses, ABIs, and storage slot numbers     |

## On-Chain Contracts Referenced

| Contract           | Address                                      |
|--------------------|----------------------------------------------|
| USDC               | `0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48` |
| WETH               | `0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2` |
| Uniswap SwapRouter02 | `0x68b3465833fb72A70ecDF485E0e4C7bD8665Fc45` |
| USDC/WETH 0.3% Pool  | `0x8ad599c3A0ff1De082011EFDDc58f1908eb6e6D8` |
| Chainlink ETH/USD  | `0x5f4eC3Df9cbd43714FE2740f5E3616155c5b8419` |

## Prerequisites

- Python 3.10+
- [Foundry](https://getfoundry.sh/) (`anvil` on PATH)
- A mainnet RPC URL (Alchemy, Infura, etc.)
- Single dependency: `web3>=6.0,<7`

## How to Run

```bash
pip install -r requirements.txt
python -m poc.main --rpc-url <MAINNET_RPC> --block 19000000
```

Default fork block is **19,000,000** (~Jan 2024, ETH ≈ $2,400). The script swaps
10,000 USDC for WETH and then attempts to puppet the pool price to $2,600.

## GO / NO-GO Gate

The POC exits with a verdict:

- **GO** — Swap executed successfully and price puppet landed within 10% of target.
  Proceed to Phase 1.
- **NO-GO** — Something failed. Investigate before continuing.
