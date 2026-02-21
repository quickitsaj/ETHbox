"""MetaMask Delegation Toolkit — caveat resolution mapping.

Maps a high-level delegation intent ("allow USDC->WETH swap up to N USDC")
to the concrete caveat list that CaveatBuilder would produce:
  - AllowedTargets  -> [USDC, SwapRouter02]
  - AllowedMethods  -> [approve(address,uint256), exactInputSingle((...))]
  - ERC20TransferAmount -> cap on USDC spend
"""

from __future__ import annotations

from web3 import Web3

from .constants import USDC, WETH, SWAP_ROUTER_02, POOL_FEE, SwapPair

# Function selectors (first 4 bytes of keccak)
APPROVE_SELECTOR = Web3.keccak(text="approve(address,uint256)")[:4].hex()
EXACT_INPUT_SINGLE_SELECTOR = Web3.keccak(
    text="exactInputSingle((address,address,uint24,address,uint256,uint256,uint160))"
)[:4].hex()


def usdc_weth_swap_caveats(max_usdc: int, recipient: str) -> dict:
    """Return the caveat map for a delegated USDC->WETH swap.

    Parameters
    ----------
    max_usdc : int
        Maximum USDC amount in 6-decimal raw units.
    recipient : str
        Address that will receive the WETH output.

    Returns
    -------
    dict with keys matching MetaMask DelegationFramework caveat types.
    """
    return {
        "AllowedTargets": [USDC, SWAP_ROUTER_02],
        "AllowedMethods": [APPROVE_SELECTOR, EXACT_INPUT_SINGLE_SELECTOR],
        "ERC20TransferAmount": {
            "token": USDC,
            "maxAmount": max_usdc,
        },
        "SwapConstraints": {
            "tokenIn": USDC,
            "tokenOut": WETH,
            "fee": POOL_FEE,
            "recipient": recipient,
        },
    }


def swap_caveats(pair: SwapPair, max_amount_in: int, recipient: str) -> dict:
    """Return the caveat map for a delegated swap on any supported pair.

    Parameters
    ----------
    pair : SwapPair
        The swap pair definition (token_in, token_out, pool, fee).
    max_amount_in : int
        Maximum input token amount in raw units (respecting token decimals).
    recipient : str
        Address that will receive the output token.

    Returns
    -------
    dict with keys matching MetaMask DelegationFramework caveat types.
    """
    return {
        "AllowedTargets": [pair.token_in.address, SWAP_ROUTER_02],
        "AllowedMethods": [APPROVE_SELECTOR, EXACT_INPUT_SINGLE_SELECTOR],
        "ERC20TransferAmount": {
            "token": pair.token_in.address,
            "maxAmount": max_amount_in,
        },
        "SwapConstraints": {
            "tokenIn": pair.token_in.address,
            "tokenOut": pair.token_out.address,
            "fee": pair.fee,
            "recipient": recipient,
        },
    }


def print_caveats(caveats: dict) -> None:
    """Pretty-print a caveat resolution map."""
    print("\n--- Caveat Resolution Map ---")
    for caveat_type, value in caveats.items():
        if isinstance(value, list):
            items = ", ".join(str(v) for v in value)
            print(f"  {caveat_type}: [{items}]")
        elif isinstance(value, dict):
            print(f"  {caveat_type}:")
            for k, v in value.items():
                print(f"    {k}: {v}")
        else:
            print(f"  {caveat_type}: {value}")
    print()
