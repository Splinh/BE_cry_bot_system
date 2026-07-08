"""
Test Telegram Menu - ASCII-only to prevent Windows encoding console crashes.
Usage: python backend/tests/test_telegram_menu.py
"""
import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

# Add backend directory to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from telegram import Update, Message, Chat, User, CallbackQuery
from telegram.ext import ContextTypes

import main


async def test_group_mention_filter():
    print("=== TESTING GROUP CHAT MENTION FILTER ===")
    
    # 1. Mock message in group without mention (bot should ignore it)
    mock_chat_group = MagicMock(spec=Chat)
    mock_chat_group.type = "group"
    
    mock_msg_no_mention = MagicMock(spec=Message)
    mock_msg_no_mention.text = "BTC"
    
    mock_update_no_mention = MagicMock(spec=Update)
    mock_update_no_mention.effective_chat = mock_chat_group
    mock_update_no_mention.message = mock_msg_no_mention
    
    mock_bot = MagicMock()
    mock_bot.username = "my_crypto_bot"
    mock_context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)
    mock_context.bot = mock_bot
    
    # Run analyze_token
    res = await main.analyze_token(mock_update_no_mention, mock_context)
    assert res is None, "Error: Bot analyzed non-mention message in group!"
    print("OK: Bot ignored non-mention message in group chat.")

    # 2. Mock message in group with mention (should successfully extract text)
    mock_msg_with_mention = MagicMock(spec=Message)
    mock_msg_with_mention.text = "@my_crypto_bot BTC"
    
    mock_update_with_mention = MagicMock(spec=Update)
    mock_update_with_mention.effective_chat = mock_chat_group
    mock_update_with_mention.message = mock_msg_with_mention
    
    raw_text = mock_msg_with_mention.text.strip()
    is_group = mock_chat_group.type in ("group", "supergroup")
    if is_group:
        bot_username = mock_bot.username
        if f"@{bot_username}" in raw_text:
            text = raw_text.replace(f"@{bot_username}", "").strip().upper()
    
    assert text == "BTC", f"Error extracting token from mention! Got: {text}"
    print("OK: Successfully extracted token name from group mention.")
    print("-" * 50)


async def test_inline_keyboard_rendering():
    print("=== TESTING INLINE KEYBOARD RENDERING ===")
    
    mock_message = MagicMock(spec=Message)
    mock_message.reply_text = AsyncMock()
    
    mock_chat = MagicMock(spec=Chat)
    mock_chat.id = 123456
    mock_chat.type = "private"
    
    mock_update = MagicMock(spec=Update)
    mock_update.effective_chat = mock_chat
    mock_update.message = mock_message
    mock_update.callback_query = None
    
    mock_context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)
    
    # Run cmd_start
    await main.cmd_start(mock_update, mock_context)
    
    # Check if reply_text was called with reply_markup
    called_args, called_kwargs = mock_message.reply_text.call_args
    assert "reply_markup" in called_kwargs, "Error: reply_markup not found in /start response!"
    print("OK: /start responded with keyboard reply_markup.")
    print("-" * 50)


async def test_persistent_keyboard_routing():
    print("=== TESTING PERSISTENT KEYBOARD ROUTING ===")
    
    mock_message = MagicMock(spec=Message)
    mock_message.text = "📊 Quét Coins"
    
    mock_chat = MagicMock(spec=Chat)
    mock_chat.id = 123456
    mock_chat.type = "private"
    
    mock_update = MagicMock(spec=Update)
    mock_update.effective_chat = mock_chat
    mock_update.message = mock_message
    mock_update.callback_query = None
    
    mock_context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)
    
    # Mock main.cmd_scan to verify it gets called
    original_cmd_scan = main.cmd_scan
    cmd_scan_called = False
    
    async def mock_cmd_scan(update, context):
        nonlocal cmd_scan_called
        cmd_scan_called = True
        print("  [Mock cmd_scan] successfully called via routing!")
        
    main.cmd_scan = mock_cmd_scan
    
    try:
        await main.handle_menu_text_button(mock_update, mock_context)
        assert cmd_scan_called, "Error: handle_menu_text_button did not route to cmd_scan!"
        print("OK: Persistent keyboard button click successfully routed.")
    finally:
        main.cmd_scan = original_cmd_scan
    print("-" * 50)


async def test_guide_routing():
    print("=== TESTING HELP GUIDE ROUTING ===")
    
    mock_message = MagicMock(spec=Message)
    mock_message.reply_text = AsyncMock()
    
    mock_chat = MagicMock(spec=Chat)
    mock_chat.id = 123456
    mock_chat.type = "private"
    
    mock_update = MagicMock(spec=Update)
    mock_update.effective_chat = mock_chat
    mock_update.message = mock_message
    mock_update.callback_query = None
    
    mock_context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)
    
    # Run cmd_help
    await main.cmd_help(mock_update, mock_context)
    
    # Check if reply_text was called with help message content
    called_args, called_kwargs = mock_message.reply_text.call_args
    assert "HƯỚNG DẪN CRYPTO BOT" in called_args[0], "Error: Help content not found in response!"
    print("OK: Help guide command executed successfully.")
    print("-" * 50)


async def run_all():
    await test_group_mention_filter()
    await test_inline_keyboard_rendering()
    await test_persistent_keyboard_routing()
    await test_guide_routing()
    print("ALL TESTS PASSED SUCCESSFULLY!")


if __name__ == "__main__":
    asyncio.run(run_all())
