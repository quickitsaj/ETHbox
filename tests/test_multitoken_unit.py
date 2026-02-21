"""Unit tests for multi-token support (pure function tests).

These tests validate:
  - Token and SwapPair dataclass creation and immutability
  - Token and pair registry contents
  - Generic swap_caveats() for every registered pair
  - Consistency between swap_caveats() and the original usdc_weth_swap_caveats()
  - Delegation enforcement with multi-token caveats
  - Violation scenarios across different token pairs
"""

import pytest
from web3 import Web3

from poc.constants import (
    USDC, WETH, DAI, USDT, WBTC,
    SWAP_ROUTER_02, POOL_USDC_WETH_030,
    Token, SwapPair, TOKENS, PAIRS,
)
from poc.caveats import (
    swap_caveats,
    usdc_weth_swap_caveats,
    APPROVE_SELECTOR,
    EXACT_INPUT_SINGLE_SELECTOR,
)
from poc.delegation import (
    Caveat,
    Delegation,
    EnforcementError,
    delegation_from_caveat_map,
    validate_delegation,
)


SENDER = "0x000000000000000000000000000000000000dEaD"


# ---------------------------------------------------------------------------
# Token dataclass
# ---------------------------------------------------------------------------

class TestTokenDataclass:
    def test_create_token(self):
        t = Token("TEST", "0x" + "ab" * 20, 18, 5)
        assert t.symbol == "TEST"
        assert t.decimals == 18
        assert t.balance_slot == 5

    def test_token_is_frozen(self):
        t = TOKENS["USDC"]
        with pytest.raises(AttributeError):
            t.symbol = "OTHER"

    def test_token_equality(self):
        t1 = Token("USDC", USDC, 6, 9)
        t2 = Token("USDC", USDC, 6, 9)
        assert t1 == t2

    def test_token_inequality(self):
        assert TOKENS["USDC"] != TOKENS["WETH"]


# ---------------------------------------------------------------------------
# SwapPair dataclass
# ---------------------------------------------------------------------------

class TestSwapPairDataclass:
    def test_create_pair(self):
        pair = PAIRS["USDC/WETH"]
        assert pair.token_in.symbol == "USDC"
        assert pair.token_out.symbol == "WETH"
        assert pair.fee == 3000

    def test_pair_is_frozen(self):
        pair = PAIRS["USDC/WETH"]
        with pytest.raises(AttributeError):
            pair.fee = 500

    def test_pair_pool_address_set(self):
        pair = PAIRS["USDC/WETH"]
        assert pair.pool_address == POOL_USDC_WETH_030

    def test_pair_equality(self):
        p1 = SwapPair(TOKENS["USDC"], TOKENS["WETH"], POOL_USDC_WETH_030, 3000)
        p2 = SwapPair(TOKENS["USDC"], TOKENS["WETH"], POOL_USDC_WETH_030, 3000)
        assert p1 == p2


# ---------------------------------------------------------------------------
# Registry contents
# ---------------------------------------------------------------------------

class TestTokenRegistry:
    def test_all_expected_tokens_present(self):
        expected = {"USDC", "WETH", "DAI", "USDT", "WBTC"}
        assert set(TOKENS.keys()) == expected

    def test_usdc_metadata(self):
        t = TOKENS["USDC"]
        assert t.address == USDC
        assert t.decimals == 6
        assert t.balance_slot == 9

    def test_weth_metadata(self):
        t = TOKENS["WETH"]
        assert t.address == WETH
        assert t.decimals == 18
        assert t.balance_slot == 3

    def test_dai_metadata(self):
        t = TOKENS["DAI"]
        assert t.address == DAI
        assert t.decimals == 18
        assert t.balance_slot == 2

    def test_usdt_metadata(self):
        t = TOKENS["USDT"]
        assert t.address == USDT
        assert t.decimals == 6
        assert t.balance_slot == 2

    def test_wbtc_metadata(self):
        t = TOKENS["WBTC"]
        assert t.address == WBTC
        assert t.decimals == 8
        assert t.balance_slot == 0

    def test_all_addresses_are_checksummed(self):
        for name, token in TOKENS.items():
            assert Web3.is_checksum_address(token.address), (
                f"{name} address {token.address} is not checksummed"
            )


class TestPairRegistry:
    def test_all_expected_pairs_present(self):
        expected = {"USDC/WETH", "DAI/WETH", "WBTC/WETH", "USDT/WETH"}
        assert set(PAIRS.keys()) == expected

    def test_all_pairs_have_weth_output(self):
        """All current pairs swap into WETH."""
        for name, pair in PAIRS.items():
            assert pair.token_out.symbol == "WETH", (
                f"{name} token_out is {pair.token_out.symbol}, expected WETH"
            )

    def test_all_pairs_have_0_3_pct_fee(self):
        for name, pair in PAIRS.items():
            assert pair.fee == 3000, f"{name} fee is {pair.fee}, expected 3000"

    def test_all_pool_addresses_are_checksummed(self):
        for name, pair in PAIRS.items():
            assert Web3.is_checksum_address(pair.pool_address), (
                f"{name} pool {pair.pool_address} is not checksummed"
            )

    def test_token_in_matches_first_symbol(self):
        for name, pair in PAIRS.items():
            first_symbol = name.split("/")[0]
            assert pair.token_in.symbol == first_symbol


# ---------------------------------------------------------------------------
# Generic swap_caveats()
# ---------------------------------------------------------------------------

class TestSwapCaveats:
    def test_returns_all_required_keys(self):
        pair = PAIRS["USDC/WETH"]
        caveats = swap_caveats(pair, max_amount_in=1000, recipient=SENDER)
        assert set(caveats.keys()) == {
            "AllowedTargets",
            "AllowedMethods",
            "ERC20TransferAmount",
            "SwapConstraints",
        }

    def test_allowed_targets_has_token_in_and_router(self):
        pair = PAIRS["DAI/WETH"]
        caveats = swap_caveats(pair, max_amount_in=1000, recipient=SENDER)
        assert DAI in caveats["AllowedTargets"]
        assert SWAP_ROUTER_02 in caveats["AllowedTargets"]
        assert len(caveats["AllowedTargets"]) == 2

    def test_allowed_methods_has_approve_and_swap(self):
        pair = PAIRS["WBTC/WETH"]
        caveats = swap_caveats(pair, max_amount_in=1000, recipient=SENDER)
        assert APPROVE_SELECTOR in caveats["AllowedMethods"]
        assert EXACT_INPUT_SINGLE_SELECTOR in caveats["AllowedMethods"]

    def test_erc20_transfer_amount_uses_token_in(self):
        pair = PAIRS["USDT/WETH"]
        max_amount = 5_000 * 10**6
        caveats = swap_caveats(pair, max_amount_in=max_amount, recipient=SENDER)
        assert caveats["ERC20TransferAmount"]["token"] == USDT
        assert caveats["ERC20TransferAmount"]["maxAmount"] == max_amount

    def test_swap_constraints_use_pair_tokens(self):
        pair = PAIRS["DAI/WETH"]
        caveats = swap_caveats(pair, max_amount_in=1000, recipient=SENDER)
        sc = caveats["SwapConstraints"]
        assert sc["tokenIn"] == DAI
        assert sc["tokenOut"] == WETH
        assert sc["fee"] == 3000
        assert sc["recipient"] == SENDER

    @pytest.mark.parametrize("pair_name", list(PAIRS.keys()))
    def test_every_pair_produces_valid_caveats(self, pair_name):
        """Every registered pair should produce a well-formed caveat map."""
        pair = PAIRS[pair_name]
        caveats = swap_caveats(pair, max_amount_in=1000, recipient=SENDER)

        # Basic structure checks
        assert len(caveats["AllowedTargets"]) == 2
        assert len(caveats["AllowedMethods"]) == 2
        assert caveats["ERC20TransferAmount"]["maxAmount"] == 1000
        assert caveats["SwapConstraints"]["tokenIn"] == pair.token_in.address
        assert caveats["SwapConstraints"]["tokenOut"] == pair.token_out.address


# ---------------------------------------------------------------------------
# Consistency with original usdc_weth_swap_caveats()
# ---------------------------------------------------------------------------

class TestBackwardsCompatibility:
    def test_swap_caveats_matches_usdc_weth_original(self):
        """swap_caveats() for USDC/WETH should produce identical output."""
        pair = PAIRS["USDC/WETH"]
        max_usdc = 10_000 * 10**6

        generic = swap_caveats(pair, max_amount_in=max_usdc, recipient=SENDER)
        original = usdc_weth_swap_caveats(max_usdc=max_usdc, recipient=SENDER)

        assert generic == original

    def test_original_function_still_works(self):
        """The original usdc_weth_swap_caveats() must still work unchanged."""
        caveats = usdc_weth_swap_caveats(max_usdc=5000, recipient=SENDER)
        assert caveats["AllowedTargets"] == [USDC, SWAP_ROUTER_02]
        assert caveats["ERC20TransferAmount"]["token"] == USDC


# ---------------------------------------------------------------------------
# Delegation enforcement with multi-token caveats
# ---------------------------------------------------------------------------

DELEGATOR = "0x000000000000000000000000000000000000dEaD"
DELEGATEE = "0x0000000000000000000000000000000000001234"


def _build_calldata(selector: str, *uint256_args: int) -> bytes:
    sel_hex = selector[2:] if selector.startswith("0x") else selector
    data = bytes.fromhex(sel_hex)
    for arg in uint256_args:
        data += arg.to_bytes(32, "big")
    return data


class TestMultiTokenDelegationEnforcement:
    """Test that delegation enforcement works for non-USDC pairs."""

    def test_dai_delegation_valid_call(self):
        pair = PAIRS["DAI/WETH"]
        max_dai = 10_000 * 10**18  # DAI has 18 decimals
        caveat_map = swap_caveats(pair, max_amount_in=max_dai, recipient=DELEGATOR)
        delegation = delegation_from_caveat_map(DELEGATOR, DELEGATEE, caveat_map)

        calldata = _build_calldata(
            APPROVE_SELECTOR,
            int(SWAP_ROUTER_02, 16),
            5_000 * 10**18,
        )
        # Should not raise
        validate_delegation(
            delegation, caller=DELEGATEE, target=DAI, calldata=calldata,
        )

    def test_dai_delegation_wrong_target(self):
        pair = PAIRS["DAI/WETH"]
        caveat_map = swap_caveats(pair, max_amount_in=1000, recipient=DELEGATOR)
        delegation = delegation_from_caveat_map(DELEGATOR, DELEGATEE, caveat_map)

        calldata = _build_calldata(APPROVE_SELECTOR, 0, 100)
        # USDC is NOT an allowed target for a DAI delegation
        with pytest.raises(EnforcementError, match="AllowedTargets"):
            validate_delegation(
                delegation, caller=DELEGATEE, target=USDC, calldata=calldata,
            )

    def test_wbtc_delegation_over_cap(self):
        pair = PAIRS["WBTC/WETH"]
        max_wbtc = 1 * 10**8  # 1 WBTC (8 decimals)
        caveat_map = swap_caveats(pair, max_amount_in=max_wbtc, recipient=DELEGATOR)
        delegation = delegation_from_caveat_map(DELEGATOR, DELEGATEE, caveat_map)

        over_amount = 2 * 10**8  # 2 WBTC
        calldata = _build_calldata(
            APPROVE_SELECTOR,
            int(SWAP_ROUTER_02, 16),
            over_amount,
        )
        with pytest.raises(EnforcementError, match="ERC20TransferAmount"):
            validate_delegation(
                delegation, caller=DELEGATEE, target=WBTC, calldata=calldata,
            )

    def test_usdt_delegation_wrong_method(self):
        pair = PAIRS["USDT/WETH"]
        caveat_map = swap_caveats(pair, max_amount_in=1000, recipient=DELEGATOR)
        delegation = delegation_from_caveat_map(DELEGATOR, DELEGATEE, caveat_map)

        transfer_selector = Web3.keccak(text="transfer(address,uint256)")[:4].hex()
        calldata = _build_calldata(transfer_selector, 0, 100)
        with pytest.raises(EnforcementError, match="AllowedMethods"):
            validate_delegation(
                delegation, caller=DELEGATEE, target=USDT, calldata=calldata,
            )

    @pytest.mark.parametrize("pair_name", list(PAIRS.keys()))
    def test_every_pair_enforces_target_whitelist(self, pair_name):
        """For every pair, calling an unrelated address should be rejected."""
        pair = PAIRS[pair_name]
        caveat_map = swap_caveats(pair, max_amount_in=1000, recipient=DELEGATOR)
        delegation = delegation_from_caveat_map(DELEGATOR, DELEGATEE, caveat_map)

        calldata = _build_calldata(APPROVE_SELECTOR, 0, 100)
        random_target = "0x0000000000000000000000000000000000099999"
        with pytest.raises(EnforcementError, match="AllowedTargets"):
            validate_delegation(
                delegation, caller=DELEGATEE, target=random_target, calldata=calldata,
            )

    @pytest.mark.parametrize("pair_name", list(PAIRS.keys()))
    def test_every_pair_enforces_method_whitelist(self, pair_name):
        """For every pair, calling a disallowed method should be rejected."""
        pair = PAIRS[pair_name]
        caveat_map = swap_caveats(pair, max_amount_in=1000, recipient=DELEGATOR)
        delegation = delegation_from_caveat_map(DELEGATOR, DELEGATEE, caveat_map)

        calldata = _build_calldata("0xdeadbeef", 0, 100)
        with pytest.raises(EnforcementError, match="AllowedMethods"):
            validate_delegation(
                delegation,
                caller=DELEGATEE,
                target=pair.token_in.address,
                calldata=calldata,
            )
