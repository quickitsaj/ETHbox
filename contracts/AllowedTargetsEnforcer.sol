// SPDX-License-Identifier: Apache-2.0
pragma solidity ^0.8.20;

/**
 * @title AllowedTargetsEnforcer
 * @notice Reverts if the target address is not in the allowed list.
 *
 * This is a simplified reference implementation of the MetaMask Delegation
 * Framework's AllowedTargetsEnforcer. The hand-assembled EVM bytecode in
 * poc/enforcers.py implements the same logic.
 *
 * @dev In the full MetaMask framework, this would be a CaveatEnforcer
 *      called by the DelegationManager during delegation redemption.
 *      Here we expose a standalone enforce() for direct testing.
 */
contract AllowedTargetsEnforcer {
    error TargetNotAllowed(address target);

    /**
     * @notice Check that `target` is in the `allowed` list.
     * @param target  The contract address being called by the delegatee.
     * @param allowed The list of permitted contract addresses.
     */
    function enforce(address target, address[] calldata allowed) external pure {
        for (uint256 i = 0; i < allowed.length; i++) {
            if (target == allowed[i]) {
                return;
            }
        }
        revert TargetNotAllowed(target);
    }
}
