"""Anvil fork lifecycle and web3 connection."""

import subprocess
import time
import signal

from web3 import Web3

from .constants import USDC, USDC_BALANCE_SLOT, Token


def start_anvil(rpc_url: str, block: int, port: int = 8545) -> subprocess.Popen:
    """Launch anvil forking mainnet at *block*. Returns the process handle."""
    proc = subprocess.Popen(
        [
            "anvil",
            "--fork-url", rpc_url,
            "--fork-block-number", str(block),
            "--port", str(port),
            "--silent",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    # Wait for RPC to be ready
    w3 = Web3(Web3.HTTPProvider(f"http://127.0.0.1:{port}"))
    for _ in range(30):
        try:
            if w3.is_connected():
                break
        except Exception:
            pass
        time.sleep(0.3)
    else:
        proc.kill()
        raise RuntimeError("Anvil failed to start")
    return proc


def stop_anvil(proc: subprocess.Popen) -> None:
    proc.send_signal(signal.SIGTERM)
    proc.wait(timeout=5)


def connect(port: int = 8545) -> Web3:
    w3 = Web3(Web3.HTTPProvider(f"http://127.0.0.1:{port}"))
    assert w3.is_connected(), "Cannot reach Anvil RPC"
    return w3


def fund_usdc(w3: Web3, address: str, amount: int) -> None:
    """Set *address*'s USDC balance to *amount* (6-decimal raw units)."""
    slot = Web3.solidity_keccak(
        ["uint256", "uint256"],
        [int(address, 16), USDC_BALANCE_SLOT],
    )
    value = "0x" + amount.to_bytes(32, "big").hex()
    w3.provider.make_request("anvil_setStorageAt", [USDC, slot.hex(), value])


def fund_token(w3: Web3, token: Token, address: str, amount: int) -> None:
    """Set *address*'s balance for any token with a known balance slot."""
    slot = Web3.solidity_keccak(
        ["uint256", "uint256"],
        [int(address, 16), token.balance_slot],
    )
    value = "0x" + amount.to_bytes(32, "big").hex()
    w3.provider.make_request("anvil_setStorageAt", [token.address, slot.hex(), value])


def fund_eth(w3: Web3, address: str, wei: int) -> None:
    w3.provider.make_request("anvil_setBalance", [address, hex(wei)])
