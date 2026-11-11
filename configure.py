"""Initialize service settings without overwriting existing configuration or printing secrets."""
from pathlib import Path
import secrets

ROOT = Path(__file__).resolve().parent


def initialize(root: Path = ROOT) -> bool:
    target = root / '.env'
    if target.exists():
        return False
    template = (root / '.env.example').read_text(encoding='utf-8')
    if template.splitlines().count('NOTIFY_SECRET=') != 1:
        raise ValueError('Template must contain exactly one empty NOTIFY_SECRET entry')
    text = template.replace('NOTIFY_SECRET=\n', 'NOTIFY_SECRET=' + secrets.token_hex(32) + '\n')
    try:
        with target.open('x', encoding='utf-8', newline='\n') as stream:
            stream.write(text)
    except FileExistsError:
        return False
    return True


if __name__ == '__main__':
    created = initialize()
    print('Created .env with a random HMAC secret.' if created else '.env already exists; nothing changed.')
    print('Edit settings locally, bind the bot, and configure the matching Hermes secret. No service started.')
