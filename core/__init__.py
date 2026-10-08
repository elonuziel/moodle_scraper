"""
Moodle Downloader Core Package
"""

def main():
    from core.cli import main as _main
    return _main()

__all__ = ["main"]

