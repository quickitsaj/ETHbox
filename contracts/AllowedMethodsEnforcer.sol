// SPDX-License-Identifier: Apache-2.0
pragma solidity ^0.8.20;

/**
 * @title AllowedMethodsEnforcer
 * @notice Reverts if the function selector is not in the allowed list.
 *
 * This is a simplified reference implementation of the MetaMask Delegation
 * Framework's AllowedMethodsEnforcer. The hand-assembled EVM bytecode in
 * poc/enforcers.py implements the same logic.
 *
 * @dev The selector is the first 4 bytes of the calldata. In ABI encoding,
 *      bytes4 values are right-padded to 32 bytes.
 */
contract AllowedMethodsEnforcer {
    error MethodNotAllowed(bytes4 selector);

    /**
     * @notice Check that `selector` is in the `allowed` list.
     * @param selector The 4-byte function selector from the calldata.
     * @param allowed  The list of permitted function selectors.
     */
    function enforce(bytes4 selector, bytes4[] calldata allowed) external pure {
        for (uint256 i = 0; i < allowed.length; i++) {
            if (selector == allowed[i]) {
                return;
            }
        }
        revert MethodNotAllowed(selector);
    }
}
