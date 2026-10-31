import os
from pathlib import Path

# Frozen Windows/macOS packages contain only PySide6.
os.environ["INTERCHANGE_QT_API"] = "PySide6"

state = Path.home() / ".interchange"
state.mkdir(parents=True, exist_ok=True)
os.chdir(str(state))
