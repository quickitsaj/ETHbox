#!/usr/bin/env python3
"""ETHbox Phase 0 POC — validate the core assumptions.

Run:
    python -m poc.main --rpc-url <MAINNET_RPC> [--block 19000000]

Requires: anvil (foundry) on PATH, web3 pip package.
"""

import argparse
import sys

from .fork import start_anvil, stop_anvil, connect, fund_usdc, fund_eth
from .swap import swap_usdc_to_weth
from .price import read_pool_price, read_chainlink_price, move_pool_price, validate_price
from .caveats import usdc_weth_swap_caveats, print_caveats
from .constants import USDC, WETH, ERC20_ABI

# Historical reference: block 19_000_000 (~Jan 2024), ETH ~$2 400
DEFAULT_BLOCK = 19_000_000
SWAP_AMOUNT_USDC = 10_000  # 10 000 USDC
TARGET_PRICE = 2_600.0     # puppet price target (USD)


def run(rpc_url: str, block: int) -> bool:
    print(f"=== ETHbox Phase 0 POC ===")
    print(f"Forking mainnet at block {block} ...")
    proc = start_anvil(rpc_url, block)
    ok = False

    try:
        w3 = connect()
        sender = w3.eth.accounts[0]

        # ---- 1. Read baseline prices ----
        sqrt_p, pool_price = read_pool_price(w3)
        cl_price = read_chainlink_price(w3)
        print(f"\n[1] Baseline prices at block {block}")
        print(f"    Uniswap pool : ${pool_price:,.2f}")
        print(f"    Chainlink    : ${cl_price:,.2f}")
        print(f"    sqrtPriceX96 : {sqrt_p}")

        # ---- 2. Fund account & execute swap ----
        raw_usdc = SWAP_AMOUNT_USDC * 10**6
        fund_usdc(w3, sender, raw_usdc)
        fund_eth(w3, sender, 10 * 10**18)

        usdc_contract = w3.eth.contract(address=USDC, abi=ERC20_ABI)
        bal_before = usdc_contract.functions.balanceOf(sender).call()
        print(f"\n[2] Swap {SWAP_AMOUNT_USDC:,} USDC -> WETH")
        print(f"    USDC balance before: {bal_before / 1e6:,.2f}")

        weth_out = swap_usdc_to_weth(w3, sender, raw_usdc)
        print(f"    WETH received: {weth_out / 1e18:.6f}")
        implied = SWAP_AMOUNT_USDC / (weth_out / 1e18) if weth_out else 0
        print(f"    Implied price: ${implied:,.2f}")

        # ---- 3. Price puppeteering ----
        print(f"\n[3] Moving pool price toward ${TARGET_PRICE:,.0f} ...")
        new_price = move_pool_price(w3, TARGET_PRICE, sender)
        print(f"    Pool price after move: ${new_price:,.2f}")
        close = validate_price(new_price, TARGET_PRICE, tolerance=0.10)
        print(f"    Within 10% of target? {'YES' if close else 'NO'}")

        # ---- 4. Caveat resolution ----
        caveats = usdc_weth_swap_caveats(
            max_usdc=raw_usdc,
            recipient=sender,
        )
        print_caveats(caveats)

        # ---- GO / NO-GO ----
        swap_ok = weth_out > 0
        price_ok = close
        ok = swap_ok and price_ok
        verdict = "GO" if ok else "NO-GO"

        print(f"=== Verdict: {verdict} ===")
        print(f"    Swap executed successfully : {swap_ok}")
        print(f"    Price puppet within range  : {price_ok}")

    except Exception as exc:
        print(f"\nFATAL: {exc}", file=sys.stderr)
        import traceback; traceback.print_exc()

    finally:
        stop_anvil(proc)

    return ok


def main() -> None:
    parser = argparse.ArgumentParser(description="ETHbox Phase 0 POC")
    parser.add_argument("--rpc-url", required=True, help="Mainnet RPC endpoint")
    parser.add_argument("--block", type=int, default=DEFAULT_BLOCK, help="Fork block")
    args = parser.parse_args()

    success = run(args.rpc_url, args.block)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
