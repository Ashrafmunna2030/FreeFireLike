from flask import Flask, request, jsonify
import asyncio
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
from google.protobuf.json_format import MessageToJson
import binascii
import aiohttp
import requests
import json
import os
import like_pb2
import like_count_pb2
import uid_generator_pb2
from google.protobuf.message import DecodeError
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = Flask(__name__)

# 🆕 State file — কোন UID-এর কত নম্বর call চলছে
STATE_FILE = "/tmp/call_state.json"


# ============================================================
# 🆕 PARITY STATE MANAGER
# ============================================================
def load_state():
    try:
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE, "r") as f:
                return json.load(f)
    except Exception as e:
        app.logger.error(f"State load error: {e}")
    return {}


def save_state(state):
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(state, f)
    except Exception as e:
        app.logger.error(f"State save error: {e}")


def get_next_parity(key):
    """
    Per-UID+server toggle:
        Call #1 -> 0 (even tokens)
        Call #2 -> 1 (odd tokens)
        Call #3 -> 0 (even, cycle)
        Call #4 -> 1 (odd, cycle)
    """
    state = load_state()
    current = state.get(key, -1)
    next_val = 1 if current == 0 else 0
    state[key] = next_val
    save_state(state)
    app.logger.info(f"[PARITY] key={key} prev={current} next={next_val}")
    return next_val


# ============================================================
# 🔑 TOKEN LOADER
# ============================================================
def xpopu_load_tokens(server_name):
    try:
        if server_name == "IND":
            with open("token_ind.json", "r") as f:
                return json.load(f)
        elif server_name in {"BR", "US", "SAC", "NA"}:
            with open("token_br.json", "r") as f:
                return json.load(f)
        else:
            with open("token_bd.json", "r") as f:
                return json.load(f)
    except Exception as e:
        app.logger.error(f"Token load error ({server_name}): {e}")
        return None


# ============================================================
# 🎯 HALF-SPLIT HELPER (parity based)
# ============================================================
def xpopu_apply_parity_split(tokens, parity):
    """
    parity=0 -> even index tokens (0, 2, 4, ...)
    parity=1 -> odd  index tokens (1, 3, 5, ...)
    """
    if not tokens:
        return tokens

    selected = tokens[parity::2]  # slice with step 2

    # safety — যদি empty হয়
    if not selected:
        selected = tokens[: max(1, len(tokens) // 2)]

    app.logger.info(
        f"[SPLIT] parity={parity} -> {len(selected)}/{len(tokens)} tokens"
    )
    return selected


# ============================================================
# 🔒 ENCRYPTION
# ============================================================
def xpopu_encrypt_message(plaintext):
    try:
        key = b'Yg&tc%DEuh6%Zc^8'
        iv = b'6oyZDr22E3ychjM%'
        cipher = AES.new(key, AES.MODE_CBC, iv)
        padded = pad(plaintext, AES.block_size)
        return binascii.hexlify(cipher.encrypt(padded)).decode('utf-8')
    except Exception as e:
        app.logger.error(f"Encrypt error: {e}")
        return None


def xpopu_create_protobuf_message(user_id, region):
    try:
        m = like_pb2.like()
        m.uid = int(user_id)
        m.region = region
        return m.SerializeToString()
    except Exception as e:
        app.logger.error(f"Like proto error: {e}")
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
            async with session.post(url, data=edata, headers=headers) as resp:
                if resp.status != 200:
                    app.logger.error(f"Like request status={resp.status}")
                    return resp.status
                return await resp.text()
    except Exception as e:
        app.logger.error(f"Send request error: {e}")
        return None


async def xpopu_send_multiple_requests(encrypted_uid, tokens, url, count=110):
    try:
        if not tokens:
            return None

        tasks = []
        for i in range(count):
            token = tokens[i % len(tokens)]["token"]
            tasks.append(xpopu_send_request(encrypted_uid, token, url))

        return await asyncio.gather(*tasks, return_exceptions=True)
    except Exception as e:
        app.logger.error(f"Multi request error: {e}")
        return None


# ============================================================
# 🧩 UID PROTOBUF
# ============================================================
def xpopu_create_protobuf(uid):
    try:
        m = uid_generator_pb2.uid_generator()
        m.saturn_ = int(uid)
        m.garena = 1
        return m.SerializeToString()
    except Exception as e:
        app.logger.error(f"Uid proto error: {e}")
        return None


def xpopu_enc(uid):
    data = xpopu_create_protobuf(uid)
    return xpopu_encrypt_message(data) if data else None


# ============================================================
# 📡 PLAYER INFO
# ============================================================
def xpopu_make_request(encrypt, server_name, token):
    try:
        if server_name == "IND":
            url = "https://client.ind.freefiremobile.com/GetPlayerPersonalShow"
        elif server_name in {"BR", "US", "SAC", "NA"}:
            url = "https://client.us.freefiremobile.com/GetPlayerPersonalShow"
        else:
            url = "https://clientbp.ppmainecoonghj.com/GetPlayerPersonalShow"

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
        resp = requests.post(url, data=bytes.fromhex(encrypt),
                             headers=headers, verify=False)
        return xpopu_decode_protobuf(resp.content)
    except Exception as e:
        app.logger.error(f"Player info error: {e}")
        return None


def xpopu_decode_protobuf(binary):
    try:
        info = like_count_pb2.Info()
        info.ParseFromString(binary)
        return info
    except DecodeError as e:
        app.logger.error(f"Proto decode error: {e}")
        return None


# ============================================================
# 🚀 MAIN ROUTE
# ============================================================
@app.route('/like', methods=['GET'])
def xpopu_handle_requests():
    uid = request.args.get("uid", "").strip()
    server_name = request.args.get("server_name", "").upper()

    # ✅ optional override (যদি কেউ চায়)
    # ?uid=...&parity=0 / ?uid=...&parity=1  দিয়ে manual control
    parity_override = request.args.get("parity", "").strip()

    if not uid or not server_name:
        return jsonify({"error": "UID and server_name are required"}), 400
    if not uid.isdigit():
        return jsonify({"error": f"Invalid UID: {uid}"}), 400

    try:
        # 🆕 Parity নির্ধারণ — override না থাকলে auto toggle
        if parity_override in {"0", "1"}:
            parity = int(parity_override)
            app.logger.info(f"[PARITY] manual override={parity}")
        else:
            parity = get_next_parity(f"{uid}_{server_name}")

        tokens = xpopu_load_tokens(server_name)
        if not tokens:
            raise Exception("Failed to load tokens")

        # 🔑 ৫০% split (parity অনুযায়ী)
        selected_tokens = xpopu_apply_parity_split(tokens, parity)

        token = tokens[0]['token']
        encrypted_uid = xpopu_enc(uid)
        if not encrypted_uid:
            raise Exception("Encryption failed")

        # Before
        before = xpopu_make_request(encrypted_uid, server_name, token)
        if not before:
            raise Exception("Failed to fetch initial info")
        data_before = json.loads(MessageToJson(before))
        before_like = int(data_before.get('AccountInfo', {}).get('Likes', 0) or 0)

        # Like URL
        if server_name == "IND":
            like_url = "https://client.ind.freefiremobile.com/LikeProfile"
        elif server_name in {"BR", "US", "SAC", "NA"}:
            like_url = "https://client.us.freefiremobile.com/LikeProfile"
        else:
            like_url = "https://clientbp.ppmainecoonghj.com/LikeProfile"

        # 🔑 110 requests with 50%-selected tokens
        asyncio.run(
            xpopu_send_multiple_requests(
                encrypted_uid, selected_tokens, like_url, count=110
            )
        )

        # After
        after = xpopu_make_request(encrypted_uid, server_name, token)
        if not after:
            raise Exception("Failed to fetch final info")
        data_after = json.loads(MessageToJson(after))
        after_like = int(data_after.get('AccountInfo', {}).get('Likes', 0) or 0)
        player_uid = int(data_after.get('AccountInfo', {}).get('UID', 0) or 0)
        player_name = str(data_after.get('AccountInfo', {}).get('PlayerNickname', ''))

        like_given = after_like - before_like
        status = 1 if like_given != 0 else 2

        return jsonify({
            "LikesGivenByAPI": like_given,
            "LikesafterCommand": after_like,
            "LikesbeforeCommand": before_like,
            "PlayerNickname": player_name,
            "UID": player_uid,
            "status": status,
            "TokenMode": "half-auto",      # 🆕 info
            "Parity": parity,              # 🆕 0=first half, 1=second half
            "TokensUsed": len(selected_tokens)
        })

    except Exception as e:
        app.logger.error(f"Handler error: {e}")
        return jsonify({"error": str(e)}), 500


if __name__ == '__main__':
    app.run(debug=True, use_reloader=False)
