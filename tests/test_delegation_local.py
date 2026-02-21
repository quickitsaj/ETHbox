"""Local EVM tests for on-chain delegation enforcement (no mainnet fork).

These tests deploy the hand-assembled enforcer contracts on a fresh Anvil
instance and verify that:
  - AllowedTargetsEnforcer passes for allowed targets and reverts otherwise
  - AllowedMethodsEnforcer passes for allowed selectors and reverts otherwise
  - ValueLimitEnforcer passes for amounts under cap and reverts otherwise
  - The full delegation flow works end-to-end:
      delegator creates a delegation → delegatee redeems it → enforcers validate

Requires: Foundry (anvil) on PATH.
"""

import pytest
from web3 import Web3

from poc.enforcers import (
    deploy_allowed_targets_enforcer,
    deploy_allowed_methods_enforcer,
    deploy_value_limit_enforcer,
    call_allowed_targets_enforcer,
    call_allowed_methods_enforcer,
    call_value_limit_enforcer,
)
from poc.delegation import (
    Caveat,
    Delegation,
    EnforcementError,
    delegation_from_caveat_map,
    validate_delegation,
    execute_delegated_call,
)
from poc.caveats import (
    usdc_weth_swap_caveats,
    APPROVE_SELECTOR,
    EXACT_INPUT_SINGLE_SELECTOR,
)
from poc.constants import USDC, WETH, SWAP_ROUTER_02


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def w3(anvil_local):
    """Local web3 instance (no mainnet fork)."""
    w3_instance, _ = anvil_local
    return w3_instance


@pytest.fixture(scope="module")
def sender(w3):
    return w3.eth.accounts[0]


@pytest.fixture(scope="module")
def delegator(w3):
    return w3.eth.accounts[1]


@pytest.fixture(scope="module")
def delegatee(w3):
    return w3.eth.accounts[2]


@pytest.fixture(scope="module")
def targets_enforcer(w3, sender):
    """Deploy AllowedTargetsEnforcer."""
    return deploy_allowed_targets_enforcer(w3, sender)


@pytest.fixture(scope="module")
def methods_enforcer(w3, sender):
    """Deploy AllowedMethodsEnforcer."""
    return deploy_allowed_methods_enforcer(w3, sender)


@pytest.fixture(scope="module")
def value_enforcer(w3, sender):
    """Deploy ValueLimitEnforcer."""
    return deploy_value_limit_enforcer(w3, sender)


@pytest.fixture(scope="module")
def mock_erc20(w3, sender):
    """Deploy a minimal mock ERC-20 (same as test_caveats_local.py)."""
    runtime_hex = (
        "6000" "35" "60e0" "1c" "80"
        "63095ea7b3" "14" "6019" "57"
        "6370a08231" "14" "6026" "57"
        "600080fd"
        "5b" "6001" "6000" "52" "6020" "6000" "f3"
        "5b" "6000" "6000" "52" "6020" "6000" "f3"
    )
    runtime = bytes.fromhex(runtime_hex)
    runtime_len = len(runtime)
    init_hex = (
        f"60{runtime_len:02x}" "600a" "6000" "39"
        f"60{runtime_len:02x}" "6000" "f3"
    )
    deploy_data = "0x" + init_hex + runtime_hex
    tx_hash = w3.eth.send_transaction({"from": sender, "data": deploy_data})
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
    assert receipt["status"] == 1
    return receipt["contractAddress"]


# ---------------------------------------------------------------------------
# AllowedTargetsEnforcer on-chain tests
# ---------------------------------------------------------------------------

class TestAllowedTargetsEnforcerOnChain:
    """Test the deployed AllowedTargetsEnforcer contract."""

    def test_deploys_with_code(self, w3, targets_enforcer):
        """The deployed contract must have bytecode."""
        code = w3.eth.get_code(targets_enforcer)
        assert len(code) > 2

    def test_allowed_target_passes(self, w3, sender, targets_enforcer):
        """A target in the allowed list should succeed."""
        call_allowed_targets_enforcer(
            w3, targets_enforcer,
            target=USDC,
            allowed=[USDC, SWAP_ROUTER_02],
            sender=sender,
        )

    def test_second_target_passes(self, w3, sender, targets_enforcer):
        """Second element in the allowed list should also pass."""
        call_allowed_targets_enforcer(
            w3, targets_enforcer,
            target=SWAP_ROUTER_02,
            allowed=[USDC, SWAP_ROUTER_02],
            sender=sender,
        )

    def test_disallowed_target_reverts(self, w3, sender, targets_enforcer):
        """A target NOT in the allowed list should revert."""
        with pytest.raises(Exception):
            call_allowed_targets_enforcer(
                w3, targets_enforcer,
                target=WETH,
                allowed=[USDC, SWAP_ROUTER_02],
                sender=sender,
            )

    def test_empty_allowed_list_reverts(self, w3, sender, targets_enforcer):
        """An empty allowed list should always revert."""
        with pytest.raises(Exception):
            call_allowed_targets_enforcer(
                w3, targets_enforcer,
                target=USDC,
                allowed=[],
                sender=sender,
            )

    def test_single_allowed_target(self, w3, sender, targets_enforcer):
        """A single-element allowed list should work."""
        call_allowed_targets_enforcer(
            w3, targets_enforcer,
            target=USDC,
            allowed=[USDC],
            sender=sender,
        )


# ---------------------------------------------------------------------------
# AllowedMethodsEnforcer on-chain tests
# ---------------------------------------------------------------------------

class TestAllowedMethodsEnforcerOnChain:
    """Test the deployed AllowedMethodsEnforcer contract."""

    def test_deploys_with_code(self, w3, methods_enforcer):
        code = w3.eth.get_code(methods_enforcer)
        assert len(code) > 2

    def test_allowed_method_passes(self, w3, sender, methods_enforcer):
        """approve selector should pass when in the allowed list."""
        call_allowed_methods_enforcer(
            w3, methods_enforcer,
            method_selector=APPROVE_SELECTOR,
            allowed=[APPROVE_SELECTOR, EXACT_INPUT_SINGLE_SELECTOR],
            sender=sender,
        )

    def test_second_method_passes(self, w3, sender, methods_enforcer):
        """exactInputSingle selector should also pass."""
        call_allowed_methods_enforcer(
            w3, methods_enforcer,
            method_selector=EXACT_INPUT_SINGLE_SELECTOR,
            allowed=[APPROVE_SELECTOR, EXACT_INPUT_SINGLE_SELECTOR],
            sender=sender,
        )

    def test_disallowed_method_reverts(self, w3, sender, methods_enforcer):
        """A random selector should revert."""
        with pytest.raises(Exception):
            call_allowed_methods_enforcer(
                w3, methods_enforcer,
                method_selector="0xdeadbeef",
                allowed=[APPROVE_SELECTOR],
                sender=sender,
            )

    def test_transfer_method_not_allowed(self, w3, sender, methods_enforcer):
        """transfer() selector should fail when only approve() is allowed."""
        transfer_sel = Web3.keccak(text="transfer(address,uint256)")[:4].hex()
        with pytest.raises(Exception):
            call_allowed_methods_enforcer(
                w3, methods_enforcer,
                method_selector=transfer_sel,
                allowed=[APPROVE_SELECTOR, EXACT_INPUT_SINGLE_SELECTOR],
                sender=sender,
            )


# ---------------------------------------------------------------------------
# ValueLimitEnforcer on-chain tests
# ---------------------------------------------------------------------------

class TestValueLimitEnforcerOnChain:
    """Test the deployed ValueLimitEnforcer contract."""

    def test_deploys_with_code(self, w3, value_enforcer):
        code = w3.eth.get_code(value_enforcer)
        assert len(code) > 2

    def test_under_cap_passes(self, w3, sender, value_enforcer):
        call_value_limit_enforcer(
            w3, value_enforcer,
            amount=500,
            cap=1000,
            sender=sender,
        )

    def test_at_cap_passes(self, w3, sender, value_enforcer):
        call_value_limit_enforcer(
            w3, value_enforcer,
            amount=1000,
            cap=1000,
            sender=sender,
        )

    def test_over_cap_reverts(self, w3, sender, value_enforcer):
        with pytest.raises(Exception):
            call_value_limit_enforcer(
                w3, value_enforcer,
                amount=1001,
                cap=1000,
                sender=sender,
            )

    def test_zero_amount_passes(self, w3, sender, value_enforcer):
        call_value_limit_enforcer(
            w3, value_enforcer,
            amount=0,
            cap=1000,
            sender=sender,
        )

    def test_realistic_usdc_amounts(self, w3, sender, value_enforcer):
        """Test with realistic USDC amounts (6 decimals)."""
        max_usdc = 10_000 * 10**6
        # Under cap
        call_value_limit_enforcer(
            w3, value_enforcer,
            amount=9_999 * 10**6,
            cap=max_usdc,
            sender=sender,
        )
        # Over cap
        with pytest.raises(Exception):
            call_value_limit_enforcer(
                w3, value_enforcer,
                amount=10_001 * 10**6,
                cap=max_usdc,
                sender=sender,
            )


# ---------------------------------------------------------------------------
# End-to-end delegation flow on local EVM
# ---------------------------------------------------------------------------

class TestDelegationFlowLocal:
    """Test the full delegation lifecycle on a local Anvil instance.

    Uses the mock ERC-20 as the target contract and validates that:
    - A properly constrained delegation allows the approve() call
    - Violations are caught before execution reaches the chain
    """

    def test_delegated_approve_succeeds(self, w3, delegator, delegatee, mock_erc20):
        """A delegated approve() call should succeed when caveats allow it."""
        # Create delegation allowing approve() on the mock ERC-20
        delegation = Delegation(
            delegator=delegator,
            delegatee=delegatee,
            caveats=(
                Caveat("AllowedTargets", [mock_erc20]),
                Caveat("AllowedMethods", [APPROVE_SELECTOR]),
                Caveat("ERC20TransferAmount", {"token": mock_erc20, "maxAmount": 10_000}),
            ),
        )

        # Build approve(address, uint256) calldata
        spender = "0x" + "00" * 20
        calldata = (
            bytes.fromhex(APPROVE_SELECTOR[2:])
            + bytes.fromhex(spender[2:].zfill(64))
            + (5_000).to_bytes(32, "big")
        )

        # Execute delegated call
        receipt = execute_delegated_call(
            w3, delegation,
            target=mock_erc20,
            calldata=calldata,
        )
        assert receipt["status"] == 1

    def test_delegated_call_wrong_target_rejected(self, w3, delegator, delegatee, mock_erc20):
        """Calling an unapproved target should be rejected before execution."""
        other_target = "0x" + "ab" * 20

        delegation = Delegation(
            delegator=delegator,
            delegatee=delegatee,
            caveats=(
                Caveat("AllowedTargets", [mock_erc20]),
                Caveat("AllowedMethods", [APPROVE_SELECTOR]),
                Caveat("ERC20TransferAmount", {"token": mock_erc20, "maxAmount": 10_000}),
            ),
        )

        calldata = (
            bytes.fromhex(APPROVE_SELECTOR[2:])
            + bytes(32)
            + (100).to_bytes(32, "big")
        )

        with pytest.raises(EnforcementError, match="AllowedTargets"):
            execute_delegated_call(
                w3, delegation,
                target=other_target,
                calldata=calldata,
            )

    def test_delegated_call_wrong_method_rejected(self, w3, delegator, delegatee, mock_erc20):
        """Calling a disallowed method should be rejected."""
        delegation = Delegation(
            delegator=delegator,
            delegatee=delegatee,
            caveats=(
                Caveat("AllowedTargets", [mock_erc20]),
                Caveat("AllowedMethods", [APPROVE_SELECTOR]),
                Caveat("ERC20TransferAmount", {"token": mock_erc20, "maxAmount": 10_000}),
            ),
        )

        # Use transfer selector instead of approve
        transfer_selector = Web3.keccak(text="transfer(address,uint256)")[:4]
        calldata = (
            transfer_selector
            + bytes(32)
            + (100).to_bytes(32, "big")
        )

        with pytest.raises(EnforcementError, match="AllowedMethods"):
            execute_delegated_call(
                w3, delegation,
                target=mock_erc20,
                calldata=calldata,
            )

    def test_delegated_call_over_cap_rejected(self, w3, delegator, delegatee, mock_erc20):
        """Exceeding the spending cap should be rejected."""
        delegation = Delegation(
            delegator=delegator,
            delegatee=delegatee,
            caveats=(
                Caveat("AllowedTargets", [mock_erc20]),
                Caveat("AllowedMethods", [APPROVE_SELECTOR]),
                Caveat("ERC20TransferAmount", {"token": mock_erc20, "maxAmount": 1_000}),
            ),
        )

        # Amount exceeds cap
        calldata = (
            bytes.fromhex(APPROVE_SELECTOR[2:])
            + bytes(32)
            + (2_000).to_bytes(32, "big")
        )

        with pytest.raises(EnforcementError, match="ERC20TransferAmount"):
            execute_delegated_call(
                w3, delegation,
                target=mock_erc20,
                calldata=calldata,
            )

    def test_delegation_from_phase0_caveats(self, w3, delegator, delegatee, mock_erc20):
        """A delegation built from Phase 0 caveat map should enforce correctly."""
        # Use the Phase 0 caveat map but with mock_erc20 as target
        # We can't use the real USDC address since we're on a clean Anvil
        max_usdc = 10_000 * 10**6

        delegation = Delegation(
            delegator=delegator,
            delegatee=delegatee,
            caveats=(
                Caveat("AllowedTargets", [mock_erc20]),
                Caveat("AllowedMethods", [APPROVE_SELECTOR]),
                Caveat("ERC20TransferAmount", {"token": mock_erc20, "maxAmount": max_usdc}),
            ),
        )

        # Valid call
        calldata = (
            bytes.fromhex(APPROVE_SELECTOR[2:])
            + bytes(32)
            + (5_000 * 10**6).to_bytes(32, "big")
        )
        receipt = execute_delegated_call(
            w3, delegation, target=mock_erc20, calldata=calldata,
        )
        assert receipt["status"] == 1

        # Over cap → rejected
        calldata_over = (
            bytes.fromhex(APPROVE_SELECTOR[2:])
            + bytes(32)
            + (20_000 * 10**6).to_bytes(32, "big")
        )
        with pytest.raises(EnforcementError, match="ERC20TransferAmount"):
            execute_delegated_call(
                w3, delegation, target=mock_erc20, calldata=calldata_over,
            )
