import unittest

from electrum_dash.protx_list import MNList
from electrum_dash.constants import CHUNK_SIZE


class ProTxListTestCase(unittest.TestCase):
    def test_calc_max_height(self):
        for base_height in [0, 1, 2, 3,
                            CHUNK_SIZE - 3, CHUNK_SIZE - 2,
                            CHUNK_SIZE - 1, CHUNK_SIZE,
                            CHUNK_SIZE + 1, CHUNK_SIZE + 2,
                            CHUNK_SIZE + 3,
                            2*CHUNK_SIZE - 3, 2*CHUNK_SIZE - 2,
                            2*CHUNK_SIZE - 1, 2*CHUNK_SIZE,
                            2*CHUNK_SIZE + 1, 2*CHUNK_SIZE + 2,
                            2*CHUNK_SIZE + 3]:
            for delta in [1, 2, 3,
                          CHUNK_SIZE - 3, CHUNK_SIZE - 2,
                          CHUNK_SIZE - 1, CHUNK_SIZE,
                          CHUNK_SIZE + 1, CHUNK_SIZE + 2,
                          CHUNK_SIZE + 3,
                          2*CHUNK_SIZE - 3, 2*CHUNK_SIZE - 2,
                          2*CHUNK_SIZE - 1, 2*CHUNK_SIZE,
                          2*CHUNK_SIZE + 1, 2*CHUNK_SIZE + 2,
                          2*CHUNK_SIZE + 3]:
                height = base_height + delta
                calc_height = MNList.calc_max_height(base_height, height)
                assert 0 < (calc_height - base_height) <= CHUNK_SIZE
                if (height - base_height) > CHUNK_SIZE:
                    assert (calc_height + 1) % CHUNK_SIZE == 0
