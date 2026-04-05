from flask import Flask, jsonify, request, render_template, session, redirect, url_for
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
import requests as req
import os
import io
import csv
from datetime import datetime
import database as db

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', os.urandom(32))

# ── INIT ────────────────────────────────────────────────

db.init_db()

import scheduler as _scheduler
_scheduler.start_scheduler()


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
    gmail = db.get_config('gmail_user')
    return jsonify({
        'email_configured': bool(gmail),
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


# ── IMPORT CSV ───────────────────────────────────────────

def parse_br_number(s):
    """Convert Brazilian number format to float: '3.213,94' -> 3213.94"""
    s = s.strip().replace('.', '').replace(',', '.')
    return float(s)


def categorize(description):
    desc = description.lower()

    # 1. Specific keywords that override payment method detection
    if any(x in desc for x in ['cartão de crédito', 'cartao de credito', 'fatura cartão', 'fatura cartao']):
        return 'Cartão de Crédito'
    if any(x in desc for x in ['rendimento', 'juros', 'yield']):
        return 'Rendimentos'
    if any(x in desc for x in ['receita federal', 'confederação nacional', 'imposto', 'tributo', 'inss', 'fgts', 'darf', 'iptu', 'ipva']):
        return 'Impostos'
    if any(x in desc for x in ['saude', 'saúde', 'plano de saude', 'plano de saúde', 'farmácia', 'farmacia', 'médico', 'medico', 'hospital', 'clínica', 'clinica', 'odonto', 'dentista']):
        return 'Saúde'
    if any(x in desc for x in ['itaú', 'itau', 'banco pan', 'bradesco', 'santander', 'caixa econômica', 'nubank', 'c6 bank', 'financiamento', 'empréstimo', 'emprestimo', 'pagamento de conta']):
        return 'Financiamentos'
    if any(x in desc for x in ['mercado', 'supermercado', 'padaria', 'restaurante', 'ifood', 'alimenta', 'açougue', 'hortifruti']):
        return 'Alimentação'
    if any(x in desc for x in ['uber', 'taxi', '99pop', 'ônibus', 'onibus', 'combustível', 'combustivel', 'gasolina', 'posto', 'pedágio', 'pedagio', 'transporte']):
        return 'Transporte'
    if any(x in desc for x in ['netflix', 'spotify', 'cinema', 'lazer', 'steam', 'amazon prime', 'disney', 'hbo', 'show', 'teatro']):
        return 'Lazer'
    if any(x in desc for x in ['aluguel', 'condomínio', 'condominio', 'energia elétrica', 'energia eletrica', 'água', 'agua', 'internet', 'moradia']):
        return 'Moradia'
    if any(x in desc for x in ['reserva', 'meta ']):
        return 'Reserva'

    # 2. PIX is the fallback for pix transactions (when no specific category matched)
    if 'pix' in desc:
        return 'PIX'

    return 'Outros'


def parse_csv_mercadopago(content):
    """
    Parse Mercado Pago CSV export.
    Returns (final_balance, movements_list) or raises ValueError.
    """
    lines = content.splitlines()

    # Need at least 5 lines: header, data, blank, col headers, 1 transaction
    if len(lines) < 4:
        raise ValueError('Arquivo CSV com formato inválido (linhas insuficientes).')

    # Line 1: column headers (INITIAL_BALANCE;CREDITS;DEBITS;FINAL_BALANCE)
    # Line 2: summary values
    summary_line = lines[1].strip()
    if not summary_line:
        raise ValueError('Linha de resumo (linha 2) está vazia.')

    summary_parts = summary_line.split(';')
    if len(summary_parts) < 4:
        raise ValueError('Linha de resumo não tem 4 colunas esperadas.')

    try:
        final_balance = parse_br_number(summary_parts[3])
    except (ValueError, IndexError) as e:
        raise ValueError(f'Não foi possível converter FINAL_BALANCE: {e}')

    # Line 3: blank, Line 4: transaction column headers
    # Lines 5+: transactions
    movements = []
    for raw_line in lines[4:]:
        line = raw_line.strip()
        if not line:
            continue

        parts = line.split(';')
        if len(parts) < 5:
            continue

        release_date    = parts[0].strip()
        transaction_type = parts[1].strip()
        reference_id    = parts[2].strip()
        net_amount_str  = parts[3].strip()
        # parts[4] is PARTIAL_BALANCE, not needed

        if not release_date or not reference_id or not net_amount_str:
            continue

        try:
            amount = parse_br_number(net_amount_str)
        except ValueError:
            continue

        try:
            date_iso = datetime.strptime(release_date, '%d-%m-%Y').strftime('%Y-%m-%d')
        except ValueError:
            continue

        tx_type = 'entrada' if amount > 0 else 'saida'

        movements.append({
            'id':           reference_id,
            'description':  transaction_type,
            'amount':       amount,
            'type':         tx_type,
            'category':     categorize(transaction_type),
            'date_created': date_iso,
        })

    return final_balance, movements


@app.route('/api/import-csv', methods=['POST'])
@login_required
def import_csv():
    if 'file' not in request.files:
        return jsonify({'error': 'Nenhum arquivo enviado. Use o campo "file".'}), 400

    file = request.files['file']
    if not file.filename:
        return jsonify({'error': 'Nome de arquivo inválido.'}), 400

    raw = file.read()

    # Try UTF-8 first, fallback to latin-1
    try:
        content = raw.decode('utf-8')
    except UnicodeDecodeError:
        content = raw.decode('latin-1')

    try:
        final_balance, movements = parse_csv_mercadopago(content)
    except ValueError as e:
        return jsonify({'error': str(e)}), 422

    parsed = len(movements)

    if parsed == 0:
        return jsonify({'error': 'Nenhuma transação encontrada no arquivo.'}), 422

    saved = db.save_transactions(movements)
    db.save_balance(final_balance)

    return jsonify({
        'ok':      True,
        'parsed':  parsed,
        'saved':   saved,
        'balance': final_balance,
    })


# ── BALANCE ──────────────────────────────────────────────

@app.route('/api/balance')
@login_required
def balance():
    bal     = db.get_latest_balance()
    summary = db.get_monthly_summary()
    disp    = bal.get('available') or (summary['entradas'] - summary['saidas'])
    pct     = float(db.get_config('investimento_pct') or 45) / 100
    return jsonify({
        'available':        disp,
        'investivel':       disp * pct,
        'investimento_pct': int(pct * 100),
        'entradas':         summary['entradas'],
        'saidas':           summary['saidas'],
        'total_tx':         summary['total_tx'],
        'month':            summary.get('month', ''),
    })


# ── TRANSACTIONS ─────────────────────────────────────────

@app.route('/api/transactions')
@login_required
def transactions():
    limit = request.args.get('limit', 50, type=int)
    month = request.args.get('month')
    txs   = db.get_transactions(limit=limit, month=month)
    return jsonify(txs)


@app.route('/api/transactions/<int:tx_id>', methods=['PUT'])
@login_required
def update_transaction(tx_id):
    data = request.get_json(silent=True) or {}
    db.update_transaction(tx_id, data)
    return jsonify({'ok': True})


@app.route('/api/transactions/<int:tx_id>', methods=['DELETE'])
@login_required
def delete_transaction(tx_id):
    db.delete_transaction(tx_id)
    return jsonify({'ok': True})


# ── CONFIG: INVESTIMENTO ──────────────────────────────────

@app.route('/api/config/investimento', methods=['POST'])
@login_required
def save_investimento_pct():
    data = request.get_json(silent=True) or {}
    pct  = data.get('pct')
    if pct is None or not (1 <= int(pct) <= 100):
        return jsonify({'error': 'Percentual inválido (1-100)'}), 400
    db.set_config('investimento_pct', str(int(pct)))
    return jsonify({'ok': True})


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


# ── CONFIG: BTC ───────────────────────────────────────────

@app.route('/api/config/btc', methods=['GET'])
@login_required
def get_btc_config():
    return jsonify({
        'quantidade':         db.get_config('btc_quantidade') or '',
        'preco_medio':        db.get_config('btc_preco_medio') or '',
        'alerta_acima':       db.get_config('btc_alerta_acima') or '',
        'alerta_abaixo':      db.get_config('btc_alerta_abaixo') or '',
        'alerta_variacao_pct': db.get_config('btc_alerta_variacao_pct') or '',
    })


@app.route('/api/config/btc', methods=['POST'])
@login_required
def save_btc_config():
    data = request.get_json(silent=True) or {}
    fields = {
        'quantidade':          'btc_quantidade',
        'preco_medio':         'btc_preco_medio',
        'alerta_acima':        'btc_alerta_acima',
        'alerta_abaixo':       'btc_alerta_abaixo',
        'alerta_variacao_pct': 'btc_alerta_variacao_pct',
    }
    for json_key, config_key in fields.items():
        value = data.get(json_key, '')
        db.set_config(config_key, str(value).strip())
    return jsonify({'ok': True})


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
