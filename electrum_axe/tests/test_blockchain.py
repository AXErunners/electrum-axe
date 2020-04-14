import shutil
import tempfile
import os

from electrum_axe import constants, blockchain
from electrum_axe.simple_config import SimpleConfig
from electrum_axe.blockchain import Blockchain, deserialize_header, hash_header
from electrum_axe.util import bh2u, bfh, make_dir

from . import SequentialTestCase


class TestBlockchain(SequentialTestCase):

    HEADERS = {
        'A': deserialize_header(bfh("010000000000000000000000000000000000000000000000000000000000000000000000aca7c2e70971cc949b615f61a6326e33a43cc7ffcdec1a7ff4047f1dc3087a989051385ef0ff0f1ed44f7ae6"), 0),
        'B': deserialize_header(bfh("0000002083b4ef4c5fc5ae5c20ac44bf4b3b62d4c9a6abd3719ce8c57b2e6609b70500006c7c0c195ebcd8b904453eb31537477e804b1014ce2366a3617860d6a31da892a352385ef0ff0f1e38770000"), 1),
        'C': deserialize_header(bfh("000000209a097e26b999e21d3f7173836552a4f3b12c76def5c4674bfce07baead0e0000600c9b402e86e1a91bbb24eec0a62ff69afd4ef9ae8a7ecd5de132da3d4b5710e253385effff0f1e0d8e0000"), 2),
        'D': deserialize_header(bfh("00000020bd8302f4c75d6207dbb1982826091e3c2ad1836360eb3fac8f16125d8a0f0000106a4406d626cdfb2d8807058287fbe49c6c21d5eb8761c56a79d29054eafc2f916d385effff0f1e000de7cb"), 3),
        'E': deserialize_header(bfh("00000020ac98be90713adcce99c6b5484e66dce25420e834a53b925396c382e1cf040000e35b2b487795323e640aedff17024b592f94865c92c9d9c362ae618f56e3fccfac6d385ef0ff0f1eaabcca8f"), 4),
        'F': deserialize_header(bfh("00000020825cfbd36e6dd40ae0c52df52cce47898f4bb9247621ad819aca4137d6070000e5e7b1d58761c60afd2beaa5c7b8de8b49f8233bd8d3edfb0930feeae606e62cc26d385ef0ff0f1eaab2908f"), 5),
        'O': deserialize_header(bfh("00000020995ce2652c55567e4b7ceac408d57764b6e75948dfc12256dff2d9ad5a0f0000c66e1768b75ad73592fbb584f1726ab9203b82197c28ea55cc0e992b6d6a36f9cb6d385ef0ff0f1eaaaedb75"), 6),
        'P': deserialize_header(bfh("00000020fd1f4ec30860b4c15e9213dd3979e00d3f19a34131d3bbc69fa515d3ac0000008e231ba3bc30e55f821c071e1700445f14d5c8ad4edac5fc91b1b0c437853d29d16d385ef0ff0f1eaab7fbf3"), 7),
        'Q': deserialize_header(bfh("00000020e326011781b343c81e31e702efff52f1ef0db3c5fb0ecbe9f57331f4800f00006c7847ab068e83c931ad752a73da624e8cae92724247511beaf57e55d62fa18ae16d385ef0ff0f1eaaab5b47"), 8),
        'R': deserialize_header(bfh("00000020e003eecfc512cd949136aebde407b12c1d99b73855dc0382c6b2115f530400006d2cd145e9acd64d5618f252ff261bad918051a2a3f55c3cba3a41cdb2cdfe87e26d385ef0ff0f1e55574140"), 9),
        'S': deserialize_header(bfh("00000020c9bd5055b8d142c126466b5def3276c830632745b6e4bd0d0ca732bd3b0c0000a3618b7be95fbc853e406fbd100f4e45438d48f3f51c6b549cb28125ee35f7c4986e385ef0ff0f1eaab438e8"), 10),
        'T': deserialize_header(bfh("000000205b69b32ba48d79201b24f6501200cd8a22440c4f4ece2314abfb738af40f000005691ed0046cfb6b602259891747557c39b8446026a7047ed4f0886eea7d811ea56e385ef0ff0f1e00016584"), 11),
        'U': deserialize_header(bfh("00000020cdd0b0c1b57ca92182192e3f73c51e4a4a1a8c04f9b93f7a5bffffdb970a0000ef427a3e32bcca46f8a72338e5aed5e612230a3f0e92d7f33d5ff420c8717b25a76e385ef0ff0f1e555e4b02"), 12),
        'G': deserialize_header(bfh("00000020ed0bfee047765d7f4233106a13b4ff6d6c67f7ef9aec0e7466759f00ea74b2613a141ce635cbb1cd2b3a4fcdd0a3380517845ba41736c82a79cab535d31128066928f45bffff7f2001000000"), 6),
        'H': deserialize_header(bfh("00000020f8ca2216e002361e7cc1dd3e1197443e0b8068adaeec43d14be0e4f2159659e39690c2fe7c1a4450c74dc908fe94dd96c3b0637d51475e9e06a78e944a0c7fe26a28f45bffff7f2002000000"), 7),
        'I': deserialize_header(bfh("00000020996b8b880bfe34b81dda59ae28ee28625a4dff565f671540a4703ebabd0ab991148be228a4c3f2061bafe7efdfc4a8d5a94759464b9b5c619994d45dfcaf49e16a28f45bffff7f2000000000"), 8),
        'J': deserialize_header(bfh("000000201d5a4dfeeda94c6e4c3e40ce5c30df07e8103dba70cbce9d6b0890405c76b06715681cb2d00ff889193f6a68a93f5096aeb2d84ca0af6185a462555822552221c928f45bffff7f2000000000"), 9),
        'K': deserialize_header(bfh("00000020f93c46944a529187faae721951e66e187a0e910104e91ec8d1d4a914cadd79a89dc087fc977b06c24a69c682d1afd1020e6dc1f087571ccec66310a786e1548fca28f45bffff7f2000000000"), 10),
        'L': deserialize_header(bfh("00000020d76bdf59ed1ce4a4a31aa7649f8a39da2b956515f3bdb78b2bcdaaed60444bad03b243756c25053253aeda309604363460a3911015929e68705bd89dff6fe064ca28f45bffff7f2000000000"), 11),
        'M': deserialize_header(bfh("000000201d5a4dfeeda94c6e4c3e40ce5c30df07e8103dba70cbce9d6b0890405c76b06715681cb2d00ff889193f6a68a93f5096aeb2d84ca0af6185a4625558225522214229f45bffff7f2000000000"), 9),
        'N': deserialize_header(bfh("00000020ff8ef64ad77c7c02103127be41dc39dda5f4dd17cbbaa7475fa8b7a3dd110ee19dc087fc977b06c24a69c682d1afd1020e6dc1f087571ccec66310a786e1548f4329f45bffff7f2003000000"), 10),
        'X': deserialize_header(bfh("000000202857b96792f630a80f7c834afd5985b833794037930c1fe655c23b6eb769c85203b243756c25053253aeda309604363460a3911015929e68705bd89dff6fe0649b29f45bffff7f2002000000"), 11),
        'Y': deserialize_header(bfh("000000206cc9a0dec93cffaab358ef9bd06fa0137d53e37a4b251f57da831ef31fccf9f2d67cb902a7d807cee7676cb543feec3e053aa824d5dfb528d5b94f9760313d9d9b29f45bffff7f2000000000"), 12),
        'Z': deserialize_header(bfh("00000020756a6bfe58694141de4abf3317bccfa105b5ec30b997dda15a9ab02a9d86eba00f2596c29203f8a0f71ae94193092dc8f113be3dbee4579f1e649fa3d6dcc38c622ef45bffff7f2003000000"), 13),
    }
    # tree of headers:
    #                                            - M <- N <- X <- Y <- Z
    #                                          /
    #                             - G <- H <- I <- J <- K <- L
    #                           /
    # A <- B <- C <- D <- E <- F <- O <- P <- Q <- R <- S <- T <- U

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        constants.set_testnet()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        constants.set_mainnet()

    def setUp(self):
        super().setUp()
        self.data_dir = tempfile.mkdtemp()
        make_dir(os.path.join(self.data_dir, 'forks'))
        self.config = SimpleConfig({'electrum_path': self.data_dir})
        blockchain.blockchains = {}

    def tearDown(self):
        super().tearDown()
        shutil.rmtree(self.data_dir)

    def _append_header(self, chain: Blockchain, header: dict):
        self.assertTrue(chain.can_connect(header))
        chain.save_header(header)

    def test_get_height_of_last_common_block_with_chain(self):
        blockchain.blockchains[constants.net.GENESIS] = chain_u = Blockchain(
            config=self.config, forkpoint=0, parent=None,
            forkpoint_hash=constants.net.GENESIS, prev_hash=None)
        #print(chain_u)
        #print(self.HEADERS['A'])
        open(chain_u.path(), 'w+').close()
        self._append_header(chain_u, self.HEADERS['A'])
        self._append_header(chain_u, self.HEADERS['B'])
        self._append_header(chain_u, self.HEADERS['C'])
        self._append_header(chain_u, self.HEADERS['D'])
        self._append_header(chain_u, self.HEADERS['E'])
        self._append_header(chain_u, self.HEADERS['F'])
        self._append_header(chain_u, self.HEADERS['O'])
        self._append_header(chain_u, self.HEADERS['P'])
        self._append_header(chain_u, self.HEADERS['Q'])
'''
        chain_l = chain_u.fork(self.HEADERS['G'])
        self._append_header(chain_l, self.HEADERS['H'])
        self._append_header(chain_l, self.HEADERS['I'])
        self._append_header(chain_l, self.HEADERS['J'])
        self._append_header(chain_l, self.HEADERS['K'])
        self._append_header(chain_l, self.HEADERS['L'])

        self.assertEqual({chain_u:  8, chain_l: 5}, chain_u.get_parent_heights())
        self.assertEqual({chain_l: 11},             chain_l.get_parent_heights())

        chain_z = chain_l.fork(self.HEADERS['M'])
        self._append_header(chain_z, self.HEADERS['N'])
        self._append_header(chain_z, self.HEADERS['X'])
        self._append_header(chain_z, self.HEADERS['Y'])
        self._append_header(chain_z, self.HEADERS['Z'])

        self.assertEqual({chain_u:  8, chain_z: 5}, chain_u.get_parent_heights())
        self.assertEqual({chain_l: 11, chain_z: 8}, chain_l.get_parent_heights())
        self.assertEqual({chain_z: 13},             chain_z.get_parent_heights())
        self.assertEqual(5, chain_u.get_height_of_last_common_block_with_chain(chain_l))
        self.assertEqual(5, chain_l.get_height_of_last_common_block_with_chain(chain_u))
        self.assertEqual(5, chain_u.get_height_of_last_common_block_with_chain(chain_z))
        self.assertEqual(5, chain_z.get_height_of_last_common_block_with_chain(chain_u))
        self.assertEqual(8, chain_l.get_height_of_last_common_block_with_chain(chain_z))
        self.assertEqual(8, chain_z.get_height_of_last_common_block_with_chain(chain_l))

        self._append_header(chain_u, self.HEADERS['R'])
        self._append_header(chain_u, self.HEADERS['S'])
        self._append_header(chain_u, self.HEADERS['T'])
        self._append_header(chain_u, self.HEADERS['U'])

        self.assertEqual({chain_u: 12, chain_z: 5}, chain_u.get_parent_heights())
        self.assertEqual({chain_l: 11, chain_z: 8}, chain_l.get_parent_heights())
        self.assertEqual({chain_z: 13},             chain_z.get_parent_heights())
        self.assertEqual(5, chain_u.get_height_of_last_common_block_with_chain(chain_l))
        self.assertEqual(5, chain_l.get_height_of_last_common_block_with_chain(chain_u))
        self.assertEqual(5, chain_u.get_height_of_last_common_block_with_chain(chain_z))
        self.assertEqual(5, chain_z.get_height_of_last_common_block_with_chain(chain_u))
        self.assertEqual(8, chain_l.get_height_of_last_common_block_with_chain(chain_z))
        self.assertEqual(8, chain_z.get_height_of_last_common_block_with_chain(chain_l))


    def test_parents_after_forking(self):
        blockchain.blockchains[constants.net.GENESIS] = chain_u = Blockchain(
            config=self.config, forkpoint=0, parent=None,
            forkpoint_hash=constants.net.GENESIS, prev_hash=None)
        open(chain_u.path(), 'w+').close()
        self._append_header(chain_u, self.HEADERS['A'])
        self._append_header(chain_u, self.HEADERS['B'])
        self._append_header(chain_u, self.HEADERS['C'])
        self._append_header(chain_u, self.HEADERS['D'])
        self._append_header(chain_u, self.HEADERS['E'])
        self._append_header(chain_u, self.HEADERS['F'])
        self._append_header(chain_u, self.HEADERS['O'])
        self._append_header(chain_u, self.HEADERS['P'])
        self._append_header(chain_u, self.HEADERS['Q'])

        self.assertEqual(None, chain_u.parent)

        chain_l = chain_u.fork(self.HEADERS['G'])
        self._append_header(chain_l, self.HEADERS['H'])
        self._append_header(chain_l, self.HEADERS['I'])
        self._append_header(chain_l, self.HEADERS['J'])
        self._append_header(chain_l, self.HEADERS['K'])
        self._append_header(chain_l, self.HEADERS['L'])

        self.assertEqual(None,    chain_l.parent)
        self.assertEqual(chain_l, chain_u.parent)

        chain_z = chain_l.fork(self.HEADERS['M'])
        self._append_header(chain_z, self.HEADERS['N'])
        self._append_header(chain_z, self.HEADERS['X'])
        self._append_header(chain_z, self.HEADERS['Y'])
        self._append_header(chain_z, self.HEADERS['Z'])

        self.assertEqual(chain_z, chain_u.parent)
        self.assertEqual(chain_z, chain_l.parent)
        self.assertEqual(None,    chain_z.parent)

        self._append_header(chain_u, self.HEADERS['R'])
        self._append_header(chain_u, self.HEADERS['S'])
        self._append_header(chain_u, self.HEADERS['T'])
        self._append_header(chain_u, self.HEADERS['U'])

        self.assertEqual(chain_z, chain_u.parent)
        self.assertEqual(chain_z, chain_l.parent)
        self.assertEqual(None,    chain_z.parent)

    def test_forking_and_swapping(self):
        blockchain.blockchains[constants.net.GENESIS] = chain_u = Blockchain(
            config=self.config, forkpoint=0, parent=None,
            forkpoint_hash=constants.net.GENESIS, prev_hash=None)
        open(chain_u.path(), 'w+').close()

        self._append_header(chain_u, self.HEADERS['A'])
        self._append_header(chain_u, self.HEADERS['B'])
        self._append_header(chain_u, self.HEADERS['C'])
        self._append_header(chain_u, self.HEADERS['D'])
        self._append_header(chain_u, self.HEADERS['E'])
        self._append_header(chain_u, self.HEADERS['F'])
        self._append_header(chain_u, self.HEADERS['O'])
        self._append_header(chain_u, self.HEADERS['P'])
        self._append_header(chain_u, self.HEADERS['Q'])
        self._append_header(chain_u, self.HEADERS['R'])

        #chain_l = chain_u.fork(self.HEADERS['G'])
        #self._append_header(chain_l, self.HEADERS['H'])
        #self._append_header(chain_l, self.HEADERS['I'])
        #self._append_header(chain_l, self.HEADERS['J'])

        # do checks
        self.assertEqual(2, len(blockchain.blockchains))
        self.assertEqual(1, len(os.listdir(os.path.join(self.data_dir, "forks"))))
        self.assertEqual(0, chain_u.forkpoint)
        self.assertEqual(None, chain_u.parent)
        self.assertEqual(constants.net.GENESIS, chain_u._forkpoint_hash)
        self.assertEqual(None, chain_u._prev_hash)
        self.assertEqual(os.path.join(self.data_dir, "blockchain_headers"), chain_u.path())
        self.assertEqual(10 * 80, os.stat(chain_u.path()).st_size)
        self.assertEqual(6, chain_l.forkpoint)
        self.assertEqual(chain_u, chain_l.parent)
        self.assertEqual(hash_header(self.HEADERS['G']), chain_l._forkpoint_hash)
        self.assertEqual(hash_header(self.HEADERS['F']), chain_l._prev_hash)
        self.assertEqual(os.path.join(self.data_dir, "forks", "fork2_6_61b274ea009f7566740eec9aeff7676c6dffb4136a1033427f5d7647e0fe0bed_e3599615f2e4e04bd143ecaead68800b3e4497113eddc17c1e3602e01622caf8"), chain_l.path())
        self.assertEqual(4 * 80, os.stat(chain_l.path()).st_size)

        self._append_header(chain_l, self.HEADERS['K'])

        # chains were swapped, do checks
        self.assertEqual(2, len(blockchain.blockchains))
        self.assertEqual(1, len(os.listdir(os.path.join(self.data_dir, "forks"))))
        self.assertEqual(6, chain_u.forkpoint)
        self.assertEqual(chain_l, chain_u.parent)
        self.assertEqual(hash_header(self.HEADERS['O']), chain_u._forkpoint_hash)
        self.assertEqual(hash_header(self.HEADERS['F']), chain_u._prev_hash)
        self.assertEqual(os.path.join(self.data_dir, "forks", "fork2_6_61b274ea009f7566740eec9aeff7676c6dffb4136a1033427f5d7647e0fe0bed_a9e0ca750c5f9d2e2a22d858c2282d64936f672ab6030ba9edd45f291e9f9b1f"), chain_u.path())
        self.assertEqual(4 * 80, os.stat(chain_u.path()).st_size)
        self.assertEqual(0, chain_l.forkpoint)
        self.assertEqual(None, chain_l.parent)
        self.assertEqual(constants.net.GENESIS, chain_l._forkpoint_hash)
        self.assertEqual(None, chain_l._prev_hash)
        self.assertEqual(os.path.join(self.data_dir, "blockchain_headers"), chain_l.path())
        self.assertEqual(11 * 80, os.stat(chain_l.path()).st_size)
        for b in (chain_u, chain_l):
            self.assertTrue(all([b.can_connect(b.read_header(i), False) for i in range(b.height())]))

        self._append_header(chain_u, self.HEADERS['S'])
        self._append_header(chain_u, self.HEADERS['T'])
        self._append_header(chain_u, self.HEADERS['U'])
        self._append_header(chain_l, self.HEADERS['L'])

        chain_z = chain_l.fork(self.HEADERS['M'])
        self._append_header(chain_z, self.HEADERS['N'])
        self._append_header(chain_z, self.HEADERS['X'])
        self._append_header(chain_z, self.HEADERS['Y'])
        self._append_header(chain_z, self.HEADERS['Z'])

        # chain_z became best chain, do checks
        self.assertEqual(3, len(blockchain.blockchains))
        self.assertEqual(2, len(os.listdir(os.path.join(self.data_dir, "forks"))))
        self.assertEqual(0, chain_z.forkpoint)
        self.assertEqual(None, chain_z.parent)
        self.assertEqual(constants.net.GENESIS, chain_z._forkpoint_hash)
        self.assertEqual(None, chain_z._prev_hash)
        self.assertEqual(os.path.join(self.data_dir, "blockchain_headers"), chain_z.path())
        self.assertEqual(14 * 80, os.stat(chain_z.path()).st_size)
        self.assertEqual(9, chain_l.forkpoint)
        self.assertEqual(chain_z, chain_l.parent)
        self.assertEqual(hash_header(self.HEADERS['J']), chain_l._forkpoint_hash)
        self.assertEqual(hash_header(self.HEADERS['I']), chain_l._prev_hash)
        self.assertEqual(os.path.join(self.data_dir, "forks", "fork2_9_67b0765c4090086b9dcecb70ba3d10e807df305cce403e4c6e4ca9edfe4d5a1d_a879ddca14a9d4d1c81ee90401910e7a186ee6511972aefa8791524a94463cf9"), chain_l.path())
        self.assertEqual(3 * 80, os.stat(chain_l.path()).st_size)
        self.assertEqual(6, chain_u.forkpoint)
        self.assertEqual(chain_z, chain_u.parent)
        self.assertEqual(hash_header(self.HEADERS['O']), chain_u._forkpoint_hash)
        self.assertEqual(hash_header(self.HEADERS['F']), chain_u._prev_hash)
        self.assertEqual(os.path.join(self.data_dir, "forks", "fork2_6_61b274ea009f7566740eec9aeff7676c6dffb4136a1033427f5d7647e0fe0bed_a9e0ca750c5f9d2e2a22d858c2282d64936f672ab6030ba9edd45f291e9f9b1f"), chain_u.path())
        self.assertEqual(7 * 80, os.stat(chain_u.path()).st_size)
        for b in (chain_u, chain_l, chain_z):
            self.assertTrue(all([b.can_connect(b.read_header(i), False) for i in range(b.height())]))

        self.assertEqual(constants.net.GENESIS, chain_z.get_hash(0))
        self.assertEqual(hash_header(self.HEADERS['F']), chain_z.get_hash(5))
        self.assertEqual(hash_header(self.HEADERS['G']), chain_z.get_hash(6))
        self.assertEqual(hash_header(self.HEADERS['I']), chain_z.get_hash(8))
        self.assertEqual(hash_header(self.HEADERS['M']), chain_z.get_hash(9))
        self.assertEqual(hash_header(self.HEADERS['Z']), chain_z.get_hash(13))

    def test_doing_multiple_swaps_after_single_new_header(self):
        blockchain.blockchains[constants.net.GENESIS] = chain_u = Blockchain(
            config=self.config, forkpoint=0, parent=None,
            forkpoint_hash=constants.net.GENESIS, prev_hash=None)
        open(chain_u.path(), 'w+').close()

        self._append_header(chain_u, self.HEADERS['A'])
        self._append_header(chain_u, self.HEADERS['B'])
        self._append_header(chain_u, self.HEADERS['C'])
        self._append_header(chain_u, self.HEADERS['D'])
        self._append_header(chain_u, self.HEADERS['E'])
        self._append_header(chain_u, self.HEADERS['F'])
        self._append_header(chain_u, self.HEADERS['O'])
        self._append_header(chain_u, self.HEADERS['P'])
        self._append_header(chain_u, self.HEADERS['Q'])
        self._append_header(chain_u, self.HEADERS['R'])
        self._append_header(chain_u, self.HEADERS['S'])

        self.assertEqual(1, len(blockchain.blockchains))
        self.assertEqual(0, len(os.listdir(os.path.join(self.data_dir, "forks"))))

        chain_l = chain_u.fork(self.HEADERS['G'])
        self._append_header(chain_l, self.HEADERS['H'])
        self._append_header(chain_l, self.HEADERS['I'])
        self._append_header(chain_l, self.HEADERS['J'])
        self._append_header(chain_l, self.HEADERS['K'])
        # now chain_u is best chain, but it's tied with chain_l

        self.assertEqual(2, len(blockchain.blockchains))
        self.assertEqual(1, len(os.listdir(os.path.join(self.data_dir, "forks"))))

        chain_z = chain_l.fork(self.HEADERS['M'])
        self._append_header(chain_z, self.HEADERS['N'])
        self._append_header(chain_z, self.HEADERS['X'])

        self.assertEqual(3, len(blockchain.blockchains))
        self.assertEqual(2, len(os.listdir(os.path.join(self.data_dir, "forks"))))

        # chain_z became best chain, do checks
        self.assertEqual(0, chain_z.forkpoint)
        self.assertEqual(None, chain_z.parent)
        self.assertEqual(constants.net.GENESIS, chain_z._forkpoint_hash)
        self.assertEqual(None, chain_z._prev_hash)
        self.assertEqual(os.path.join(self.data_dir, "blockchain_headers"), chain_z.path())
        self.assertEqual(12 * 80, os.stat(chain_z.path()).st_size)
        self.assertEqual(9, chain_l.forkpoint)
        self.assertEqual(chain_z, chain_l.parent)
        self.assertEqual(hash_header(self.HEADERS['J']), chain_l._forkpoint_hash)
        self.assertEqual(hash_header(self.HEADERS['I']), chain_l._prev_hash)
        self.assertEqual(os.path.join(self.data_dir, "forks", "fork2_9_67b0765c4090086b9dcecb70ba3d10e807df305cce403e4c6e4ca9edfe4d5a1d_a879ddca14a9d4d1c81ee90401910e7a186ee6511972aefa8791524a94463cf9"), chain_l.path())
        self.assertEqual(2 * 80, os.stat(chain_l.path()).st_size)
        self.assertEqual(6, chain_u.forkpoint)
        self.assertEqual(chain_z, chain_u.parent)
        self.assertEqual(hash_header(self.HEADERS['O']), chain_u._forkpoint_hash)
        self.assertEqual(hash_header(self.HEADERS['F']), chain_u._prev_hash)
        self.assertEqual(os.path.join(self.data_dir, "forks", "fork2_6_61b274ea009f7566740eec9aeff7676c6dffb4136a1033427f5d7647e0fe0bed_a9e0ca750c5f9d2e2a22d858c2282d64936f672ab6030ba9edd45f291e9f9b1f"), chain_u.path())
        self.assertEqual(5 * 80, os.stat(chain_u.path()).st_size)

        self.assertEqual(constants.net.GENESIS, chain_z.get_hash(0))
        self.assertEqual(hash_header(self.HEADERS['F']), chain_z.get_hash(5))
        self.assertEqual(hash_header(self.HEADERS['G']), chain_z.get_hash(6))
        self.assertEqual(hash_header(self.HEADERS['I']), chain_z.get_hash(8))
        self.assertEqual(hash_header(self.HEADERS['M']), chain_z.get_hash(9))
        self.assertEqual(hash_header(self.HEADERS['X']), chain_z.get_hash(11))

        for b in (chain_u, chain_l, chain_z):
            self.assertTrue(all([b.can_connect(b.read_header(i), False) for i in range(b.height())]))
'''
