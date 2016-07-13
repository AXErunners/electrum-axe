from datetime import datetime
import inspect
import requests
import sys
from threading import Thread
import time
import traceback
import csv
from decimal import Decimal

from electrum_dash.bitcoin import COIN
from electrum_dash.plugins import BasePlugin, hook
from electrum_dash.i18n import _
from electrum_dash.util import PrintError, ThreadJob
from electrum_dash.util import format_satoshis


# See https://en.wikipedia.org/wiki/ISO_4217
CCY_PRECISIONS = {'BHD': 3, 'BIF': 0, 'BYR': 0, 'CLF': 4, 'CLP': 0,
                  'CVE': 0, 'DJF': 0, 'GNF': 0, 'IQD': 3, 'ISK': 0,
                  'JOD': 3, 'JPY': 0, 'KMF': 0, 'KRW': 0, 'KWD': 3,
                  'LYD': 3, 'MGA': 1, 'MRO': 1, 'OMR': 3, 'PYG': 0,
                  'RWF': 0, 'TND': 3, 'UGX': 0, 'UYI': 0, 'VND': 0,
                  'VUV': 0, 'XAF': 0, 'XAU': 4, 'XOF': 0, 'XPF': 0,
                  # Not ISO 4217.
                  'BTC': 8,}

DEFAULT_EXCHANGE = 'Bittrex'
DEFAULT_CCY = 'BTC'

class ExchangeBase(PrintError):

    def __init__(self, on_quotes, on_history):
        self.history = {}
        self.quotes = {}
        self.on_quotes = on_quotes
        self.on_history = on_history

    def protocol(self):
        return "https"

    def get_json(self, site, get_string):
        url = "".join([self.protocol(), '://', site, get_string])
        response = requests.request('GET', url,
                                    headers={'User-Agent' : 'Electrum'})
        return response.json()

    def get_csv(self, site, get_string):
        url = "".join([self.protocol(), '://', site, get_string])
        response = requests.request('GET', url,
                                    headers={'User-Agent' : 'Electrum'})
        reader = csv.DictReader(response.content.split('\n'))
        return list(reader)

    def name(self):
        return self.__class__.__name__

    def update_safe(self, ccy):
        try:
            self.print_error("getting fx quotes for", ccy)
            self.quotes = self.get_rates(ccy)
            self.print_error("received fx quotes")
        except BaseException as e:
            self.print_error("failed fx quotes:", e)
        self.on_quotes()

    def update(self, ccy):
        t = Thread(target=self.update_safe, args=(ccy,))
        t.setDaemon(True)
        t.start()

    def get_historical_rates_safe(self, ccy):
        try:
            self.print_error("requesting fx history for", ccy)
            self.history[ccy] = self.historical_rates(ccy)
            self.print_error("received fx history for", ccy)
            self.on_history()
        except BaseException as e:
            self.print_error("failed fx history:", e)

    def get_historical_rates(self, ccy):
        result = self.history.get(ccy)
        if not result and ccy in self.history_ccys():
            t = Thread(target=self.get_historical_rates_safe, args=(ccy,))
            t.setDaemon(True)
            t.start()
        return result

    def history_ccys(self):
        return []

    def historical_rate(self, ccy, d_t):
        return self.history.get(ccy, {}).get(d_t.strftime('%Y-%m-%d'))


class Bittrex(ExchangeBase):
    def get_rates(self, ccy):
        json = self.get_json('bittrex.com', '/api/v1.1/public/getticker?market=BTC-DASH')
        quote_currencies = {}
        if not json.get('success', False):
            return quote_currencies
        last = Decimal(json['result']['Last'])
        quote_currencies['BTC'] = last
        return quote_currencies

class Poloniex(ExchangeBase):
    def get_rates(self, ccy):
        json = self.get_json('poloniex.com', '/public?command=returnTicker')
        quote_currencies = {}
        dash_ticker = json.get('BTC_DASH')
        quote_currencies['BTC'] = Decimal(dash_ticker['last'])
        return quote_currencies

class CoinMarketCap(ExchangeBase):
    def get_rates(self, ccy):
        json = self.get_json('api.coinmarketcap.com', '/v1/ticker/dash/')
        quote_currencies = {}
        if not isinstance(json, list):
            return quote_currencies
        json = json[0]
        for ccy, key in [
            ('USD', 'price_usd'),
            ('BTC', 'price_btc'),
        ]:
            quote_currencies[ccy] = Decimal(json[key])
        return quote_currencies



def dictinvert(d):
    inv = {}
    for k, vlist in d.iteritems():
        for v in vlist:
            keys = inv.setdefault(v, [])
            keys.append(k)
    return inv

def get_exchanges():
    is_exchange = lambda obj: (inspect.isclass(obj)
                               and issubclass(obj, ExchangeBase)
                               and obj != ExchangeBase)
    return dict(inspect.getmembers(sys.modules[__name__], is_exchange))

def get_exchanges_by_ccy():
    "return only the exchanges that have history rates (which is hardcoded)"
    d = {}
    exchanges = get_exchanges()
    for name, klass in exchanges.items():
        exchange = klass(None, None)
        d[name] = exchange.history_ccys()
    return dictinvert(d)



class FxPlugin(BasePlugin, ThreadJob):

    def __init__(self, parent, config, name):
        BasePlugin.__init__(self, parent, config, name)
        self.ccy = self.get_currency()
        self.history_used_spot = False
        self.ccy_combo = None
        self.hist_checkbox = None
        self.exchanges = get_exchanges()
        self.exchanges_by_ccy = get_exchanges_by_ccy()
        self.set_exchange(self.config_exchange())

    def ccy_amount_str(self, amount, commas):
        prec = CCY_PRECISIONS.get(self.ccy, 2)
        fmt_str = "{:%s.%df}" % ("," if commas else "", max(0, prec))
        return fmt_str.format(round(amount, prec))

    def thread_jobs(self):
        return [self]

    def run(self):
        # This runs from the plugins thread which catches exceptions
        if self.timeout <= time.time():
            self.timeout = time.time() + 150
            self.exchange.update(self.ccy)

    def get_currency(self):
        '''Use when dynamic fetching is needed'''
        return self.config.get("currency", DEFAULT_CCY)

    def config_exchange(self):
        return self.config.get('use_exchange', DEFAULT_EXCHANGE)

    def show_history(self):
        return self.ccy in self.exchange.history_ccys()

    def set_currency(self, ccy):
        self.ccy = ccy
        self.config.set_key('currency', ccy, True)
        self.get_historical_rates() # Because self.ccy changes
        self.on_quotes()

    def set_exchange(self, name):
        class_ = self.exchanges.get(name) or self.exchanges.values()[0]
        name = class_.__name__
        self.print_error("using exchange", name)
        if self.config_exchange() != name:
            self.config.set_key('use_exchange', name, True)

        self.exchange = class_(self.on_quotes, self.on_history)
        # A new exchange means new fx quotes, initially empty.  Force
        # a quote refresh
        self.timeout = 0
        self.get_historical_rates()

    def on_quotes(self):
        pass

    def on_history(self):
        pass

    @hook
    def exchange_rate(self):
        '''Returns None, or the exchange rate as a Decimal'''
        rate = self.exchange.quotes.get(self.ccy)
        if rate:
            return Decimal(rate)

    @hook
    def format_amount_and_units(self, btc_balance):
        rate = self.exchange_rate()
        return '' if rate is None else "%s %s" % (self.value_str(btc_balance, rate), self.ccy)

    @hook
    def get_fiat_status_text(self, btc_balance):
        rate = self.exchange_rate()
        return _("  (No FX rate available)") if rate is None else "1 DASH~%s %s" % (self.value_str(COIN, rate), self.ccy)

    def get_historical_rates(self):
        if self.show_history():
            self.exchange.get_historical_rates(self.ccy)

    def requires_settings(self):
        return True

    @hook
    def value_str(self, satoshis, rate):
        if satoshis is None:  # Can happen with incomplete history
            return _("Unknown")
        if rate:
            value = Decimal(satoshis) / COIN * Decimal(rate)
            return "%s" % (self.ccy_amount_str(value, True))
        return _("No data")

    @hook
    def history_rate(self, d_t):
        rate = self.exchange.historical_rate(self.ccy, d_t)
        # Frequently there is no rate for today, until tomorrow :)
        # Use spot quotes in that case
        if rate is None and (datetime.today().date() - d_t.date()).days <= 2:
            rate = self.exchange.quotes.get(self.ccy)
            self.history_used_spot = True
        return rate

    @hook
    def historical_value_str(self, satoshis, d_t):
        rate = self.history_rate(d_t)
        return self.value_str(satoshis, rate)
