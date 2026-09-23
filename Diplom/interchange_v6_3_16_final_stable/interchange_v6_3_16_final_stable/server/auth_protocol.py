import hashlib
import hmac
import json
import secrets


PROTOCOL_VERSION = "IKP3"
TOKEN_LENGTH = 15
PASSWORD_MIN_LENGTH = 10
PASSWORD_MAX_LENGTH = 128
PASSWORD_KDF_ITERATIONS = 250000
SESSION_TTL_SEC = 3600

P_HEX = (
    "FFFFFFFFFFFFFFFFC90FDAA22168C234C4C6628B80DC1CD1"
    "29024E088A67CC74020BBEA63B139B22514A08798E3404DD"
    "EF9519B3CD3A431B302B0A6DF25F14374FE1356D6D51C245"
    "E485B576625E7EC6F44C42E9A637ED6B0BFF5CB6F406B7ED"
    "EE386BFB5A899FA5AE9F24117C4B1FE649286651ECE45B3D"
    "C2007CB8A163BF0598DA48361C55D39A69163FA8FD24CF5F"
    "83655D23DCA3AD961C62F356208552BB9ED529077096966D"
    "670C354E4ABC9804F1746C08CA18217C32905E462E36CE3B"
    "E39E772C180E86039B2783A2EC07A28FB5C55DF06F4C52C9"
    "DE2BCBF6955817183995497CEA956AE515D2261898FA0510"
    "15728E5A8AACAA68FFFFFFFFFFFFFFFF"
)
P = int(P_HEX, 16)
Q = (P - 1) // 2
G = 2
GROUP_BYTES = (P.bit_length() + 7) // 8


def _sha256(data):
    return hashlib.sha256(data).digest()


def _int_bytes(value):
    return int(value).to_bytes(GROUP_BYTES, "big")


def int_hex(value):
    return format(int(value), "x")


def parse_group_value(value):
    try:
        number = int(str(value), 16)
    except Exception:
        raise ValueError("Invalid authentication group value")
    if number <= 1 or number >= P - 1:
        raise ValueError("Authentication group value is out of range")
    return number


def parse_scalar(value):
    try:
        number = int(str(value), 16)
    except Exception:
        raise ValueError("Invalid authentication scalar")
    if number <= 0 or number >= Q:
        raise ValueError("Authentication scalar is out of range")
    return number


def validate_token(token):
    token = str(token or "")
    if len(token) != TOKEN_LENGTH or not token.isalnum():
        raise ValueError("Invalid client token")
    try:
        token.encode("ascii")
    except Exception:
        raise ValueError("Invalid client token")
    return token


def validate_password(password):
    password = str(password or "")
    if len(password) < PASSWORD_MIN_LENGTH:
        raise ValueError(
            "Password must contain at least %d characters"
            % PASSWORD_MIN_LENGTH
        )
    if len(password) > PASSWORD_MAX_LENGTH:
        raise ValueError("Password is too long")
    if not any(ch.isalpha() for ch in password):
        raise ValueError("Password must contain at least one letter")
    if not any(ch.isdigit() for ch in password):
        raise ValueError("Password must contain at least one digit")
    return password


def new_password_salt():
    return secrets.token_hex(16)


def derive_password_secret(password, token, salt_hex,
                           iterations=PASSWORD_KDF_ITERATIONS):
    password = validate_password(password)
    token = validate_token(token)
    try:
        salt = bytes.fromhex(str(salt_hex))
    except Exception:
        raise ValueError("Invalid password salt")
    if len(salt) != 16:
        raise ValueError("Invalid password salt")
    material = (
        b"Interchange password and token v3\x00"
        + password.encode("utf-8")
        + b"\x00"
        + token.encode("ascii")
    )
    raw = hashlib.pbkdf2_hmac(
        "sha256",
        material,
        salt,
        int(iterations),
        dklen=32
    )
    secret = int.from_bytes(raw, "big") % Q
    if secret == 0:
        secret = 1
    return secret


def derive_token_secret(token):
    token = validate_token(token)
    raw = _sha256(
        b"Interchange token proof v3\x00"
        + token.encode("ascii")
    )
    secret = int.from_bytes(raw, "big") % Q
    if secret == 0:
        secret = 1
    return secret


def verifier_from_secret(secret):
    secret = int(secret) % Q
    if secret == 0:
        raise ValueError("Invalid authentication secret")
    return pow(G, secret, P)


def token_identifier_from_verifier(token_verifier):
    token_verifier = parse_group_value(
        int_hex(token_verifier)
    )
    return hashlib.sha256(
        b"Interchange token id v3\x00"
        + _int_bytes(token_verifier)
    ).hexdigest()


def token_verifier(token):
    return verifier_from_secret(
        derive_token_secret(token)
    )


def token_id(token):
    return token_identifier_from_verifier(
        token_verifier(token)
    )


def registration_material(password, token):
    salt_hex = new_password_salt()
    password_secret = derive_password_secret(
        password,
        token,
        salt_hex,
        PASSWORD_KDF_ITERATIONS
    )
    token_secret = derive_token_secret(token)
    password_verifier = verifier_from_secret(password_secret)
    token_public = verifier_from_secret(token_secret)
    return {
        "token_id": token_identifier_from_verifier(token_public),
        "token_verifier": int_hex(token_public),
        "password_salt": salt_hex,
        "kdf_iterations": PASSWORD_KDF_ITERATIONS,
        "password_verifier": int_hex(password_verifier),
        "password_secret": password_secret,
        "token_secret": token_secret,
    }


def new_private_scalar():
    return secrets.randbelow(Q - 1) + 1


def new_challenge_scalar():
    return secrets.randbelow(Q - 1) + 1


def public_value(private_value):
    return pow(G, int(private_value) % Q, P)


def proof_response(commitment_private, challenge, secret):
    return (
        int(commitment_private)
        + int(challenge) * int(secret)
    ) % Q


def verify_secret_proof(commitment, challenge, response, verifier):
    commitment = parse_group_value(int_hex(commitment))
    verifier = parse_group_value(int_hex(verifier))
    response = int(response)
    challenge = int(challenge)
    if response <= 0 or response >= Q:
        return False
    if challenge <= 0 or challenge >= Q:
        return False
    left = pow(G, response, P)
    right = (
        commitment * pow(verifier, challenge, P)
    ) % P
    return hmac.compare_digest(
        _int_bytes(left),
        _int_bytes(right)
    )


def auth_transcript(token_identifier, user_id, dh_client, dh_server,
                    password_commitment, token_commitment, challenge,
                    password_salt, kdf_iterations):
    data = {
        "challenge": int_hex(challenge),
        "dh_client": int_hex(dh_client),
        "dh_server": int_hex(dh_server),
        "kdf_iterations": int(kdf_iterations),
        "password_commitment": int_hex(password_commitment),
        "password_salt": str(password_salt),
        "protocol": PROTOCOL_VERSION,
        "token_commitment": int_hex(token_commitment),
        "token_id": str(token_identifier),
        "user_id": str(user_id),
    }
    raw = json.dumps(
        data,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True
    ).encode("ascii")
    return _sha256(raw)


def derive_session_key(shared_secret, transcript_hash):
    return _sha256(
        b"Interchange session key v3\x00"
        + _int_bytes(shared_secret)
        + bytes(transcript_hash)
    )


def _responses_bytes(password_response, token_response):
    return (
        int(password_response).to_bytes(GROUP_BYTES, "big")
        + int(token_response).to_bytes(GROUP_BYTES, "big")
    )


def client_auth_proof(session_key, transcript_hash,
                      password_response, token_response):
    message = (
        b"Interchange client proof v3\x00"
        + bytes(transcript_hash)
        + _responses_bytes(password_response, token_response)
    )
    return hmac.new(
        session_key,
        message,
        hashlib.sha256
    ).hexdigest()


def server_auth_proof(session_key, transcript_hash,
                      password_response, token_response):
    message = (
        b"Interchange server proof v3\x00"
        + bytes(transcript_hash)
        + _responses_bytes(password_response, token_response)
    )
    return hmac.new(
        session_key,
        message,
        hashlib.sha256
    ).hexdigest()


def verify_hex_mac(expected, supplied):
    try:
        expected = str(expected).lower()
        supplied = str(supplied).lower()
    except Exception:
        return False
    if len(expected) != 64 or len(supplied) != 64:
        return False
    return hmac.compare_digest(expected, supplied)


def new_session_id():
    return secrets.token_hex(24)


def new_http_nonce():
    return secrets.token_hex(16)


def http_request_message(method, path, user_id, nonce, extra):
    values = [
        PROTOCOL_VERSION,
        str(method).upper(),
        str(path),
        str(user_id),
        str(nonce),
        str(extra or "")
    ]
    return "\n".join(values).encode("utf-8")


def http_request_mac(session_key, method, path, user_id, nonce, extra=""):
    return hmac.new(
        session_key,
        http_request_message(
            method,
            path,
            user_id,
            nonce,
            extra
        ),
        hashlib.sha256
    ).hexdigest()


def canonical_extra(values):
    return json.dumps(
        [str(value) for value in values],
        separators=(",", ":"),
        ensure_ascii=True
    )


def new_client_auth_material():
    dh_private = new_private_scalar()
    password_commitment_private = new_private_scalar()
    token_commitment_private = new_private_scalar()
    return {
        "dh_private": dh_private,
        "dh_public": public_value(dh_private),
        "password_commitment_private": password_commitment_private,
        "password_commitment": public_value(
            password_commitment_private
        ),
        "token_commitment_private": token_commitment_private,
        "token_commitment": public_value(
            token_commitment_private
        ),
    }


def client_finish_auth(material, password_secret, token_secret,
                       token_identifier, challenge_message):
    dh_server = parse_group_value(challenge_message.get("dh_server"))
    challenge = parse_scalar(challenge_message.get("challenge"))
    user_id = str(challenge_message.get("user_id", ""))
    password_salt = str(challenge_message.get("password_salt", ""))
    kdf_iterations = int(challenge_message.get("kdf_iterations", 0))
    transcript_hash = auth_transcript(
        token_identifier,
        user_id,
        material["dh_public"],
        dh_server,
        material["password_commitment"],
        material["token_commitment"],
        challenge,
        password_salt,
        kdf_iterations
    )
    password_response = proof_response(
        material["password_commitment_private"],
        challenge,
        password_secret
    )
    token_response = proof_response(
        material["token_commitment_private"],
        challenge,
        token_secret
    )
    shared_secret = pow(
        dh_server,
        material["dh_private"],
        P
    )
    session_key = derive_session_key(
        shared_secret,
        transcript_hash
    )
    proof = client_auth_proof(
        session_key,
        transcript_hash,
        password_response,
        token_response
    )
    return {
        "password_response": password_response,
        "password_response_hex": int_hex(password_response),
        "token_response": token_response,
        "token_response_hex": int_hex(token_response),
        "transcript_hash": transcript_hash,
        "session_key": session_key,
        "client_proof": proof,
        "user_id": user_id,
    }


def verify_server_finish(client_state, server_message):
    expected = server_auth_proof(
        client_state["session_key"],
        client_state["transcript_hash"],
        client_state["password_response"],
        client_state["token_response"]
    )
    if not verify_hex_mac(
        expected,
        server_message.get("server_proof")
    ):
        raise ValueError("Server authentication proof is invalid")
    session_id = str(server_message.get("session_id", ""))
    if len(session_id) != 48:
        raise ValueError("Invalid server session")
    return session_id
