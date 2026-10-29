"""Compatibility entry point; no config/network side effects when imported."""
from bureau.telegram_app import main

if __name__=='__main__':
    main()
