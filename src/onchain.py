import logging
import os
from .config import Config

logger = logging.getLogger(__name__)

class OnChainTradingEngine:
    def __init__(self):
        self.enabled = bool(Config.ONCHAIN_ENABLED)
        self.rpc = os.getenv("RPC_URL") or ""
        self.addr = os.getenv("WALLET_ADDRESS") or ""
        self.pk = os.getenv("PRIVATE_KEY") or ""
        self.slippage_bps = int(os.getenv("SLIPPAGE_BPS", "150") or "150")
        self.max_usd = float(os.getenv("MAX_ONCHAIN_USD", "10") or "10")
        self.usdt = os.getenv("USDT_ADDRESS", "0x55d398326f99059fF775485246999027B3197955")
        self.router = os.getenv("DEX_ROUTER", "0x10ED43C718714eb63d5aA57B78B54704E256024E")
        self.whitelist = [x.strip() for x in (os.getenv("WHITELIST_TOKENS", "") or "").split(",") if x.strip()]
        self.web3 = None
        self.router_c = None
        self.erc20_abi = [
            {"constant":True,"inputs":[{"name":"_owner","type":"address"}],"name":"balanceOf","outputs":[{"name":"balance","type":"uint256"}],"type":"function"},
            {"constant":False,"inputs":[{"name":"_spender","type":"address"},{"name":"_value","type":"uint256"}],"name":"approve","outputs":[{"name":"success","type":"bool"}],"type":"function"},
            {"constant":True,"inputs":[{"name":"_owner","type":"address"},{"name":"_spender","type":"address"}],"name":"allowance","outputs":[{"name":"remaining","type":"uint256"}],"type":"function"},
            {"inputs":[],"payable":False,"stateMutability":"nonpayable","type":"constructor"},
            {"anonymous":False,"inputs":[{"indexed":True,"name":"owner","type":"address"},{"indexed":True,"name":"spender","type":"address"},{"indexed":False,"name":"value","type":"uint256"}],"name":"Approval","type":"event"}
        ]
        self.router_abi = [
            {"inputs":[{"internalType":"uint256","name":"amountIn","type":"uint256"},{"internalType":"uint256","name":"amountOutMin","type":"uint256"},{"internalType":"address[]","name":"path","type":"address[]"},{"internalType":"address","name":"to","type":"address"},{"internalType":"uint256","name":"deadline","type":"uint256"}],"name":"swapExactTokensForTokens","outputs":[{"internalType":"uint256[]","name":"amounts","type":"uint256[]"}],"stateMutability":"nonpayable","type":"function"},
            {"inputs":[{"internalType":"uint256","name":"amountIn","type":"uint256"},{"internalType":"address[]","name":"path","type":"address[]"}],"name":"getAmountsOut","outputs":[{"internalType":"uint256[]","name":"amounts","type":"uint256[]"}],"stateMutability":"view","type":"function"}
        ]
        try:
            from web3 import Web3
            self.web3 = Web3(Web3.HTTPProvider(self.rpc)) if (self.enabled and self.rpc) else None
            if self.web3:
                self.router_c = self.web3.eth.contract(address=self.web3.to_checksum_address(self.router), abi=self.router_abi)
        except Exception as e:
            self.web3 = None
            self.router_c = None
            self.enabled = False

    def _token_c(self, address):
        return self.web3.eth.contract(address=self.web3.to_checksum_address(address), abi=self.erc20_abi)

    def _get_decimals(self, address):
        try:
            erc = self._token_c(address)
            fn = erc.functions
            try:
                return erc.functions.decimals().call()
            except Exception:
                return 18
        except Exception:
            return 18

    def _fetch_balance(self, address):
        try:
            erc = self._token_c(address)
            bal = erc.functions.balanceOf(self.web3.to_checksum_address(self.addr)).call()
            return int(bal or 0)
        except Exception:
            return 0

    def _allow(self, token, amount):
        try:
            erc = self._token_c(token)
            cur = erc.functions.allowance(self.web3.to_checksum_address(self.addr), self.web3.to_checksum_address(self.router)).call()
            if cur >= amount:
                return True
            tx = erc.functions.approve(self.web3.to_checksum_address(self.router), amount).build_transaction({
                'from': self.web3.to_checksum_address(self.addr),
                'nonce': self.web3.eth.get_transaction_count(self.web3.to_checksum_address(self.addr)),
                'gasPrice': self.web3.eth.gas_price
            })
            signed = self.web3.eth.account.sign_transaction(tx, self.pk)
            txh = self.web3.eth.send_raw_transaction(signed.rawTransaction)
            self.web3.eth.wait_for_transaction_receipt(txh, timeout=180)
            return True
        except Exception:
            return False

    def _quote_out(self, amount_in, path):
        try:
            return self.router_c.functions.getAmountsOut(amount_in, [self.web3.to_checksum_address(x) for x in path]).call()
        except Exception:
            return None

    def buy_token_usdt(self, token_address, usd_amount):
        if not self.enabled or not self.web3 or not self.router_c:
            return None
        if token_address not in self.whitelist:
            return None
        try:
            bal_token_before = self._fetch_balance(token_address)
            usdt_dec = self._get_decimals(self.usdt)
            token_dec = self._get_decimals(token_address)
            amt_in = int(float(usd_amount) * (10 ** usdt_dec))
            bal = self._fetch_balance(self.usdt)
            if bal < amt_in:
                return None
            q = self._quote_out(amt_in, [self.usdt, token_address])
            if not q or len(q) < 2:
                return None
            out_min = int(q[-1] * (10000 - self.slippage_bps) / 10000)
            if not self._allow(self.usdt, amt_in):
                return None
            tx = self.router_c.functions.swapExactTokensForTokens(amt_in, out_min, [self.web3.to_checksum_address(self.usdt), self.web3.to_checksum_address(token_address)], self.web3.to_checksum_address(self.addr), int(self.web3.eth.get_block('latest').timestamp + 900)).build_transaction({
                'from': self.web3.to_checksum_address(self.addr),
                'nonce': self.web3.eth.get_transaction_count(self.web3.to_checksum_address(self.addr)),
                'gasPrice': self.web3.eth.gas_price
            })
            signed = self.web3.eth.account.sign_transaction(tx, self.pk)
            txh = self.web3.eth.send_raw_transaction(signed.rawTransaction)
            receipt = self.web3.eth.wait_for_transaction_receipt(txh, timeout=300)
            bal_token_after = self._fetch_balance(token_address)
            received = max(0, bal_token_after - bal_token_before)
            return {'hash': txh.hex(), 'status': receipt.status, 'received_wei': received, 'decimals': token_dec, 'cost_usdt': float(usd_amount)}
        except Exception as e:
            return None

    def sell_token_to_usdt(self, token_address, percent):
        if not self.enabled or not self.web3 or not self.router_c:
            return None
        if token_address not in self.whitelist:
            return None
        try:
            token_dec = self._get_decimals(token_address)
            usdt_dec = self._get_decimals(self.usdt)
            bal_usdt_before = self._fetch_balance(self.usdt)
            bal = self._fetch_balance(token_address)
            amt_in = int(bal * max(0.0, min(1.0, float(percent))))
            if amt_in <= 0:
                return None
            q = self._quote_out(amt_in, [token_address, self.usdt])
            if not q or len(q) < 2:
                return None
            out_min = int(q[-1] * (10000 - self.slippage_bps) / 10000)
            if not self._allow(token_address, amt_in):
                return None
            tx = self.router_c.functions.swapExactTokensForTokens(amt_in, out_min, [self.web3.to_checksum_address(token_address), self.web3.to_checksum_address(self.usdt)], self.web3.to_checksum_address(self.addr), int(self.web3.eth.get_block('latest').timestamp + 900)).build_transaction({
                'from': self.web3.to_checksum_address(self.addr),
                'nonce': self.web3.eth.get_transaction_count(self.web3.to_checksum_address(self.addr)),
                'gasPrice': self.web3.eth.gas_price
            })
            signed = self.web3.eth.account.sign_transaction(tx, self.pk)
            txh = self.web3.eth.send_raw_transaction(signed.rawTransaction)
            receipt = self.web3.eth.wait_for_transaction_receipt(txh, timeout=300)
            bal_usdt_after = self._fetch_balance(self.usdt)
            recv_usdt_wei = max(0, bal_usdt_after - bal_usdt_before)
            recv_usdt = float(recv_usdt_wei) / float(10 ** usdt_dec)
            return {'hash': txh.hex(), 'status': receipt.status, 'sold_wei': amt_in, 'decimals': token_dec, 'received_usdt': recv_usdt}
        except Exception:
            return None
