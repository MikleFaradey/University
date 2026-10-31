"""Force a single Qt binding and keep packaged state in the user's home."""
import os
from pathlib import Path

os.environ["INTERCHANGE_QT_API"] = "PySide6"
state = Path.home() / ".interchange"
state.mkdir(parents=True, exist_ok=True)
os.chdir(str(state))
