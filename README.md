# CurrencyPP (Settings UI Fixed)
This is a community-maintained fork of the original [CurrencyPP](https://github.com/LeLocTai/Flow.Launcher.Plugin.CurrencyPP) plugin by **[LeLocTai](https://github.com/LeLocTai)**. The primary purpose of this fork is to provide a usable version for users affected by the broken settings UI bug.

<img width="826" height="711" alt="image" src="https://github.com/user-attachments/assets/6164e8f2-a8f6-4bd6-a1ff-b02ad94cbc91" />

## ✨ What's New in This Fork

This version addresses the most critical bug preventing users from configuring the plugin.

*   ✅ **Fixed Broken Settings UI:** The main achievement of this fork is a completely repaired settings page. All configuration options (API Key, default currencies, aliases, etc.) are now fully visible and editable within the Flow Launcher settings window.
> 🔄 **Restart Required:** Right-click the Flow Launcher tray icon, choose **Exit**, and reopen the app for changes to take effect.

## 🚀 Installation
### 📦 Install from Flow Launcher Plugin Store

1. Launch Flow Launcher (`Alt + Space`)
2. Type `pm install CurrencyPP by SweedXD` and search for CurrencyPP (UI Fixed) and hit **Enter**

That’s it — the plugin will be installed and ready to use instantly 🎉

---

### 🛠 Manual Installation

1.  Go to the [**Releases**](https://github.com/YOUR_USERNAME/YOUR_REPOSITORY/releases) page of this repository.
2.  Download the latest `.zip` file.
3.  Unzip the contents into your Flow Launcher's plugins directory (`%APPDATA%\FlowLauncher\Settings\Plugins`).
4.  Restart Flow Launcher.

## 💡 Usage

The core currency conversion functionality remains the same.

| Query Type                         | Example                                                                | Description                                                                  |
| ---------------------------------- | ---------------------------------------------------------------------- | ---------------------------------------------------------------------------- |
| **Simple Conversion**              | `5 . EUR`                                                              | Converts 5 of your default input currency to your default output currencies. |
| **Specific Amount & Currency**     | `100 usd`                                                              | Converts 100 US Dollars to your default output currencies.                   |
| **Specify Source and Destination** | `50 eur usd`<br>`100 gbp . jpy`<br>`100 gbp : jpy`<br>`100 gbp to jpy` | Converts 100 British Pounds to Japanese Yen.                                 |
| **Specify Multiple Destinations**  | `50 eur usd , cad`<br>`50 eur usd & cad`<br>`50 eur usd and cad`       | Converts 50 Euros to both US Dollars and Canadian Dollars.                   |
| **Using Aliases/Symbols**          | `EUR = euro euros €`                                                   | Use common symbols or custom-defined aliases for currencies.                 |

- 💡 **Tip:** You can configure the **`$` alias** (or any other) to match any currency you want—making conversions quicker and more intuitive.
### Math

| **Functionality**           | **Example**            | **Description**                                                 |
| --------------------------- | ---------------------- | --------------------------------------------------------------- |
| **Simple arithmetic**       | `10 + 5 USD in EUR`    | Adds a number to the source amount before converting.           |
| **Grouped math on input**   | `10*(2+1) USD in EUR`  | Uses math expressions (with parentheses) on the source amount.  |
| **Math on result**          | `5 USD in EUR / 2`     | Converts first, then divides the resulting amount.              |
| **Multi-currency addition** | `5 USD + 2 GBP in EUR` | Adds values from different currencies, then converts the total. |


## ⚙️ Configuration

You can configure the plugin from the Flow Launcher settings window. **Remember to restart Flow Launcher after making changes.**

| Setting                       | Description                                                                                                                                                          |
| ----------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Update Frequency**          | How often the plugin should fetch new rates. "Daily" is recommended for most users.                                                                                  |
| **Default input currency**    | The currency code (e.g., `USD`) to use when you use Simple Conversion, etc.                                                                                          |
| **Default output currencies** | A space-separated list of currency codes (e.g., `USD EUR JPY`) to show as results when no destination currency is specified in the query.                            |
| **OpenExchangeRates App ID**  | App ID for OpenExchangeRates, used if the cache fails. (untested)                                                                                                    |
| **Separator**                 | Source-to-destination separators (whitespace-separated). Examples include `to`, `in`, `:` and `.`                                                                    |
| **Destination Separator**     | Separators used between multiple destination currencies (whitespace-separated). Examples include `and`, `&`, and `,`                                                 |
| **Aliases**                   | Define custom aliases for currencies, one per line. Use the format `CODE = symbol` (space-separated). **Example:** `USD = $ dollar dollars bucks` `EUR = euro euros` |

## 📚 Additional Features (from Original Plugin)

The original Currency++ plugin includes advanced functionality for math operations, grammar-based queries, and backend integrations.

**Please Note:** The focus of this fork was solely on fixing the settings UI. These advanced features have **not been tested** in this version. For detailed documentation on how to use them, please refer to the [**Original Repository's Documentation**](https://github.com/LeLocTai/Flow.Launcher.Plugin.CurrencyPP).

## 👨‍💼 Credits

*   Original updated plugin created by **@LeLocTai**.
*   This updated version was created by **@SweedXD**.
