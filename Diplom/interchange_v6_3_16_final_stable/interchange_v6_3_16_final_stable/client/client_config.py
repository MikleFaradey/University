import configparser
import os
import secrets
import string
from pathlib import Path


APP_DIR_NAME = "interchange"
CONFIG_FILE_NAME = "client.ini"
TOKEN_LENGTH = 15
TOKEN_ALPHABET = string.ascii_letters + string.digits


def default_config_path():
    base = os.environ.get("XDG_CONFIG_HOME")
    if base:
        return Path(base).expanduser() / APP_DIR_NAME / CONFIG_FILE_NAME
    return Path.home() / ".config" / APP_DIR_NAME / CONFIG_FILE_NAME


def generate_client_token():
    return "".join(
        secrets.choice(TOKEN_ALPHABET)
        for _ in range(TOKEN_LENGTH)
    )


def default_values():
    return {
        "server_ip": "",
        "display_name": "",
        "client_token": "",
        "user_id": "",
        "download_dir": str(Path.home() / "InterchangeReceived"),
        "http_port": 8080,
        "socket_port": 8081,
    }


def load_client_config(path=None):
    path = Path(path or default_config_path()).expanduser()
    values = default_values()
    if not path.exists():
        return values

    parser = configparser.ConfigParser()
    parser.read(str(path), encoding="utf-8")
    section = parser["client"] if parser.has_section("client") else {}

    values["server_ip"] = section.get(
        "server_ip",
        values["server_ip"]
    ).strip()
    values["display_name"] = section.get(
        "display_name",
        values["display_name"]
    ).strip()
    values["client_token"] = section.get(
        "client_token",
        values["client_token"]
    ).strip()
    values["user_id"] = section.get(
        "user_id",
        values["user_id"]
    ).strip()
    values["download_dir"] = section.get(
        "download_dir",
        values["download_dir"]
    ).strip()

    if not values["display_name"] and values["user_id"]:
        values["display_name"] = values["user_id"]

    try:
        values["http_port"] = int(
            section.get("http_port", values["http_port"])
        )
    except Exception:
        pass
    try:
        values["socket_port"] = int(
            section.get("socket_port", values["socket_port"])
        )
    except Exception:
        pass

    return values


def save_client_config(values, path=None):
    path = Path(path or default_config_path()).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)

    parser = configparser.ConfigParser()
    parser["client"] = {
        "server_ip": str(values["server_ip"]).strip(),
        "display_name": str(values["display_name"]).strip(),
        "client_token": str(values["client_token"]).strip(),
        "user_id": str(values.get("user_id", "")).strip(),
        "download_dir": str(values["download_dir"]).strip(),
        "http_port": str(int(values["http_port"])),
        "socket_port": str(int(values["socket_port"])),
    }

    temp_path = path.with_name(path.name + ".tmp")
    with temp_path.open("w", encoding="utf-8") as handle:
        parser.write(handle)
    temp_path.replace(path)

    if os.name == "posix":
        try:
            os.chmod(str(path), 0o600)
        except Exception:
            pass

    return path


def is_client_config_complete(values):
    token = str(values.get("client_token", "")).strip()
    return bool(
        str(values.get("server_ip", "")).strip()
        and str(values.get("display_name", "")).strip()
        and len(token) == TOKEN_LENGTH
        and token.isalnum()
        and str(values.get("user_id", "")).strip()
        and str(values.get("download_dir", "")).strip()
    )
