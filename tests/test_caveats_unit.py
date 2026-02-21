"""Unit tests for the caveat resolution mapping (pure function tests).

These tests validate that usdc_weth_swap_caveats() returns the correct
structure without any EVM interaction. They catch regressions in the
static dict shape, selectors, and address references.
"""

from web3 import Web3

from poc.caveats import (
    usdc_weth_swap_caveats,
    APPROVE_SELECTOR,
    EXACT_INPUT_SINGLE_SELECTOR,
)
from poc.constants import USDC, WETH, SWAP_ROUTER_02, POOL_FEE


# ---------------------------------------------------------------------------
# Selector correctness
# ---------------------------------------------------------------------------

def test_approve_selector_matches_erc20():
    """approve(address,uint256) selector must be 0x095ea7b3."""
    expected = Web3.keccak(text="approve(address,uint256)")[:4].hex()
    assert APPROVE_SELECTOR == expected
    assert APPROVE_SELECTOR == "0x095ea7b3"


def test_exact_input_single_selector():
    """exactInputSingle((...)) selector must match the SwapRouter02 ABI."""
    sig = "exactInputSingle((address,address,uint24,address,uint256,uint256,uint160))"
    expected = Web3.keccak(text=sig)[:4].hex()
    assert EXACT_INPUT_SINGLE_SELECTOR == expected


# ---------------------------------------------------------------------------
# Dict structure
# ---------------------------------------------------------------------------

SENDER = "0x000000000000000000000000000000000000dEaD"
MAX_USDC = 10_000 * 10**6  # 10k USDC in raw units


def _caveats():
    return usdc_weth_swap_caveats(max_usdc=MAX_USDC, recipient=SENDER)


def test_returns_all_required_keys():
    caveats = _caveats()
    assert set(caveats.keys()) == {
        "AllowedTargets",
        "AllowedMethods",
        "ERC20TransferAmount",
        "SwapConstraints",
    }


def test_allowed_targets_contains_usdc_and_router():
    targets = _caveats()["AllowedTargets"]
    assert USDC in targets
    assert SWAP_ROUTER_02 in targets
    assert len(targets) == 2


def test_allowed_targets_does_not_include_pool():
    """The pool is called internally by the router, not by the delegatee."""
    from poc.constants import POOL_USDC_WETH_030
    targets = _caveats()["AllowedTargets"]
    assert POOL_USDC_WETH_030 not in targets


def test_allowed_methods_contains_both_selectors():
    methods = _caveats()["AllowedMethods"]
    assert APPROVE_SELECTOR in methods
    assert EXACT_INPUT_SINGLE_SELECTOR in methods
    assert len(methods) == 2


def test_erc20_transfer_amount_cap():
    cap = _caveats()["ERC20TransferAmount"]
    assert cap["token"] == USDC
    assert cap["maxAmount"] == MAX_USDC


def test_erc20_transfer_amount_respects_input():
    """Cap should reflect the max_usdc argument, not a hardcoded value."""
    small = usdc_weth_swap_caveats(max_usdc=100, recipient=SENDER)
    large = usdc_weth_swap_caveats(max_usdc=999_999, recipient=SENDER)
    assert small["ERC20TransferAmount"]["maxAmount"] == 100
    assert large["ERC20TransferAmount"]["maxAmount"] == 999_999


def test_swap_constraints():
    sc = _caveats()["SwapConstraints"]
    assert sc["tokenIn"] == USDC
    assert sc["tokenOut"] == WETH
    assert sc["fee"] == POOL_FEE
    assert sc["recipient"] == SENDER


def test_swap_constraints_recipient_matches_input():
    other = "0x0000000000000000000000000000000000001234"
    caveats = usdc_weth_swap_caveats(max_usdc=MAX_USDC, recipient=other)
    assert caveats["SwapConstraints"]["recipient"] == other


# ---------------------------------------------------------------------------
# Sanity: no mutation between calls
# ---------------------------------------------------------------------------

def test_independent_calls_do_not_share_state():
    a = usdc_weth_swap_caveats(max_usdc=100, recipient=SENDER)
    b = usdc_weth_swap_caveats(max_usdc=200, recipient=SENDER)
    assert a["ERC20TransferAmount"]["maxAmount"] == 100
    assert b["ERC20TransferAmount"]["maxAmount"] == 200
