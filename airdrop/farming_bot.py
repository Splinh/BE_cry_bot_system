"""
Airdrop Farming Bot - Tu dong tao volume on-chain de farm airdrop.
Ho tro: Swap, Bridge, Claim hang loat cho nhieu vi.
"""
import asyncio
import random
import time
from typing import Optional
from datetime import datetime

from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware
from loguru import logger

from airdrop.wallet_manager import WalletManager
from airdrop.onchain_bot import NETWORKS, ERC20_ABI


# ==================================================
# DEX ROUTERS & BRIDGE CONFIGS
# ==================================================
DEX_CONFIGS = {
    "arbitrum": {
        "uniswap_v3_router": "0xE592427A0AEce92De3Edee1F18E0157C05861564",
        "sushiswap_router": "0x1b02dA8Cb0d097eB8D57A175b88c7D8b47997506",
        "weth": "0x82aF49447D8a07e3bd95BD0d56f35241523fBab1",
        "usdc": "0xaf88d065e77c8cC2239327C5EDb3A432268e5831",
    },
    "base": {
        "uniswap_v3_router": "0x2626664c2603336E57B271c5C0b26F421741e481",
        "weth": "0x4200000000000000000000000000000000000006",
        "usdc": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
    },
    "scroll": {
        "syncswap_router": "0x80e38291e06339d10AAB483C65695D004dBD5C69",
        "weth": "0x5300000000000000000000000000000000000004",
        "usdc": "0x06eFdBFf2a14a7c8E15944D1F4A48F9F95F663A4",
    },
    "zksync": {
        "syncswap_router": "0x2da10A1e27bF85cEdD8FFb1AbBe97e53391C0295",
        "weth": "0x5AEa5775959fBC2557Cc8789bC1bf90A239D9a91",
        "usdc": "0x3355df6D4c9C3035724Fd0e3914dE96A5a83aaf4",
    },
}

# Uniswap V2 Router ABI (simplified)
SWAP_ROUTER_ABI = [
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

# Generic Claim ABI (pho bien nhat)
CLAIM_ABI = [
    {
        "name": "claim",
        "type": "function",
        "inputs": [],
        "outputs": [],
    },
    {
        "name": "claim",
        "type": "function",
        "inputs": [{"name": "amount", "type": "uint256"}, {"name": "proof", "type": "bytes32[]"}],
        "outputs": [],
    },
]


class AirdropFarmer:
    """
    Bot farming airdrop tu dong:
    - Swap ETH <-> USDC tao volume
    - Bridge giua cac chain
    - Claim airdrop tu smart contract bat ky
    - Chong Sybil: random delay, random amount, random order
    """

    def __init__(self, wallet_manager: WalletManager):
        self.wm = wallet_manager
        self.tx_log: list[dict] = []

    def _get_web3(self, network: str) -> Web3:
        net = NETWORKS.get(network)
        if not net:
            raise ValueError(f"Mang '{network}' khong ho tro")
        w3 = Web3(Web3.HTTPProvider(net["rpc"]))
        if net.get("poa"):
            w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
        return w3

    def _random_delay(self, min_sec: int = 10, max_sec: int = 60):
        """Delay ngau nhien chong bot detection."""
        delay = random.uniform(min_sec, max_sec)
        logger.info(f"Cho {delay:.0f}s...")
        return delay

    def _random_amount(self, base_amount: float, variance: float = 0.3) -> float:
        """Random so tien +-30% chong Sybil."""
        factor = 1 + random.uniform(-variance, variance)
        return round(base_amount * factor, 8)
    
    # ==================================================
    # SWAP (Tao volume)
    # ==================================================

    async def swap_eth_to_usdc(
        self,
        wallet_id: int,
        amount_eth: float,
        network: str = "arbitrum",
        slippage: float = 0.05,
    ) -> dict:
        """Swap ETH -> USDC tren DEX."""
        wallet = self.wm.get_wallet(wallet_id)
        if not wallet:
            return {"error": f"Khong tim thay vi #{wallet_id}"}

        dex = DEX_CONFIGS.get(network)
        if not dex:
            return {"error": f"Chua ho tro DEX tren {network}"}

        w3 = self._get_web3(network)
        net = NETWORKS[network]

        try:
            # Random amount +-30%
            actual_amount = self._random_amount(amount_eth)
            amount_wei = w3.to_wei(actual_amount, "ether")

            router_addr = dex.get("uniswap_v3_router") or dex.get("sushiswap_router") or dex.get("syncswap_router")
            if not router_addr:
                return {"error": "Khong tim thay router DEX"}

            router = w3.eth.contract(
                address=Web3.to_checksum_address(router_addr),
                abi=SWAP_ROUTER_ABI,
            )

            path = [
                Web3.to_checksum_address(dex["weth"]),
                Web3.to_checksum_address(dex["usdc"]),
            ]
            deadline = int(time.time()) + 300

            tx = router.functions.swapExactETHForTokens(
                0,  # amountOutMin (set 0 for simplicity; production: calculate properly)
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

            tx["gas"] = w3.eth.estimate_gas(tx)
            signed = w3.eth.account.sign_transaction(tx, wallet["private_key"])
            tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)

            self.wm.update_tx_count(wallet_id, network)

            result = {
                "status": "success",
                "type": "swap_eth_to_usdc",
                "tx_hash": tx_hash.hex(),
                "amount": actual_amount,
                "network": network,
                "wallet_id": wallet_id,
                "explorer": f"{net['explorer']}{tx_hash.hex()}",
            }
            self.tx_log.append(result)
            logger.success(f"Swap {actual_amount} ETH -> USDC on {network} | Wallet #{wallet_id}")
            return result

        except Exception as e:
            logger.error(f"Swap failed: {e}")
            return {"error": str(e), "wallet_id": wallet_id}

    # ==================================================
    # FARMING BATCH (Nhieu vi, nhieu mang)
    # ==================================================

    async def farm_batch(
        self,
        wallet_ids: list[int],
        amount_eth: float = 0.001,
        network: str = "arbitrum",
        rounds: int = 1,
    ) -> dict:
        """
        Farming hang loat: Swap ETH->USDC cho nhieu vi.
        Random delay + random amount + random order.
        """
        results = {"success": 0, "failed": 0, "total_tx": 0, "details": []}

        for round_num in range(rounds):
            logger.info(f"=== Round {round_num + 1}/{rounds} ===")

            # Random thu tu vi (chong Sybil)
            shuffled = wallet_ids.copy()
            random.shuffle(shuffled)

            for wid in shuffled:
                result = await self.swap_eth_to_usdc(wid, amount_eth, network)
                results["total_tx"] += 1
                results["details"].append(result)

                if "error" in result:
                    results["failed"] += 1
                else:
                    results["success"] += 1

                # Random delay 10-60s
                await asyncio.sleep(self._random_delay(10, 60))

        return results

    # ==================================================
    # GENERIC CLAIM (Claim airdrop tu contract bat ky)
    # ==================================================

    async def claim_airdrop(
        self,
        wallet_id: int,
        claim_contract: str,
        network: str = "ethereum",
        claim_abi: list = None,
        function_name: str = "claim",
        args: list = None,
    ) -> dict:
        """
        Claim airdrop tu 1 smart contract bat ky.
        Chi can nhap: contract address, network, function name.
        """
        wallet = self.wm.get_wallet(wallet_id)
        if not wallet:
            return {"error": f"Khong tim thay vi #{wallet_id}"}

        w3 = self._get_web3(network)
        net = NETWORKS[network]

        try:
            # Dung ABI mac dinh neu khong truyen
            abi = claim_abi or [
                {
                    "name": function_name,
                    "type": "function",
                    "inputs": [{"name": a[0], "type": a[1]} for a in (args or [])] if args else [],
                    "outputs": [],
                }
            ]

            contract = w3.eth.contract(
                address=Web3.to_checksum_address(claim_contract),
                abi=abi,
            )

            # Goi function claim
            func = getattr(contract.functions, function_name)
            if args:
                tx = func(*[a[2] for a in args]).build_transaction({
                    "from": wallet["address"],
                    "nonce": w3.eth.get_transaction_count(wallet["address"]),
                    "gasPrice": w3.eth.gas_price,
                    "chainId": net["chain_id"],
                })
            else:
                tx = func().build_transaction({
                    "from": wallet["address"],
                    "nonce": w3.eth.get_transaction_count(wallet["address"]),
                    "gasPrice": w3.eth.gas_price,
                    "chainId": net["chain_id"],
                })

            tx["gas"] = w3.eth.estimate_gas(tx)
            signed = w3.eth.account.sign_transaction(tx, wallet["private_key"])
            tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)

            self.wm.update_tx_count(wallet_id, network)

            result = {
                "status": "claimed",
                "tx_hash": tx_hash.hex(),
                "contract": claim_contract,
                "function": function_name,
                "network": net["name"],
                "wallet_id": wallet_id,
                "explorer": f"{net['explorer']}{tx_hash.hex()}",
            }
            self.tx_log.append(result)
            logger.success(f"Claim OK | Wallet #{wallet_id} on {net['name']}")
            return result

        except Exception as e:
            logger.error(f"Claim failed: {e}")
            return {"error": str(e), "wallet_id": wallet_id}

    async def claim_batch(
        self,
        wallet_ids: list[int],
        claim_contract: str,
        network: str = "ethereum",
        function_name: str = "claim",
    ) -> dict:
        """Claim airdrop hang loat cho nhieu vi."""
        results = {"success": 0, "failed": 0, "details": []}

        shuffled = wallet_ids.copy()
        random.shuffle(shuffled)

        for wid in shuffled:
            result = await self.claim_airdrop(wid, claim_contract, network, function_name=function_name)
            results["details"].append(result)

            if "error" in result:
                results["failed"] += 1
            else:
                results["success"] += 1

            await asyncio.sleep(self._random_delay(15, 90))

        return results

    # ==================================================
    # SELF-TRANSFER (Tao hoat dong giua cac vi)
    # ==================================================

    async def self_transfers(
        self,
        wallet_ids: list[int],
        amount_eth: float = 0.0005,
        network: str = "arbitrum",
    ) -> dict:
        """Gui ETH giua cac vi (tao lich su onchain)."""
        results = {"success": 0, "failed": 0, "details": []}

        pairs = []
        for i in range(len(wallet_ids)):
            j = (i + 1) % len(wallet_ids)
            pairs.append((wallet_ids[i], wallet_ids[j]))
        random.shuffle(pairs)

        w3 = self._get_web3(network)
        net = NETWORKS[network]

        for from_id, to_id in pairs:
            from_wallet = self.wm.get_wallet(from_id)
            to_wallet = self.wm.get_wallet(to_id)
            if not from_wallet or not to_wallet:
                continue

            actual_amount = self._random_amount(amount_eth)
            try:
                nonce = w3.eth.get_transaction_count(from_wallet["address"])
                tx = {
                    "nonce": nonce,
                    "to": Web3.to_checksum_address(to_wallet["address"]),
                    "value": w3.to_wei(actual_amount, "ether"),
                    "gas": 21000,
                    "gasPrice": w3.eth.gas_price,
                    "chainId": net["chain_id"],
                }

                signed = w3.eth.account.sign_transaction(tx, from_wallet["private_key"])
                tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)

                self.wm.update_tx_count(from_id, network)
                self.wm.update_tx_count(to_id, network)

                result = {
                    "status": "sent",
                    "from": from_id,
                    "to": to_id,
                    "amount": actual_amount,
                    "tx_hash": tx_hash.hex(),
                }
                results["success"] += 1
                results["details"].append(result)
                logger.success(f"Transfer #{from_id} -> #{to_id}: {actual_amount} ETH")

            except Exception as e:
                results["failed"] += 1
                results["details"].append({"error": str(e), "from": from_id, "to": to_id})

            await asyncio.sleep(self._random_delay(10, 45))

        return results

    def get_farming_report(self) -> str:
        """Bao cao farming."""
        total = len(self.tx_log)
        success = sum(1 for t in self.tx_log if t.get("status") != "error")
        networks = set(t.get("network", "") for t in self.tx_log)
        return (
            f"Tong TX: {total} | Thanh cong: {success} | "
            f"That bai: {total - success} | Mang: {', '.join(networks)}"
        )
