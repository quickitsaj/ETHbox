"""Delegation enforcement — validate and execute delegated calls.

Implements the core logic of MetaMask's Delegation Framework in Python:
  - A Delegation ties a delegator to a delegatee with a list of caveats
  - Each caveat is a named enforcer that checks one constraint
  - Before executing a delegated call, all caveats must pass
  - If any caveat fails, the call is rejected

This module provides both off-chain validation (pure Python) and on-chain
execution (via web3 on Anvil) for delegation enforcement.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from web3 import Web3


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Caveat:
    """A single enforcement rule within a delegation.

    Attributes
    ----------
    enforcer : str
        The caveat type name (e.g. "AllowedTargets", "AllowedMethods").
    terms : Any
        The enforcer-specific parameters. Structure depends on the enforcer:
          - AllowedTargets: list[str]  (allowed contract addresses)
          - AllowedMethods: list[str]  (allowed 4-byte selectors, hex)
          - ERC20TransferAmount: dict  {"token": str, "maxAmount": int}
    """

    enforcer: str
    terms: Any


@dataclass(frozen=True)
class Delegation:
    """A delegation from a delegator to a delegatee with enforcement caveats.

    Attributes
    ----------
    delegator : str
        The address that grants the delegation.
    delegatee : str
        The address that may act on behalf of the delegator.
    caveats : tuple[Caveat, ...]
        The enforcement rules that constrain the delegatee's actions.
    """

    delegator: str
    delegatee: str
    caveats: tuple[Caveat, ...] = field(default_factory=tuple)


# ---------------------------------------------------------------------------
# Enforcement errors
# ---------------------------------------------------------------------------

class EnforcementError(Exception):
    """Raised when a caveat enforcement check fails."""

    def __init__(self, enforcer: str, reason: str):
        self.enforcer = enforcer
        self.reason = reason
        super().__init__(f"{enforcer}: {reason}")


# ---------------------------------------------------------------------------
# Individual enforcer functions (off-chain / pure Python)
# ---------------------------------------------------------------------------

def enforce_allowed_targets(target: str, allowed: list[str]) -> None:
    """Check that *target* is in the *allowed* list.

    Raises EnforcementError if the target is not allowed.
    """
    normalized_target = Web3.to_checksum_address(target)
    normalized_allowed = [Web3.to_checksum_address(a) for a in allowed]
    if normalized_target not in normalized_allowed:
        raise EnforcementError(
            "AllowedTargets",
            f"target {normalized_target} not in allowed list "
            f"[{', '.join(normalized_allowed)}]",
        )


def enforce_allowed_methods(calldata: bytes, allowed: list[str]) -> None:
    """Check that the function selector in *calldata* is in the *allowed* list.

    Raises EnforcementError if the selector is not allowed.

    Parameters
    ----------
    calldata : bytes
        The full calldata of the transaction (at least 4 bytes).
    allowed : list[str]
        Hex-encoded 4-byte selectors (with or without 0x prefix).
    """
    if len(calldata) < 4:
        raise EnforcementError(
            "AllowedMethods",
            f"calldata too short ({len(calldata)} bytes, need >= 4)",
        )
    selector = "0x" + calldata[:4].hex()
    normalized_allowed = []
    for a in allowed:
        s = a if a.startswith("0x") else "0x" + a
        normalized_allowed.append(s.lower())
    if selector.lower() not in normalized_allowed:
        raise EnforcementError(
            "AllowedMethods",
            f"selector {selector} not in allowed list "
            f"[{', '.join(normalized_allowed)}]",
        )


def enforce_erc20_transfer_amount(
    amount: int,
    max_amount: int,
    token: str | None = None,
) -> None:
    """Check that *amount* does not exceed *max_amount*.

    Raises EnforcementError if the amount is over the cap.
    """
    if amount > max_amount:
        token_info = f" for token {token}" if token else ""
        raise EnforcementError(
            "ERC20TransferAmount",
            f"amount {amount} exceeds cap {max_amount}{token_info}",
        )


# ---------------------------------------------------------------------------
# Delegation validation (off-chain)
# ---------------------------------------------------------------------------

def validate_delegation(
    delegation: Delegation,
    *,
    caller: str,
    target: str,
    calldata: bytes,
    value: int = 0,
) -> None:
    """Validate that a delegated call satisfies all caveats.

    Parameters
    ----------
    delegation : Delegation
        The delegation to validate.
    caller : str
        The address attempting to use the delegation (must be the delegatee).
    target : str
        The contract address being called.
    calldata : bytes
        The calldata for the call.
    value : int
        The ETH value being sent (in wei).

    Raises
    ------
    EnforcementError
        If any caveat check fails.
    ValueError
        If the caller is not the delegatee.
    """
    # Check caller is the delegatee
    if Web3.to_checksum_address(caller) != Web3.to_checksum_address(delegation.delegatee):
        raise ValueError(
            f"caller {caller} is not the delegatee {delegation.delegatee}"
        )

    # Run each caveat enforcer
    for caveat in delegation.caveats:
        _enforce_caveat(caveat, target=target, calldata=calldata, value=value)


def _enforce_caveat(
    caveat: Caveat,
    *,
    target: str,
    calldata: bytes,
    value: int,
) -> None:
    """Dispatch to the correct enforcer for a single caveat."""
    if caveat.enforcer == "AllowedTargets":
        enforce_allowed_targets(target, caveat.terms)

    elif caveat.enforcer == "AllowedMethods":
        enforce_allowed_methods(calldata, caveat.terms)

    elif caveat.enforcer == "ERC20TransferAmount":
        # For ERC-20 transfers, extract the amount from calldata.
        # approve(address,uint256) and transfer(address,uint256) both
        # encode the amount as the second parameter (bytes 36-68).
        amount = _extract_uint256_param(calldata, param_index=1)
        enforce_erc20_transfer_amount(
            amount=amount,
            max_amount=caveat.terms["maxAmount"],
            token=caveat.terms.get("token"),
        )

    else:
        raise EnforcementError(
            caveat.enforcer,
            f"unknown enforcer type: {caveat.enforcer}",
        )


def _extract_uint256_param(calldata: bytes, param_index: int) -> int:
    """Extract a uint256 parameter from ABI-encoded calldata.

    Parameters
    ----------
    calldata : bytes
        Full calldata (4-byte selector + ABI-encoded params).
    param_index : int
        0-based index of the parameter to extract.

    Returns
    -------
    int
        The decoded uint256 value.
    """
    offset = 4 + param_index * 32
    if len(calldata) < offset + 32:
        raise EnforcementError(
            "ERC20TransferAmount",
            f"calldata too short to extract param at index {param_index}",
        )
    return int.from_bytes(calldata[offset : offset + 32], "big")


# ---------------------------------------------------------------------------
# Delegation creation helpers
# ---------------------------------------------------------------------------

def delegation_from_caveat_map(
    delegator: str,
    delegatee: str,
    caveat_map: dict,
) -> Delegation:
    """Convert a Phase 0 caveat map dict to a Phase 1 Delegation object.

    This bridges the gap between the static dict from caveats.py and the
    structured Delegation used for enforcement.

    Parameters
    ----------
    delegator : str
        Address of the account granting delegation.
    delegatee : str
        Address of the account receiving delegation.
    caveat_map : dict
        Output of usdc_weth_swap_caveats() from caveats.py.

    Returns
    -------
    Delegation
        A Delegation with caveats derived from the caveat map.
    """
    caveats = []

    if "AllowedTargets" in caveat_map:
        caveats.append(Caveat(
            enforcer="AllowedTargets",
            terms=caveat_map["AllowedTargets"],
        ))

    if "AllowedMethods" in caveat_map:
        caveats.append(Caveat(
            enforcer="AllowedMethods",
            terms=caveat_map["AllowedMethods"],
        ))

    if "ERC20TransferAmount" in caveat_map:
        caveats.append(Caveat(
            enforcer="ERC20TransferAmount",
            terms=caveat_map["ERC20TransferAmount"],
        ))

    return Delegation(
        delegator=delegator,
        delegatee=delegatee,
        caveats=tuple(caveats),
    )


# ---------------------------------------------------------------------------
# On-chain delegation execution
# ---------------------------------------------------------------------------

def execute_delegated_call(
    w3: Web3,
    delegation: Delegation,
    *,
    target: str,
    calldata: bytes,
    value: int = 0,
) -> bytes:
    """Validate caveats and execute a delegated call on-chain.

    The call is executed from the delegator's address (simulating the
    delegation framework executing on behalf of the delegator). On Anvil,
    we can impersonate the delegator to achieve this.

    Parameters
    ----------
    w3 : Web3
        Connected web3 instance (must be Anvil).
    delegation : Delegation
        The delegation to execute.
    target : str
        The contract to call.
    calldata : bytes
        The calldata for the call.
    value : int
        ETH value to send (in wei).

    Returns
    -------
    bytes
        The return data from the call.

    Raises
    ------
    EnforcementError
        If any caveat check fails (call is NOT executed).
    """
    # 1. Validate all caveats off-chain first
    validate_delegation(
        delegation,
        caller=delegation.delegatee,
        target=target,
        calldata=calldata,
        value=value,
    )

    # 2. Impersonate the delegator on Anvil
    w3.provider.make_request(
        "anvil_impersonateAccount", [delegation.delegator]
    )

    try:
        # 3. Execute the call as the delegator
        tx_hash = w3.eth.send_transaction({
            "from": delegation.delegator,
            "to": target,
            "data": calldata,
            "value": value,
        })
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
        if receipt["status"] != 1:
            raise RuntimeError(
                f"Delegated call to {target} reverted on-chain"
            )

        # Return receipt for caller inspection
        return receipt

    finally:
        # 4. Stop impersonation
        w3.provider.make_request(
            "anvil_stopImpersonatingAccount", [delegation.delegator]
        )
