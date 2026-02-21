# Caveat Testing Assessment

## Current State

`caveats.py` produces the right shape of caveat data for a delegated USDC→WETH swap,
but it is a **pure function that returns a static dict**. The caveat map is generated
after the swap is already done and is never connected to on-chain delegation
infrastructure. There is no interaction with MetaMask's `DelegationManager` or any
`CaveatEnforcer` contracts.

As a result, **assumption 3 (caveat resolution mapping) is currently a design exercise,
not a runtime validation**. A simple unit test against the dict output would catch the
same things the POC catches today.

## Where unit tests on a local EVM are sufficient

Testing that the caveat configuration is correct — does it allow `approve()` on USDC?
Does it block calls to unapproved targets? Does the spending cap enforce? — does not
require real Uniswap state. On a fresh Anvil/Hardhat instance you could:

- Deploy the `DelegationManager` + enforcer contracts
- Deploy a mock ERC-20 and a mock "router" with the right function selectors
- Create a delegation with the caveats, redeem it, assert it passes
- Try violations (wrong target, wrong method, over the cap), assert they revert

This approach is:

- **Faster** — no RPC calls, no forking
- **Deterministic** — no dependency on a specific block's state
- **Focused** — tests exactly what we care about
- **Cheaper** — no Alchemy/Infura credits

MetaMask's own repo tests the enforcers this way — unit tests against a local EVM with
mock contracts.

## Where a mainnet fork adds value

The fork becomes useful for a narrower set of concerns:

1. **Selector correctness against real bytecode** — we compute
   `exactInputSingle((address,address,uint24,address,uint256,uint256,uint160))` as a
   string and hash it. Does that selector actually match what the deployed SwapRouter02
   expects? A mock wouldn't catch a typo in the tuple signature. The real contract would.

2. **Multi-step transaction flow** — a USDC→WETH swap is `approve()` then
   `exactInputSingle()`. The delegation framework redeems one execution at a time. Can
   the caveats handle the fact that this is two separate redemptions (or one batched
   redemption)? Testing against the real router with real state catches flow issues that
   a simplified mock might hide.

3. **Edge cases in real protocols** — Uniswap V3's router might make internal calls, use
   callbacks, or interact with contracts the caveats didn't whitelist. If the router
   internally calls the pool contract and `AllowedTargets` only lists the router, does
   that matter? (It doesn't — the enforcer checks the top-level target, not internal
   calls — but you only discover that question by running the real flow.)

4. **Gas and execution limits** — real pool state with real liquidity gives realistic gas
   costs. A mock swap that always returns a constant doesn't.

## Recommendation

Use both approaches, layered:

- **Unit tests (local EVM, no fork):** test that each caveat type does what we expect.
  Deploy the framework + mocks. These run in seconds, go in CI, catch regressions. This
  is the bulk of test coverage.

- **Integration tests (mainnet fork):** one or two tests that run the full flow — create
  delegation, fund account, execute the real swap through the delegation on forked
  Uniswap — to confirm nothing falls apart at the seams. This is a smoke test, not
  primary coverage.

## Test Architecture

```
tests/
  conftest.py              — shared fixtures (Anvil start/stop, web3 connection)
  test_caveats_unit.py     — pure function tests for caveat dict output
  test_caveats_local.py    — local EVM: deploy enforcers + mocks, test enforcement
  test_integration_fork.py — mainnet fork: full delegation + swap flow
```
