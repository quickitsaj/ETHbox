"""MetaMask Delegation Toolkit — caveat resolution and enforcement.

Maps a high-level delegation intent ("allow USDC->WETH swap up to N USDC")
to the concrete caveat list that CaveatBuilder would produce, and enforces
those constraints against actual transactions before they execute.

Caveat types:
  - AllowedTargets  -> [USDC, SwapRouter02]
  - AllowedMethods  -> [approve(address,uint256), exactInputSingle((...))]
  - ERC20TransferAmount -> cap on USDC spend
  - SwapConstraints -> token pair / fee / recipient restrictions
"""

from __future__ import annotations

from web3 import Web3

from .constants import USDC, WETH, SWAP_ROUTER_02, POOL_FEE

# Function selectors (first 4 bytes of keccak)
APPROVE_SELECTOR = Web3.keccak(text="approve(address,uint256)")[:4].hex()
EXACT_INPUT_SINGLE_SELECTOR = Web3.keccak(
    text="exactInputSingle((address,address,uint24,address,uint256,uint256,uint160))"
)[:4].hex()


# ---------------------------------------------------------------------------
# Caveat resolution (building the constraint map)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Caveat enforcement — validate transactions against the constraint map
# ---------------------------------------------------------------------------

class CaveatViolation(Exception):
    """Raised when a transaction violates a caveat constraint."""


class CaveatEnforcer:
    """Stateful enforcer that tracks cumulative spend against a caveat map.

    Mirrors the on-chain CaveatEnforcer pattern: each call to
    :meth:`enforce` checks the proposed action against AllowedTargets,
    AllowedMethods, ERC20TransferAmount, and SwapConstraints, and
    accumulates spend toward the cap.
    """

    def __init__(self, caveats: dict) -> None:
        self._caveats = caveats
        self._spent: int = 0  # cumulative token spend (raw units)

    # -- read-only accessors --------------------------------------------------

    @property
    def caveats(self) -> dict:
        return self._caveats

    @property
    def spent(self) -> int:
        return self._spent

    @property
    def remaining(self) -> int:
        cap = self._caveats["ERC20TransferAmount"]["maxAmount"]
        return max(0, cap - self._spent)

    # -- enforcement ----------------------------------------------------------

    def enforce(
        self,
        target: str,
        selector: str,
        value: int = 0,
        swap_params: dict | None = None,
    ) -> None:
        """Validate a single proposed execution step.

        Parameters
        ----------
        target : str
            Contract address being called (checksummed or lower).
        selector : str
            4-byte hex selector of the function being called.
        value : int
            Token amount for ERC20TransferAmount enforcement (raw units).
            Pass 0 for calls that don't transfer the capped token.
        swap_params : dict, optional
            If calling exactInputSingle, the params dict to validate
            against SwapConstraints.

        Raises
        ------
        CaveatViolation
            If any caveat check fails.
        """
        self._check_target(target)
        self._check_method(selector)
        if value > 0:
            self._check_spend(value)
        if swap_params is not None:
            self._check_swap(swap_params)

    # -- private checks -------------------------------------------------------

    def _check_target(self, target: str) -> None:
        allowed = self._caveats["AllowedTargets"]
        if target.lower() not in (t.lower() for t in allowed):
            raise CaveatViolation(
                f"Target {target} not in AllowedTargets {allowed}"
            )

    def _check_method(self, selector: str) -> None:
        allowed = self._caveats["AllowedMethods"]
        sel = selector.lower().replace("0x", "")
        if sel not in (s.lower().replace("0x", "") for s in allowed):
            raise CaveatViolation(
                f"Method selector {selector} not in AllowedMethods {allowed}"
            )

    def _check_spend(self, amount: int) -> None:
        cap = self._caveats["ERC20TransferAmount"]["maxAmount"]
        if self._spent + amount > cap:
            raise CaveatViolation(
                f"Spend {self._spent + amount} exceeds cap {cap} "
                f"(already spent {self._spent})"
            )
        self._spent += amount

    def _check_swap(self, params: dict) -> None:
        sc = self._caveats["SwapConstraints"]
        for field in ("tokenIn", "tokenOut", "fee", "recipient"):
            expected = sc[field]
            actual = params.get(field)
            if isinstance(expected, str) and isinstance(actual, str):
                if expected.lower() != actual.lower():
                    raise CaveatViolation(
                        f"SwapConstraints.{field}: expected {expected}, "
                        f"got {actual}"
                    )
            elif actual != expected:
                raise CaveatViolation(
                    f"SwapConstraints.{field}: expected {expected}, "
                    f"got {actual}"
                )


# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------

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
