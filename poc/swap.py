"""Execute swaps through Uniswap V3 SwapRouter02."""

from __future__ import annotations

from web3 import Web3

from .constants import (
    USDC, WETH, SWAP_ROUTER_02, POOL_FEE,
    ERC20_ABI, SWAP_ROUTER_ABI, SwapPair,
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


def swap(w3: Web3, sender: str, pair: SwapPair, amount_in: int) -> int:
    """Swap *amount_in* of pair.token_in for pair.token_out.

    Parameters
    ----------
    w3 : Web3
        Connected web3 instance.
    sender : str
        Address executing the swap.
    pair : SwapPair
        The swap pair definition.
    amount_in : int
        Amount of input token in raw units (respecting token decimals).

    Returns
    -------
    int
        Balance of output token after the swap (in raw units).
    """
    token_in = w3.eth.contract(address=pair.token_in.address, abi=ERC20_ABI)
    tx = token_in.functions.approve(SWAP_ROUTER_02, amount_in).transact(
        {"from": sender}
    )
    w3.eth.wait_for_transaction_receipt(tx)

    router = w3.eth.contract(address=SWAP_ROUTER_02, abi=SWAP_ROUTER_ABI)
    tx = router.functions.exactInputSingle({
        "tokenIn": pair.token_in.address,
        "tokenOut": pair.token_out.address,
        "fee": pair.fee,
        "recipient": sender,
        "amountIn": amount_in,
        "amountOutMinimum": 0,
        "sqrtPriceLimitX96": 0,
    }).transact({"from": sender})
    receipt = w3.eth.wait_for_transaction_receipt(tx)
    assert receipt["status"] == 1, "Swap reverted"

    token_out = w3.eth.contract(address=pair.token_out.address, abi=ERC20_ABI)
    return token_out.functions.balanceOf(sender).call()
