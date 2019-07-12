ELECTRUM_VERSION = '3.3.8'   # version of the client package
APK_VERSION = '3.3.8.0'      # read by buildozer.spec

PROTOCOL_VERSION = '1.4'     # protocol version requested

# The hash of the mnemonic seed must begin with this
SEED_PREFIX      = '01'      # Standard wallet


def seed_prefix(seed_type):
    if seed_type == 'standard':
        return SEED_PREFIX
