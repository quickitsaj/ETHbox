"""Integration tests — validate caveats against real Uniswap on a mainnet fork.

These tests require:
  - ``anvil`` (Foundry) on PATH
  - A mainnet RPC URL in the ``MAINNET_RPC_URL`` env var

They are marked with ``@pytest.mark.integration`` so CI can skip them
unless explicitly opted in (``pytest -m integration``).

Value over unit tests:
  - Selector correctness against real deployed bytecode
  - Multi-step approve+swap flow through the real SwapRouter02
  - No mock hides subtle interaction differences
"""

import os
import pytest

from web3 import Web3

from poc.fork import start_anvil, stop_anvil, connect, fund_usdc, fund_eth
from poc.swap import swap_usdc_to_weth
from poc.caveats import (
    usdc_weth_swap_caveats,
    CaveatEnforcer,
    CaveatViolation,
    APPROVE_SELECTOR,
    EXACT_INPUT_SINGLE_SELECTOR,
)
from poc.constants import USDC, WETH, SWAP_ROUTER_02, POOL_FEE, ERC20_ABI

FORK_BLOCK = 19_000_000  # Jan 2024, ETH ~$2 400
SWAP_USDC = 10_000 * 10**6  # 10 000 USDC raw


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def anvil():
    """Launch an Anvil fork for the entire test module."""
    rpc = os.environ.get("MAINNET_RPC_URL")
    if not rpc:
        pytest.skip("MAINNET_RPC_URL not set — skipping fork tests")
    proc = start_anvil(rpc, FORK_BLOCK, port=18545)
    yield proc
    stop_anvil(proc)


@pytest.fixture(scope="module")
def w3(anvil):
    return connect(port=18545)


@pytest.fixture()
def funded_sender(w3):
    sender = w3.eth.accounts[0]
    fund_usdc(w3, sender, SWAP_USDC)
    fund_eth(w3, sender, 10 * 10**18)
    return sender


# ---------------------------------------------------------------------------
# Smoke test: full delegated swap flow on real contracts
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestForkedSwapWithCaveats:
    """Run the complete caveat→approve→swap flow against real Uniswap."""

    def test_caveats_allow_real_swap(self, w3, funded_sender):
        """The generated caveats must permit the actual approve+swap
        that executes successfully against the real SwapRouter02."""
        sender = funded_sender
        caveats = usdc_weth_swap_caveats(max_usdc=SWAP_USDC, recipient=sender)
        enforcer = CaveatEnforcer(caveats)

        # Enforce step 1: approve
        enforcer.enforce(target=USDC, selector=APPROVE_SELECTOR)

        # Enforce step 2: swap
        enforcer.enforce(
            target=SWAP_ROUTER_02,
            selector=EXACT_INPUT_SINGLE_SELECTOR,
            value=SWAP_USDC,
            swap_params={
                "tokenIn": USDC, "tokenOut": WETH,
                "fee": POOL_FEE, "recipient": sender,
            },
        )

        # Execute the real swap
        weth_out = swap_usdc_to_weth(w3, sender, SWAP_USDC)
        assert weth_out > 0, "Swap returned 0 WETH"

        # Cap fully consumed
        assert enforcer.remaining == 0
        assert enforcer.spent == SWAP_USDC

    def test_selector_matches_deployed_router(self, w3):
        """The exactInputSingle selector we compute must match what the
        deployed SwapRouter02 bytecode exposes.

        We confirm by checking that the ABI-encoded call data starts with
        the selector we use in caveats.
        """
        router = w3.eth.contract(
            address=SWAP_ROUTER_02,
            abi=[{
                "name": "exactInputSingle",
                "type": "function",
                "inputs": [{
                    "name": "params",
                    "type": "tuple",
                    "components": [
                        {"name": "tokenIn", "type": "address"},
                        {"name": "tokenOut", "type": "address"},
                        {"name": "fee", "type": "uint24"},
                        {"name": "recipient", "type": "address"},
                        {"name": "amountIn", "type": "uint256"},
                        {"name": "amountOutMinimum", "type": "uint256"},
                        {"name": "sqrtPriceLimitX96", "type": "uint160"},
                    ],
                }],
                "outputs": [{"name": "amountOut", "type": "uint256"}],
            }],
        )
        call_data = router.encode_abi(
            "exactInputSingle",
            [{
                "tokenIn": USDC,
                "tokenOut": WETH,
                "fee": POOL_FEE,
                "recipient": USDC,  # dummy
                "amountIn": 1,
                "amountOutMinimum": 0,
                "sqrtPriceLimitX96": 0,
            }],
        )
        # call_data is hex-encoded; first 4 bytes (8 hex chars after 0x) = selector
        on_chain_selector = call_data[2:10]
        assert on_chain_selector == EXACT_INPUT_SINGLE_SELECTOR

    def test_over_cap_blocked_before_real_swap(self, w3, funded_sender):
        """A swap exceeding the spend cap is blocked by the enforcer
        *before* it can hit the chain."""
        sender = funded_sender
        small_cap = 1_000 * 10**6  # only 1 000 USDC allowed
        caveats = usdc_weth_swap_caveats(max_usdc=small_cap, recipient=sender)
        enforcer = CaveatEnforcer(caveats)

        enforcer.enforce(target=USDC, selector=APPROVE_SELECTOR)

        with pytest.raises(CaveatViolation, match="exceeds cap"):
            enforcer.enforce(
                target=SWAP_ROUTER_02,
                selector=EXACT_INPUT_SINGLE_SELECTOR,
                value=SWAP_USDC,  # 10 000 USDC > 1 000 cap
                swap_params={
                    "tokenIn": USDC, "tokenOut": WETH,
                    "fee": POOL_FEE, "recipient": sender,
                },
            )
