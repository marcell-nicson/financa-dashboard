from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import database as db
import email_service
import pytz

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


def start_scheduler():
    # E-mail diário às 8:30 horário de Brasília
    scheduler.add_job(
        send_daily_email,
        trigger=CronTrigger(hour=8, minute=30, timezone=TZ),
        id='daily_email',
        replace_existing=True
    )

    scheduler.start()
    print('[Scheduler] Job iniciado: e-mail diário às 8:30.')


def stop_scheduler():
    if scheduler.running:
        scheduler.shutdown()
