import sys
import os
parent_folder_path = os.path.abspath(os.path.dirname(__file__))
sys.path.append(parent_folder_path)
sys.path.append(os.path.join(parent_folder_path, 'lib'))
sys.path.append(os.path.join(parent_folder_path, 'src'))

from currencypp import CurrencyPP

if __name__ == "__main__":
    plugin = CurrencyPP()
    CurrencyPP.__del__ = lambda self: None
    plugin.run()
