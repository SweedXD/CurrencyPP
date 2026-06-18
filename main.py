import sys
import os

# Reconfigure standard streams to use UTF-8 (prevents encoding crashes under Windows Turkish/non-UTF-8 locales)
for stream in (sys.stdout, sys.stderr):
    if stream and hasattr(stream, 'reconfigure'):
        try:
            stream.reconfigure(encoding='utf-8')
        except Exception:
            pass

parent_folder_path = os.path.abspath(os.path.dirname(__file__))
sys.path.append(parent_folder_path)
sys.path.append(os.path.join(parent_folder_path, 'lib'))
sys.path.append(os.path.join(parent_folder_path, 'src'))

# Monkeypatch Flox components to resolve encoding issues and reload bugs without touching the library files
try:
    from flox.settings import Settings
    import json

    def patched_load(self):
        data = {}
        with open(self._filepath, 'r', encoding='utf-8') as f:
            try:
                data.update(json.load(f))
            except json.decoder.JSONDecodeError:
                pass
        self._save = False
        self.clear()
        self.update(data)
        self._save = True

    def patched_save(self):
        if self._save:
            data = {}
            data.update(self)
            with open(self._filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, sort_keys=True, indent=4)

    Settings._load = patched_load
    Settings.save = patched_save
    Settings.reload = lambda self: self._load()
except Exception:
    pass

try:
    import flox.utils
    from pathlib import Path
    
    def patched_write_json(data, path):
        if not Path(path).parent.exists():
            Path(path).parent.mkdir(parents=True)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f)
            
    flox.utils.write_json = patched_write_json
except Exception:
    pass

from currencypp import CurrencyPP  # type: ignore

if __name__ == "__main__":
    CurrencyPP()
