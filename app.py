from flask import Flask, request, jsonify
import asyncio
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
from google.protobuf.json_format import MessageToJson
import binascii
import aiohttp
import requests
import json
import like_pb2
import like_count_pb2
import uid_generator_pb2
from google.protobuf.message import DecodeError
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = Flask(__name__)


# ============================================================
# 🔑 TOKEN LOADER
# ============================================================
def xpopu_load_tokens(server_name):
    try:
        if server_name == "IND":
            with open("token_ind.json", "r") as f:
                tokens = json.load(f)
        elif server_name in {"BR", "US", "SAC", "NA"}:
            with open("token_br.json", "r") as f:
                tokens = json.load(f)
        else:
            with open("token_bd.json", "r") as f:
                tokens = json.load(f)
        return tokens
    except Exception as e:
        app.logger.error(f"Error loading tokens for server {server_name}: {e}")
        return None


# ============================================================
# 🆕 TOKEN MODE HELPERS
# ============================================================
def xpopu_apply_token_mode(tokens, mode):
    """
    mode == "half" -> first 50% of tokens
    mode == "full" -> all tokens
    """
    if not tokens:
        return tokens

    if mode == "half":
        half_len = max(1, len(tokens) // 2)
        selected = tokens[:half_len]
        app.logger.info(f"[TOKEN MODE] half -> {len(selected)}/{len(tokens)} tokens")
        return selected

    app.logger.info(f"[TOKEN MODE] full -> {len(tokens)} tokens")
    return tokens


def xpopu_request_count(mode):
    """Half mode = 110 requests, Full mode = 220 requests."""
    return 110 if mode == "half" else 220


# ============================================================
# 🔒 ENCRYPTION
# ============================================================
def xpopu_encrypt_message(plaintext):
    try:
        key = b'Yg&tc%DEuh6%Zc^8'
        iv = b'6oyZDr22E3ychjM%'
        cipher = AES.new(key, AES.MODE_CBC, iv)
        padded_message = pad(plaintext, AES.block_size)
        encrypted_message = cipher.encrypt(padded_message)
        return binascii.hexlify(encrypted_message).decode('utf-8')
    except Exception as e:
        app.logger.error(f"Error encrypting message: {e}")
        return None


def xpopu_create_protobuf_message(user_id, region):
    try:
        message = like_pb2.like()
        message.uid = int(user_id)
        message.region = region
        return message.SerializeToString()
    except Exception as e:
        app.logger.error(f"Error creating protobuf message: {e}")
        return None


# ============================================================
# 🌐 ASYNC LIKE REQUESTS
# ============================================================
async def xpopu_send_request(encrypted_uid, token, url):
    try:
        edata = bytes.fromhex(encrypted_uid)
        headers = {
            'User-Agent': "Dalvik/2.1.0 (Linux; U; Android 9; ASUS_Z01QD Build/PI)",
            'Connection': "Keep-Alive",
            'Accept-Encoding': "gzip",
            'Authorization': f"Bearer {token}",
            'Content-Type': "application/x-www-form-urlencoded",
            'Expect': "100-continue",
            'X-Unity-Version': "2018.4.11f1",
            'X-GA': "v1 1",
            'ReleaseVersion': "OB55"
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(url, data=edata, headers=headers) as response:
                if response.status != 200:
                    app.logger.error(f"Request failed with status code: {response.status}")
                    return response.status
                return await response.text()
    except Exception as e:
        app.logger.error(f"Exception in send_request: {e}")
        return None


async def xpopu_send_multiple_requests(uid, server_name, url, token_mode="full"):
    try:
        region = server_name
        protobuf_message = xpopu_create_protobuf_message(uid, region)
        if protobuf_message is None:
            app.logger.error("Failed to create protobuf message.")
            return None

        encrypted_uid = xpopu_encrypt_message(protobuf_message)
        if encrypted_uid is None:
            app.logger.error("Encryption failed.")
            return None

        tokens = xpopu_load_tokens(server_name)
        if tokens is None:
            app.logger.error("Failed to load tokens.")
            return None

        # 🔑 Apply token mode
        tokens = xpopu_apply_token_mode(tokens, token_mode)
        if not tokens:
            app.logger.error("No tokens selected after mode filtering.")
            return None

        count = xpopu_request_count(token_mode)
        app.logger.info(f"[REQUESTS] sending {count} like requests (mode={token_mode})")

        tasks = []
        for i in range(count):
            token = tokens[i % len(tokens)]["token"]
            tasks.append(xpopu_send_request(encrypted_uid, token, url))

        results = await asyncio.gather(*tasks, return_exceptions=True)
        return results
    except Exception as e:
        app.logger.error(f"Exception in send_multiple_requests: {e}")
        return None


# ============================================================
# 🧩 UID PROTOBUF
# ============================================================
def xpopu_create_protobuf(uid):
    try:
        message = uid_generator_pb2.uid_generator()
        message.saturn_ = int(uid)
        message.garena = 1
        return message.SerializeToString()
    except Exception as e:
        app.logger.error(f"Error creating uid protobuf: {e}")
        return None


def xpopu_enc(uid):
    protobuf_data = xpopu_create_protobuf(uid)
    if protobuf_data is None:
        return None
    return xpopu_encrypt_message(protobuf_data)


# ============================================================
# 📡 SYNC PLAYER INFO REQUEST
# ============================================================
def xpopu_make_request(encrypt, server_name, token):
    try:
        if server_name == "IND":
            url = "https://client.ind.freefiremobile.com/GetPlayerPersonalShow"
        elif server_name in {"BR", "US", "SAC", "NA"}:
            url = "https://client.us.freefiremobile.com/GetPlayerPersonalShow"
        else:
            url = "https://clientbp.ppmainecoonghj.com/GetPlayerPersonalShow"

        edata = bytes.fromhex(encrypt)
        headers = {
            'User-Agent': "Dalvik/2.1.0 (Linux; U; Android 9; ASUS_Z01QD Build/PI)",
            'Connection': "Keep-Alive",
            'Accept-Encoding': "gzip",
            'Authorization': f"Bearer {token}",
            'Content-Type': "application/x-www-form-urlencoded",
            'Expect': "100-continue",
            'X-Unity-Version': "2018.4.11f1",
            'X-GA': "v1 1",
            'ReleaseVersion': "OB55"
        }
        response = requests.post(url, data=edata, headers=headers, verify=False)
        return xpopu_decode_protobuf(response.content)
    except Exception as e:
        app.logger.error(f"Error in make_request: {e}")
        return None


def xpopu_decode_protobuf(binary):
    try:
        items = like_count_pb2.Info()
        items.ParseFromString(binary)
        return items
    except DecodeError as e:
        app.logger.error(f"Error decoding Protobuf data: {e}")
        return None
    except Exception as e:
        app.logger.error(f"Unexpected error during protobuf decoding: {e}")
        return None


# ============================================================
# 🚀 MAIN ROUTE
# ============================================================
@app.route('/like', methods=['GET'])
def xpopu_handle_requests():
    # 🆕 Read raw query string to preserve "&100" / "&200"
    raw_qs = request.query_string.decode('utf-8', errors='ignore')

    raw_uid = request.args.get("uid", "").strip()
    server_name = request.args.get("server_name", "").upper()

    # 🔑 Detect token mode from RAW query string
    token_mode = "full"  # default
    if "&100" in raw_qs or raw_uid.endswith("&100"):
        token_mode = "half"
    elif "&200" in raw_qs or raw_uid.endswith("&200"):
        token_mode = "full"

    # Strip suffix if it leaked into uid
    if raw_uid.endswith("&100"):
        raw_uid = raw_uid[:-4]
    elif raw_uid.endswith("&200"):
        raw_uid = raw_uid[:-4]

    uid = raw_uid.strip()

    app.logger.info(f"[PARSE] raw_qs={raw_qs} | uid={uid} | mode={token_mode}")

    if not uid or not server_name:
        return jsonify({"error": "UID and server_name are required"}), 400
    if not uid.isdigit():
        return jsonify({"error": f"Invalid UID: {uid}"}), 400

    try:
        def xpopu_process_request():
            tokens = xpopu_load_tokens(server_name)
            if tokens is None:
                raise Exception("Failed to load tokens.")

            token = tokens[0]['token']
            encrypted_uid = xpopu_enc(uid)
            if encrypted_uid is None:
                raise Exception("Encryption of UID failed.")

            # Before
            before = xpopu_make_request(encrypted_uid, server_name, token)
            if before is None:
                raise Exception("Failed to retrieve initial player info.")
            try:
                jsone = MessageToJson(before)
            except Exception as e:
                raise Exception(f"Error converting 'before' protobuf to JSON: {e}")
            data_before = json.loads(jsone)
            before_like = data_before.get('AccountInfo', {}).get('Likes', 0)
            try:
                before_like = int(before_like)
            except Exception:
                before_like = 0
            app.logger.info(f"Likes before command: {before_like}")

            # Like endpoint
            if server_name == "IND":
                url = "https://client.ind.freefiremobile.com/LikeProfile"
            elif server_name in {"BR", "US", "SAC", "NA"}:
                url = "https://client.us.freefiremobile.com/LikeProfile"
            else:
                url = "https://clientbp.ppmainecoonghj.com/LikeProfile"

            # 🔑 Send likes with mode
            asyncio.run(xpopu_send_multiple_requests(uid, server_name, url, token_mode))

            # After
            after = xpopu_make_request(encrypted_uid, server_name, token)
            if after is None:
                raise Exception("Failed to retrieve player info after like requests.")
            try:
                jsone_after = MessageToJson(after)
            except Exception as e:
                raise Exception(f"Error converting 'after' protobuf to JSON: {e}")
            data_after = json.loads(jsone_after)
            after_like = int(data_after.get('AccountInfo', {}).get('Likes', 0))
            player_uid = int(data_after.get('AccountInfo', {}).get('UID', 0))
            player_name = str(data_after.get('AccountInfo', {}).get('PlayerNickname', ''))

            like_given = after_like - before_like
            status = 1 if like_given != 0 else 2

            return {
                "LikesGivenByAPI": like_given,
                "LikesafterCommand": after_like,
                "LikesbeforeCommand": before_like,
                "PlayerNickname": player_name,
                "UID": player_uid,
                "status": status,
                "TokenMode": token_mode
            }

        result = xpopu_process_request()
        return jsonify(result)
    except Exception as e:
        app.logger.error(f"Error processing request: {e}")
        return jsonify({"error": str(e)}), 500


if __name__ == '__main__':
    app.run(debug=True, use_reloader=False)
