"""Execute a USDC -> WETH swap through Uniswap V3 SwapRouter02."""

from web3 import Web3

from .constants import (
    USDC, WETH, SWAP_ROUTER_02, POOL_FEE,
    ERC20_ABI, SWAP_ROUTER_ABI,
)


def approve_usdc(w3: Web3, sender: str, amount: int) -> None:
    usdc = w3.eth.contract(address=USDC, abi=ERC20_ABI)
    tx = usdc.functions.approve(SWAP_ROUTER_02, amount).transact({"from": sender})
    w3.eth.wait_for_transaction_receipt(tx)


def swap_usdc_to_weth(w3: Web3, sender: str, amount_usdc: int) -> int:
    """Swap *amount_usdc* (6-decimal raw) for WETH. Returns amountOut in wei."""
    approve_usdc(w3, sender, amount_usdc)

    router = w3.eth.contract(address=SWAP_ROUTER_02, abi=SWAP_ROUTER_ABI)
    params = {
        "tokenIn": USDC,
        "tokenOut": WETH,
        "fee": POOL_FEE,
        "recipient": sender,
        "amountIn": amount_usdc,
        "amountOutMinimum": 0,
        "sqrtPriceLimitX96": 0,
    }

    tx = router.functions.exactInputSingle(params).transact({"from": sender})
    receipt = w3.eth.wait_for_transaction_receipt(tx)
    assert receipt["status"] == 1, "Swap reverted"

    # Read WETH balance to determine output
    weth = w3.eth.contract(address=WETH, abi=ERC20_ABI)
    return weth.functions.balanceOf(sender).call()
