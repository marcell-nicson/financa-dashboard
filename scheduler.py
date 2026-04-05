from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import database as db
import email_service
import pytz
import time

TZ = pytz.timezone('America/Sao_Paulo')
scheduler = BackgroundScheduler(timezone=TZ)


# sync_mercadopago is disabled — MP API does not provide financial movements.
# Use the manual CSV import feature (/api/import-csv) instead.


def send_daily_email():
    """Envia o resumo diário por e-mail às 8:30."""
    print('[Email] Disparando resumo diário...')
    ok = email_service.send_daily_summary()
    if ok:
        print('[Email] Resumo enviado com sucesso.')
    else:
        print('[Email] Falha ao enviar resumo.')


def fetch_and_store_btc_price():
    """Busca preço atual do BTC no Mercado Bitcoin e persiste no histórico."""
    try:
        import requests as req
        r = req.get('https://www.mercadobitcoin.net/api/BTC/ticker/', timeout=10)
        ticker = r.json().get('ticker', {})
        price = float(ticker.get('last', 0))
        if price > 0:
            db.insert_btc_price(price)
            print(f'[BTC] Preço salvo: R$ {price:,.2f}')
        else:
            print('[BTC] Preço inválido retornado pela API MB.')
    except Exception as e:
        print(f'[BTC] Erro ao buscar/salvar preço: {e}')


def check_btc_alerts():
    """Verifica alertas de preço/variação BTC e envia e-mail se necessário (cooldown 3h)."""
    print('[BTC] Verificando alertas...')

    # Busca preço BTC via CoinGecko (inclui variação 1h)
    try:
        import requests as req
        r = req.get(
            'https://api.coingecko.com/api/v3/simple/price'
            '?ids=bitcoin&vs_currencies=brl&include_24hr_change=true&include_1h_change=true',
            timeout=10
        )
        data = r.json()
    except Exception as e:
        print(f'[BTC] Erro ao buscar preço: {e}')
        return

    try:
        price_brl = data['bitcoin']['brl']
        change_1h = data['bitcoin'].get('brl_1h_change', 0)
    except (KeyError, TypeError) as e:
        print(f'[BTC] Dados inesperados da API: {e}')
        return

    # Lê configs de alerta
    alerta_acima_str     = db.get_config('btc_alerta_acima') or ''
    alerta_abaixo_str    = db.get_config('btc_alerta_abaixo') or ''
    alerta_var_pct_str   = db.get_config('btc_alerta_variacao_pct') or ''
    ultimo_ts_str        = db.get_config('btc_alerta_ultimo_ts') or '0'

    # Cooldown de 3 horas
    try:
        ultimo_ts = float(ultimo_ts_str)
    except ValueError:
        ultimo_ts = 0
    if time.time() - ultimo_ts < 10800:
        print('[BTC] Cooldown ativo, pulando verificação.')
        return

    # Verifica condições de alerta
    motivo     = None
    change_pct = change_1h

    if alerta_acima_str:
        try:
            if price_brl > float(alerta_acima_str):
                motivo = f'Preço acima do limite de R$ {float(alerta_acima_str):,.2f}'
        except ValueError:
            pass

    if not motivo and alerta_abaixo_str:
        try:
            if price_brl < float(alerta_abaixo_str):
                motivo = f'Preço abaixo do limite de R$ {float(alerta_abaixo_str):,.2f}'
        except ValueError:
            pass

    if not motivo and alerta_var_pct_str:
        try:
            if abs(change_1h) > float(alerta_var_pct_str):
                sinal  = '+' if change_1h >= 0 else ''
                motivo = f'Variação de {sinal}{change_1h:.2f}% em 1h'
        except ValueError:
            pass

    if not motivo:
        print('[BTC] Nenhum alerta disparado.')
        return

    print(f'[BTC] Alerta disparado: {motivo}')

    # Envia e-mail de alerta
    try:
        to_email  = db.get_config('email_destinatario') or 'marcellnicson@gmail.com'
        html_body = email_service.build_btc_alert_email(price_brl, change_pct, motivo, '1h')
        subject   = f'⚠️ Alerta BTC — {motivo}'
        ok        = email_service.send_email(subject, html_body, to_email)
        if ok:
            db.set_config('btc_alerta_ultimo_ts', str(time.time()))
            print('[BTC] Alerta enviado com sucesso.')
        else:
            print('[BTC] Falha ao enviar alerta.')
    except Exception as e:
        print(f'[BTC] Erro ao enviar alerta: {e}')


def start_scheduler():
    # E-mail diário às 8:30 horário de Brasília
    scheduler.add_job(
        send_daily_email,
        trigger=CronTrigger(hour=8, minute=30, timezone=TZ),
        id='daily_email',
        replace_existing=True
    )

    # Verificação de alertas BTC a cada hora
    scheduler.add_job(
        check_btc_alerts,
        trigger=CronTrigger(minute=0, timezone=TZ),
        id='btc_alerts',
        replace_existing=True
    )

    # Coleta de preço BTC a cada hora (no minuto 1 para não conflitar com alertas)
    scheduler.add_job(
        fetch_and_store_btc_price,
        trigger=CronTrigger(minute=1, timezone=TZ),
        id='btc_price_history',
        replace_existing=True
    )

    scheduler.start()
    print('[Scheduler] Jobs iniciados: e-mail diário às 8:30, alertas BTC e histórico de preço a cada hora.')


def stop_scheduler():
    if scheduler.running:
        scheduler.shutdown()
