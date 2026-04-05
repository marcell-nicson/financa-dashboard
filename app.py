from flask import Flask, jsonify, request, render_template, session, redirect, url_for
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
import requests as req
import os
import io
import csv
import time
import hmac
import hashlib
import base64
import json
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
    symbols = ['BTC', 'ETH', 'SOL', 'XRP']
    result = {}
    for symbol in symbols:
        try:
            r = req.get(f'https://www.mercadobitcoin.net/api/{symbol}/ticker/', timeout=8)
            t = r.json().get('ticker', {})
            last = float(t.get('last', 0))
            open_ = float(t.get('open', 0))
            change = round((last - open_) / open_ * 100, 2) if open_ else 0
            result[symbol] = {'brl': last, 'brl_24h_change': change}
        except Exception:
            pass
    return jsonify(result)


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


# ── CONFIG: MERCADO BITCOIN ──────────────────────────────

@app.route('/api/config/mb', methods=['GET'])
@login_required
def get_mb_config():
    api_id = db.get_config('mb_api_id') or ''
    return jsonify({
        'mb_api_id':     api_id,
        'configured':    bool(api_id),
        # never expose the secret
    })


@app.route('/api/config/mb', methods=['POST'])
@login_required
def save_mb_config():
    data   = request.get_json(silent=True) or {}
    api_id = data.get('mb_api_id', '').strip()
    secret = data.get('mb_api_secret', '').strip()
    if not api_id or not secret:
        return jsonify({'error': 'mb_api_id e mb_api_secret são obrigatórios'}), 400
    db.set_config('mb_api_id',     api_id)
    db.set_config('mb_api_secret', secret)
    return jsonify({'ok': True})


def _mb_get_token(api_id: str, api_secret: str) -> str:
    """Obtém access_token da MB API v4 via endpoint de autorização."""
    r = req.post(
        'https://api.mercadobitcoin.net/api/v4/authorize',
        json={'login': api_id, 'password': api_secret},
        timeout=10
    )
    r.raise_for_status()
    return r.json()['access_token']


def _btc_moving_avg(days: int) -> float | None:
    history = db.get_btc_price_history(days)
    if not history:
        return None
    return sum(r['price'] for r in history) / len(history)


# ── MERCADO BITCOIN: TICKER ──────────────────────────────

@app.route('/api/mercadobitcoin/ticker')
@login_required
def mb_ticker():
    try:
        r = req.get('https://www.mercadobitcoin.net/api/BTC/ticker/', timeout=10)
        r.raise_for_status()
        ticker = r.json().get('ticker', {})
    except Exception as e:
        return jsonify({'error': f'Erro ao buscar ticker MB: {e}'}), 502

    last = float(ticker.get('last', 0))
    ma7  = _btc_moving_avg(7)
    ma30 = _btc_moving_avg(30)

    variation_from_ma30 = None
    if ma30 and ma30 > 0:
        variation_from_ma30 = round((last - ma30) / ma30 * 100, 2)

    return jsonify({
        'last':                  last,
        'high':                  float(ticker.get('high', 0)),
        'low':                   float(ticker.get('low', 0)),
        'vol':                   float(ticker.get('vol', 0)),
        'date':                  ticker.get('date'),
        'ma7':                   round(ma7, 2)  if ma7  else None,
        'ma30':                  round(ma30, 2) if ma30 else None,
        'variation_pct_from_ma30': variation_from_ma30,
    })


# ── MERCADO BITCOIN: ORDERBOOK ───────────────────────────

@app.route('/api/mercadobitcoin/orderbook')
@login_required
def mb_orderbook():
    try:
        r = req.get('https://www.mercadobitcoin.net/api/BTC/orderbook/', timeout=10)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        return jsonify({'error': f'Erro ao buscar orderbook MB: {e}'}), 502

    bids = [[float(p), float(q)] for p, q in data.get('bids', [])[:5]]
    asks = [[float(p), float(q)] for p, q in data.get('asks', [])[:5]]

    spread     = None
    spread_pct = None
    if asks and bids:
        best_ask   = asks[0][0]
        best_bid   = bids[0][0]
        spread     = round(best_ask - best_bid, 2)
        spread_pct = round(spread / best_bid * 100, 4) if best_bid > 0 else None

    return jsonify({
        'bids':       bids,
        'asks':       asks,
        'spread':     spread,
        'spread_pct': spread_pct,
    })


# ── MERCADO BITCOIN: CONTA ───────────────────────────────

@app.route('/api/mercadobitcoin/conta')
@login_required
def mb_conta():
    api_id     = db.get_config('mb_api_id')
    api_secret = db.get_config('mb_api_secret')
    if not api_id or not api_secret:
        return jsonify({'configured': False})

    try:
        token = _mb_get_token(api_id, api_secret)
        r = req.get(
            'https://api.mercadobitcoin.net/api/v4/accounts',
            headers={'Authorization': f'Bearer {token}'},
            timeout=10
        )
        r.raise_for_status()
        accounts = r.json()
        account_id = accounts[0]['id'] if isinstance(accounts, list) and accounts else None
        if not account_id:
            return jsonify({'configured': True, 'error': 'Nenhuma conta encontrada'}), 502
        r2 = req.get(
            f'https://api.mercadobitcoin.net/api/v4/accounts/{account_id}/balances',
            headers={'Authorization': f'Bearer {token}'},
            timeout=10
        )
        r2.raise_for_status()
        balances = r2.json()
    except Exception as e:
        return jsonify({'configured': True, 'error': f'Erro ao buscar saldo MB: {e}'}), 502

    btc_balance = 0.0
    brl_balance = 0.0
    for b in balances if isinstance(balances, list) else []:
        symbol    = b.get('symbol', '')
        available = float(b.get('available', 0) or 0)
        on_hold   = float(b.get('on_hold', 0) or 0)
        total     = available + on_hold
        if symbol == 'BTC':
            btc_balance = total
        elif symbol == 'BRL':
            brl_balance = total

    return jsonify({
        'configured':    True,
        'btc_balance':   btc_balance,
        'brl_balance':   brl_balance,
    })


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
