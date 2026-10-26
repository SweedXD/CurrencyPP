from datetime import datetime
from enum import Enum
from webservice import OpenExchangeRates, PrivateDomain

import json
import os
import re
import unicodedata


def normalize_code(value):
    """Normalize a currency code or alias so storage and lookup always agree.

    Compatibility decomposition folds forms like the full-width '＄' onto '$'.
    Dropping the combining marks it exposes is what makes this work outside
    English: Turkish 'İ' decomposes to 'I' plus a combining dot, so 'LİRA',
    'LIRA', 'lira' and dotless 'lıra' all become one alias, and 'dólar' matches
    'dolar'. Symbols such as '₺' and '₽' have no decomposition and pass through
    untouched. casefold() before upper() keeps pairs like German 'ß'/'SS' and
    Greek final sigma consistent in both directions, which plain upper() does not.
    """
    if value is None:
        return None
    text = unicodedata.normalize('NFKD', str(value)).strip()
    text = ''.join(ch for ch in text if not unicodedata.combining(ch))
    return unicodedata.normalize('NFKC', text).casefold().upper()


class CurrencyError(RuntimeError):
    def __init__(self, currency):
        self.currency = currency

    def __str__(self):
        return 'Unrecognized currency "{}". You can create aliases in the package configuration file.'.format(self.currency)


class UpdateFreq(Enum):
    NEVER = 'never'
    HOURLY = 'hourly'
    DAILY = 'daily'


class ExchangeRates():

    in_cur_fallback = 'USD'
    out_cur_fallback = 'USD EUR JPY'

    def __init__(self, path, update_freq, app_id, plugin):
        self.plugin = plugin
        # These used to be class attributes, so every instance shared the same
        # mutable dicts and clear_aliases() mutated class state.
        self._currencies = {}
        self._aliases = {}
        self.last_update = None
        self.error = None
        self.default_cur_in = self.in_cur_fallback
        self.default_curs_out = self.out_cur_fallback.split()

        self.cheap_service = PrivateDomain(self.plugin)
        self.expensive_service = OpenExchangeRates(self.plugin, app_id)
        self.update_freq = update_freq
        self._file_path = os.path.join(path, 'rates.json')

        if os.path.exists(self._file_path):
            try:
                self.load_from_file()
            except Exception as e:
                self.plugin.logger.warning(
                    'Could not read cached rates from {}: {}'.format(self._file_path, e))
                self.update()
        else:
            self.update()

        self.tryUpdate()

    @property
    def aliases(self):
        """The configured aliases. Callers read `.aliases` while the data lived
        in `_aliases`, so every diagnostic used to report zero aliases."""
        return self._aliases

    @property
    def has_rates(self):
        return bool(self._currencies)

    def shouldUpdate(self):
        time_diff = datetime.now() - self.last_update
        if self.update_freq.value == UpdateFreq.HOURLY.value:
            return time_diff.total_seconds() >= 3600
        elif self.update_freq.value == UpdateFreq.DAILY.value:
            return time_diff.days >= 1
        else:
            return False

    def tryUpdate(self):
        if not self.last_update:
            return self.update()
        if self.shouldUpdate():
            return self.update()
        else:
            return False

    def update(self):
        try:
            age = None
            try:
                self._currencies, update_time = self.cheap_service.load_from_url()
                self.last_update = datetime.now()
                age = self.last_update - datetime.fromtimestamp(update_time)
            except Exception as e:
                self.plugin.logger.info(
                    'cache server has returned error. Requesting from main API')
                self.plugin.logger.error(e)
                if not self.has_custom_app_id():
                    return False
                self._currencies, update_time = self.expensive_service.load_from_url()
                self.last_update = datetime.now()

            # `age` stays None when the cache server failed and we already fell
            # back to the paid API. Reading it unconditionally used to raise
            # NameError here and throw away the rates we had just fetched.
            if age is not None and age.total_seconds() > 3600 * 2:
                self.plugin.logger.info(
                    'cache server is more than 2 hours old. Requesting from main API')
                if not self.has_custom_app_id():
                    return False
                self._currencies, update_time = self.expensive_service.load_from_url()
                self.last_update = datetime.now()

            self.save_to_file()
            self.error = None
            return True
        except Exception as e:
            self.plugin.logger.error(e)
            self.error = e
            return False

    def has_custom_app_id(self):
        if self.expensive_service.app_id:
            return True
        self.plugin.logger.error(
            'No OpenExchangeRates App ID declared in the configuration file.')
        self.error = Exception(
            'The cache has failed. More information (and a fix) are available in the Currency plugin configuration file.')
        return False

    def load_from_file(self):
        with open(self._file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        self.last_update = datetime.strptime(
            data['last_update'], '%Y-%m-%dT%H:%M:%S')
        self._currencies = data['rates']

    def save_to_file(self):
        data = {
            'rates': self._currencies,
            'last_update': self.last_update.strftime('%Y-%m-%dT%H:%M:%S')
        }

        with open(self._file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f)

    def rate(self, code):
        code = normalize_code(code)
        if code == 'USD':
            return 1
        elif code in self._aliases:
            return self.rate(self._aliases[code])
        else:
            return self._currencies[code]['price']

    def name(self, code):
        code = normalize_code(code)
        if code in self._aliases:
            return self.name(self._aliases[code])
        else:
            return self._currencies[code]['name']

    def knows(self, code):
        return code in self._currencies or code in self._aliases

    def clear_aliases(self):
        self._aliases.clear()

    def validate_alias(self, alias):
        """Return (normalized_alias, reason).

        `reason` is None when the alias is usable, and otherwise explains the
        rejection so the caller can tell the user instead of dropping it silently.
        """
        validated = normalize_code(alias)
        if not validated:
            return None, 'it is empty'
        elif validated in self._currencies:
            return None, 'it is already a real currency code'
        elif validated in self._aliases:
            return None, 'it is already used for {}'.format(self._aliases[validated])
        elif re.search(r'\d', validated):
            return None, 'aliases cannot contain digits'
        else:
            return validated, None

    def add_alias(self, alias, forCurrency):
        self._aliases[normalize_code(alias)] = self.validate_code(forCurrency)

    def validate_code(self, codeString, raiseOnNone=False):
        if codeString is None:
            if raiseOnNone:
                raise CurrencyError(None)
            return self.default_cur_in

        code = normalize_code(codeString)
        if self.knows(code):
            return code
        if not self._currencies:
            # Rates were never loaded, so there is nothing to validate against.
            # Accept the code rather than discarding the user's configuration:
            # no conversion can run in this state anyway, and the missing-rates
            # error is reported separately.
            return code
        raise CurrencyError(codeString)

    def format_number(self, number, fullDigits=False):
        if fullDigits:
            formatted = '{:,.8f}'.format(number).rstrip('0').rstrip('.')
        else:
            formatted = '{:,.2f}'.format(number).rstrip('.')
        return formatted

    def convert(self, query):
        results = []
        for destination in query['destinations']:
            destinationCode = self.validate_code(destination['currency'], True)
            total = 0
            srcDescription = ''
            for index, source in enumerate(query['sources']):
                sourceCode = self.validate_code(source['currency'])
                rate = self.rate(destinationCode) / self.rate(sourceCode)
                amount = source['amount'] if source['amount'] else 1
                convertedAmount = rate * amount
                total += convertedAmount
                if amount < 0 or index > 0:
                    srcDescription += ' - ' if amount < 0 else ' + '
                srcDescription += '{} {}'.format(self.format_number(abs(amount)),
                                                 self.name(sourceCode))

            fullDigits = len(query['sources']) == 1 and \
                (query['sources'][0]['amount'] or 1) == 1

            formatted_total = self.format_number(total, fullDigits)
            result = {
                'amount': total,
                'description': srcDescription,
                'title': '{}'.format(formatted_total + ' ' + self.name(destinationCode))
            }
            results.append(result)
        return results

    def set_default_cur_in(self, string):
        code = normalize_code(string)
        if not code:
            return False
        if self.knows(code) or not self._currencies:
            self.default_cur_in = code
            return True
        return False

    def set_default_curs_out(self, string):
        """Keep the codes we recognize and report the rest.

        Returns (accepted, rejected). This used to be all-or-nothing, so a single
        unrecognized token - a trailing comma in 'USD, EUR, JPY' was enough -
        threw the whole list away and reverted to the built-in default.
        """
        tokens = [t for t in re.split(r'[\s,;]+', str(string).strip()) if t]
        optimistic = not self._currencies
        accepted = []
        rejected = []
        for token in tokens:
            code = normalize_code(token)
            if self.knows(code) or optimistic:
                if code not in accepted:
                    accepted.append(code)
            else:
                rejected.append(token)
        if accepted:
            self.default_curs_out = accepted
        return accepted, rejected
