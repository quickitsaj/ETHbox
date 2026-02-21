"""Unit tests for delegation enforcement (pure function tests).

These tests validate the off-chain enforcement logic in poc/delegation.py
without any EVM interaction. They cover:
  - AllowedTargets enforcement
  - AllowedMethods enforcement
  - ERC20TransferAmount enforcement
  - Full delegation validation (all caveats together)
  - Delegation creation from Phase 0 caveat maps
  - Violation scenarios (wrong target, wrong method, over-cap)
"""

import pytest
from web3 import Web3

from poc.delegation import (
    Caveat,
    Delegation,
    EnforcementError,
    enforce_allowed_targets,
    enforce_allowed_methods,
    enforce_erc20_transfer_amount,
    validate_delegation,
    delegation_from_caveat_map,
    _extract_uint256_param,
)
from poc.caveats import (
    usdc_weth_swap_caveats,
    APPROVE_SELECTOR,
    EXACT_INPUT_SINGLE_SELECTOR,
)
from poc.constants import USDC, WETH, SWAP_ROUTER_02, POOL_FEE


# ---------------------------------------------------------------------------
# Test addresses
# ---------------------------------------------------------------------------

DELEGATOR = "0x000000000000000000000000000000000000dEaD"
DELEGATEE = "0x0000000000000000000000000000000000001234"
RANDOM_ADDR = "0x0000000000000000000000000000000000005678"


# ---------------------------------------------------------------------------
# Helper: build calldata
# ---------------------------------------------------------------------------

def _build_calldata(selector: str, *uint256_args: int) -> bytes:
    """Build calldata from a 4-byte selector and uint256 arguments."""
    sel_hex = selector[2:] if selector.startswith("0x") else selector
    data = bytes.fromhex(sel_hex)
    for arg in uint256_args:
        data += arg.to_bytes(32, "big")
    return data


# ---------------------------------------------------------------------------
# AllowedTargets enforcer
# ---------------------------------------------------------------------------

class TestEnforceAllowedTargets:
    def test_target_in_list_passes(self):
        enforce_allowed_targets(USDC, [USDC, SWAP_ROUTER_02])

    def test_target_not_in_list_raises(self):
        with pytest.raises(EnforcementError, match="AllowedTargets"):
            enforce_allowed_targets(WETH, [USDC, SWAP_ROUTER_02])

    def test_single_allowed_target(self):
        enforce_allowed_targets(USDC, [USDC])

    def test_empty_allowed_list_raises(self):
        with pytest.raises(EnforcementError, match="AllowedTargets"):
            enforce_allowed_targets(USDC, [])

    def test_case_insensitive_comparison(self):
        """Addresses should be compared after checksum normalization."""
        lower = USDC.lower()
        enforce_allowed_targets(lower, [USDC])

    def test_error_message_includes_target(self):
        with pytest.raises(EnforcementError) as exc_info:
            enforce_allowed_targets(WETH, [USDC])
        assert WETH in str(exc_info.value) or Web3.to_checksum_address(WETH) in str(exc_info.value)


# ---------------------------------------------------------------------------
# AllowedMethods enforcer
# ---------------------------------------------------------------------------

class TestEnforceAllowedMethods:
    def test_allowed_selector_passes(self):
        calldata = _build_calldata(APPROVE_SELECTOR, 0, 1000)
        enforce_allowed_methods(calldata, [APPROVE_SELECTOR, EXACT_INPUT_SINGLE_SELECTOR])

    def test_disallowed_selector_raises(self):
        calldata = _build_calldata("0xdeadbeef", 0)
        with pytest.raises(EnforcementError, match="AllowedMethods"):
            enforce_allowed_methods(calldata, [APPROVE_SELECTOR])

    def test_short_calldata_raises(self):
        with pytest.raises(EnforcementError, match="calldata too short"):
            enforce_allowed_methods(b"\x00\x01\x02", [APPROVE_SELECTOR])

    def test_empty_calldata_raises(self):
        with pytest.raises(EnforcementError, match="calldata too short"):
            enforce_allowed_methods(b"", [APPROVE_SELECTOR])

    def test_exact_4_bytes_works(self):
        """Calldata with exactly 4 bytes (selector only, no args) should work."""
        sel_hex = APPROVE_SELECTOR[2:] if APPROVE_SELECTOR.startswith("0x") else APPROVE_SELECTOR
        calldata = bytes.fromhex(sel_hex)
        enforce_allowed_methods(calldata, [APPROVE_SELECTOR])

    def test_selector_with_and_without_0x_prefix(self):
        """Both 0x-prefixed and non-prefixed selectors should work."""
        calldata = _build_calldata(APPROVE_SELECTOR, 0)
        # With 0x
        enforce_allowed_methods(calldata, ["0x095ea7b3"])
        # Without 0x
        enforce_allowed_methods(calldata, ["095ea7b3"])

    def test_error_message_includes_selector(self):
        calldata = _build_calldata("0xdeadbeef")
        with pytest.raises(EnforcementError) as exc_info:
            enforce_allowed_methods(calldata, [APPROVE_SELECTOR])
        assert "deadbeef" in str(exc_info.value).lower()


# ---------------------------------------------------------------------------
# ERC20TransferAmount enforcer
# ---------------------------------------------------------------------------

class TestEnforceERC20TransferAmount:
    def test_amount_under_cap_passes(self):
        enforce_erc20_transfer_amount(500, 1000)

    def test_amount_at_cap_passes(self):
        enforce_erc20_transfer_amount(1000, 1000)

    def test_amount_over_cap_raises(self):
        with pytest.raises(EnforcementError, match="ERC20TransferAmount"):
            enforce_erc20_transfer_amount(1001, 1000)

    def test_zero_amount_passes(self):
        enforce_erc20_transfer_amount(0, 1000)

    def test_zero_cap_zero_amount_passes(self):
        enforce_erc20_transfer_amount(0, 0)

    def test_zero_cap_nonzero_amount_raises(self):
        with pytest.raises(EnforcementError, match="exceeds cap"):
            enforce_erc20_transfer_amount(1, 0)

    def test_large_amounts(self):
        """Test with realistic USDC amounts (6 decimals)."""
        max_usdc = 10_000 * 10**6  # 10k USDC
        enforce_erc20_transfer_amount(9_999 * 10**6, max_usdc)
        with pytest.raises(EnforcementError):
            enforce_erc20_transfer_amount(10_001 * 10**6, max_usdc)

    def test_error_includes_token_info(self):
        with pytest.raises(EnforcementError) as exc_info:
            enforce_erc20_transfer_amount(200, 100, token=USDC)
        assert USDC in str(exc_info.value)


# ---------------------------------------------------------------------------
# Calldata parameter extraction
# ---------------------------------------------------------------------------

class TestExtractUint256Param:
    def test_extract_first_param(self):
        calldata = _build_calldata("0x12345678", 42, 99)
        assert _extract_uint256_param(calldata, 0) == 42

    def test_extract_second_param(self):
        calldata = _build_calldata("0x12345678", 42, 99)
        assert _extract_uint256_param(calldata, 1) == 99

    def test_calldata_too_short_raises(self):
        calldata = _build_calldata("0x12345678")  # selector only
        with pytest.raises(EnforcementError, match="calldata too short"):
            _extract_uint256_param(calldata, 0)

    def test_large_uint256(self):
        large = 2**255 - 1
        calldata = _build_calldata("0x12345678", large)
        assert _extract_uint256_param(calldata, 0) == large


# ---------------------------------------------------------------------------
# Full delegation validation
# ---------------------------------------------------------------------------

class TestValidateDelegation:
    @pytest.fixture()
    def swap_delegation(self):
        """Create a delegation for a USDC→WETH swap."""
        max_usdc = 10_000 * 10**6
        caveat_map = usdc_weth_swap_caveats(max_usdc=max_usdc, recipient=DELEGATOR)
        return delegation_from_caveat_map(
            delegator=DELEGATOR,
            delegatee=DELEGATEE,
            caveat_map=caveat_map,
        )

    def test_valid_approve_call_passes(self, swap_delegation):
        """approve(router, 10k USDC) should pass all caveats."""
        calldata = _build_calldata(
            APPROVE_SELECTOR,
            int(SWAP_ROUTER_02, 16),  # spender
            10_000 * 10**6,           # amount
        )
        validate_delegation(
            swap_delegation,
            caller=DELEGATEE,
            target=USDC,
            calldata=calldata,
        )

    def test_wrong_caller_raises_value_error(self, swap_delegation):
        """Only the delegatee can use the delegation."""
        calldata = _build_calldata(APPROVE_SELECTOR, 0, 1000)
        with pytest.raises(ValueError, match="not the delegatee"):
            validate_delegation(
                swap_delegation,
                caller=RANDOM_ADDR,
                target=USDC,
                calldata=calldata,
            )

    def test_wrong_target_raises(self, swap_delegation):
        """Calling an unapproved contract should fail AllowedTargets."""
        calldata = _build_calldata(APPROVE_SELECTOR, 0, 1000)
        with pytest.raises(EnforcementError, match="AllowedTargets"):
            validate_delegation(
                swap_delegation,
                caller=DELEGATEE,
                target=WETH,  # WETH is not in allowed targets
                calldata=calldata,
            )

    def test_wrong_method_raises(self, swap_delegation):
        """Calling a disallowed method should fail AllowedMethods."""
        # transfer(address,uint256) selector
        transfer_selector = Web3.keccak(text="transfer(address,uint256)")[:4].hex()
        calldata = _build_calldata(transfer_selector, 0, 1000)
        with pytest.raises(EnforcementError, match="AllowedMethods"):
            validate_delegation(
                swap_delegation,
                caller=DELEGATEE,
                target=USDC,
                calldata=calldata,
            )

    def test_over_cap_raises(self, swap_delegation):
        """Exceeding the USDC cap should fail ERC20TransferAmount."""
        over_amount = 20_000 * 10**6  # 20k USDC, cap is 10k
        calldata = _build_calldata(
            APPROVE_SELECTOR,
            int(SWAP_ROUTER_02, 16),
            over_amount,
        )
        with pytest.raises(EnforcementError, match="ERC20TransferAmount"):
            validate_delegation(
                swap_delegation,
                caller=DELEGATEE,
                target=USDC,
                calldata=calldata,
            )

    def test_amount_at_cap_passes(self, swap_delegation):
        """Exactly at the cap should pass."""
        exact_amount = 10_000 * 10**6
        calldata = _build_calldata(
            APPROVE_SELECTOR,
            int(SWAP_ROUTER_02, 16),
            exact_amount,
        )
        validate_delegation(
            swap_delegation,
            caller=DELEGATEE,
            target=USDC,
            calldata=calldata,
        )


# ---------------------------------------------------------------------------
# Delegation creation from caveat map
# ---------------------------------------------------------------------------

class TestDelegationFromCaveatMap:
    def test_creates_delegation_with_correct_addresses(self):
        caveat_map = usdc_weth_swap_caveats(
            max_usdc=10_000 * 10**6,
            recipient=DELEGATOR,
        )
        d = delegation_from_caveat_map(DELEGATOR, DELEGATEE, caveat_map)
        assert d.delegator == DELEGATOR
        assert d.delegatee == DELEGATEE

    def test_creates_three_caveats(self):
        caveat_map = usdc_weth_swap_caveats(
            max_usdc=10_000 * 10**6,
            recipient=DELEGATOR,
        )
        d = delegation_from_caveat_map(DELEGATOR, DELEGATEE, caveat_map)
        assert len(d.caveats) == 3

    def test_caveat_types_match(self):
        caveat_map = usdc_weth_swap_caveats(
            max_usdc=10_000 * 10**6,
            recipient=DELEGATOR,
        )
        d = delegation_from_caveat_map(DELEGATOR, DELEGATEE, caveat_map)
        enforcer_types = {c.enforcer for c in d.caveats}
        assert enforcer_types == {
            "AllowedTargets",
            "AllowedMethods",
            "ERC20TransferAmount",
        }

    def test_allowed_targets_terms(self):
        caveat_map = usdc_weth_swap_caveats(
            max_usdc=10_000 * 10**6,
            recipient=DELEGATOR,
        )
        d = delegation_from_caveat_map(DELEGATOR, DELEGATEE, caveat_map)
        targets_caveat = next(c for c in d.caveats if c.enforcer == "AllowedTargets")
        assert USDC in targets_caveat.terms
        assert SWAP_ROUTER_02 in targets_caveat.terms

    def test_allowed_methods_terms(self):
        caveat_map = usdc_weth_swap_caveats(
            max_usdc=10_000 * 10**6,
            recipient=DELEGATOR,
        )
        d = delegation_from_caveat_map(DELEGATOR, DELEGATEE, caveat_map)
        methods_caveat = next(c for c in d.caveats if c.enforcer == "AllowedMethods")
        assert APPROVE_SELECTOR in methods_caveat.terms
        assert EXACT_INPUT_SINGLE_SELECTOR in methods_caveat.terms

    def test_erc20_cap_terms(self):
        max_usdc = 10_000 * 10**6
        caveat_map = usdc_weth_swap_caveats(
            max_usdc=max_usdc,
            recipient=DELEGATOR,
        )
        d = delegation_from_caveat_map(DELEGATOR, DELEGATEE, caveat_map)
        cap_caveat = next(c for c in d.caveats if c.enforcer == "ERC20TransferAmount")
        assert cap_caveat.terms["token"] == USDC
        assert cap_caveat.terms["maxAmount"] == max_usdc

    def test_empty_caveat_map(self):
        d = delegation_from_caveat_map(DELEGATOR, DELEGATEE, {})
        assert len(d.caveats) == 0


# ---------------------------------------------------------------------------
# Data structure immutability
# ---------------------------------------------------------------------------

class TestDataStructures:
    def test_caveat_is_frozen(self):
        c = Caveat(enforcer="AllowedTargets", terms=[USDC])
        with pytest.raises(AttributeError):
            c.enforcer = "other"

    def test_delegation_is_frozen(self):
        d = Delegation(delegator=DELEGATOR, delegatee=DELEGATEE)
        with pytest.raises(AttributeError):
            d.delegator = RANDOM_ADDR

    def test_delegation_caveats_default_empty(self):
        d = Delegation(delegator=DELEGATOR, delegatee=DELEGATEE)
        assert d.caveats == ()

    def test_independent_delegations(self):
        """Two delegations from the same caveat map are independent."""
        caveat_map = usdc_weth_swap_caveats(max_usdc=100, recipient=DELEGATOR)
        d1 = delegation_from_caveat_map(DELEGATOR, DELEGATEE, caveat_map)
        d2 = delegation_from_caveat_map(DELEGATOR, RANDOM_ADDR, caveat_map)
        assert d1.delegatee != d2.delegatee
        assert d1.caveats == d2.caveats


# ---------------------------------------------------------------------------
# Violation scenario matrix
# ---------------------------------------------------------------------------

class TestViolationMatrix:
    """Comprehensive violation testing — every enforcer must reject bad input."""

    @pytest.fixture()
    def delegation(self):
        max_usdc = 5_000 * 10**6
        return Delegation(
            delegator=DELEGATOR,
            delegatee=DELEGATEE,
            caveats=(
                Caveat("AllowedTargets", [USDC, SWAP_ROUTER_02]),
                Caveat("AllowedMethods", [APPROVE_SELECTOR, EXACT_INPUT_SINGLE_SELECTOR]),
                Caveat("ERC20TransferAmount", {"token": USDC, "maxAmount": max_usdc}),
            ),
        )

    def test_valid_call(self, delegation):
        """Baseline: a valid call should pass."""
        calldata = _build_calldata(APPROVE_SELECTOR, 0, 5_000 * 10**6)
        validate_delegation(
            delegation, caller=DELEGATEE, target=USDC, calldata=calldata,
        )

    @pytest.mark.parametrize("bad_target", [
        WETH,
        "0x0000000000000000000000000000000000000001",
        "0x0000000000000000000000000000000000000000",
    ])
    def test_wrong_target_variants(self, delegation, bad_target):
        calldata = _build_calldata(APPROVE_SELECTOR, 0, 100)
        with pytest.raises(EnforcementError, match="AllowedTargets"):
            validate_delegation(
                delegation, caller=DELEGATEE, target=bad_target, calldata=calldata,
            )

    @pytest.mark.parametrize("bad_selector", [
        "0xa9059cbb",  # transfer(address,uint256)
        "0x23b872dd",  # transferFrom(address,address,uint256)
        "0xdeadbeef",  # random
    ])
    def test_wrong_method_variants(self, delegation, bad_selector):
        calldata = _build_calldata(bad_selector, 0, 100)
        with pytest.raises(EnforcementError, match="AllowedMethods"):
            validate_delegation(
                delegation, caller=DELEGATEE, target=USDC, calldata=calldata,
            )

    @pytest.mark.parametrize("bad_amount", [
        5_001 * 10**6,      # just over cap
        10_000 * 10**6,     # double cap
        2**128,             # absurdly large
    ])
    def test_over_cap_variants(self, delegation, bad_amount):
        calldata = _build_calldata(APPROVE_SELECTOR, 0, bad_amount)
        with pytest.raises(EnforcementError, match="ERC20TransferAmount"):
            validate_delegation(
                delegation, caller=DELEGATEE, target=USDC, calldata=calldata,
            )
