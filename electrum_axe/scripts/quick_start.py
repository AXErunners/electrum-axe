import os

from electrum_axe.simple_config import SimpleConfig
from electrum_axe import constants
from electrum_axe.daemon import Daemon
from electrum_axe.storage import WalletStorage
from electrum_axe.wallet import Wallet, create_new_wallet
from electrum_axe.commands import Commands


config = SimpleConfig({"testnet": True})  # to use ~/.electrum-axe/testnet as datadir
constants.set_testnet()  # to set testnet magic bytes
daemon = Daemon(config, listen_jsonrpc=False)
network = daemon.network
assert network.asyncio_loop.is_running()

# get wallet on disk
wallet_dir = os.path.dirname(config.get_wallet_path())
wallet_path = os.path.join(wallet_dir, "test_wallet")
if not os.path.exists(wallet_path):
    create_new_wallet(path=wallet_path)

# open wallet
storage = WalletStorage(wallet_path)
wallet = Wallet(storage)
wallet.start_network(network)

# you can use ~CLI commands by accessing command_runner
command_runner = Commands(config, wallet=None, network=network)
command_runner.wallet = wallet
print("balance", command_runner.getbalance())
print("addr",    command_runner.getunusedaddress())
print("gettx",   command_runner.gettransaction("d8ee577f6b864071c6ccbac1e30d0d19edd6fa9a171be02b85a73fd533f2734d"))

# but you might as well interact with the underlying methods directly
print("balance", wallet.get_balance())
print("addr",    wallet.get_unused_address())
print("gettx",   network.run_from_another_thread(network.get_transaction("d8ee577f6b864071c6ccbac1e30d0d19edd6fa9a171be02b85a73fd533f2734d")))
