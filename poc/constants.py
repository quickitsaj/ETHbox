"""Mainnet contract addresses, ABIs, and storage slots."""

from dataclasses import dataclass


# --- Token addresses ---
USDC = "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48"
WETH = "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2"
DAI = "0x6B175474E89094C44Da98b954EedeAC495271d0F"
USDT = "0xdAC17F958D2ee523a2206206994597C13D831ec7"
WBTC = "0x2260FAC5E5542a773Aa44fBCfeDf7C193bc2C599"

# --- Uniswap V3 ---
SWAP_ROUTER_02 = "0x68b3465833fb72A70ecDF485E0e4C7bD8665Fc45"
POOL_USDC_WETH_030 = "0x8ad599c3A0ff1De082011EFDDc58f1908eb6e6D8"  # 0.3% fee
POOL_FEE = 3000

# --- Chainlink ---
CHAINLINK_ETH_USD = "0x5f4eC3Df9cbd43714FE2740f5E3616155c5b8419"

# --- Storage slots ---
USDC_BALANCE_SLOT = 9
WETH_BALANCE_SLOT = 3


# ---------------------------------------------------------------------------
# Token & pair registry
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Token:
    """An ERC-20 token with metadata needed for Anvil simulation.

    Attributes
    ----------
    symbol : str
        Human-readable ticker (e.g. "USDC").
    address : str
        Checksummed mainnet address.
    decimals : int
        Token decimals (6 for USDC, 18 for WETH, 8 for WBTC).
    balance_slot : int
        Storage slot index for the balance mapping, used by
        ``anvil_setStorageAt`` to inject test balances.
    """

    symbol: str
    address: str
    decimals: int
    balance_slot: int


@dataclass(frozen=True)
class SwapPair:
    """A Uniswap V3 swap pair with pool metadata.

    Attributes
    ----------
    token_in : Token
        The token being sold.
    token_out : Token
        The token being bought.
    pool_address : str
        Checksummed address of the Uniswap V3 pool.
    fee : int
        Pool fee tier in hundredths of a bip (3000 = 0.3%).
    """

    token_in: Token
    token_out: Token
    pool_address: str
    fee: int


# --- Token registry ---
TOKENS = {
    "USDC": Token("USDC", USDC, 6, 9),
    "WETH": Token("WETH", WETH, 18, 3),
    "DAI": Token("DAI", DAI, 18, 2),
    "USDT": Token("USDT", USDT, 6, 2),
    "WBTC": Token("WBTC", WBTC, 8, 0),
}

# --- Swap pair registry ---
PAIRS = {
    "USDC/WETH": SwapPair(TOKENS["USDC"], TOKENS["WETH"], POOL_USDC_WETH_030, 3000),
    "DAI/WETH": SwapPair(TOKENS["DAI"], TOKENS["WETH"], "0xC2e9F25Be6257c210d7Adf0D4Cd6E3E881ba25f8", 3000),
    "WBTC/WETH": SwapPair(TOKENS["WBTC"], TOKENS["WETH"], "0xCBCdF9626bC03E24f779434178A73a0B4bad62eD", 3000),
    "USDT/WETH": SwapPair(TOKENS["USDT"], TOKENS["WETH"], "0x4e68Ccd3E89f51C3074ca5072bbAC773960dFa36", 3000),
}

# --- ABIs (minimal) ---
ERC20_ABI = [
    {
        "name": "approve",
        "type": "function",
        "inputs": [
            {"name": "spender", "type": "address"},
            {"name": "amount", "type": "uint256"},
        ],
        "outputs": [{"name": "", "type": "bool"}],
    },
    {
        "name": "balanceOf",
        "type": "function",
        "inputs": [{"name": "account", "type": "address"}],
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
    },
]

SWAP_ROUTER_ABI = [
    {
        "name": "exactInputSingle",
        "type": "function",
        "inputs": [
            {
                "name": "params",
                "type": "tuple",
                "components": [
                    {"name": "tokenIn", "type": "address"},
                    {"name": "tokenOut", "type": "address"},
                    {"name": "fee", "type": "uint24"},
                    {"name": "recipient", "type": "address"},
                    {"name": "amountIn", "type": "uint256"},
                    {"name": "amountOutMinimum", "type": "uint256"},
                    {"name": "sqrtPriceLimitX96", "type": "uint160"},
                ],
            }
        ],
        "outputs": [{"name": "amountOut", "type": "uint256"}],
    }
]

POOL_ABI = [
    {
        "name": "slot0",
        "type": "function",
        "inputs": [],
        "outputs": [
            {"name": "sqrtPriceX96", "type": "uint160"},
            {"name": "tick", "type": "int24"},
            {"name": "observationIndex", "type": "uint16"},
            {"name": "observationCardinality", "type": "uint16"},
            {"name": "observationCardinalityNext", "type": "uint16"},
            {"name": "feeProtocol", "type": "uint8"},
            {"name": "unlocked", "type": "bool"},
        ],
        "stateMutability": "view",
    },
    {
        "name": "liquidity",
        "type": "function",
        "inputs": [],
        "outputs": [{"name": "", "type": "uint128"}],
        "stateMutability": "view",
    },
]

CHAINLINK_ABI = [
    {
        "name": "latestRoundData",
        "type": "function",
        "inputs": [],
        "outputs": [
            {"name": "roundId", "type": "uint80"},
            {"name": "answer", "type": "int256"},
            {"name": "startedAt", "type": "uint256"},
            {"name": "updatedAt", "type": "uint256"},
            {"name": "answeredInRound", "type": "uint80"},
        ],
        "stateMutability": "view",
    },
    {
        "name": "decimals",
        "type": "function",
        "inputs": [],
        "outputs": [{"name": "", "type": "uint8"}],
        "stateMutability": "view",
    },
]
