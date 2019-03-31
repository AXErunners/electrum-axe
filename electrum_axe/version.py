ELECTRUM_VERSION = '3.2.5.2' # version of the client package
APK_VERSION = '3.2.5.2'      # read by buildozer.spec

PROTOCOL_VERSION = '1.4'     # protocol version requested
PROTOCOL_MIN_VER = '1.2'     # minimum suitable protocol version

# The hash of the mnemonic seed must begin with this
SEED_PREFIX      = '01'      # Standard wallet


def seed_prefix(seed_type):
    if seed_type == 'standard':
        return SEED_PREFIX
