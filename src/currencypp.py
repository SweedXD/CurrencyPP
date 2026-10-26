import json
import locale
import logging
import logging.handlers
import re

from functools import cached_property

from exchange import ExchangeRates, UpdateFreq, CurrencyError
from flox.utils import cache_path
from parsy import ParseError
from currencyparser import make_parser, ParserProperties
from flox import Flox, clipboard


DEFAULT_INPUT_CUR = 'USD'
DEFAULT_OUTPUT_CUR = 'USD EUR JPY'
DEFAULT_SEPARATORS = 'to in : .'
DEFAULT_DEST_SEPARATORS = 'and & ,'
DEFAULT_ALIASES = 'USD = $ dollar dollars bucks\nEUR = euro euros'
DEFAULT_UPDATE_FREQ = 'daily'


class CurrencyPP(Flox):

    def __init__(self):
        """Set up cheap state only.

        Configuration deliberately does not happen here: flox fills
        `self._settings` while parsing argv inside Launcher.run(), which runs
        after __init__, so anything reading settings this early would only ever
        see the file on disk. See _ensure_config().
        """
        super().__init__()
        self.logger_level("debug")
        self.broker = None
        self.parser = None
        self.config_warnings = []
        self._disk_settings = None
        self._configured = False

    @cached_property
    def logger(self):
        """The same rotating plugin.log as flox, but written as UTF-8.

        flox opens it with the process default encoding (flox/__init__.py:275),
        which is the ANSI codepage on Windows. Any message containing '₺' - or a
        localized alias, or a currency name - then raises inside logging, gets
        dropped, and leaks a traceback onto stderr. Those are exactly the lines a
        non-English user needs in order to see why a setting was rejected.
        """
        logger = logging.getLogger('CurrencyPP')
        logger.propagate = False
        if not logger.handlers:
            handler = logging.handlers.RotatingFileHandler(
                self.logfile, maxBytes=1024 * 2024, backupCount=1, encoding='utf-8')
            handler.setFormatter(logging.Formatter(
                '%(asctime)s %(levelname)s (%(filename)s): %(message)s',
                datefmt='%H:%M:%S'))
            logger.addHandler(handler)
        logger.setLevel(logging.WARNING)
        return logger

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------

    @property
    def settings(self):
        """Prefer the settings Flow sent with this request over the file on disk.

        flox 0.18.1 always re-reads Settings.json (flox/__init__.py:318) and then
        hands it back to Flow as an authoritative `SettingsChange` on every query:
        flox/launcher.py:53 guards that with `self.rpc_request.get('Settings')`
        while the request actually carries the key `settings`, so the guard never
        holds. Because this plugin uses ActionKeyword '*' it runs on every
        keystroke, and a disk snapshot that is merely a moment out of date gets
        pushed back over what the user is typing in the settings window - which is
        what made input/output currencies and aliases appear to reset themselves.

        Returning what Flow just sent makes that echo a no-op, and when Flow sends
        nothing the second half of the guard short-circuits so no SettingsChange
        is emitted at all.
        """
        if self._settings is not None:
            return self._settings
        if self._disk_settings is None:
            self._disk_settings = self._settings_from_disk()
        return self._disk_settings

    def _settings_from_disk(self):
        """Read Settings.json ourselves, as UTF-8, and never write it back.

        flox opens the file with the process default encoding, which is the ANSI
        codepage on Windows: a '₺' stored as UTF-8 either turns into mojibake or
        raises UnicodeDecodeError, which flox does not catch (it only handles
        JSONDecodeError). Its Settings class also writes an empty '{}' over a
        missing file.
        """
        try:
            path = self.settings_path
        except Exception as e:
            self.logger.error("Could not resolve the settings path: {}".format(e))
            return {}

        encodings = ['utf-8-sig']
        preferred = locale.getpreferredencoding(False)
        if preferred and preferred.lower() not in ('utf-8', 'utf8'):
            encodings.append(preferred)

        for encoding in encodings:
            try:
                with open(path, 'r', encoding=encoding) as f:
                    data = json.load(f)
            except FileNotFoundError:
                return {}
            except UnicodeDecodeError:
                self.logger.warning(
                    "{} is not valid {}, trying the next encoding".format(path, encoding))
                continue
            except (json.JSONDecodeError, OSError) as e:
                self.logger.error("Could not read settings from {}: {}".format(path, e))
                return {}
            return data if isinstance(data, dict) else {}

        self.logger.error("Could not decode {} with any known encoding".format(path))
        return {}

    def _ensure_config(self, force=False):
        """Build the broker and parser once per process, on first use."""
        if self._configured and not force:
            return
        if force:
            self._disk_settings = None
        self._configured = True
        self._read_config()

    def reload_settings(self):
        """Called by Flow when the user changes settings."""
        self._ensure_config(force=True)

    # ------------------------------------------------------------------
    # Query handling
    # ------------------------------------------------------------------

    def query(self, user_input):
        """Process a currency conversion query from the user."""
        self._ensure_config()
        if self.broker is None or self.parser is None:
            # Startup failed outright; it is already logged. Stay quiet rather
            # than putting an error on every unrelated search, since this plugin
            # sees every query.
            return

        self.logger.debug(f"Processing query: '{user_input}'")

        try:
            # Validate query format
            if not self._is_direct_request(self._parse_and_merge_input(user_input, True)):
                return

            # Parse and validate query content
            query = self._parse_and_merge_input(user_input)
            if not query or query.get('destinations') is None or query.get('sources') is None:
                return

            # Update rates if needed
            self.broker.tryUpdate()

            if self.broker.error:
                self.add_item("Webservice failed", f"{self.broker.error}")
            elif not self.broker.has_rates:
                self.add_item("No exchange rates available",
                              "Click 'Update Currency' below to try again")
            else:
                results = self.broker.convert(query)
                for result in results:
                    self.add_item(
                        result['title'],
                        result['description'],
                        context=result['description'],
                        method=self.item_action,
                        parameters=[result['amount']],
                        score=100,
                    )

        except CurrencyError as ce:
            self.logger.error(f"Currency error: {ce}")
            return
        except Exception as e:
            self.logger.error("Unexpected error", exc_info=True)
            self.add_item("Error", f"An error occurred: {str(e)}")

        # Tell the user about settings we could not apply, instead of letting
        # them look like the settings reset themselves.
        for warning in self.config_warnings:
            self.add_item(
                'Check the CurrencyPP settings',
                warning,
                score=90,
                dont_hide=True,
            )

        if self.broker.last_update:
            update_subtitle = 'Last updated at ' + self.broker.last_update.isoformat()
        else:
            update_subtitle = 'Exchange rates have never been loaded'
        self.add_item(
            'Update Currency',
            update_subtitle,
            method=self.update_rates,
            parameters=[user_input],
            dont_hide=True
        )

    def item_action(self, amount):
        clipboard.put(str(amount))

    def update_rates(self, last_query):
        self._ensure_config()
        if self.broker:
            self.broker.update()
        self.change_query(str(last_query), True)

    def _is_direct_request(self, query):
        """Determine if the query explicitly specifies currencies."""
        entered_dest = ('destinations' in query and query['destinations'] is not None)
        entered_source = (query['sources'] is not None and
                        len(query['sources']) > 0 and
                        query['sources'][0]['currency'] is not None)
        return entered_dest or entered_source

    def _parse_and_merge_input(self, user_input=None, empty=False):
        """Parse user input and merge with default currency configuration.

        Args:
            user_input: Raw input string from the user
            empty: If True, creates a query template without values

        Returns:
            dict: Parsed query with source and destination currencies
        """
        default_cur_in = self.broker.default_cur_in
        default_curs_out = self.broker.default_curs_out

        base_query = {
            'sources': None if empty else [{'currency': default_cur_in, 'amount': 1.0}],
            'destinations': None if empty else [{'currency': cur} for cur in default_curs_out],
            'extra': None
        }

        if not user_input or not user_input.strip():
            return base_query

        user_input = user_input.strip()

        # Handle direct number input (e.g., "100")
        try:
            amount = float(user_input)
            return {
                'sources': [{'currency': default_cur_in, 'amount': amount}],
                'destinations': [{'currency': cur} for cur in default_curs_out],
                'extra': None
            }
        except ValueError:
            pass  # Not a number, continue with full parsing

        # Parse and validate full query
        try:
            parsed = self.parser.parse(user_input)

            # Apply default currencies if not specified
            if not parsed.get('destinations'):
                parsed['destinations'] = [{'currency': cur} for cur in default_curs_out]
            if not parsed.get('sources'):
                parsed['sources'] = [{'currency': default_cur_in, 'amount': 1.0}]

            return parsed

        except ParseError:
            return base_query

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    def _warn(self, message):
        """Record a problem the user needs to see, not just one for the log.

        Every one of these used to be a bare `except: continue`, so a dropped
        alias or currency left no trace anywhere.
        """
        self.logger.warning(message)
        if message not in self.config_warnings:
            self.config_warnings.append(message)

    def _read_text(self, settings, key, default):
        value = settings.get(key, default)
        if not isinstance(value, str) or not value.strip():
            return default
        return value.strip()

    def _read_words(self, settings, key, default):
        """Split a setting on whitespace only.

        Deliberately not comma-tolerant, unlike the currency settings: the
        destination separators default to 'and & ,', where the comma is itself a
        token the user configured.
        """
        words = self._read_text(settings, key, default).split()
        return words or default.split()

    def _read_update_freq(self, settings):
        value = self._read_text(settings, 'update_freq', DEFAULT_UPDATE_FREQ)
        try:
            return UpdateFreq(value.lower())
        except ValueError:
            self._warn("Unknown update frequency '{}' - using '{}'".format(
                value, DEFAULT_UPDATE_FREQ))
            return UpdateFreq(DEFAULT_UPDATE_FREQ)

    def _read_config(self):
        """Load configuration and build the broker and parser.

        Idempotent: safe to call again to pick up changed settings.
        """
        self.config_warnings = []
        settings = self.settings

        self.update_freq = self._read_update_freq(settings)
        app_id = self._read_text(settings, 'app_id', '')

        try:
            cache_dir = cache_path(self.name)
            cache_dir.mkdir(exist_ok=True)
            self.broker = ExchangeRates(cache_dir, self.update_freq, app_id, self)
        except Exception as e:
            self.logger.error(
                "Failed to initialize ExchangeRates broker: {}".format(e), exc_info=True)
            self.broker = None
            return

        separators = self._read_words(settings, 'separators', DEFAULT_SEPARATORS)
        dest_separators = self._read_words(
            settings, 'destination_separators', DEFAULT_DEST_SEPARATORS)

        # Aliases come first: the default input and output currencies may be
        # written as aliases ('lira', '₺'), which only resolves once the alias
        # table is populated. The old order made that impossible.
        self._apply_aliases(settings)
        self._apply_input_currency(settings)
        self._apply_output_currencies(settings)

        properties = ParserProperties()
        properties.default_cur_in = self.broker.default_cur_in
        properties.default_curs_out = self.broker.default_curs_out
        properties.to_keywords = separators
        properties.sep_keywords = dest_separators
        properties.aliases = self.broker.aliases

        try:
            self.parser = make_parser(properties)
        except Exception as e:
            self.logger.error(
                "Parser setup failed with the configured separators, "
                "falling back to the defaults: {}".format(e), exc_info=True)
            self._warn("Could not use the configured separators - using the defaults")
            self.parser = make_parser(ParserProperties())

        self.logger.info("Configured input currency: {}".format(self.broker.default_cur_in))
        self.logger.info("Configured output currencies: {}".format(self.broker.default_curs_out))
        self.logger.info("Configured {} aliases".format(len(self.broker.aliases)))

    def _apply_aliases(self, settings):
        """Register the 'CODE = alias alias ...' lines, reporting each rejection."""
        self.broker.clear_aliases()
        raw = settings.get('aliases', DEFAULT_ALIASES)
        if not isinstance(raw, str):
            self._warn("The aliases setting is not text - ignoring it")
            return

        for line in raw.splitlines():
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if '=' not in line:
                self._warn("Alias line '{}' has no '=' - expected 'TRY = {} lira tl'".format(
                    line, '₺'))
                continue

            key, _, aliases_part = line.partition('=')
            key = key.strip()
            aliases_part = aliases_part.strip()
            if not key or not aliases_part:
                self._warn("Alias line '{}' is incomplete".format(line))
                continue

            try:
                currency = self.broker.validate_code(key)
            except CurrencyError:
                self._warn("Unknown currency '{}' - that alias line is ignored".format(key))
                continue

            # Commas and semicolons are tolerated here: 'TRY = ₺, lira, tl' is a
            # natural way to write this and used to produce aliases literally
            # named '₺,' that could never match.
            for token in re.split(r'[\s,;]+', aliases_part):
                if not token:
                    continue
                alias, reason = self.broker.validate_alias(token)
                if alias is None:
                    self._warn("Alias '{}' for {} was skipped because {}".format(
                        token, currency, reason))
                    continue
                self.broker.add_alias(alias, currency)

    def _apply_input_currency(self, settings):
        code = self._read_text(settings, 'input_cur', DEFAULT_INPUT_CUR)
        if self.broker.set_default_cur_in(code):
            return
        self._warn("Unknown input currency '{}' - using {} instead".format(
            code, DEFAULT_INPUT_CUR))
        self.broker.set_default_cur_in(DEFAULT_INPUT_CUR)

    def _apply_output_currencies(self, settings):
        raw = self._read_text(settings, 'output_cur', DEFAULT_OUTPUT_CUR)
        accepted, rejected = self.broker.set_default_curs_out(raw)

        if rejected:
            self._warn("Unknown output {}: {} - the rest are still used".format(
                'currencies' if len(rejected) > 1 else 'currency', ', '.join(rejected)))
        if not accepted:
            self._warn("No usable output currency in '{}' - using {} instead".format(
                raw, DEFAULT_OUTPUT_CUR))
            self.broker.set_default_curs_out(DEFAULT_OUTPUT_CUR)

