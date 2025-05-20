import asyncio
import logging
import os
import re
from dotenv import load_dotenv
import nest_asyncio

import aiohttp
from bs4 import BeautifulSoup, Comment
from openai import AsyncOpenAI
from anthropic import AsyncAnthropic

from telethon import TelegramClient, events
from telethon.tl.types import PeerChannel, PeerChat, PeerUser
from telethon.utils import get_peer_id

# Apply nest_asyncio at the very beginning if not already applied by another module
# This is important for environments like Jupyter notebooks or when running Telethon within an existing asyncio loop
# that might not be managed by Telethon itself.
try:
    asyncio.get_event_loop()
    nest_asyncio.apply()
except RuntimeError: # This happens if there is no current event loop
    nest_asyncio.apply()


load_dotenv()

# --- Configuration ---
TELEGRAM_API_ID = os.getenv('TELEGRAM_API_ID')
TELEGRAM_API_HASH = os.getenv('TELEGRAM_API_HASH')
SESSION_NAME = os.getenv('TELEGRAM_SESSION_NAME', 'mihaaru_translator_user') # Name for the .session file

# For MIHAARU_CHANNEL_ID and TARGET_CHANNEL_ID, Telethon can accept:
# - Integer ID (e.g., -1001234567890 for a channel, or a user ID)
# - Username (e.g., 'mihaaruchannelname' or 'myusername')
# - Invite link (e.g., 'https://t.me/joinchat/XXXXXX' or 't.me/publicchannel')
MIHAARU_CHANNEL_ENV = os.getenv('MIHAARU_CHANNEL_ID') # This will be resolved to an entity later
TARGET_CHANNEL_ENV = os.getenv('TARGET_CHANNEL_ID')   # This will be resolved to an entity later

OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
ANTHROPIC_API_KEY = os.getenv('ANTHROPIC_API_KEY')
TRANSLATION_PROVIDER = os.getenv('TRANSLATION_PROVIDER', 'openai').lower()
OPENAI_MODEL_NAME = os.getenv('OPENAI_MODEL_NAME', 'gpt-3.5-turbo')
ANTHROPIC_MODEL_NAME = os.getenv('ANTHROPIC_MODEL_NAME', 'claude-3-haiku-20240307')

# --- API Client Setup ---
openai_client = None
anthropic_client = None

if TRANSLATION_PROVIDER == 'openai':
    if OPENAI_API_KEY:
        openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)
    else:
        logging.warning("TRANSLATION_PROVIDER is 'openai' but OPENAI_API_KEY not found. Translation will not work.")
elif TRANSLATION_PROVIDER == 'anthropic':
    if ANTHROPIC_API_KEY:
        anthropic_client = AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
    else:
        logging.warning("TRANSLATION_PROVIDER is 'anthropic' but ANTHROPIC_API_KEY not found. Translation will not work.")
else:
    logging.warning(f"Invalid TRANSLATION_PROVIDER: '{TRANSLATION_PROVIDER}'. Translation will not work. Choose 'openai' or 'anthropic'.")

# --- Logging Setup ---
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# Re-evaluate client logging after logger is defined
if TRANSLATION_PROVIDER == 'openai':
    if OPENAI_API_KEY:
        # openai_client is already initialized above
        logger.info(f"Using OpenAI for translations with model: {OPENAI_MODEL_NAME}")
    # else warning is already issued
elif TRANSLATION_PROVIDER == 'anthropic':
    if ANTHROPIC_API_KEY:
        # anthropic_client is already initialized above
        logger.info(f"Using Anthropic for translations with model: {ANTHROPIC_MODEL_NAME}")
    # else warning is already issued
# else invalid provider warning already issued

# --- Constants ---
URL_REGEX = re.compile(r'https?://\S+')
MAX_MESSAGE_LENGTH = 4000  # Telegram's limit is 4096, being a bit conservative for HTML

# --- Helper Functions (largely unchanged) ---
async def fetch_article_text(url: str) -> tuple[str | None, str | None]:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=30) as response: # Increased timeout
                if response.status != 200:
                    logger.error(f"Failed to fetch URL {url}: HTTP {response.status}")
                    return None, None
                html = await response.text()
        
        soup = BeautifulSoup(html, 'html.parser')
        
        # Extract Title
        dhivehi_title = None
        title_tag = soup.find('h1', class_=lambda c: c and all(cls in c.split() for cls in ['text-waheed', 'text-black-two']))
        if not title_tag: # Fallback for slightly different common title structures
            title_tag = soup.find('h1', class_=lambda c: c and 'text-40px' in c.split() and 'text-waheed' in c.split())
        if title_tag:
            dhivehi_title = title_tag.get_text(strip=True)
            # logger.info(f"DEBUG_FETCH_TITLE: Extracted Dhivehi title: {dhivehi_title}")
        else:
            logger.warning(f"Could not find title H1 tag for {url}")

        for tag_name in ['script', 'style', 'header', 'footer', 'nav', 'aside', 'form', 'img', 'figure', 'figcaption', 'iframe', 'button', 'input', 'textarea', 'select', 'option']:
            for tag in soup.find_all(tag_name):
                tag.decompose()

        extracted_body_text = ""
        article_body_comment = soup.find(string=lambda text: isinstance(text, Comment) and "article body" in text.lower())

        if article_body_comment:
            # logger.info("Found '<!-- article body -->' comment. Extracting content based on it.")
            article_texts = []
            for element in article_body_comment.find_all_next():
                current_element_classes = element.get('class', [])
                if element.name == 'div' and \
                   'hidden' in current_element_classes and \
                   'lg:block' in current_element_classes and \
                   any(cls in current_element_classes for cls in ['m1-10', 'ml-10']):
                    # logger.info(f"Found stopping div with classes: {current_element_classes}. Stopping content extraction.")
                    break
                if element.name == 'p':
                    required_p_classes = ['text-19px', 'leading-loose']
                    has_required_classes = all(rc in current_element_classes for rc in required_p_classes)
                    has_faseyha = 'text-faseyha' in current_element_classes
                    if has_required_classes and has_faseyha:
                        article_texts.append(element.get_text(separator='\n', strip=True))
                    elif has_required_classes and 'max-w-3xl' in current_element_classes and 'text-black-two' in current_element_classes:
                         article_texts.append(element.get_text(separator='\n', strip=True))
            if article_texts:
                extracted_body_text = "\n\n".join(article_texts)
                # logger.info(f"Extracted {len(article_texts)} paragraphs using comment-based P-tag matching.")
            # else:
                # logger.warning("Comment '<!-- article body -->' found, but no matching <p> tags were extracted before stop marker.")
        
        if not extracted_body_text:
            # logger.info("Comment-based extraction failed or comment not found. Using <article> tag or body as fallback.")
            article_tag = soup.find('article')
            if article_tag:
                extracted_body_text = article_tag.get_text(separator='\n', strip=True)
            else:
                extracted_body_text = soup.body.get_text(separator='\n', strip=True) if soup.body else soup.get_text(separator='\n', strip=True)

        final_body_text = None
        if extracted_body_text:
            text = re.sub(r'(\s*\n\s*){3,}', '\n\n', extracted_body_text)
            final_body_text = text.strip()
            # logger.info(f"DEBUG_FETCH_RESULT: Final extracted Dhivehi text (first 500 chars):\n{final_body_text[:500]}")
        
        if not dhivehi_title and not final_body_text:
             logger.error(f"Failed to extract any title or meaningful body text from {url} after all methods.")
             return None, None
        
        return dhivehi_title, final_body_text

    except Exception as e:
        logger.error(f"General error in fetch_article_text for {url}: {e}", exc_info=True)
        return None, None

async def translate_text(dhivehi_text: str, is_title: bool = False) -> str | None:
    if not dhivehi_text: # Prevent API call with empty string
        return None

    system_prompt_translate = (
        "You are a helpful assistant that translates Dhivehi text to English. "
        "Provide only the translated English text as output, without any additional commentary or phrases like 'Here is the translation:'. "
        "Maintain a journalistic and formal tone in the English translation."
    )
    if is_title:
         system_prompt_translate = ( # Slightly different prompt for titles if needed, or could be the same
            "You are a helpful assistant that translates a Dhivehi news article title to English. "
            "Provide only the translated English title. Keep it concise and impactful."
        )
    
    user_message_content = f"Translate the following Dhivehi text to English:\\n\\n{dhivehi_text}"

    if TRANSLATION_PROVIDER == 'openai':
        if not openai_client:
            logger.error("OpenAI client not initialized for translation.")
            return None
        try:
            # logger.info(f"DEBUG_TRANSLATE_PROMPT (OpenAI): System: {system_prompt_translate} User: {dhivehi_text[:100]}...")
            response = await openai_client.chat.completions.create(
                model=OPENAI_MODEL_NAME,
                messages=[
                    {"role": "system", "content": system_prompt_translate},
                    {"role": "user", "content": user_message_content}
                ],
                max_tokens=1000 if is_title else 3000, # Shorter max_tokens for title
                temperature=0.3,
            )
            translation = response.choices[0].message.content.strip()
            # logger.info(f"DEBUG_TRANSLATE_RESPONSE (OpenAI): {translation[:200]}...")
            return translation
        except Exception as e:
            logger.error(f"OpenAI API error: {e}", exc_info=True)
            return None
            
    elif TRANSLATION_PROVIDER == 'anthropic':
        if not anthropic_client:
            logger.error("Anthropic client not initialized for translation.")
            return None
        try:
            # logger.info(f"DEBUG_TRANSLATE_PROMPT (Anthropic): System: {system_prompt_translate} User: {dhivehi_text[:100]}...")
            response = await anthropic_client.messages.create(
                model=ANTHROPIC_MODEL_NAME,
                max_tokens=1000 if is_title else 3000, # Shorter max_tokens for title
                temperature=0.3,
                system=system_prompt_translate,
                messages=[
                    {"role": "user", "content": user_message_content}
                ]
            )
            translation = response.content[0].text.strip()
            # logger.info(f"DEBUG_TRANSLATE_RESPONSE (Anthropic): {translation[:200]}...")
            return translation
        except Exception as e:
            logger.error(f"Anthropic API error: {e}", exc_info=True)
            return None
            
    else:
        logger.error(f"No valid translation provider configured ('{TRANSLATION_PROVIDER}'). Cannot translate.")
        return None

# --- Telethon Specific Functions ---
async def send_telegram_message_telethon(client: TelegramClient, entity, text: str):
    """Sends a message using Telethon, splitting if necessary."""
    # Telethon handles HTML parsing slightly differently, 
    # but send_message has a parse_mode argument.
    # For links, ensure they are properly formatted.
    # Example: <a href="https://example.com">Link</a>
    
    if len(text) <= MAX_MESSAGE_LENGTH:
        try:
            await client.send_message(entity, text, parse_mode='html', link_preview=False)
        except Exception as e:
            logger.error(f"Failed to send message to {entity}: {e}", exc_info=True)
    else:
        logger.info(f"Message is too long ({len(text)} chars). Splitting into multiple messages.")
        parts = []
        current_pos = 0
        while current_pos < len(text):
            chunk_end = current_pos + MAX_MESSAGE_LENGTH
            if chunk_end >= len(text):
                parts.append(text[current_pos:])
                break
            split_at = text.rfind('\n', current_pos, chunk_end)
            if split_at != -1 and split_at > current_pos:
                parts.append(text[current_pos:split_at])
                current_pos = split_at + 1
            else:
                parts.append(text[current_pos:chunk_end])
                current_pos = chunk_end

        for i, part in enumerate(parts):
            try:
                logger.info(f"Sending part {i+1}/{len(parts)} to {entity}")
                await client.send_message(entity, part, parse_mode='html', link_preview=False)
                if i < len(parts) - 1:
                    await asyncio.sleep(1) # Increased delay for userbots
            except Exception as e:
                logger.error(f"Failed to send part {i+1} of message to {entity}: {e}", exc_info=True)

async def get_entity_safely(client: TelegramClient, entity_identifier):
    """Gets a Telethon entity, handling potential string->int conversion for IDs."""
    if not entity_identifier:
        return None
    try:
        # If it looks like a number (potentially negative for channels/chats), try converting to int
        if isinstance(entity_identifier, str) and (entity_identifier.startswith('-') or entity_identifier.isdigit()):
            try:
                return await client.get_entity(int(entity_identifier))
            except ValueError: # Not a valid integer string, proceed as string (username/link)
                pass
        return await client.get_entity(entity_identifier)
    except Exception as e:
        logger.error(f"Could not get entity for identifier '{entity_identifier}': {e}. Ensure it's a valid username, ID, or invite link accessible to your account.")
        return None

# --- Main Application Logic ---
async def main():
    # Critical environment variable check
    common_vars = [TELEGRAM_API_ID, TELEGRAM_API_HASH, MIHAARU_CHANNEL_ENV, TARGET_CHANNEL_ENV]
    provider_specific_vars_ok = False
    if TRANSLATION_PROVIDER == 'openai' and OPENAI_API_KEY:
        provider_specific_vars_ok = True
    elif TRANSLATION_PROVIDER == 'anthropic' and ANTHROPIC_API_KEY:
        provider_specific_vars_ok = True

    if not all(common_vars) or not provider_specific_vars_ok:
        missing_vars_details = []
        if not all(common_vars):
            missing_vars_details.append("Core Telegram variables missing (API_ID, API_HASH, MIHAARU_CHANNEL_ID, TARGET_CHANNEL_ID).")
        if TRANSLATION_PROVIDER == 'openai' and not OPENAI_API_KEY:
            missing_vars_details.append("TRANSLATION_PROVIDER is 'openai' but OPENAI_API_KEY is missing.")
        elif TRANSLATION_PROVIDER == 'anthropic' and not ANTHROPIC_API_KEY:
            missing_vars_details.append("TRANSLATION_PROVIDER is 'anthropic' but ANTHROPIC_API_KEY is missing.")
        elif TRANSLATION_PROVIDER not in ['openai', 'anthropic']:
             missing_vars_details.append(f"Invalid TRANSLATION_PROVIDER: {TRANSLATION_PROVIDER}. Must be 'openai' or 'anthropic'.")

        logger.critical(f"Critical environment variables missing or misconfigured. Details: {' '.join(missing_vars_details)} Exiting.")
        return

    logger.info(f"Initializing Telegram client with session: {SESSION_NAME}")
    # system_version is useful for Telethon to know the environment, e.g., for server-side optimizations
    # Often not strictly necessary but good practice.
    client = TelegramClient(SESSION_NAME, int(TELEGRAM_API_ID), TELEGRAM_API_HASH, system_version="4.16.30-vxCUSTOM")

    try:
        await client.connect()
        if not await client.is_user_authorized():
            logger.info("Client not authorized. Please follow the prompts to log in.")
            # Authentication will be handled by Telethon automatically if not authorized.
            # It will print to console: "Please enter your phone (or bot token):"
            # And then: "Please enter the code you received:"
            # Or similar prompts.
            # If using a bot token (not recommended for user account features):
            # await client.sign_in(bot_token=YOUR_BOT_TOKEN)
            # For user accounts, client.start() handles interactive login.
            await client.start() # This will trigger the interactive login if needed
        
        logger.info("Client successfully connected and authorized.")

        mihaaru_channel_entity = await get_entity_safely(client, MIHAARU_CHANNEL_ENV)
        target_channel_entity = await get_entity_safely(client, TARGET_CHANNEL_ENV)

        if not mihaaru_channel_entity:
            logger.error(f"Could not resolve Mihaaru channel: {MIHAARU_CHANNEL_ENV}. Ensure your account has access and the ID/username is correct. Exiting.")
            return
        if not target_channel_entity:
            logger.error(f"Could not resolve Target channel: {TARGET_CHANNEL_ENV}. Ensure your account has access and the ID/username is correct. Exiting.")
            return
        
        # Use get_peer_id for consistent ID format in events.chat_id
        # For channels, it's usually negative.
        mihaaru_channel_id_resolved = get_peer_id(mihaaru_channel_entity)

        logger.info(f"Listening for new messages in Mihaaru channel: {MIHAARU_CHANNEL_ENV} (Resolved ID for events.NewMessage: {mihaaru_channel_id_resolved})")
        logger.info(f"Translations will be sent to: {TARGET_CHANNEL_ENV} (Resolved ID: {get_peer_id(target_channel_entity)})")

        # TEMP: Log all incoming messages to see their chat_id and sender_id
        # @client.on(events.NewMessage()) # REMOVED temp_global_handler
        # async def temp_global_handler(event: events.NewMessage.Event):
        #     actual_chat_id = event.chat_id
        #     sender_id = event.sender_id
        #     is_channel = isinstance(event.peer_id, PeerChannel)
        #     if not event.out: 
        #         logger.info(f"GLOBAL_HANDLER: New message detected. actual_chat_id: {actual_chat_id}, sender_id: {sender_id}, is_channel: {is_channel}, message_text: '{event.message.text[:70]}...' (Listening for Mihaaru on: {mihaaru_channel_id_resolved})")

        @client.on(events.NewMessage(chats=[mihaaru_channel_id_resolved]))
        async def handle_new_post(event: events.NewMessage.Event):
            logger.info(f"New message received from Mihaaru channel (ID: {event.chat_id})")
            message_text = event.message.text or ""
            urls = URL_REGEX.findall(message_text)
            if not urls:
                # logger.info(f"No URLs found in message: {message_text[:100]}...") # Quieter log
                return

            url = urls[0]
            logger.info(f"Detected article URL: {url} from Mihaaru channel post.")

            dhivehi_title, article_text_dhivehi = await fetch_article_text(url)
            
            if not article_text_dhivehi or len(article_text_dhivehi) < 50:
                logger.warning(f"Article body text extraction failed or text too short for URL: {url}")
                return
            
            translated_title_english = None
            if dhivehi_title:
                logger.info(f"Translating title for {url}...")
                translated_title_english = await translate_text(dhivehi_title, is_title=True)
            
            logger.info(f"Translating article body from {url}...")
            translation_english_body = await translate_text(article_text_dhivehi)
            if not translation_english_body:
                logger.warning(f"Translation of body failed for article from {url}.")
                return
            
            message_to_send = ""
            if translated_title_english:
                message_to_send += f"<b>{translated_title_english}</b>\n\n"
            message_to_send += f"{translation_english_body}\n\n"
            
            formatted_url = url.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            message_to_send += f"<a href=\"{formatted_url}\">Original Article</a>"
            
            # logger.info(f"DEBUG_FINAL_MESSAGE_TO_SEND:\n{message_to_send}") # REMOVED
            logger.info(f"Sending translation for {url} to target: {TARGET_CHANNEL_ENV}")
            await send_telegram_message_telethon(client, target_channel_entity, message_to_send)
            logger.info(f"Translation for {url} sent successfully.")

        # Handler for /translate command
        @client.on(events.NewMessage(pattern=r'/translate(?:\s+|$)(.*)'))
        async def manual_translate_handler(event: events.NewMessage.Event):
            command_text = event.pattern_match.group(1).strip()
            urls = URL_REGEX.findall(command_text)

            if not urls:
                await event.reply("Please provide a URL after the /translate command. Example: `/translate https://example.com/article`")
                return

            url = urls[0]
            logger.info(f"Manual /translate command received for URL: {url} in chat {event.chat_id}")
            await event.reply(f"Processing manual translation for: {url}...")

            dhivehi_title, article_text_dhivehi = await fetch_article_text(url)

            if not article_text_dhivehi or len(article_text_dhivehi) < 30:
                logger.warning(f"Manual Translate: Article body text extraction failed or text too short for URL: {url}")
                await event.reply(f"Could not extract enough article body text from {url}. Please check the URL or try another.")
                return

            translated_title_english = None
            if dhivehi_title:
                logger.info(f"Manual Translate: Translating title for {url}...")
                translated_title_english = await translate_text(dhivehi_title, is_title=True)

            logger.info(f"Manual Translate: Translating article body from {url}...")
            translation_english_body = await translate_text(article_text_dhivehi)
            if not translation_english_body:
                logger.warning(f"Manual Translate: Translation of body failed for article from {url}.")
                await event.reply(f"Translation of body failed for {url}. The translation service might be unavailable or the content is not translatable.")
                return
            
            message_to_send = ""
            if translated_title_english:
                message_to_send += f"<b>{translated_title_english}</b>\n\n"
            message_to_send += f"{translation_english_body}\n\n"

            formatted_url = url.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            message_to_send += f"<a href=\"{formatted_url}\">Original Article</a>"
            
            logger.info(f"Manual Translate: Sending translation for {url} to chat {event.chat_id}") 
            await send_telegram_message_telethon(client, event.chat_id, message_to_send)
            logger.info(f"Manual Translate: Translation for {url} sent successfully to chat {event.chat_id}.")

        logger.info("Userbot started. Listening for Mihaaru channel messages and /translate commands...") # MODIFIED log
        await client.run_until_disconnected()

    except ConnectionError as e:
        logger.error(f"Connection error: {e}. Please check your network and API ID/Hash.", exc_info=True)
    except Exception as e:
        logger.error(f"An unexpected error occurred: {e}", exc_info=True)
    finally:
        if client.is_connected():
            logger.info("Disconnecting client...")
            await client.disconnect()
        logger.info("Client disconnected.")

if __name__ == '__main__':
    # nest_asyncio.apply() # Moved to the top
    asyncio.run(main()) 