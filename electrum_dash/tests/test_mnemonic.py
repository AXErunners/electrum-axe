from typing import NamedTuple, Optional

from electrum_dash import keystore
from electrum_dash import mnemonic
from electrum_dash import old_mnemonic
from electrum_dash.util import bh2u, bfh
from electrum_dash.mnemonic import is_new_seed, is_old_seed, seed_type
from electrum_dash.version import SEED_PREFIX

from . import SequentialTestCase
from .test_wallet_vertical import UNICODE_HORROR, UNICODE_HORROR_HEX


class SeedTestCase(NamedTuple):
    words: str
    bip32_seed: str
    lang: Optional[str] = 'en'
    words_hex: Optional[str] = None
    entropy: Optional[int] = None
    passphrase: Optional[str] = None
    passphrase_hex: Optional[str] = None
    seed_version: str = SEED_PREFIX


SEED_TEST_CASES = {
    'english': SeedTestCase(
        words='what vocal wage wealth renew busy emerge execute rival soda card auto',
        seed_version=SEED_PREFIX,
        bip32_seed='1139b2701f261290ccce5d1d91658ac017c835807147b758ed96ac2b37fbe77b3eb108ae45b976a770bc58bc23267916ff462b8c34f721c5109f55d1b933f01d'),
    'english_with_passphrase': SeedTestCase(
        words='what vocal wage wealth renew busy emerge execute rival soda card auto',
        seed_version=SEED_PREFIX,
        passphrase='Did you ever hear the tragedy of Darth Plagueis the Wise?',
        bip32_seed='3cdb87dfa132a93d889c3bdd9ebd5b9c421ff1d85ea0d32644c167cedaa8c8dc0e9364d6fc9a54d90a00a74dce881c2cb3989961e96fa72876a9790f542b7bda'),
    'japanese': SeedTestCase(
        lang='ja',
        words='なのか ひろい しなん まなぶ つぶす さがす おしゃれ かわく おいかける けさき かいとう さたん',
        words_hex='e381aae381aee3818b20e381b2e3828de3818420e38197e381aae3829320e381bee381aae381b5e3829920e381a4e381b5e38299e3819920e38195e3818be38299e3819920e3818ae38197e38283e3828c20e3818be3828fe3818f20e3818ae38184e3818be38191e3828b20e38191e38195e3818d20e3818be38184e381a8e3818620e38195e3819fe38293',
        entropy=1938439226660562861250521787963972783469,
        bip32_seed='d3eaf0e44ddae3a5769cb08a26918e8b308258bcb057bb704c6f69713245c0b35cb92c03df9c9ece5eff826091b4e74041e010b701d44d610976ce8bfb66a8ad'),
    'japanese_with_passphrase': SeedTestCase(
        lang='ja',
        words='なのか ひろい しなん まなぶ つぶす さがす おしゃれ かわく おいかける けさき かいとう さたん',
        words_hex='e381aae381aee3818b20e381b2e3828de3818420e38197e381aae3829320e381bee381aae381b5e3829920e381a4e381b5e38299e3819920e38195e3818be38299e3819920e3818ae38197e38283e3828c20e3818be3828fe3818f20e3818ae38184e3818be38191e3828b20e38191e38195e3818d20e3818be38184e381a8e3818620e38195e3819fe38293',
        entropy=1938439226660562861250521787963972783469,
        passphrase=UNICODE_HORROR,
        passphrase_hex=UNICODE_HORROR_HEX,
        bip32_seed='251ee6b45b38ba0849e8f40794540f7e2c6d9d604c31d68d3ac50c034f8b64e4bc037c5e1e985a2fed8aad23560e690b03b120daf2e84dceb1d7857dda042457'),
    'chinese': SeedTestCase(
        lang='zh',
        words='煮 驻 化 唱 锋 炮 当 卢 川 熔 曰 跨',
        words_hex='e785ae20e9a9bb20e58c9620e594b120e9948b20e782ae20e5bd9320e58da220e5b79d20e7869420e69bb020e8b7a8',
        seed_version=SEED_PREFIX,
        entropy=3767017487582277809014027973551483866900,
        bip32_seed='0e1980c2b6c4896664cf8b56c3186d65b005e828920442964051a60ebba4b30f9b4dd99c81d0b5dd32be73582bdfa8b8be02e29cb330dac503ceed6d632cc6d9'),
    'chinese_with_passphrase': SeedTestCase(
        lang='zh',
        words='煮 驻 化 唱 锋 炮 当 卢 川 熔 曰 跨',
        words_hex='e785ae20e9a9bb20e58c9620e594b120e9948b20e782ae20e5bd9320e58da220e5b79d20e7869420e69bb020e8b7a8',
        seed_version=SEED_PREFIX,
        entropy=3767017487582277809014027973551483866900,
        passphrase='给我一些测试向量谷歌',
        passphrase_hex='e7bb99e68891e4b880e4ba9be6b58be8af95e59091e9878fe8b0b7e6ad8c',
        bip32_seed='627d3d71dccdb367729756452ab5a8d48a3aeaa55cce2fee441592a928a18cca7e950a1d7917b8855f39838471ba8aa8f468acc5329f67b0bc99c96f70cd7603'),
    'spanish': SeedTestCase(
        lang='es',
        words='almíbar tibio superar vencer hacha peatón príncipe matar consejo polen vehículo odisea',
        words_hex='616c6d69cc8162617220746962696f20737570657261722076656e63657220686163686120706561746fcc816e20707269cc816e63697065206d6174617220636f6e73656a6f20706f6c656e2076656869cc8163756c6f206f6469736561',
        entropy=3423992296655289706780599506247192518735,
        bip32_seed='18bffd573a960cc775bbd80ed60b7dc00bc8796a186edebe7fc7cf1f316da0fe937852a969c5c79ded8255cdf54409537a16339fbe33fb9161af793ea47faa7a'),
    'spanish_with_passphrase': SeedTestCase(
        lang='es',
        words='almíbar tibio superar vencer hacha peatón príncipe matar consejo polen vehículo odisea',
        words_hex='616c6d69cc8162617220746962696f20737570657261722076656e63657220686163686120706561746fcc816e20707269cc816e63697065206d6174617220636f6e73656a6f20706f6c656e2076656869cc8163756c6f206f6469736561',
        entropy=3423992296655289706780599506247192518735,
        passphrase='araña difícil solución término cárcel',
        passphrase_hex='6172616ecc83612064696669cc8163696c20736f6c7563696fcc816e207465cc81726d696e6f206361cc817263656c',
        bip32_seed='363dec0e575b887cfccebee4c84fca5a3a6bed9d0e099c061fa6b85020b031f8fe3636d9af187bf432d451273c625e20f24f651ada41aae2c4ea62d87e9fa44c'),
    'spanish2': SeedTestCase(
        lang='es',
        words='tiburón caer bola fracaso fecha usuario baile sesión momia tutor corazón juerga',
        words_hex='74696275726fcc816e206361657220626f6c61206672616361736f206665636861207573756172696f206261696c6520736573696fcc816e206d6f6d6961207475746f7220636f72617a6fcc816e206a7565726761',
        seed_version=SEED_PREFIX,
        entropy=2526119849008492538961863188757911019317,
        bip32_seed='504cf49b8eca95a01f5a4de9999f3aabdf1b9a93bb4dc09a2a4532b9d089a9114d70b87db1de14eaae629e374ee359ec66b2a9e32126f45f0829cc9ddfac9455'),
    'spanish3': SeedTestCase(
        lang='es',
        words='tiburón caer bola fracaso fecha usuario baile sesión momia tutor corazón juerga',
        words_hex='74696275726fcc816e206361657220626f6c61206672616361736f206665636861207573756172696f206261696c6520736573696fcc816e206d6f6d6961207475746f7220636f72617a6fcc816e206a7565726761',
        seed_version=SEED_PREFIX,
        entropy=2526119849008492538961863188757911019317,
        passphrase='¡Viva España! repiten veinte pueblos y al hablar dan fe del ánimo español... ¡Marquen arado martillo y clarín',
        passphrase_hex='c2a1566976612045737061c3b16121207265706974656e207665696e746520707565626c6f73207920616c206861626c61722064616e2066652064656c20c3a16e696d6f2065737061c3b16f6c2e2e2e20c2a14d61727175656e20617261646f206d617274696c6c6f207920636c6172c3ad6e',
        bip32_seed='89658718a34a62313470e8757f097cee97e415de2b687f7c031d02f5840f8f8f9022a9a18ca929633534085e6d53d7338a80229130b3fd58066a8c43c640a01f'),
}


class Test_NewMnemonic(SequentialTestCase):

    def test_mnemonic_to_seed_basic(self):
        # note: not a valid electrum seed
        seed = mnemonic.Mnemonic.mnemonic_to_seed(mnemonic='foobar', passphrase='none')
        self.assertEqual('741b72fd15effece6bfe5a26a52184f66811bd2be363190e07a42cca442b1a5bb22b3ad0eb338197287e6d314866c7fba863ac65d3f156087a5052ebc7157fce',
                         bh2u(seed))

    def test_mnemonic_to_seed(self):
        for test_name, test in SEED_TEST_CASES.items():
            if test.words_hex is not None:
                self.assertEqual(test.words_hex, bh2u(test.words.encode('utf8')), msg=test_name)
            self.assertTrue(is_new_seed(test.words, prefix=test.seed_version), msg=test_name)
            m = mnemonic.Mnemonic(lang=test.lang)
            if test.entropy is not None:
                self.assertEqual(test.entropy, m.mnemonic_decode(test.words), msg=test_name)
            if test.passphrase_hex is not None:
                self.assertEqual(test.passphrase_hex, bh2u(test.passphrase.encode('utf8')), msg=test_name)
            seed = mnemonic.Mnemonic.mnemonic_to_seed(mnemonic=test.words, passphrase=test.passphrase)
            self.assertEqual(test.bip32_seed, bh2u(seed), msg=test_name)

    def test_random_seeds(self):
        iters = 10
        m = mnemonic.Mnemonic(lang='en')
        for _ in range(iters):
            seed = m.make_seed()
            i = m.mnemonic_decode(seed)
            self.assertEqual(m.mnemonic_encode(i), seed)


class Test_OldMnemonic(SequentialTestCase):

    def test(self):
        seed = '8edad31a95e7d59f8837667510d75a4d'
        result = old_mnemonic.mn_encode(seed)
        words = 'hardly point goal hallway patience key stone difference ready caught listen fact'
        self.assertEqual(result, words.split())
        self.assertEqual(old_mnemonic.mn_decode(result), seed)


class Test_BIP39Checksum(SequentialTestCase):

    def test(self):
        mnemonic = u'gravity machine north sort system female filter attitude volume fold club stay feature office ecology stable narrow fog'
        is_checksum_valid, is_wordlist_valid = keystore.bip39_is_checksum_valid(mnemonic)
        self.assertTrue(is_wordlist_valid)
        self.assertTrue(is_checksum_valid)


class Test_seeds(SequentialTestCase):
    """ Test old and new seeds. """

    mnemonics = {
        ('cell dumb heartbeat north boom tease ship baby bright kingdom rare squeeze', 'old'),
        ('cell dumb heartbeat north boom tease ' * 4, 'old'),
        ('cell dumb heartbeat north boom tease ship baby bright kingdom rare badword', ''),
        ('cElL DuMb hEaRtBeAt nOrTh bOoM TeAsE ShIp bAbY BrIgHt kInGdOm rArE SqUeEzE', 'old'),
        ('   cElL  DuMb hEaRtBeAt nOrTh bOoM  TeAsE ShIp    bAbY BrIgHt kInGdOm rArE SqUeEzE   ', 'old'),
        # below seed is actually 'invalid old' as it maps to 33 hex chars
        ('hurry idiot prefer sunset mention mist jaw inhale impossible kingdom rare squeeze', 'old'),
        ('cram swing cover prefer miss modify ritual silly deliver chunk behind inform able', 'standard'),
        ('cram swing cover prefer miss modify ritual silly deliver chunk behind inform', ''),
        ('ostrich security deer aunt climb inner alpha arm mutual marble solid task', 'standard'),
        ('OSTRICH SECURITY DEER AUNT CLIMB INNER ALPHA ARM MUTUAL MARBLE SOLID TASK', 'standard'),
        ('   oStRiCh sEcUrItY DeEr aUnT ClImB       InNeR AlPhA ArM MuTuAl mArBlE   SoLiD TaSk  ', 'standard'),
        ('x8', 'standard'),
        ('science dawn member doll dutch real ca brick knife deny drive list', ''),
    }

    def test_new_seed(self):
        seed = "cram swing cover prefer miss modify ritual silly deliver chunk behind inform able"
        self.assertTrue(is_new_seed(seed))

        seed = "cram swing cover prefer miss modify ritual silly deliver chunk behind inform"
        self.assertFalse(is_new_seed(seed))

    def test_old_seed(self):
        self.assertTrue(is_old_seed(" ".join(["like"] * 12)))
        self.assertFalse(is_old_seed(" ".join(["like"] * 18)))
        self.assertTrue(is_old_seed(" ".join(["like"] * 24)))
        self.assertFalse(is_old_seed("not a seed"))

        self.assertTrue(is_old_seed("0123456789ABCDEF" * 2))
        self.assertTrue(is_old_seed("0123456789ABCDEF" * 4))

    def test_seed_type(self):
        for seed_words, _type in self.mnemonics:
            self.assertEqual(_type, seed_type(seed_words), msg=seed_words)
