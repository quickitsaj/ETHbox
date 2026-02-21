"""Shared pytest fixtures for ETHbox tests.

Provides Anvil lifecycle management and web3 connections for both
local-only tests (no fork) and mainnet fork tests.
"""

import os
import shutil
import signal
import subprocess
import time

import pytest
from web3 import Web3


def _anvil_available() -> bool:
    """Check if anvil is on PATH."""
    return shutil.which("anvil") is not None


def _find_free_port() -> int:
    """Return a free TCP port (OS-assigned)."""
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _start_anvil(args: list[str], port: int, timeout: float = 15.0) -> subprocess.Popen:
    """Start anvil with *args* on *port* and wait until the RPC is reachable."""
    proc = subprocess.Popen(
        ["anvil", "--port", str(port), "--silent"] + args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    w3 = Web3(Web3.HTTPProvider(f"http://127.0.0.1:{port}"))
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if w3.is_connected():
                return proc
        except Exception:
            pass
        time.sleep(0.2)
    proc.kill()
    raise RuntimeError(f"Anvil failed to start on port {port}")


def _stop_anvil(proc: subprocess.Popen) -> None:
    proc.send_signal(signal.SIGTERM)
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


# ---------------------------------------------------------------------------
# Local Anvil (no fork) — fast, deterministic
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def anvil_local():
    """Session-scoped local Anvil (no mainnet fork).

    Yields (web3_instance, port).
    """
    if not _anvil_available():
        pytest.skip("anvil not found on PATH — install Foundry")
    port = _find_free_port()
    proc = _start_anvil([], port)
    w3 = Web3(Web3.HTTPProvider(f"http://127.0.0.1:{port}"))
    yield w3, port
    _stop_anvil(proc)


# ---------------------------------------------------------------------------
# Forked Anvil — requires RPC_URL env var
# ---------------------------------------------------------------------------

DEFAULT_FORK_BLOCK = 19_000_000


@pytest.fixture(scope="session")
def anvil_fork():
    """Session-scoped Anvil forking mainnet at a historical block.

    Requires the RPC_URL environment variable. Tests using this fixture
    are marked as integration tests and are skipped if RPC_URL is not set.

    Yields (web3_instance, port).
    """
    if not _anvil_available():
        pytest.skip("anvil not found on PATH — install Foundry")
    rpc_url = os.environ.get("RPC_URL")
    if not rpc_url:
        pytest.skip("RPC_URL not set — skipping mainnet fork tests")
    port = _find_free_port()
    proc = _start_anvil(
        ["--fork-url", rpc_url, "--fork-block-number", str(DEFAULT_FORK_BLOCK)],
        port,
    )
    w3 = Web3(Web3.HTTPProvider(f"http://127.0.0.1:{port}"))
    yield w3, port
    _stop_anvil(proc)
