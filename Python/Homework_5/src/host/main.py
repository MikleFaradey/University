import argparse
import tomllib
from pathlib import Path
from core.loader import load
from core.cli import run_shell

def main():
    parser = argparse.ArgumentParser(description='Modular Bank')
    parser.add_argument('--config', default=str(Path(__file__).resolve().parents[2] / 'config.toml'))
    args = parser.parse_args()
    with open(args.config, 'rb') as f:
        config = tomllib.load(f)
    ctx, mods = load(config)
    try:
        run_shell(ctx)
    finally:
        repo = mods.get('persistence')
        if repo is not None:
            repo.repository.close()
if __name__ == '__main__':
    main()
