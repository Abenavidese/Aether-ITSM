import base64
import os
from cryptography.fernet import Fernet

key = Fernet.generate_key().decode('utf-8')
print(f'NEW_FERNET_KEY={key}')

with open('.env', 'a', encoding='utf-8') as f:
    f.write(f'\nENCRYPTION_KEY="{key}"\n')

with open('.env.example', 'a', encoding='utf-8') as f:
    f.write(f'\nENCRYPTION_KEY="your_32_byte_urlsafe_base64_encryption_key_here"\n')
