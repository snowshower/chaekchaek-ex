"""Publish only participant static assets to Vercel's public directory."""
from pathlib import Path
from shutil import copytree


def build(root):
    root = Path(root)
    copytree(root / "app/static", root / "public/static", dirs_exist_ok=True)


if __name__ == "__main__":
    build(Path(__file__).resolve().parents[1])
