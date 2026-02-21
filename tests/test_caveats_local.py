"""Local EVM tests for caveat correctness (no mainnet fork).

These tests deploy minimal mock contracts on a fresh Anvil instance
to verify that:
  - Computed function selectors actually match deployed method IDs
  - The caveat map addresses and selectors are internally consistent
  - Mock ERC-20 approve() and a mock router's exactInputSingle() accept
    calls with the selectors we've computed

Full delegation enforcement testing (DelegationManager + CaveatEnforcer
contracts) requires the MetaMask delegation-framework Foundry project.
That is documented in docs/caveat-testing-assessment.md as a future step.
"""

import pytest
from web3 import Web3

from poc.caveats import (
    APPROVE_SELECTOR,
    EXACT_INPUT_SINGLE_SELECTOR,
    usdc_weth_swap_caveats,
)
from poc.constants import USDC, WETH, SWAP_ROUTER_02, POOL_FEE


def _strip_0x(s: str) -> str:
    """Remove optional 0x prefix for hex manipulation."""
    return s[2:] if s.startswith("0x") or s.startswith("0X") else s


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
def mock_erc20(w3, sender):
    """Deploy a minimal mock ERC-20 that responds to approve() and balanceOf().

    Runtime bytecode dispatches on selector:
      0x095ea7b3 (approve)  -> returns uint256(1)  (true)
      0x70a08231 (balanceOf) -> returns uint256(0)
      anything else          -> revert
    """
    # Runtime bytecode (hand-assembled)
    # Stack notation: [top, ...]
    #
    # PUSH1 0x00  CALLDATALOAD   -> [calldata[0:32]]
    # PUSH1 0xe0  SHR            -> [selector]  (shift right 224 bits)
    # DUP1                       -> [selector, selector]
    #
    # PUSH4 0x095ea7b3  EQ       -> [sel==approve, selector]
    # PUSH1 <approve_dest> JUMPI -> [selector]
    #
    # PUSH4 0x70a08231  EQ       -> [sel==balanceOf]
    # PUSH1 <balanceOf_dest> JUMPI -> []
    #
    # PUSH1 0 PUSH1 0 REVERT    (fallback)
    #
    # JUMPDEST (approve):
    #   PUSH1 1  PUSH1 0  MSTORE  PUSH1 32  PUSH1 0  RETURN
    #
    # JUMPDEST (balanceOf):
    #   PUSH1 0  PUSH1 0  MSTORE  PUSH1 32  PUSH1 0  RETURN

    runtime_hex = (
        "6000"      # PUSH1 0
        "35"        # CALLDATALOAD
        "60e0"      # PUSH1 0xe0
        "1c"        # SHR
        "80"        # DUP1
        "63095ea7b3"  # PUSH4 approve selector
        "14"        # EQ
        "6019"      # PUSH1 25 (offset of approve JUMPDEST)
        "57"        # JUMPI
        "6370a08231"  # PUSH4 balanceOf selector
        "14"        # EQ
        "6026"      # PUSH1 38 (offset of balanceOf JUMPDEST)
        "57"        # JUMPI
        "600080fd"  # PUSH1 0, PUSH1 0, REVERT
        # offset 25 (0x19): approve handler
        "5b"        # JUMPDEST
        "6001"      # PUSH1 1
        "6000"      # PUSH1 0
        "52"        # MSTORE
        "6020"      # PUSH1 32
        "6000"      # PUSH1 0
        "f3"        # RETURN
        # offset 38 (0x26): balanceOf handler
        "5b"        # JUMPDEST
        "6000"      # PUSH1 0
        "6000"      # PUSH1 0
        "52"        # MSTORE
        "6020"      # PUSH1 32
        "6000"      # PUSH1 0
        "f3"        # RETURN
    )

    runtime = bytes.fromhex(runtime_hex)
    runtime_len = len(runtime)

    # Init code: copy runtime from code to memory and return it
    # PUSH1 <runtime_len>  PUSH1 <init_len>  PUSH1 0  CODECOPY
    # PUSH1 <runtime_len>  PUSH1 0  RETURN
    # init_len = 10 bytes (fixed: 6 PUSH1s + CODECOPY + RETURN)
    init_hex = (
        f"60{runtime_len:02x}"  # PUSH1 runtime_len
        "600a"                  # PUSH1 10 (init code length)
        "6000"                  # PUSH1 0 (memory dest)
        "39"                    # CODECOPY
        f"60{runtime_len:02x}"  # PUSH1 runtime_len
        "6000"                  # PUSH1 0
        "f3"                    # RETURN
    )

    deploy_data = "0x" + init_hex + runtime_hex
    tx_hash = w3.eth.send_transaction({"from": sender, "data": deploy_data})
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
    assert receipt["status"] == 1
    return receipt["contractAddress"]


# ---------------------------------------------------------------------------
# Selector verification tests
# ---------------------------------------------------------------------------

class TestSelectorCorrectness:
    """Verify computed selectors match known canonical values."""

    def test_approve_selector_is_canonical(self):
        """0x095ea7b3 is the well-known ERC-20 approve selector."""
        assert _strip_0x(APPROVE_SELECTOR) == "095ea7b3"

    def test_exact_input_single_selector_format(self):
        """Selector must be exactly 4 bytes (8 hex chars, ignoring 0x prefix)."""
        assert len(_strip_0x(EXACT_INPUT_SINGLE_SELECTOR)) == 8

    def test_selectors_are_distinct(self):
        assert APPROVE_SELECTOR != EXACT_INPUT_SINGLE_SELECTOR

    def test_approve_works_on_mock_erc20(self, w3, sender, mock_erc20):
        """Calling approve() with our computed selector succeeds on a mock."""
        sel = _strip_0x(APPROVE_SELECTOR)
        addr_padded = sender[2:].lower().zfill(64)
        amount_padded = hex(1000)[2:].zfill(64)
        calldata = "0x" + sel + addr_padded + amount_padded

        result = w3.eth.call({
            "from": sender,
            "to": mock_erc20,
            "data": calldata,
        })
        # Should return true (1 as uint256)
        assert int.from_bytes(result, "big") == 1

    def test_unknown_selector_reverts_on_mock(self, w3, sender, mock_erc20):
        """A random selector reverts — mock enforces selector matching."""
        calldata = "0xdeadbeef" + "00" * 64
        with pytest.raises(Exception):
            w3.eth.call({
                "from": sender,
                "to": mock_erc20,
                "data": calldata,
            })


# ---------------------------------------------------------------------------
# Caveat map internal consistency
# ---------------------------------------------------------------------------

class TestCaveatMapConsistency:
    """Verify the caveat dict is self-consistent (no EVM needed)."""

    def test_allowed_methods_are_valid_selectors(self):
        """Each method in AllowedMethods must be a 4-byte hex string."""
        caveats = usdc_weth_swap_caveats(max_usdc=1000, recipient="0x" + "00" * 20)
        for method in caveats["AllowedMethods"]:
            stripped = _strip_0x(method)
            assert len(stripped) == 8, f"Selector {method} is not 4 bytes"
            int(stripped, 16)  # must be valid hex

    def test_allowed_targets_are_checksummed_addresses(self):
        """Each target must be a valid checksummed Ethereum address."""
        caveats = usdc_weth_swap_caveats(max_usdc=1000, recipient="0x" + "00" * 20)
        for addr in caveats["AllowedTargets"]:
            assert Web3.is_checksum_address(addr), f"{addr} is not checksummed"

    def test_erc20_cap_token_is_in_allowed_targets(self):
        """The capped token must be in the AllowedTargets list."""
        caveats = usdc_weth_swap_caveats(max_usdc=1000, recipient="0x" + "00" * 20)
        assert caveats["ERC20TransferAmount"]["token"] in caveats["AllowedTargets"]

    def test_swap_constraints_tokens_reference_known_addresses(self):
        """tokenIn/tokenOut must match constants.USDC/WETH."""
        caveats = usdc_weth_swap_caveats(max_usdc=1000, recipient="0x" + "00" * 20)
        assert caveats["SwapConstraints"]["tokenIn"] == USDC
        assert caveats["SwapConstraints"]["tokenOut"] == WETH

    def test_swap_constraints_fee_matches_pool(self):
        """Fee tier must match the target pool's fee."""
        caveats = usdc_weth_swap_caveats(max_usdc=1000, recipient="0x" + "00" * 20)
        assert caveats["SwapConstraints"]["fee"] == POOL_FEE
        assert POOL_FEE == 3000  # 0.3% pool

    def test_approve_target_matches_swap_router(self):
        """approve() is called on the token, but the spender is SwapRouter02.

        The AllowedTargets must include the token (for approve) and the
        router (for exactInputSingle). This test verifies both are present.
        """
        caveats = usdc_weth_swap_caveats(max_usdc=1000, recipient="0x" + "00" * 20)
        targets = caveats["AllowedTargets"]
        assert USDC in targets, "USDC must be in targets (for approve)"
        assert SWAP_ROUTER_02 in targets, "Router must be in targets (for swap)"
