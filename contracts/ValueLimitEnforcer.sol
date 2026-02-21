// SPDX-License-Identifier: Apache-2.0
pragma solidity ^0.8.20;

/**
 * @title ValueLimitEnforcer
 * @notice Reverts if the amount exceeds the cap.
 *
 * This is a simplified reference implementation equivalent to the MetaMask
 * Delegation Framework's ERC20TransferAmountEnforcer. The hand-assembled
 * EVM bytecode in poc/enforcers.py implements the same logic.
 *
 * @dev In the full framework, this enforcer would also track cumulative
 *      spend across multiple redemptions. This simplified version only
 *      checks a single call's amount against a static cap.
 */
contract ValueLimitEnforcer {
    error AmountExceedsCap(uint256 amount, uint256 cap);

    /**
     * @notice Check that `amount` does not exceed `cap`.
     * @param amount The value being transferred or approved.
     * @param cap    The maximum allowed value.
     */
    function enforce(uint256 amount, uint256 cap) external pure {
        if (amount > cap) {
            revert AmountExceedsCap(amount, cap);
        }
    }
}
