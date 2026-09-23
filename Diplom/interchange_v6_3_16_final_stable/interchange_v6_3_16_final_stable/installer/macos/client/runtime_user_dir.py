import os
from pathlib import Path

state = Path.home() / ".interchange"
state.mkdir(parents=True, exist_ok=True)
os.chdir(str(state))
