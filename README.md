# Mihaaru Dhivehi News Translation Userbot (Telethon)

This script monitors a specified Telegram channel for new messages containing URLs to Dhivehi news articles using your personal Telegram account (via Telethon). It then scrapes the article content, translates it to English using either OpenAI or Anthropic (Claude), and sends the translated article to your chosen chat or channel.

**Important Note:** This version uses Telethon and your personal Telegram account. It is different from a standard Telegram Bot API bot.

## Features
- Monitors a Telegram channel for new article links using your Telegram account.
- Scrapes and extracts the main article text based on HTML comments and structure.
- Translates Dhivehi news articles to English using **OpenAI or Anthropic (Claude)**.
- Sends the translated article to your Telegram chat or channel (splits long messages).
- Allows manual translation of a URL via a `/translate <URL>` command.

## Prerequisites
- Python 3.8+
- A personal Telegram account.
- API credentials from Telegram (API ID and API Hash).
- An API key from **either OpenAI or Anthropic**.

## Setup

1.  **Clone the repository (if you haven't already):**
    ```bash
    # git clone <repository_url>
    # cd <repository_directory>
    ```

2.  **Create a virtual environment and activate it:**
    ```bash
    python -m venv .venv
    # On Windows
    .venv\Scripts\activate
    # On macOS/Linux
    source .venv/bin/activate
    ```

3.  **Install dependencies:**
    ```bash
    pip install -r requirements.txt
    ```
    The `requirements.txt` file includes:
    - `telethon`: For interacting with the Telegram API as a user.
    - `python-dotenv`: For managing environment variables.
    - `aiohttp`: For asynchronous HTTP requests (used for fetching article content).
    - `beautifulsoup4`: For parsing HTML content.
    - `openai`: For the OpenAI API (if chosen as provider).
    - `anthropic`: For the Anthropic API (if chosen as provider).
    - `nest_asyncio`: To allow Telethon's asyncio loop to run within other asyncio environments if needed.

4.  **Create a `.env` file:**
    Copy the `example.env` (if provided, otherwise create a new file named `.env`) and fill in your credentials:
    ```env
    TELEGRAM_API_ID=YOUR_TELEGRAM_API_ID
    TELEGRAM_API_HASH=YOUR_TELEGRAM_API_HASH
    TELEGRAM_SESSION_NAME=mihaaru_translator_user # Or any name for your session file

    MIHAARU_CHANNEL_ID=YOUR_MIHAARU_CHANNEL_ID_OR_USERNAME # e.g., -1001234567890 or 'channelusername'
    TARGET_CHANNEL_ID=YOUR_TARGET_CHANNEL_ID_OR_USERNAME # e.g., -1009876543210 or 'mytranslationchannel'

    # --- Translation Provider Configuration ---
    # Choose your translation provider: 'openai' or 'anthropic'
    TRANSLATION_PROVIDER=openai 

    # --- OpenAI Configuration (only needed if TRANSLATION_PROVIDER='openai') ---
    OPENAI_API_KEY=YOUR_OPENAI_API_KEY
    OPENAI_MODEL_NAME=gpt-3.5-turbo # Optional, defaults to gpt-3.5-turbo

    # --- Anthropic Configuration (only needed if TRANSLATION_PROVIDER='anthropic') ---
    ANTHROPIC_API_KEY=YOUR_ANTHROPIC_API_KEY
    ANTHROPIC_MODEL_NAME=claude-3-haiku-20240307 # Optional, defaults to claude-3-haiku-20240307 (fast & good for translation)
    # Other options: claude-3-sonnet-20240229, claude-3-opus-20240229
    ```
    - **`TELEGRAM_API_ID`** and **`TELEGRAM_API_HASH`**: Get these from [my.telegram.org](https://my.telegram.org) > API development tools.
    - **`TELEGRAM_SESSION_NAME`**: A name for the session file Telethon will create (e.g., `my_user_session`). This file stores your login session so you don't have to re-authenticate every time.
    - **`MIHAARU_CHANNEL_ID`**: The ID or username of the Mihaaru channel to monitor. For public channels, it can be the username (e.g., 'MihaaruNews'). For private channels or if you prefer using IDs, you'll need the numerical ID (often starting with -100 for channels).
    - **`TARGET_CHANNEL_ID`**: The ID or username of the channel/chat where translated articles should be sent.
    - **`TRANSLATION_PROVIDER`**: Set to `openai` or `anthropic`.
    - **`OPENAI_API_KEY`**: Your OpenAI API key (if using OpenAI).
    - **`OPENAI_MODEL_NAME`**: (Optional) The OpenAI model to use. Defaults to `gpt-3.5-turbo`.
    - **`ANTHROPIC_API_KEY`**: Your Anthropic API key (if using Anthropic).
    - **`ANTHROPIC_MODEL_NAME`**: (Optional) The Anthropic model to use. Defaults to `claude-3-haiku-20240307`. Other good options for translation could be `claude-3-sonnet-20240229`.

## Running the Userbot

1.  **Ensure your `.env` file is correctly configured.**
2.  **Run the script from your activated virtual environment:**
    ```bash
    python mihaaru_translate_bot.py
    ```
3.  **First Run - Telegram Authentication:**
    - If this is the first time you're running the script with your `TELEGRAM_API_ID` and `TELEGRAM_API_HASH`, Telethon will prompt you in the console to enter your phone number, then a login code sent to your Telegram account.
    - Once authenticated, Telethon will create a session file (e.g., `mihaaru_translator_user.session` or whatever you named it in `TELEGRAM_SESSION_NAME`). Subsequent runs will use this session file and won't require you to log in again unless the session becomes invalid.

4.  **Operation:**
    - The userbot will connect to your Telegram account.
    - It will start listening for new messages in the specified `MIHAARU_CHANNEL_ID`.
    - When a message containing a URL is detected, it will attempt to fetch, parse, and translate the article.
    - The translated content will be sent to the `TARGET_CHANNEL_ID`.
    - You can also manually trigger a translation by sending a message `/translate <article_url>` to any chat the userbot is in (e.g., your Saved Messages, or the target channel if your user account can post there).

## Logging
- The script logs its activities to the console, including connection status, detected articles, translation attempts, and any errors.
- Debug logs (commented out by default in the script) can be enabled for more detailed troubleshooting of article scraping and API interactions.

## How it Works

1.  **Telethon Client**: Connects to Telegram as a user account using your API ID and Hash.
2.  **Event Handler**: Listens for new messages in the `MIHAARU_CHANNEL_ID`.
3.  **URL Extraction**: If a message contains a URL, it's extracted.
4.  **Article Fetching (`aiohttp`)**: The content of the URL is fetched asynchronously.
5.  **Content Scraping (`BeautifulSoup4`)**: The HTML is parsed. The script looks for a comment `<!-- article body -->` and then tries to extract paragraph (`<p>`) tags that match specific Dhivehi news styling. It has fallback mechanisms if the primary method fails.
6.  **Translation (OpenAI or Anthropic)**: The extracted Dhivehi text is sent to the chosen LLM API for translation to English.
7.  **Message Sending**: The translated English text, along with a link to the original article, is sent to the `TARGET_CHANNEL_ID` via Telethon. Long messages are automatically split.

## Important Considerations
- **User Account, Not a Bot Account**: This script uses your personal Telegram account. Be mindful of Telegram's terms of service and API usage limits to avoid any issues with your account.
- **API Costs**: Calls to OpenAI or Anthropic APIs are not free. Monitor your usage and costs on their respective platforms.
- **Error Handling**: The script includes basic error handling, but complex scraping or API issues might require further debugging.
- **Scraping Robustness**: Website structures can change, which might break the scraping logic. The current selectors are based on observed patterns on Mihaaru news articles but might need adjustments if the site's HTML changes significantly.

## License
MIT 