"""On-chain caveat enforcer contracts for Anvil deployment.

Each enforcer is a minimal smart contract deployed as hand-assembled EVM
bytecode on a local Anvil instance. The contracts expose an `enforce()`
function that reverts if the caveat is violated.

These are simplified versions of the MetaMask Delegation Framework's
CaveatEnforcer contracts, sufficient for validating enforcement logic
without the full framework dependency.

Contract interfaces (Solidity equivalent):
    AllowedTargetsEnforcer:
        enforce(address target, address[] allowed) → reverts if target ∉ allowed

    AllowedMethodsEnforcer:
        enforce(bytes4 selector, bytes4[] allowed) → reverts if selector ∉ allowed

    ValueLimitEnforcer:
        enforce(uint256 amount, uint256 cap) → reverts if amount > cap
"""

from web3 import Web3


# ---------------------------------------------------------------------------
# AllowedTargetsEnforcer
# ---------------------------------------------------------------------------
#
# Solidity equivalent:
#   function enforce(address target, address[] calldata allowed) external pure {
#       for (uint i = 0; i < allowed.length; i++) {
#           if (target == allowed[i]) return;
#       }
#       revert("target not allowed");
#   }
#
# ABI: enforce(address,address[])
# Selector: keccak256("enforce(address,address[])")[:4]

ALLOWED_TARGETS_ENFORCE_SIG = "enforce(address,address[])"


def _build_allowed_targets_bytecode() -> str:
    """Build runtime bytecode for AllowedTargetsEnforcer.

    Calldata layout (ABI-encoded):
      [0:4]    selector
      [4:36]   address target (left-padded to 32 bytes)
      [36:68]  offset to dynamic array (always 0x40 = 64)
      [68:100] array length N
      [100:100+N*32]  array elements (addresses, each 32 bytes)

    Algorithm:
      1. Extract target from calldata[4:36]
      2. Extract array length from calldata[68:100]
      3. Loop: compare target to each element in calldata[100 + i*32]
      4. If match found → STOP (success)
      5. If no match → REVERT
    """
    # We build the bytecode as a sequence of opcodes.
    # For readability, we use an assembler-like approach.
    ops = []

    def push1(val):
        ops.append(f"60{val:02x}")

    def push4(val):
        ops.append(f"63{val:08x}")

    def push32(val):
        ops.append(f"7f{val:064x}")

    def op(name):
        opcodes = {
            "STOP": "00", "ADD": "01", "MUL": "02", "SUB": "03",
            "LT": "10", "GT": "11", "SLT": "12", "SGT": "13",
            "EQ": "14", "ISZERO": "15",
            "CALLDATALOAD": "35", "CALLDATASIZE": "36",
            "POP": "50", "MLOAD": "51", "MSTORE": "52",
            "JUMP": "56", "JUMPI": "57", "JUMPDEST": "5b",
            "DUP1": "80", "DUP2": "81", "DUP3": "82", "DUP4": "83",
            "SWAP1": "90", "SWAP2": "91",
            "RETURN": "f3", "REVERT": "fd",
        }
        ops.append(opcodes[name])

    # --- Function selector check ---
    # Load selector from calldata
    push1(0x00)
    op("CALLDATALOAD")
    push1(0xe0)
    ops.append("1c")  # SHR

    # Compare with enforce(address,address[]) selector
    selector_int = int(Web3.keccak(text=ALLOWED_TARGETS_ENFORCE_SIG)[:4].hex(), 16)
    push4(selector_int)
    op("EQ")

    # If selector doesn't match, revert
    push1(0x0e)  # jump to JUMPDEST at offset 14
    op("JUMPI")
    push1(0x00)
    push1(0x00)
    op("REVERT")

    # JUMPDEST: selector matched
    op("JUMPDEST")  # offset 14 (0x0e)

    # --- Load target address ---
    push1(0x04)      # offset 4 in calldata
    op("CALLDATALOAD")  # target (32 bytes, address is in lower 20)

    # --- Load array length ---
    push1(0x44)      # offset 68 (0x44) in calldata
    op("CALLDATALOAD")  # array length N

    # --- Loop setup ---
    # Stack: [N, target]
    # Counter i = 0
    push1(0x00)      # i = 0
    # Stack: [i, N, target]

    # LOOP_START JUMPDEST
    op("JUMPDEST")   # loop_start

    # Check i < N
    op("DUP2")       # [N, i, N, target]
    op("DUP2")       # [i, N, i, N, target]
    op("LT")         # [i<N, i, N, target]

    # If i >= N (not LT), jump to NOT_FOUND
    op("ISZERO")     # [i>=N, i, N, target]
    # We'll fill in the jump destination later
    # For now, calculate: jump to NOT_FOUND
    push1(0x00)      # placeholder - will be patched
    not_found_push_idx = len(ops) - 1
    op("JUMPI")

    # --- Load allowed[i] ---
    # allowed[i] is at calldata offset: 100 + i * 32 = 0x64 + i * 0x20
    op("DUP1")       # [i, i, N, target]
    push1(0x20)      # [32, i, i, N, target]
    op("MUL")        # [i*32, i, N, target]
    push1(0x64)      # [100, i*32, i, N, target]
    op("ADD")        # [100+i*32, i, N, target]
    op("CALLDATALOAD")  # [allowed[i], i, N, target]

    # Compare target == allowed[i]
    op("DUP4")       # [target, allowed[i], i, N, target]
    op("EQ")         # [target==allowed[i], i, N, target]

    # If match, jump to FOUND
    push1(0x00)      # placeholder
    found_push_idx = len(ops) - 1
    op("JUMPI")

    # Increment i
    push1(0x01)      # [1, i, N, target]
    op("ADD")        # [i+1, N, target]

    # Jump back to LOOP_START
    push1(0x13)      # loop_start offset (19 = 0x13)
    op("JUMP")

    # --- FOUND: target is in the list ---
    found_offset = sum(len(o) // 2 for o in ops)
    op("JUMPDEST")
    # Clean stack and return success (empty return)
    op("POP")        # pop i
    op("POP")        # pop N
    op("POP")        # pop target
    push1(0x00)
    push1(0x00)
    op("RETURN")

    # --- NOT_FOUND: target is not in the list ---
    not_found_offset = sum(len(o) // 2 for o in ops)
    op("JUMPDEST")
    # Clean stack and revert
    op("POP")        # pop i
    op("POP")        # pop N
    op("POP")        # pop target
    push1(0x00)
    push1(0x00)
    op("REVERT")

    # Patch jump destinations
    ops[found_push_idx] = f"60{found_offset:02x}"
    ops[not_found_push_idx] = f"60{not_found_offset:02x}"

    return "".join(ops)


# ---------------------------------------------------------------------------
# AllowedMethodsEnforcer
# ---------------------------------------------------------------------------
#
# Solidity equivalent:
#   function enforce(bytes4 selector, bytes4[] calldata allowed) external pure {
#       for (uint i = 0; i < allowed.length; i++) {
#           if (selector == allowed[i]) return;
#       }
#       revert("method not allowed");
#   }
#
# ABI: enforce(bytes4,bytes4[])
# We reuse the same structure as AllowedTargetsEnforcer but with bytes4.
# Since ABI-encoding pads bytes4 to 32 bytes (right-padded), the bytecode
# is structurally identical — we compare 32-byte slots in both cases.

ALLOWED_METHODS_ENFORCE_SIG = "enforce(bytes4,bytes4[])"


def _build_allowed_methods_bytecode() -> str:
    """Build runtime bytecode for AllowedMethodsEnforcer.

    Same structure as AllowedTargetsEnforcer. ABI encoding pads bytes4
    to 32 bytes, so the comparison logic is identical.
    """
    ops = []

    def push1(val):
        ops.append(f"60{val:02x}")

    def push4(val):
        ops.append(f"63{val:08x}")

    def op(name):
        opcodes = {
            "STOP": "00", "ADD": "01", "MUL": "02",
            "LT": "10", "EQ": "14", "ISZERO": "15",
            "CALLDATALOAD": "35",
            "POP": "50",
            "JUMP": "56", "JUMPI": "57", "JUMPDEST": "5b",
            "DUP1": "80", "DUP2": "81", "DUP4": "83",
            "RETURN": "f3", "REVERT": "fd",
        }
        ops.append(opcodes[name])

    # Selector check
    push1(0x00)
    op("CALLDATALOAD")
    push1(0xe0)
    ops.append("1c")  # SHR
    selector_int = int(Web3.keccak(text=ALLOWED_METHODS_ENFORCE_SIG)[:4].hex(), 16)
    push4(selector_int)
    op("EQ")
    push1(0x0e)
    op("JUMPI")
    push1(0x00)
    push1(0x00)
    op("REVERT")

    # Selector matched
    op("JUMPDEST")  # 0x0e

    # Load first param (bytes4, padded to 32 bytes)
    push1(0x04)
    op("CALLDATALOAD")

    # Load array length
    push1(0x44)
    op("CALLDATALOAD")

    # Loop counter
    push1(0x00)

    # LOOP_START
    op("JUMPDEST")  # 0x13

    op("DUP2")
    op("DUP2")
    op("LT")
    op("ISZERO")
    push1(0x00)  # placeholder for NOT_FOUND
    not_found_push_idx = len(ops) - 1
    op("JUMPI")

    # Load allowed[i]
    op("DUP1")
    push1(0x20)
    op("MUL")
    push1(0x64)
    op("ADD")
    op("CALLDATALOAD")

    # Compare
    op("DUP4")
    op("EQ")
    push1(0x00)  # placeholder for FOUND
    found_push_idx = len(ops) - 1
    op("JUMPI")

    # i++
    push1(0x01)
    op("ADD")
    push1(0x13)
    op("JUMP")

    # FOUND
    found_offset = sum(len(o) // 2 for o in ops)
    op("JUMPDEST")
    op("POP")
    op("POP")
    op("POP")
    push1(0x00)
    push1(0x00)
    op("RETURN")

    # NOT_FOUND
    not_found_offset = sum(len(o) // 2 for o in ops)
    op("JUMPDEST")
    op("POP")
    op("POP")
    op("POP")
    push1(0x00)
    push1(0x00)
    op("REVERT")

    ops[found_push_idx] = f"60{found_offset:02x}"
    ops[not_found_push_idx] = f"60{not_found_offset:02x}"

    return "".join(ops)


# ---------------------------------------------------------------------------
# ValueLimitEnforcer (ERC20TransferAmount equivalent)
# ---------------------------------------------------------------------------
#
# Solidity equivalent:
#   function enforce(uint256 amount, uint256 cap) external pure {
#       if (amount > cap) revert("over cap");
#   }
#
# ABI: enforce(uint256,uint256)

VALUE_LIMIT_ENFORCE_SIG = "enforce(uint256,uint256)"


def _build_value_limit_bytecode() -> str:
    """Build runtime bytecode for ValueLimitEnforcer.

    Calldata layout:
      [0:4]    selector
      [4:36]   uint256 amount
      [36:68]  uint256 cap

    Algorithm:
      1. If amount > cap → REVERT
      2. Else → RETURN (success)
    """
    ops = []

    def push1(val):
        ops.append(f"60{val:02x}")

    def push4(val):
        ops.append(f"63{val:08x}")

    def op(name):
        opcodes = {
            "STOP": "00",
            "GT": "11", "EQ": "14", "ISZERO": "15",
            "CALLDATALOAD": "35",
            "POP": "50",
            "JUMP": "56", "JUMPI": "57", "JUMPDEST": "5b",
            "RETURN": "f3", "REVERT": "fd",
        }
        ops.append(opcodes[name])

    # Selector check
    push1(0x00)
    op("CALLDATALOAD")
    push1(0xe0)
    ops.append("1c")  # SHR
    selector_int = int(Web3.keccak(text=VALUE_LIMIT_ENFORCE_SIG)[:4].hex(), 16)
    push4(selector_int)
    op("EQ")
    push1(0x0e)
    op("JUMPI")
    push1(0x00)
    push1(0x00)
    op("REVERT")

    # Selector matched
    op("JUMPDEST")  # 0x0e

    # Load cap (second param)
    push1(0x24)
    op("CALLDATALOAD")

    # Load amount (first param)
    push1(0x04)
    op("CALLDATALOAD")

    # Check amount > cap
    op("GT")  # (amount > cap) ? 1 : 0

    # If amount > cap, jump to REVERT
    push1(0x00)  # placeholder
    revert_push_idx = len(ops) - 1
    op("JUMPI")

    # amount <= cap: return success
    push1(0x00)
    push1(0x00)
    op("RETURN")

    # amount > cap: revert
    revert_offset = sum(len(o) // 2 for o in ops)
    op("JUMPDEST")
    push1(0x00)
    push1(0x00)
    op("REVERT")

    ops[revert_push_idx] = f"60{revert_offset:02x}"

    return "".join(ops)


# ---------------------------------------------------------------------------
# Deployment helpers
# ---------------------------------------------------------------------------

def _wrap_with_init_code(runtime_hex: str) -> str:
    """Wrap runtime bytecode with init code that deploys it.

    The init code copies the runtime bytecode from code to memory
    and returns it, causing the EVM to store it as the contract code.
    """
    runtime_bytes = bytes.fromhex(runtime_hex)
    runtime_len = len(runtime_bytes)

    if runtime_len > 255:
        # Use PUSH2 for larger bytecodes
        init_hex = (
            f"61{runtime_len:04x}"  # PUSH2 runtime_len
            "600c"                  # PUSH1 12 (init code length)
            "6000"                  # PUSH1 0 (memory dest)
            "39"                    # CODECOPY
            f"61{runtime_len:04x}"  # PUSH2 runtime_len
            "6000"                  # PUSH1 0
            "f3"                    # RETURN
        )
    else:
        init_hex = (
            f"60{runtime_len:02x}"  # PUSH1 runtime_len
            "600a"                  # PUSH1 10 (init code length)
            "6000"                  # PUSH1 0 (memory dest)
            "39"                    # CODECOPY
            f"60{runtime_len:02x}"  # PUSH1 runtime_len
            "6000"                  # PUSH1 0
            "f3"                    # RETURN
        )

    return init_hex + runtime_hex


def deploy_enforcer(w3: Web3, sender: str, runtime_hex: str) -> str:
    """Deploy an enforcer contract and return its address.

    Parameters
    ----------
    w3 : Web3
        Connected web3 instance (Anvil).
    sender : str
        Address to deploy from.
    runtime_hex : str
        Hex-encoded runtime bytecode (no 0x prefix).

    Returns
    -------
    str
        The deployed contract address.
    """
    deploy_data = "0x" + _wrap_with_init_code(runtime_hex)
    tx_hash = w3.eth.send_transaction({
        "from": sender,
        "data": deploy_data,
    })
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
    assert receipt["status"] == 1, "Enforcer deployment failed"
    return receipt["contractAddress"]


def deploy_allowed_targets_enforcer(w3: Web3, sender: str) -> str:
    """Deploy AllowedTargetsEnforcer and return its address."""
    return deploy_enforcer(w3, sender, _build_allowed_targets_bytecode())


def deploy_allowed_methods_enforcer(w3: Web3, sender: str) -> str:
    """Deploy AllowedMethodsEnforcer and return its address."""
    return deploy_enforcer(w3, sender, _build_allowed_methods_bytecode())


def deploy_value_limit_enforcer(w3: Web3, sender: str) -> str:
    """Deploy ValueLimitEnforcer and return its address."""
    return deploy_enforcer(w3, sender, _build_value_limit_bytecode())


# ---------------------------------------------------------------------------
# On-chain enforcement calls
# ---------------------------------------------------------------------------

def call_allowed_targets_enforcer(
    w3: Web3,
    enforcer_address: str,
    target: str,
    allowed: list[str],
    sender: str,
) -> bool:
    """Call the on-chain AllowedTargetsEnforcer.

    Returns True if the target is allowed, raises if reverted.
    """
    selector = Web3.keccak(text=ALLOWED_TARGETS_ENFORCE_SIG)[:4]
    # ABI-encode: address target, address[] allowed
    encoded_target = bytes.fromhex(target[2:].lower().zfill(64))
    # Dynamic array: offset, length, elements
    offset = (64).to_bytes(32, "big")  # offset to array data
    length = len(allowed).to_bytes(32, "big")
    elements = b"".join(
        bytes.fromhex(a[2:].lower().zfill(64)) for a in allowed
    )
    calldata = selector + encoded_target + offset + length + elements

    result = w3.eth.call({
        "from": sender,
        "to": enforcer_address,
        "data": "0x" + calldata.hex(),
    })
    return True


def call_allowed_methods_enforcer(
    w3: Web3,
    enforcer_address: str,
    method_selector: str,
    allowed: list[str],
    sender: str,
) -> bool:
    """Call the on-chain AllowedMethodsEnforcer.

    Returns True if the method is allowed, raises if reverted.
    """
    selector = Web3.keccak(text=ALLOWED_METHODS_ENFORCE_SIG)[:4]
    # ABI-encode: bytes4 method (right-padded to 32), bytes4[] allowed
    method_hex = method_selector[2:] if method_selector.startswith("0x") else method_selector
    # bytes4 is right-padded in ABI encoding
    encoded_method = bytes.fromhex(method_hex.ljust(64, "0"))
    offset = (64).to_bytes(32, "big")
    length = len(allowed).to_bytes(32, "big")
    elements = b"".join(
        bytes.fromhex(
            (a[2:] if a.startswith("0x") else a).ljust(64, "0")
        )
        for a in allowed
    )
    calldata = selector + encoded_method + offset + length + elements

    result = w3.eth.call({
        "from": sender,
        "to": enforcer_address,
        "data": "0x" + calldata.hex(),
    })
    return True


def call_value_limit_enforcer(
    w3: Web3,
    enforcer_address: str,
    amount: int,
    cap: int,
    sender: str,
) -> bool:
    """Call the on-chain ValueLimitEnforcer.

    Returns True if amount <= cap, raises if reverted.
    """
    selector = Web3.keccak(text=VALUE_LIMIT_ENFORCE_SIG)[:4]
    encoded_amount = amount.to_bytes(32, "big")
    encoded_cap = cap.to_bytes(32, "big")
    calldata = selector + encoded_amount + encoded_cap

    result = w3.eth.call({
        "from": sender,
        "to": enforcer_address,
        "data": "0x" + calldata.hex(),
    })
    return True
