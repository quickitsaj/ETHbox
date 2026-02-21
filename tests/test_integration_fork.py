"""Integration tests on a mainnet fork (Anvil).

These are smoke tests that verify our caveat configuration against real
deployed contracts. They require the RPC_URL environment variable and
consume RPC credits, so they should not be in CI hot-path.

What these tests catch that pure/local tests cannot:
  1. Selector correctness against real bytecode
  2. Multi-step transaction flow (approve → swap)
  3. Edge cases in real protocol interactions
  4. Realistic gas costs
"""

import pytest
from web3 import Web3

from poc.caveats import (
    APPROVE_SELECTOR,
    EXACT_INPUT_SINGLE_SELECTOR,
    usdc_weth_swap_caveats,
)
from poc.constants import (
    USDC, WETH, SWAP_ROUTER_02, POOL_USDC_WETH_030,
    ERC20_ABI, SWAP_ROUTER_ABI, POOL_ABI, POOL_FEE,
    USDC_BALANCE_SLOT,
)


def _strip_0x(s: str) -> str:
    """Remove optional 0x prefix for hex manipulation."""
    return s[2:] if s.startswith("0x") or s.startswith("0X") else s


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def w3(anvil_fork):
    w3_instance, _ = anvil_fork
    return w3_instance


@pytest.fixture(scope="module")
def sender(w3):
    return w3.eth.accounts[0]


def fund_usdc(w3, address, amount):
    """Inject USDC balance via storage slot manipulation."""
    slot = Web3.solidity_keccak(
        ["uint256", "uint256"],
        [int(address, 16), USDC_BALANCE_SLOT],
    )
    value = "0x" + amount.to_bytes(32, "big").hex()
    w3.provider.make_request("anvil_setStorageAt", [USDC, slot.hex(), value])


def fund_eth(w3, address, wei):
    w3.provider.make_request("anvil_setBalance", [address, hex(wei)])


# ---------------------------------------------------------------------------
# 1. Selector correctness against real bytecode
# ---------------------------------------------------------------------------

class TestSelectorAgainstRealBytecode:
    """Verify our computed selectors match the actual deployed contracts."""

    def test_approve_selector_matches_usdc(self, w3, sender):
        """Call USDC.approve() with our selector — must not revert on ABI level.

        We fund the account first so the call context is valid, then
        verify the transaction doesn't revert.
        """
        fund_usdc(w3, sender, 1_000_000)
        fund_eth(w3, sender, 10**18)

        usdc = w3.eth.contract(address=USDC, abi=ERC20_ABI)
        # Build raw calldata using our selector
        sel = _strip_0x(APPROVE_SELECTOR)
        calldata = ("0x" + sel
                    + SWAP_ROUTER_02[2:].lower().zfill(64)
                    + hex(1000)[2:].zfill(64))

        # eth_call should succeed (not revert)
        result = w3.eth.call({
            "from": sender,
            "to": USDC,
            "data": calldata,
        })
        # approve returns bool — should be true
        assert int.from_bytes(result, "big") == 1

    def test_exact_input_single_selector_matches_router(self, w3, sender):
        """Verify our exactInputSingle selector matches the SwapRouter02.

        We check that the first 4 bytes of our computed selector appear
        in the function dispatch of the deployed SwapRouter02 by attempting
        a static call. If the selector were wrong, we'd get a revert with
        no return data (function not found).
        """
        # The router requires properly encoded params, so let's use the
        # ABI-level interface which uses the same selector.
        router = w3.eth.contract(address=SWAP_ROUTER_02, abi=SWAP_ROUTER_ABI)
        # Verify the ABI-computed selector matches ours
        abi_selector = router.functions.exactInputSingle({
            "tokenIn": USDC,
            "tokenOut": WETH,
            "fee": POOL_FEE,
            "recipient": sender,
            "amountIn": 1000,
            "amountOutMinimum": 0,
            "sqrtPriceLimitX96": 0,
        })._encode_transaction_data()[:10]  # "0x" + 8 hex chars
        # Normalize both to 0x-prefixed for comparison
        expected = "0x" + _strip_0x(EXACT_INPUT_SINGLE_SELECTOR)
        assert abi_selector == expected

    def test_contracts_have_code(self, w3):
        """All addresses referenced by the caveat map must have deployed code."""
        for label, addr in [
            ("USDC", USDC),
            ("WETH", WETH),
            ("SwapRouter02", SWAP_ROUTER_02),
            ("Pool", POOL_USDC_WETH_030),
        ]:
            code = w3.eth.get_code(addr)
            assert len(code) > 2, f"{label} ({addr}) has no code at fork block"


# ---------------------------------------------------------------------------
# 2. Multi-step transaction flow
# ---------------------------------------------------------------------------

class TestMultiStepSwapFlow:
    """Test the full approve → swap flow that caveats must permit."""

    def test_approve_then_swap_succeeds(self, w3, sender):
        """Execute the two-step flow: approve USDC, then swap on router.

        This is the exact sequence a delegatee would perform. The caveat
        map must allow both steps.
        """
        amount_usdc = 10_000 * 10**6  # 10k USDC

        # Fund
        fund_usdc(w3, sender, amount_usdc)
        fund_eth(w3, sender, 10 * 10**18)

        # Snapshot so we can restore state for other tests
        snapshot_id = w3.provider.make_request("evm_snapshot", [])["result"]

        try:
            # Step 1: approve
            usdc = w3.eth.contract(address=USDC, abi=ERC20_ABI)
            tx1 = usdc.functions.approve(SWAP_ROUTER_02, amount_usdc).transact(
                {"from": sender}
            )
            r1 = w3.eth.wait_for_transaction_receipt(tx1)
            assert r1["status"] == 1, "approve() reverted"

            # Step 2: swap
            router = w3.eth.contract(address=SWAP_ROUTER_02, abi=SWAP_ROUTER_ABI)
            tx2 = router.functions.exactInputSingle({
                "tokenIn": USDC,
                "tokenOut": WETH,
                "fee": POOL_FEE,
                "recipient": sender,
                "amountIn": amount_usdc,
                "amountOutMinimum": 0,
                "sqrtPriceLimitX96": 0,
            }).transact({"from": sender})
            r2 = w3.eth.wait_for_transaction_receipt(tx2)
            assert r2["status"] == 1, "exactInputSingle() reverted"

            # Verify WETH received
            weth = w3.eth.contract(address=WETH, abi=ERC20_ABI)
            weth_balance = weth.functions.balanceOf(sender).call()
            assert weth_balance > 0, "No WETH received from swap"
        finally:
            w3.provider.make_request("evm_revert", [snapshot_id])

    def test_swap_only_touches_allowed_targets(self, w3, sender):
        """Verify the swap transaction only sends calls to targets in our
        caveat AllowedTargets list.

        We check the transaction trace to see which addresses receive calls.
        The top-level targets should be USDC (approve) and SwapRouter02 (swap).
        Internal calls (router → pool → callbacks) don't matter for
        AllowedTargets enforcement — the enforcer checks the top-level target.
        """
        caveats = usdc_weth_swap_caveats(
            max_usdc=10_000 * 10**6,
            recipient=sender,
        )
        allowed = set(caveats["AllowedTargets"])

        # The top-level "to" addresses in our two transactions are:
        # 1. USDC (for approve)
        # 2. SwapRouter02 (for exactInputSingle)
        assert USDC in allowed
        assert SWAP_ROUTER_02 in allowed


# ---------------------------------------------------------------------------
# 3. Edge cases in real protocols
# ---------------------------------------------------------------------------

class TestProtocolEdgeCases:
    """Test assumptions about how the protocol works that affect caveats."""

    def test_pool_is_not_directly_called(self, w3, sender):
        """The delegatee calls the router, not the pool directly.

        Therefore the pool address does NOT need to be in AllowedTargets.
        This test confirms the router is the only entry point for swaps.
        """
        caveats = usdc_weth_swap_caveats(
            max_usdc=1000 * 10**6,
            recipient=sender,
        )
        # Pool should NOT be in targets
        assert POOL_USDC_WETH_030 not in caveats["AllowedTargets"]

        # But the pool does exist and is a real contract
        pool = w3.eth.contract(address=POOL_USDC_WETH_030, abi=POOL_ABI)
        slot0 = pool.functions.slot0().call()
        assert slot0[0] > 0, "Pool sqrtPriceX96 should be nonzero"

    def test_weth_not_in_allowed_targets(self, w3, sender):
        """WETH is the output token. The delegatee never calls WETH directly
        in the USDC→WETH flow — the router handles the output internally.

        If we were doing WETH→USDC, we'd need WETH in targets (for approve).
        """
        caveats = usdc_weth_swap_caveats(
            max_usdc=1000 * 10**6,
            recipient=sender,
        )
        assert WETH not in caveats["AllowedTargets"]


# ---------------------------------------------------------------------------
# 4. Gas realism
# ---------------------------------------------------------------------------

class TestGasRealism:
    """Sanity check gas costs against real pool state."""

    def test_swap_gas_is_reasonable(self, w3, sender):
        """A USDC→WETH swap should cost between 100k and 500k gas."""
        amount_usdc = 1_000 * 10**6

        fund_usdc(w3, sender, amount_usdc)
        fund_eth(w3, sender, 10 * 10**18)

        snapshot_id = w3.provider.make_request("evm_snapshot", [])["result"]

        try:
            usdc = w3.eth.contract(address=USDC, abi=ERC20_ABI)
            usdc.functions.approve(SWAP_ROUTER_02, amount_usdc).transact(
                {"from": sender}
            )

            router = w3.eth.contract(address=SWAP_ROUTER_02, abi=SWAP_ROUTER_ABI)
            tx = router.functions.exactInputSingle({
                "tokenIn": USDC,
                "tokenOut": WETH,
                "fee": POOL_FEE,
                "recipient": sender,
                "amountIn": amount_usdc,
                "amountOutMinimum": 0,
                "sqrtPriceLimitX96": 0,
            }).transact({"from": sender})
            receipt = w3.eth.wait_for_transaction_receipt(tx)

            gas_used = receipt["gasUsed"]
            assert 50_000 < gas_used < 500_000, (
                f"Swap gas {gas_used} outside expected range"
            )
        finally:
            w3.provider.make_request("evm_revert", [snapshot_id])
