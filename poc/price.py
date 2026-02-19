"""Price reading, manipulation, and validation against historical data."""

import math
from web3 import Web3

from .constants import (
    POOL_USDC_WETH_030, POOL_ABI,
    CHAINLINK_ETH_USD, CHAINLINK_ABI,
    USDC, USDC_BALANCE_SLOT, SWAP_ROUTER_02,
    ERC20_ABI, SWAP_ROUTER_ABI, POOL_FEE, WETH,
)


# ---------------------------------------------------------------------------
# Read prices
# ---------------------------------------------------------------------------

def read_pool_price(w3: Web3) -> tuple[int, float]:
    """Return (sqrtPriceX96, eth_price_usd) from the 0.3% pool."""
    pool = w3.eth.contract(address=POOL_USDC_WETH_030, abi=POOL_ABI)
    slot0 = pool.functions.slot0().call()
    sqrt_price_x96 = slot0[0]
    price_raw = (sqrt_price_x96 / (2**96)) ** 2
    eth_price = (1 / price_raw) * (10**12) if price_raw else 0
    return sqrt_price_x96, eth_price


def read_chainlink_price(w3: Web3) -> float:
    """Return ETH/USD from Chainlink (8-decimal)."""
    oracle = w3.eth.contract(address=CHAINLINK_ETH_USD, abi=CHAINLINK_ABI)
    (_, answer, _, _, _) = oracle.functions.latestRoundData().call()
    return answer / 1e8


# ---------------------------------------------------------------------------
# Manipulate price via large swap (realistic approach)
# ---------------------------------------------------------------------------

def _target_sqrt_price_x96(eth_price_usd: float) -> int:
    """Compute sqrtPriceX96 for a target ETH/USD price.

    In the USDC/WETH pool token0=USDC, token1=WETH so
    price = token1/token0 = 1 / (eth_price * 1e12).
    """
    price = 1.0 / (eth_price_usd * 1e12)
    return int(math.sqrt(price) * (2**96))


def move_pool_price(w3: Web3, target_eth_usd: float, sender: str) -> float:
    """Push the pool price toward *target_eth_usd* by executing a large swap.

    Returns the resulting ETH price after the move.
    """
    _, current_price = read_pool_price(w3)

    if abs(current_price - target_eth_usd) / current_price < 0.001:
        return current_price  # already close enough

    if target_eth_usd > current_price:
        # Need to buy WETH (sell USDC) -> price goes up
        _push_price_up(w3, sender, target_eth_usd)
    else:
        # Need to sell WETH (buy USDC) -> price goes down
        _push_price_down(w3, sender, target_eth_usd)

    _, new_price = read_pool_price(w3)
    return new_price


def _push_price_up(w3: Web3, sender: str, target: float) -> None:
    """Buy WETH with USDC to push price up."""
    usdc = w3.eth.contract(address=USDC, abi=ERC20_ABI)
    router = w3.eth.contract(address=SWAP_ROUTER_02, abi=SWAP_ROUTER_ABI)

    for _ in range(10):
        _, price = read_pool_price(w3)
        if price >= target * 0.999:
            return
        # Swap a chunk of USDC -> WETH
        chunk = int(5_000_000 * 1e6)  # 5M USDC per iteration
        from .fork import fund_usdc
        fund_usdc(w3, sender, chunk)

        usdc.functions.approve(SWAP_ROUTER_02, chunk).transact({"from": sender})
        w3.eth.wait_for_transaction_receipt(
            router.functions.exactInputSingle({
                "tokenIn": USDC,
                "tokenOut": WETH,
                "fee": POOL_FEE,
                "recipient": sender,
                "amountIn": chunk,
                "amountOutMinimum": 0,
                "sqrtPriceLimitX96": 0,
            }).transact({"from": sender})
        )


def _push_price_down(w3: Web3, sender: str, target: float) -> None:
    """Sell WETH for USDC to push price down."""
    from .fork import fund_usdc
    weth = w3.eth.contract(address=WETH, abi=ERC20_ABI)
    router = w3.eth.contract(address=SWAP_ROUTER_02, abi=SWAP_ROUTER_ABI)

    for _ in range(10):
        _, price = read_pool_price(w3)
        if price <= target * 1.001:
            return
        # Deposit ETH -> WETH then swap WETH -> USDC
        chunk_wei = int(2000 * 1e18)  # 2000 WETH per iteration
        from .fork import fund_eth
        fund_eth(w3, sender, chunk_wei * 2)

        # Wrap ETH -> WETH via deposit
        w3.eth.send_transaction({
            "from": sender,
            "to": WETH,
            "value": chunk_wei,
        })
        weth.functions.approve(SWAP_ROUTER_02, chunk_wei).transact({"from": sender})
        w3.eth.wait_for_transaction_receipt(
            router.functions.exactInputSingle({
                "tokenIn": WETH,
                "tokenOut": USDC,
                "fee": POOL_FEE,
                "recipient": sender,
                "amountIn": chunk_wei,
                "amountOutMinimum": 0,
                "sqrtPriceLimitX96": 0,
            }).transact({"from": sender})
        )


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_price(actual: float, expected: float, tolerance: float = 0.05) -> bool:
    """Check that *actual* is within *tolerance* (fraction) of *expected*."""
    pct_diff = abs(actual - expected) / expected
    return pct_diff <= tolerance
