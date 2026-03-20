from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import database as db
from mercadopago import MercadoPagoClient
import email_service
import pytz

TZ = pytz.timezone('America/Sao_Paulo')
scheduler = BackgroundScheduler(timezone=TZ)


def sync_mercadopago():
    """Busca movimentos e saldo na API do MP e salva no banco."""
    token = db.get_config('mp_token')
    if not token:
        print('[Sync] Token não configurado, pulando sync.')
        return

    print('[Sync] Iniciando sincronização com Mercado Pago...')
    mp = MercadoPagoClient(token)

    movements = mp.fetch_movements(limit=100)
    saved = db.save_transactions(movements)
    print(f'[Sync] {len(movements)} movimentos buscados, {saved} novos salvos.')

    balance = mp.fetch_balance()
    if balance is not None:
        db.save_balance(balance)
        print(f'[Sync] Saldo atualizado: R$ {balance:,.2f}')


def send_daily_email():
    """Envia o resumo diário por e-mail às 8:30."""
    print('[Email] Disparando resumo diário...')
    ok = email_service.send_daily_summary()
    if ok:
        print('[Email] Resumo enviado com sucesso.')
    else:
        print('[Email] Falha ao enviar resumo.')


def start_scheduler():
    # Sync a cada hora
    scheduler.add_job(
        sync_mercadopago,
        trigger=CronTrigger(minute=0, timezone=TZ),
        id='sync_mp',
        replace_existing=True
    )

    # E-mail diário às 8:30 horário de Brasília
    scheduler.add_job(
        send_daily_email,
        trigger=CronTrigger(hour=8, minute=30, timezone=TZ),
        id='daily_email',
        replace_existing=True
    )

    scheduler.start()
    print('[Scheduler] Jobs iniciados: sync a cada hora + e-mail às 8:30.')


def stop_scheduler():
    if scheduler.running:
        scheduler.shutdown()
