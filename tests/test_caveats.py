"""Unit tests for caveat resolution and enforcement.

These tests exercise the caveat map generation and CaveatEnforcer logic
without any EVM or network dependency.  They run in milliseconds and
belong in CI as the primary caveat coverage.
"""

import pytest
from web3 import Web3

from poc.caveats import (
    usdc_weth_swap_caveats,
    CaveatEnforcer,
    CaveatViolation,
    APPROVE_SELECTOR,
    EXACT_INPUT_SINGLE_SELECTOR,
)
from poc.constants import USDC, WETH, SWAP_ROUTER_02, POOL_FEE


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

RECIPIENT = "0x000000000000000000000000000000000000dEaD"
MAX_USDC = 10_000 * 10**6  # 10 000 USDC in raw 6-decimal units


@pytest.fixture()
def caveats():
    return usdc_weth_swap_caveats(max_usdc=MAX_USDC, recipient=RECIPIENT)


@pytest.fixture()
def enforcer(caveats):
    return CaveatEnforcer(caveats)


# ---------------------------------------------------------------------------
# Caveat map structure
# ---------------------------------------------------------------------------

class TestCaveatResolution:
    """Verify the static caveat map has the expected shape and values."""

    def test_allowed_targets(self, caveats):
        targets = caveats["AllowedTargets"]
        assert USDC in targets
        assert SWAP_ROUTER_02 in targets
        assert len(targets) == 2

    def test_allowed_methods(self, caveats):
        methods = caveats["AllowedMethods"]
        assert APPROVE_SELECTOR in methods
        assert EXACT_INPUT_SINGLE_SELECTOR in methods
        assert len(methods) == 2

    def test_erc20_transfer_amount(self, caveats):
        cap = caveats["ERC20TransferAmount"]
        assert cap["token"] == USDC
        assert cap["maxAmount"] == MAX_USDC

    def test_swap_constraints(self, caveats):
        sc = caveats["SwapConstraints"]
        assert sc["tokenIn"] == USDC
        assert sc["tokenOut"] == WETH
        assert sc["fee"] == POOL_FEE
        assert sc["recipient"] == RECIPIENT


# ---------------------------------------------------------------------------
# Selector correctness
# ---------------------------------------------------------------------------

class TestSelectors:
    """Verify that computed selectors match known canonical values."""

    def test_approve_selector(self):
        expected = Web3.keccak(text="approve(address,uint256)")[:4].hex()
        assert APPROVE_SELECTOR == expected

    def test_exact_input_single_selector(self):
        sig = (
            "exactInputSingle("
            "(address,address,uint24,address,uint256,uint256,uint160))"
        )
        expected = Web3.keccak(text=sig)[:4].hex()
        assert EXACT_INPUT_SINGLE_SELECTOR == expected

    def test_approve_selector_canonical(self):
        # 0x095ea7b3 is the well-known ERC-20 approve selector
        assert APPROVE_SELECTOR.replace("0x", "") == "095ea7b3"


# ---------------------------------------------------------------------------
# AllowedTargets enforcement
# ---------------------------------------------------------------------------

class TestAllowedTargets:
    def test_usdc_target_passes(self, enforcer):
        enforcer.enforce(target=USDC, selector=APPROVE_SELECTOR)

    def test_router_target_passes(self, enforcer):
        enforcer.enforce(
            target=SWAP_ROUTER_02,
            selector=EXACT_INPUT_SINGLE_SELECTOR,
            value=1_000 * 10**6,
            swap_params={
                "tokenIn": USDC, "tokenOut": WETH,
                "fee": POOL_FEE, "recipient": RECIPIENT,
            },
        )

    def test_unknown_target_reverts(self, enforcer):
        random_addr = "0x0000000000000000000000000000000000001234"
        with pytest.raises(CaveatViolation, match="AllowedTargets"):
            enforcer.enforce(target=random_addr, selector=APPROVE_SELECTOR)

    def test_weth_target_reverts(self, enforcer):
        """WETH is not in AllowedTargets — direct calls to it must fail."""
        with pytest.raises(CaveatViolation, match="AllowedTargets"):
            enforcer.enforce(target=WETH, selector=APPROVE_SELECTOR)

    def test_case_insensitive_match(self, enforcer):
        enforcer.enforce(target=USDC.lower(), selector=APPROVE_SELECTOR)


# ---------------------------------------------------------------------------
# AllowedMethods enforcement
# ---------------------------------------------------------------------------

class TestAllowedMethods:
    def test_approve_passes(self, enforcer):
        enforcer.enforce(target=USDC, selector=APPROVE_SELECTOR)

    def test_exact_input_single_passes(self, enforcer):
        enforcer.enforce(
            target=SWAP_ROUTER_02,
            selector=EXACT_INPUT_SINGLE_SELECTOR,
            value=100 * 10**6,
            swap_params={
                "tokenIn": USDC, "tokenOut": WETH,
                "fee": POOL_FEE, "recipient": RECIPIENT,
            },
        )

    def test_transfer_selector_reverts(self, enforcer):
        transfer_sel = Web3.keccak(text="transfer(address,uint256)")[:4].hex()
        with pytest.raises(CaveatViolation, match="AllowedMethods"):
            enforcer.enforce(target=USDC, selector=transfer_sel)

    def test_random_selector_reverts(self, enforcer):
        with pytest.raises(CaveatViolation, match="AllowedMethods"):
            enforcer.enforce(target=USDC, selector="deadbeef")

    def test_selector_with_0x_prefix(self, enforcer):
        enforcer.enforce(target=USDC, selector=f"0x{APPROVE_SELECTOR}")


# ---------------------------------------------------------------------------
# ERC20TransferAmount (spend cap) enforcement
# ---------------------------------------------------------------------------

class TestSpendCap:
    def test_under_cap_passes(self, enforcer):
        enforcer.enforce(
            target=SWAP_ROUTER_02,
            selector=EXACT_INPUT_SINGLE_SELECTOR,
            value=MAX_USDC - 1,
            swap_params={
                "tokenIn": USDC, "tokenOut": WETH,
                "fee": POOL_FEE, "recipient": RECIPIENT,
            },
        )

    def test_exact_cap_passes(self, enforcer):
        enforcer.enforce(
            target=SWAP_ROUTER_02,
            selector=EXACT_INPUT_SINGLE_SELECTOR,
            value=MAX_USDC,
            swap_params={
                "tokenIn": USDC, "tokenOut": WETH,
                "fee": POOL_FEE, "recipient": RECIPIENT,
            },
        )

    def test_over_cap_reverts(self, enforcer):
        with pytest.raises(CaveatViolation, match="exceeds cap"):
            enforcer.enforce(
                target=SWAP_ROUTER_02,
                selector=EXACT_INPUT_SINGLE_SELECTOR,
                value=MAX_USDC + 1,
                swap_params={
                    "tokenIn": USDC, "tokenOut": WETH,
                    "fee": POOL_FEE, "recipient": RECIPIENT,
                },
            )

    def test_cumulative_spend_tracked(self, enforcer):
        half = MAX_USDC // 2
        enforcer.enforce(
            target=SWAP_ROUTER_02,
            selector=EXACT_INPUT_SINGLE_SELECTOR,
            value=half,
            swap_params={
                "tokenIn": USDC, "tokenOut": WETH,
                "fee": POOL_FEE, "recipient": RECIPIENT,
            },
        )
        assert enforcer.spent == half
        assert enforcer.remaining == MAX_USDC - half

        # Second spend that exceeds remaining cap
        with pytest.raises(CaveatViolation, match="exceeds cap"):
            enforcer.enforce(
                target=SWAP_ROUTER_02,
                selector=EXACT_INPUT_SINGLE_SELECTOR,
                value=half + 1,
                swap_params={
                    "tokenIn": USDC, "tokenOut": WETH,
                    "fee": POOL_FEE, "recipient": RECIPIENT,
                },
            )

    def test_zero_value_skips_spend_check(self, enforcer):
        """approve() doesn't transfer the capped token — value=0 is fine."""
        enforcer.enforce(target=USDC, selector=APPROVE_SELECTOR, value=0)
        assert enforcer.spent == 0


# ---------------------------------------------------------------------------
# SwapConstraints enforcement
# ---------------------------------------------------------------------------

class TestSwapConstraints:
    def _valid_params(self):
        return {
            "tokenIn": USDC,
            "tokenOut": WETH,
            "fee": POOL_FEE,
            "recipient": RECIPIENT,
        }

    def test_valid_params_pass(self, enforcer):
        enforcer.enforce(
            target=SWAP_ROUTER_02,
            selector=EXACT_INPUT_SINGLE_SELECTOR,
            value=1_000 * 10**6,
            swap_params=self._valid_params(),
        )

    def test_wrong_token_in_reverts(self, enforcer):
        params = self._valid_params()
        params["tokenIn"] = WETH  # should be USDC
        with pytest.raises(CaveatViolation, match="tokenIn"):
            enforcer.enforce(
                target=SWAP_ROUTER_02,
                selector=EXACT_INPUT_SINGLE_SELECTOR,
                value=1_000 * 10**6,
                swap_params=params,
            )

    def test_wrong_token_out_reverts(self, enforcer):
        params = self._valid_params()
        params["tokenOut"] = USDC  # should be WETH
        with pytest.raises(CaveatViolation, match="tokenOut"):
            enforcer.enforce(
                target=SWAP_ROUTER_02,
                selector=EXACT_INPUT_SINGLE_SELECTOR,
                value=1_000 * 10**6,
                swap_params=params,
            )

    def test_wrong_fee_reverts(self, enforcer):
        params = self._valid_params()
        params["fee"] = 500  # 0.05% instead of 0.3%
        with pytest.raises(CaveatViolation, match="fee"):
            enforcer.enforce(
                target=SWAP_ROUTER_02,
                selector=EXACT_INPUT_SINGLE_SELECTOR,
                value=1_000 * 10**6,
                swap_params=params,
            )

    def test_wrong_recipient_reverts(self, enforcer):
        params = self._valid_params()
        params["recipient"] = "0x0000000000000000000000000000000000005678"
        with pytest.raises(CaveatViolation, match="recipient"):
            enforcer.enforce(
                target=SWAP_ROUTER_02,
                selector=EXACT_INPUT_SINGLE_SELECTOR,
                value=1_000 * 10**6,
                swap_params=params,
            )

    def test_no_swap_params_skips_check(self, enforcer):
        """approve() has no swap_params — should pass without checking."""
        enforcer.enforce(
            target=USDC,
            selector=APPROVE_SELECTOR,
            swap_params=None,
        )


# ---------------------------------------------------------------------------
# Full delegation flow (approve + swap)
# ---------------------------------------------------------------------------

class TestDelegationFlow:
    """Simulate the two-step delegation redemption: approve then swap."""

    def test_happy_path(self, enforcer):
        # Step 1: approve
        enforcer.enforce(target=USDC, selector=APPROVE_SELECTOR)
        # Step 2: swap
        enforcer.enforce(
            target=SWAP_ROUTER_02,
            selector=EXACT_INPUT_SINGLE_SELECTOR,
            value=MAX_USDC,
            swap_params={
                "tokenIn": USDC, "tokenOut": WETH,
                "fee": POOL_FEE, "recipient": RECIPIENT,
            },
        )
        assert enforcer.spent == MAX_USDC
        assert enforcer.remaining == 0

    def test_double_spend_blocked(self, enforcer):
        """After spending the full cap, a second swap is blocked."""
        enforcer.enforce(target=USDC, selector=APPROVE_SELECTOR)
        enforcer.enforce(
            target=SWAP_ROUTER_02,
            selector=EXACT_INPUT_SINGLE_SELECTOR,
            value=MAX_USDC,
            swap_params={
                "tokenIn": USDC, "tokenOut": WETH,
                "fee": POOL_FEE, "recipient": RECIPIENT,
            },
        )
        with pytest.raises(CaveatViolation, match="exceeds cap"):
            enforcer.enforce(
                target=SWAP_ROUTER_02,
                selector=EXACT_INPUT_SINGLE_SELECTOR,
                value=1,
                swap_params={
                    "tokenIn": USDC, "tokenOut": WETH,
                    "fee": POOL_FEE, "recipient": RECIPIENT,
                },
            )

    def test_wrong_target_in_flow(self, enforcer):
        """Calling an unapproved contract in the middle of the flow fails."""
        enforcer.enforce(target=USDC, selector=APPROVE_SELECTOR)
        with pytest.raises(CaveatViolation, match="AllowedTargets"):
            enforcer.enforce(
                target=WETH,
                selector=APPROVE_SELECTOR,
            )
