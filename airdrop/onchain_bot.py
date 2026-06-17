"""
On-chain Interaction Scripts - Tu dong tuong tac Smart Contract.
Ho tro nhieu mang EVM: Ethereum, BSC, Polygon, Arbitrum, zkSync, Base, Scroll...
"""
import asyncio
import random
from typing import Optional
from datetime import datetime

from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware
from eth_account import Account
from loguru import logger

from airdrop.wallet_manager import WalletManager


# ==================================================
# CAU HINH MANG (RPC Endpoints)
# ==================================================
NETWORKS = {
    # === TIER 1: San lon, thanh khoan cao ===
    "ethereum": {
        "name": "Ethereum Mainnet",
        "rpc": "https://eth.llamarpc.com",
        "chain_id": 1,
        "explorer": "https://etherscan.io/tx/",
        "symbol": "ETH",
    },
    "bsc": {
        "name": "BNB Smart Chain",
        "rpc": "https://bsc-dataseed1.binance.org",
        "chain_id": 56,
        "explorer": "https://bscscan.com/tx/",
        "symbol": "BNB",
        "poa": True,
    },
    "polygon": {
        "name": "Polygon",
        "rpc": "https://polygon-rpc.com",
        "chain_id": 137,
        "explorer": "https://polygonscan.com/tx/",
        "symbol": "POL",
        "poa": True,
    },
    "arbitrum": {
        "name": "Arbitrum One",
        "rpc": "https://arb1.arbitrum.io/rpc",
        "chain_id": 42161,
        "explorer": "https://arbiscan.io/tx/",
        "symbol": "ETH",
    },
    "optimism": {
        "name": "Optimism",
        "rpc": "https://mainnet.optimism.io",
        "chain_id": 10,
        "explorer": "https://optimistic.etherscan.io/tx/",
        "symbol": "ETH",
    },
    "avalanche": {
        "name": "Avalanche C-Chain",
        "rpc": "https://api.avax.network/ext/bc/C/rpc",
        "chain_id": 43114,
        "explorer": "https://snowtrace.io/tx/",
        "symbol": "AVAX",
    },
    # === TIER 2: L2 hot, airdrop potential ===
    "base": {
        "name": "Base",
        "rpc": "https://mainnet.base.org",
        "chain_id": 8453,
        "explorer": "https://basescan.org/tx/",
        "symbol": "ETH",
    },
    "zksync": {
        "name": "zkSync Era",
        "rpc": "https://mainnet.era.zksync.io",
        "chain_id": 324,
        "explorer": "https://explorer.zksync.io/tx/",
        "symbol": "ETH",
    },
    "scroll": {
        "name": "Scroll",
        "rpc": "https://rpc.scroll.io",
        "chain_id": 534352,
        "explorer": "https://scrollscan.com/tx/",
        "symbol": "ETH",
    },
    "linea": {
        "name": "Linea",
        "rpc": "https://rpc.linea.build",
        "chain_id": 59144,
        "explorer": "https://lineascan.build/tx/",
        "symbol": "ETH",
    },
    "blast": {
        "name": "Blast",
        "rpc": "https://rpc.blast.io",
        "chain_id": 81457,
        "explorer": "https://blastscan.io/tx/",
        "symbol": "ETH",
    },
    "mantle": {
        "name": "Mantle",
        "rpc": "https://rpc.mantle.xyz",
        "chain_id": 5000,
        "explorer": "https://mantlescan.xyz/tx/",
        "symbol": "MNT",
    },
    "manta": {
        "name": "Manta Pacific",
        "rpc": "https://pacific-rpc.manta.network/http",
        "chain_id": 169,
        "explorer": "https://pacific-explorer.manta.network/tx/",
        "symbol": "ETH",
    },
    "mode": {
        "name": "Mode Network",
        "rpc": "https://mainnet.mode.network",
        "chain_id": 34443,
        "explorer": "https://explorer.mode.network/tx/",
        "symbol": "ETH",
    },
    # === TIER 3: Chain khac ===
    "fantom": {
        "name": "Fantom",
        "rpc": "https://rpc.ftm.tools",
        "chain_id": 250,
        "explorer": "https://ftmscan.com/tx/",
        "symbol": "FTM",
    },
    "celo": {
        "name": "Celo",
        "rpc": "https://forno.celo.org",
        "chain_id": 42220,
        "explorer": "https://celoscan.io/tx/",
        "symbol": "CELO",
    },
    "gnosis": {
        "name": "Gnosis Chain",
        "rpc": "https://rpc.gnosischain.com",
        "chain_id": 100,
        "explorer": "https://gnosisscan.io/tx/",
        "symbol": "xDAI",
        "poa": True,
    },
    "cronos": {
        "name": "Cronos",
        "rpc": "https://evm.cronos.org",
        "chain_id": 25,
        "explorer": "https://cronoscan.com/tx/",
        "symbol": "CRO",
    },
    "sei": {
        "name": "Sei Network",
        "rpc": "https://evm-rpc.sei-apis.com",
        "chain_id": 1329,
        "explorer": "https://seitrace.com/tx/",
        "symbol": "SEI",
    },
    "taiko": {
        "name": "Taiko",
        "rpc": "https://rpc.mainnet.taiko.xyz",
        "chain_id": 167000,
        "explorer": "https://taikoscan.io/tx/",
        "symbol": "ETH",
    },
}

# Uniswap V2 Router ABI (swap)
UNISWAP_ROUTER_ABI = [
    {
        "name": "swapExactETHForTokens",
        "type": "function",
        "inputs": [
            {"name": "amountOutMin", "type": "uint256"},
            {"name": "path", "type": "address[]"},
            {"name": "to", "type": "address"},
            {"name": "deadline", "type": "uint256"},
        ],
        "outputs": [{"name": "amounts", "type": "uint256[]"}],
    },
    {
        "name": "swapExactTokensForETH",
        "type": "function",
        "inputs": [
            {"name": "amountIn", "type": "uint256"},
            {"name": "amountOutMin", "type": "uint256"},
            {"name": "path", "type": "address[]"},
            {"name": "to", "type": "address"},
            {"name": "deadline", "type": "uint256"},
        ],
        "outputs": [{"name": "amounts", "type": "uint256[]"}],
    },
]

# ERC-20 ABI (approve + transfer)
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
    },
    {
        "name": "transfer",
        "type": "function",
        "inputs": [
            {"name": "to", "type": "address"},
            {"name": "amount", "type": "uint256"},
        ],
        "outputs": [{"name": "", "type": "bool"}],
    },
]


class OnChainBot:
    """
    Bot tuong tac on-chain tu dong:
    - Gui ETH/token giua cac vi
    - Swap token tren DEX (Uniswap-like)
    - Kiem tra so du nhieu vi
    - Chong Sybil: random delay, random amount
    """

    def __init__(self, wallet_manager: WalletManager):
        self.wm = wallet_manager

    def _get_web3(self, network: str) -> Web3:
        """Ket noi RPC theo ten mang."""
        net = NETWORKS.get(network)
        if not net:
            raise ValueError(f"Mang '{network}' khong duoc ho tro. Chon: {list(NETWORKS.keys())}")

        w3 = Web3(Web3.HTTPProvider(net["rpc"]))
        if net.get("poa"):
            w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
        return w3

    async def check_balance(self, wallet_id: int, network: str = "ethereum") -> dict:
        """Kiem tra so du native token (ETH/BNB/MATIC)."""
        wallet = self.wm.get_wallet(wallet_id)
        if not wallet:
            return {"error": f"Khong tim thay vi #{wallet_id}"}

        w3 = self._get_web3(network)
        net = NETWORKS[network]

        try:
            balance_wei = w3.eth.get_balance(wallet["address"])
            balance = w3.from_wei(balance_wei, "ether")
            return {
                "wallet_id": wallet_id,
                "address": wallet["address"],
                "network": net["name"],
                "balance": float(balance),
                "symbol": net["symbol"],
            }
        except Exception as e:
            return {"error": str(e)}

    async def check_all_balances(self, network: str = "ethereum") -> list[dict]:
        """Kiem tra so du tat ca vi tren 1 mang."""
        results = []
        for w in self.wm.wallets:
            result = await self.check_balance(w["id"], network)
            results.append(result)
        return results

    async def send_native(
        self,
        from_wallet_id: int,
        to_address: str,
        amount_ether: float,
        network: str = "ethereum",
    ) -> dict:
        """Gui native token (ETH/BNB) tu 1 vi sang dia chi khac."""
        wallet = self.wm.get_wallet(from_wallet_id)
        if not wallet:
            return {"error": f"Khong tim thay vi #{from_wallet_id}"}

        w3 = self._get_web3(network)
        net = NETWORKS[network]

        try:
            nonce = w3.eth.get_transaction_count(wallet["address"])
            gas_price = w3.eth.gas_price
            amount_wei = w3.to_wei(amount_ether, "ether")

            tx = {
                "nonce": nonce,
                "to": Web3.to_checksum_address(to_address),
                "value": amount_wei,
                "gas": 21000,
                "gasPrice": gas_price,
                "chainId": net["chain_id"],
            }

            signed = w3.eth.account.sign_transaction(tx, wallet["private_key"])
            tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)

            self.wm.update_tx_count(from_wallet_id, network)

            result = {
                "status": "sent",
                "tx_hash": tx_hash.hex(),
                "from": wallet["address"],
                "to": to_address,
                "amount": amount_ether,
                "symbol": net["symbol"],
                "network": net["name"],
                "explorer": f"{net['explorer']}{tx_hash.hex()}",
            }
            logger.success(f"TX sent: {amount_ether} {net['symbol']} on {net['name']}")
            return result

        except Exception as e:
            logger.error(f"TX failed: {e}")
            return {"error": str(e)}

    async def distribute_gas(
        self,
        from_wallet_id: int,
        to_wallet_ids: list[int],
        amount_per_wallet: float,
        network: str = "ethereum",
        random_variance: float = 0.2,
    ) -> list[dict]:
        """
        Phan bo gas tu vi me sang nhieu vi con.
        random_variance: +/- % so tien de chong phat hien (0.2 = +-20%)
        """
        results = []
        for wid in to_wallet_ids:
            target = self.wm.get_wallet(wid)
            if not target:
                continue

            # Random so tien +-20% de chong Sybil
            variance = 1 + random.uniform(-random_variance, random_variance)
            amount = round(amount_per_wallet * variance, 6)

            result = await self.send_native(from_wallet_id, target["address"], amount, network)
            results.append(result)

            # Random delay 5-30 giay giua cac giao dich (chong bot detection)
            delay = random.uniform(5, 30)
            logger.info(f"Cho {delay:.0f}s truoc giao dich tiep...")
            await asyncio.sleep(delay)

        return results

    async def swap_eth_for_token(
        self,
        wallet_id: int,
        router_address: str,
        token_address: str,
        amount_ether: float,
        network: str = "ethereum",
        weth_address: str = "",
    ) -> dict:
        """Swap native token -> ERC20 token tren DEX (Uniswap-like)."""
        wallet = self.wm.get_wallet(wallet_id)
        if not wallet:
            return {"error": f"Khong tim thay vi #{wallet_id}"}

        w3 = self._get_web3(network)
        net = NETWORKS[network]

        try:
            router = w3.eth.contract(
                address=Web3.to_checksum_address(router_address),
                abi=UNISWAP_ROUTER_ABI,
            )

            amount_wei = w3.to_wei(amount_ether, "ether")
            deadline = int(datetime.now().timestamp()) + 300  # 5 phut

            path = [
                Web3.to_checksum_address(weth_address),
                Web3.to_checksum_address(token_address),
            ]

            tx = router.functions.swapExactETHForTokens(
                0,  # amountOutMin (0 = chap nhan bat ky gia nao, can chinh lai cho production)
                path,
                Web3.to_checksum_address(wallet["address"]),
                deadline,
            ).build_transaction({
                "from": wallet["address"],
                "value": amount_wei,
                "nonce": w3.eth.get_transaction_count(wallet["address"]),
                "gasPrice": w3.eth.gas_price,
                "chainId": net["chain_id"],
            })

            # Estimate gas
            tx["gas"] = w3.eth.estimate_gas(tx)

            signed = w3.eth.account.sign_transaction(tx, wallet["private_key"])
            tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)

            self.wm.update_tx_count(wallet_id, network)

            return {
                "status": "swapped",
                "tx_hash": tx_hash.hex(),
                "type": "swap_eth_to_token",
                "amount_in": amount_ether,
                "token_out": token_address,
                "network": net["name"],
                "explorer": f"{net['explorer']}{tx_hash.hex()}",
            }

        except Exception as e:
            logger.error(f"Swap failed: {e}")
            return {"error": str(e)}

    def list_networks(self) -> list[dict]:
        """Liet ke tat ca mang duoc ho tro."""
        return [
            {
                "key": k,
                "name": v["name"],
                "symbol": v["symbol"],
                "chain_id": v["chain_id"],
            }
            for k, v in NETWORKS.items()
        ]
