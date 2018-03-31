ELECTRUM_VERSION = '2.9.4'   # version of the client package
PROTOCOL_VERSION = '1.0'     # protocol version requested

# The hash of the mnemonic seed must begin with this
SEED_PREFIX      = '01'      # Electrum standard wallet


def seed_prefix(seed_type):
    if seed_type == 'standard':
        return SEED_PREFIX
