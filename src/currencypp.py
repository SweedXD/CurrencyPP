from exchange import ExchangeRates, UpdateFreq, CurrencyError
from flox.utils import cache_path
from parsy import ParseError
from currencyparser import make_parser, ParserProperties
from flox import Flox, clipboard


class CurrencyPP(Flox):

    broker = None

    def __init__(self):
        """Initialize the CurrencyPP plugin."""
        super().__init__()
        self.logger_level("debug")
        self.logger.debug("=== CurrencyPP Plugin Initializing ===")
        self._read_config()

    def query(self, user_input):
        """Process a currency conversion query from the user."""
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
            if self.broker.tryUpdate():
                self._update_update_item()
                
            if self.broker.error:
                self.add_item("Webservice failed", f"{self.broker.error}")
                return
                
            # Perform conversion and show results
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

        # Always show the update status
        self.add_item(
            'Update Currency',
            'Last updated at ' + self.broker.last_update.isoformat(),
            method=self.update_rates,
            parameters=[user_input],
            dont_hide=True
        )

    def item_action(self, amount):
        clipboard.put(str(amount))

    def update_rates(self, last_query):
        self.broker.update()
        self.change_query(str(last_query), True)

    def reload_settings(self):
        """Handle plugin settings changes from the Flow Launcher UI."""
        try:
            if self.broker:
                # Save current state for change detection
                old_state = {
                    'input': getattr(self.broker, 'default_cur_in', None),
                    'output': getattr(self.broker, 'default_curs_out', None)
                }
            
            # Reload and apply new settings
            self.settings.reload()
            self._read_config()
            
            # Check for and handle currency changes
            if self.broker:
                if old_state['input'] != self.broker.default_cur_in:
                    self.logger.info(f"Input currency updated: {old_state['input']} -> {self.broker.default_cur_in}")
                if old_state['output'] != self.broker.default_curs_out:
                    self.logger.info(f"Output currencies updated: {old_state['output']} -> {self.broker.default_curs_out}")
                
                # Force rate update if currencies changed
                if (old_state['input'] != self.broker.default_cur_in or 
                    old_state['output'] != self.broker.default_curs_out):
                    self.broker.force_update()
                    
        except Exception as e:
            self.logger.error(f"Settings reload failed: {e}")
            # Attempt recovery through full reset
            try:
                if hasattr(self, 'broker'):
                    delattr(self, 'broker')
                self._read_config()
            except Exception as e2:
                self.logger.critical(f"Settings recovery failed: {e2}")

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
        try:
            default_cur_in = self.broker.default_cur_in
            default_curs_out = self.broker.default_curs_out
            
            base_query = {
                'sources': None if empty else [{'currency': default_cur_in, 'amount': 1.0}],
                'destinations': None if empty else [{'currency': cur} for cur in default_curs_out],
                'extra': None
            }
        except Exception as e:
            self.logger.error(f"Error creating base query: {e}")
            base_query = {
                'sources': None if empty else [{'currency': 'USD', 'amount': 1.0}],
                'destinations': None if empty else [{'currency': 'EUR'}],
                'extra': None
            }

        if not user_input or not user_input.strip():
            return base_query

        user_input = user_input.strip()
        
        # Handle direct number input (e.g., "100")
        try:
            amount = float(user_input)
            return {
                'sources': [{'currency': self.broker.default_cur_in, 'amount': amount}],
                'destinations': [{'currency': cur} for cur in self.broker.default_curs_out],
                'extra': None
            }
        except ValueError:
            pass  # Not a number, continue with full parsing

        # Parse and validate full query
        try:
            parsed = self.parser.parse(user_input)
            
            # Apply default currencies if not specified
            if not parsed.get('destinations'):
                parsed['destinations'] = [{'currency': cur} for cur in self.broker.default_curs_out]
            if not parsed.get('sources'):
                parsed['sources'] = [{'currency': self.broker.default_cur_in, 'amount': 1.0}]
            
            return parsed
            
        except ParseError:
            return base_query

    def _read_config(self):
        """Load configuration from settings.json and initialize the plugin.
        This method is called during __init__ and by reload_settings() when settings change.
        Uses defensive programming to prevent crashes from malformed settings.
        This method is idempotent - it can be safely called multiple times to reload settings.
        
        CRITICAL: This method has been refactored to fix a runtime state corruption bug.
        The bug was caused by re-instantiating the ExchangeRates broker during settings reload,
        which reset user-configured default currencies back to hardcoded class defaults.
        The fix ensures the broker instance is created only once and its state is preserved.
        """
        def _warn_cur_code(name, fallback):
            try:
                fmt = "Invalid {} value in config. Using: {}"
                self.logger.warning(fmt.format(name, fallback))
            except:
                pass  # Prevent logging errors from crashing the plugin

        try:
            # Read update frequency with safe fallback
            update_freq_str = self.settings.get('update_freq', 'daily')
            if not update_freq_str or not isinstance(update_freq_str, str):
                update_freq_str = 'daily'
            self.update_freq = UpdateFreq(update_freq_str)
        except:
            self.update_freq = UpdateFreq('daily')

        try:
            # Read API key with safe fallback
            app_id_key = self.settings.get('app_id', '')
            if not isinstance(app_id_key, str):
                app_id_key = ''
            app_id_key = app_id_key.strip()
        except:
            app_id_key = ''

        # Initialize or update the broker
        try:
            # Ensure cache directory exists
            cache_dir = cache_path(self.name)
            cache_dir.mkdir(exist_ok=True)
            
            # Track if this is first initialization
            is_first_init = not hasattr(self, 'broker') or self.broker is None
            
            if is_first_init:
                # First-time initialization only
                self.broker = ExchangeRates(
                    cache_dir, self.update_freq, app_id_key, self)
                self.logger.info("Created new ExchangeRates broker instance")
            else:
                # CRITICAL FIX: During settings reload, preserve the existing broker
                # but ensure all its configuration is fully updated
                self.logger.info("Updating existing broker instance during settings reload")
                
                # 1. Verify we can access the existing broker
                if not self.broker or not hasattr(self.broker, 'update_freq'):
                    raise ValueError("Invalid broker state detected")
                    
                # 2. Update configuration and track changes
                changes = []
                
                if self.broker.update_freq != self.update_freq:
                    self.broker.update_freq = self.update_freq
                    changes.append("update frequency")
                    
                if (hasattr(self.broker, 'expensive_service') and 
                    self.broker.expensive_service and 
                    self.broker.expensive_service.app_id != app_id_key):
                    self.broker.expensive_service.app_id = app_id_key
                    changes.append("API key")
                
                # 3. Reset broker state
                self.broker.clear_aliases()
                self.broker.error = None
                
                # 4. Force immediate update if config changed
                if changes:
                    self.logger.info("Config changes detected: " + ", ".join(changes))
                    self.broker.force_update()
                    self.logger.info("Forced rate refresh due to config changes")
        except Exception as e:
            self.logger.error("Failed to initialize ExchangeRates broker: {}".format(e))
            return

        # --- Read and set input currency from user settings ---
        # This section runs for both new brokers and existing brokers during live reload
        try:
            # Get input currency from settings
            current_input = getattr(self.broker, 'default_cur_in', None)
            self.logger.debug(f"Current input currency before update: {current_input}")
            
            input_code = self.settings.get('input_cur', 'USD' if is_first_init else current_input)
            if not isinstance(input_code, str) or not input_code.strip():
                input_code = 'USD' if is_first_init else current_input
            input_code = input_code.strip()
            
            self.logger.debug(f"New input currency from settings: {input_code}")
            
            if is_first_init:
                # First run - try to set the currency, fall back to USD if needed
                success = self.broker.set_default_cur_in(input_code)
                if not success:
                    self.logger.warning(f"Failed to set initial input currency: {input_code}")
                    self.broker.set_default_cur_in('USD')
            else:
                # During reload, only update if the setting actually changed
                if current_input and input_code != current_input:
                    self.logger.info(f"Updating input currency from '{current_input}' to '{input_code}'")
                    success = self.broker.set_default_cur_in(input_code)
                    if not success:
                        self.logger.warning(f"Failed to update input currency to: {input_code}")
                        self.logger.info(f"Keeping existing input currency: {current_input}")
                else:
                    self.logger.debug("Input currency unchanged, skipping update")
        except Exception as e:
            if is_first_init:
                self.logger.warning("Error setting input currency, using USD: {}".format(e))
                self.broker.set_default_cur_in('USD')
            else:
                self.logger.error("Error updating input currency: {}".format(e))

        # --- Handle Output Currencies ---
        # FINAL RUNTIME STATE CORRUPTION FIX:
        # The root cause was that this fallback logic would overwrite user settings during runtime
        # (e.g., when exchange rates are updated and validation temporarily fails).
        # The fix: Only use fallbacks during first-run bootstrap, preserve user settings at runtime.
        
        # 1. Define a single, authoritative default value. This is the only place it needs to be set.
        DEFAULT_OUTPUT_CUR = 'USD EUR JPY'
        ULTIMATE_FALLBACK_CUR = 'USD EUR'  # A minimal, safe fallback for bootstrap only

        try:
            # 2. Get the user's setting from settings.json, falling back to our default if it's missing.
            output_code = self.settings.get('output_cur', DEFAULT_OUTPUT_CUR)

            # 3. Sanitize the value. If it's not a string or is empty after stripping, use the default.
            if not isinstance(output_code, str) or not output_code.strip():
                output_code = DEFAULT_OUTPUT_CUR
            else:
                output_code = output_code.strip()

            # 4. Handle output currencies differently for first run vs. reload
            current_currencies = getattr(self.broker, 'default_curs_out', None)
            self.logger.debug(f"Current output currencies before update: {current_currencies}")
            self.logger.debug(f"New output currencies from settings: {output_code}")
            
            if is_first_init:
                # On first run, try user setting, then default, then fallback
                success = self.broker.set_default_curs_out(output_code)
                if not success:
                    self.logger.warning(f"Failed to set initial output currencies: {output_code}")
                    if not self.broker.set_default_curs_out(DEFAULT_OUTPUT_CUR):
                        self.logger.warning(f"Failed to set default output currencies: {DEFAULT_OUTPUT_CUR}")
                        self.broker.set_default_curs_out(ULTIMATE_FALLBACK_CUR)
            else:
                # During runtime/reload, ONLY update if the setting actually changed
                if current_currencies is None:
                    # Something's wrong, broker lost its state
                    self.logger.error("Broker lost currency state during reload")
                    success = self.broker.set_default_curs_out(output_code)
                    if not success:
                        self.broker.set_default_curs_out(ULTIMATE_FALLBACK_CUR)
                else:
                    # Convert current_currencies to space-separated string for comparison
                    current_str = ' '.join(current_currencies)
                    if current_str != output_code:
                        # Only try to update if the setting actually changed
                        self.logger.info(f"Updating output currencies from '{current_str}' to '{output_code}'")
                        success = self.broker.set_default_curs_out(output_code)
                        if success:
                            self.logger.info("Successfully updated output currencies")
                        else:
                            self.logger.warning(f"Failed to update to new output currencies: {output_code}")
                            self.logger.info(f"Keeping existing currencies: {current_str}")
                    else:
                        self.logger.debug("Output currencies unchanged, skipping update")

        except Exception as e:
            # 6. If any other unexpected error occurs, preserve existing settings during runtime
            existing_currencies = getattr(self.broker, 'default_curs_out', None)
            if not existing_currencies or existing_currencies == ['USD', 'EUR', 'JPY']:
                # First-run bootstrap: use safe fallback
                self.logger.error("Error processing output currencies during bootstrap: {}. "
                                  "Using safe default '{}'.".format(e, ULTIMATE_FALLBACK_CUR))
                self.broker.set_default_curs_out(ULTIMATE_FALLBACK_CUR)
            else:
                # Runtime: preserve existing user settings
                self.logger.error("Error processing output currencies during runtime: {}. "
                                  "Preserving existing settings: {}.".format(e, existing_currencies))

        # Read separators from settings with safe fallbacks
        try:
            separators_string = self.settings.get('separators', 'to in :')
            if not isinstance(separators_string, str):
                separators_string = 'to in :'
            separators_string = separators_string.strip()
            separators = separators_string.split() if separators_string else ['to', 'in', ':']
            if not separators:
                separators = ['to', 'in', ':']
        except:
            separators = ['to', 'in', ':']

        # Read destination separators from settings with safe fallbacks
        try:
            dest_seps_string = self.settings.get('destination_separators', 'and & ,')
            if not isinstance(dest_seps_string, str):
                dest_seps_string = 'and & ,'
            dest_seps_string = dest_seps_string.strip()
            dest_separators = dest_seps_string.split() if dest_seps_string else ['and', '&', ',']
            if not dest_separators:
                dest_separators = ['and', '&', ',']
        except:
            dest_separators = ['and', '&', ',']

        # Read and process aliases from settings with comprehensive error handling
        # Clear all existing aliases to ensure clean state on reload
        try:
            self.broker.clear_aliases()  # This ensures idempotent behavior
            aliases_string = self.settings.get('aliases', 'EUR = euro euros\nusd = dollar dollars $ bucks')
            
            if aliases_string and isinstance(aliases_string, str):
                for line in aliases_string.splitlines():
                    try:
                        line = line.strip()
                        if not line or '=' not in line:
                            continue
                        
                        parts = line.split('=', 1)
                        if len(parts) != 2:
                            continue
                            
                        key = parts[0].strip()
                        aliases_part = parts[1].strip()
                        
                        if not key or not aliases_part:
                            continue

                        # Validate the currency key
                        try:
                            validated_key = self.broker.validate_code(key)
                            if validated_key:
                                aliases = aliases_part.split()
                                for alias in aliases:
                                    if alias:  # Skip empty aliases
                                        try:
                                            validated_alias = self.broker.validate_alias(alias)
                                            if validated_alias:
                                                self.broker.add_alias(validated_alias, validated_key)
                                        except:
                                            continue  # Skip invalid aliases silently
                        except:
                            continue  # Skip invalid currency keys silently
                    except Exception:
                        continue  # Skip malformed lines silently
        except Exception as e:
            self.logger.warning("Error processing aliases: {}".format(e))

        # CRITICAL: Parser initialization must ALWAYS succeed for plugin to work
        # If it fails, we keep retrying with increasingly minimal configurations
        parser_initialized = False
        
        # Attempt 1: Full configuration
        try:
            properties = ParserProperties()
            properties.default_cur_in = getattr(self.broker, 'default_cur_in', 'USD')
            properties.default_curs_out = getattr(self.broker, 'default_curs_out', ['USD', 'EUR'])
            properties.to_keywords = separators
            properties.sep_keywords = dest_separators
            properties.aliases = getattr(self.broker, 'aliases', {})
            
            self.parser = make_parser(properties)
            parser_initialized = True
            self.logger.info("Parser initialized successfully with full configuration")
            
        except Exception as e:
            self.logger.error("Full parser initialization failed: {}".format(e))
            
            # Attempt 2: Minimal configuration with current currencies
            try:
                minimal_props = ParserProperties()
                minimal_props.default_cur_in = getattr(self.broker, 'default_cur_in', 'USD')
                minimal_props.default_curs_out = getattr(self.broker, 'default_curs_out', ['USD', 'EUR'])
                
                self.parser = make_parser(minimal_props)
                parser_initialized = True
                self.logger.warning("Parser initialized with minimal configuration (currencies only)")
                
            except Exception as e2:
                self.logger.error("Minimal parser initialization failed: {}".format(e2))
                
                # Final Attempt: Absolute minimal fallback
                try:
                    ultimate_props = ParserProperties()
                    self.parser = make_parser(ultimate_props)
                    parser_initialized = True
                    self.logger.warning("Parser initialized with ultimate fallback configuration")
                    
                except Exception as e3:
                    self.logger.critical("All parser initialization attempts failed")
                    self.parser = None
        
        if not parser_initialized:
            self.logger.critical("Parser initialization completely failed - plugin may not function correctly")
            # Even here, we don't return - let the plugin try to continue
        
        # Log the final configuration for debugging (with safe string formatting)
        try:
            input_cur = getattr(self.broker, 'default_cur_in', 'USD')
            output_curs = getattr(self.broker, 'default_curs_out', ['USD'])
            alias_count = len(getattr(self.broker, 'aliases', {}))
            self.logger.info("Plugin configured with input currency: {}".format(input_cur))
            self.logger.info("Plugin configured with output currencies: {}".format(output_curs))
            self.logger.info("Plugin configured with {} aliases".format(alias_count))
        except:
            self.logger.info("Plugin configuration completed")


if __name__ == "__main__":
    CurrencyPP()
