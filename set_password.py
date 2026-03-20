"""
Execute este script no servidor para criar o usuário de acesso ao dashboard:

  cd /var/www/financa
  python3 set_password.py
"""
from werkzeug.security import generate_password_hash
import database as db

db.init_db()

print("\n=== Configurar acesso ao Dashboard ===\n")
username = input("Usuário: ").strip()
password = input("Senha:   ").strip()

if not username or not password:
    print("Usuário e senha não podem ser vazios.")
    exit(1)

if len(password) < 6:
    print("A senha precisa ter pelo menos 6 caracteres.")
    exit(1)

db.set_config('auth_username',      username)
db.set_config('auth_password_hash', generate_password_hash(password))

print(f"\n✅ Usuário '{username}' configurado com sucesso!")
print("Reinicie o serviço: systemctl restart financa\n")
