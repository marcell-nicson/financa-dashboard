from flask import Flask, jsonify, request, render_template, session, redirect, url_for
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
import requests as req
import os
import database as db
from mercadopago import MercadoPagoClient
from scheduler import start_scheduler, sync_mercadopago
import atexit

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', os.urandom(32))

# ── INIT ────────────────────────────────────────────────

db.init_db()
start_scheduler()

@atexit.register
def shutdown():
    from scheduler import stop_scheduler
    stop_scheduler()


# ── AUTH ─────────────────────────────────────────────────

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('logged_in'):
            if request.path.startswith('/api/'):
                return jsonify({'error': 'Não autorizado'}), 401
            return redirect(url_for('login_page'))
        return f(*args, **kwargs)
    return decorated


@app.route('/login', methods=['GET'])
def login_page():
    if session.get('logged_in'):
        return redirect('/')
    return render_template('login.html', error=None)


@app.route('/login', methods=['POST'])
def login_post():
    username = request.form.get('username', '').strip()
    password = request.form.get('password', '').strip()

    stored_user = db.get_config('auth_username')
    stored_hash = db.get_config('auth_password_hash')

    if not stored_user or not stored_hash:
        return render_template('login.html', error='Nenhum usuário configurado. Execute o set_password.py no servidor.')

    if username == stored_user and check_password_hash(stored_hash, password):
        session['logged_in'] = True
        session['username']  = username
        return redirect('/')

    return render_template('login.html', error='Usuário ou senha incorretos.')


@app.route('/logout')
def logout():
    session.clear()
    return redirect('/login')


# ── FRONTEND ────────────────────────────────────────────

@app.route('/')
@login_required
def index():
    return render_template('dashboard.html')


# ── STATUS ──────────────────────────────────────────────

@app.route('/api/status')
@login_required
def status():
    token = db.get_config('mp_token')
    gmail = db.get_config('gmail_user')
    return jsonify({
        'mp_connected':     bool(token),
        'email_configured': bool(gmail),
        'demo_mode':        not bool(token),
    })


# ── CONFIG: TOKEN ────────────────────────────────────────

@app.route('/api/config/token', methods=['POST'])
@login_required
def save_token():
    data  = request.get_json(silent=True) or {}
    token = data.get('token', '').strip()

    if not token:
        return jsonify({'error': 'Token não informado'}), 400

    mp   = MercadoPagoClient(token)
    user = mp.get_user()

    if not user:
        return jsonify({'error': 'Token inválido ou expirado.'}), 401

    db.set_config('mp_token', token)

    from threading import Thread
    Thread(target=sync_mercadopago, daemon=True).start()

    return jsonify({
        'ok':   True,
        'email': user.get('email', ''),
        'name':  user.get('first_name', 'Usuário'),
    })


# ── CONFIG: EMAIL ────────────────────────────────────────

@app.route('/api/config/email', methods=['POST'])
@login_required
def save_email_config():
    data     = request.get_json(silent=True) or {}
    gmail    = data.get('gmail_user', '').strip()
    password = data.get('gmail_app_password', '').strip()
    destino  = data.get('email_destinatario', '').strip()

    if not gmail or not password:
        return jsonify({'error': 'Gmail e senha de app são obrigatórios'}), 400

    db.set_config('gmail_user',         gmail)
    db.set_config('gmail_app_password', password)
    if destino:
        db.set_config('email_destinatario', destino)

    return jsonify({'ok': True})


@app.route('/api/config/email', methods=['GET'])
@login_required
def get_email_config():
    return jsonify({
        'gmail_user':         db.get_config('gmail_user') or '',
        'email_destinatario': db.get_config('email_destinatario') or 'marcellnicson@gmail.com',
        'configured':         bool(db.get_config('gmail_user')),
    })


# ── SYNC MANUAL ──────────────────────────────────────────

@app.route('/api/sync', methods=['POST'])
@login_required
def sync():
    token = db.get_config('mp_token')
    if not token:
        return jsonify({'error': 'Token do Mercado Pago não configurado'}), 400

    mp        = MercadoPagoClient(token)
    movements = mp.fetch_movements(limit=100)
    saved     = db.save_transactions(movements)
    balance   = mp.fetch_balance()

    if balance is not None:
        db.save_balance(balance)

    return jsonify({'ok': True, 'fetched': len(movements), 'saved': saved, 'balance': balance})


# ── BALANCE ──────────────────────────────────────────────

@app.route('/api/balance')
@login_required
def balance():
    bal     = db.get_latest_balance()
    summary = db.get_monthly_summary()
    disp    = bal.get('available') or (summary['entradas'] - summary['saidas'])
    return jsonify({
        'available':  disp,
        'investivel': disp * 0.45,
        'entradas':   summary['entradas'],
        'saidas':     summary['saidas'],
        'total_tx':   summary['total_tx'],
    })


# ── TRANSACTIONS ─────────────────────────────────────────

@app.route('/api/transactions')
@login_required
def transactions():
    limit = request.args.get('limit', 50, type=int)
    month = request.args.get('month')
    txs   = db.get_transactions(limit=limit, month=month)
    return jsonify(txs)


# ── CRYPTO ───────────────────────────────────────────────

@app.route('/api/crypto')
@login_required
def crypto():
    try:
        r = req.get(
            'https://api.coingecko.com/api/v3/simple/price'
            '?ids=bitcoin,ethereum,solana,binancecoin'
            '&vs_currencies=brl&include_24hr_change=true',
            timeout=10
        )
        return jsonify(r.json())
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ── TEST EMAIL ───────────────────────────────────────────

@app.route('/api/test-email', methods=['POST'])
@login_required
def test_email():
    from email_service import send_daily_summary
    ok = send_daily_summary()
    return jsonify({'ok': ok, 'message': 'E-mail enviado!' if ok else 'Falha — verifique as credenciais Gmail.'})


# ── MAIN ─────────────────────────────────────────────────

if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5000, debug=False)
