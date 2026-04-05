import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timedelta
import database as db


def send_email(subject: str, html_body: str, to_email: str):
    gmail_user = db.get_config('gmail_user')
    gmail_pass = db.get_config('gmail_app_password')

    if not gmail_user or not gmail_pass:
        print('[Email] Credenciais Gmail não configuradas.')
        return False

    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From']    = f'Dashboard Financeiro <{gmail_user}>'
        msg['To']      = to_email

        msg.attach(MIMEText(html_body, 'html', 'utf-8'))

        with smtplib.SMTP('smtp.gmail.com', 587) as server:
            server.ehlo()
            server.starttls()
            server.login(gmail_user, gmail_pass)
            server.sendmail(gmail_user, to_email, msg.as_string())

        print(f'[Email] Enviado para {to_email}')
        return True

    except Exception as e:
        print(f'[Email] Erro ao enviar: {e}')
        return False


def build_daily_email(crypto_data: dict = None, btc_analysis_html: str = ''):
    yesterday = (datetime.utcnow() - timedelta(days=1)).strftime('%Y-%m-%d')
    date_label = (datetime.utcnow() - timedelta(days=1)).strftime('%d/%m/%Y')

    txs     = db.get_daily_summary(yesterday)
    summary = db.get_monthly_summary()
    balance = db.get_latest_balance()

    total_day  = sum(abs(t['amount']) for t in txs if t['amount'] < 0)
    entradas   = summary.get('entradas', 0)
    saidas     = summary.get('saidas', 0)
    disponivel = balance.get('available', entradas - saidas)
    investivel = disponivel * 0.45

    # Orientações dinâmicas
    orientacoes = []
    pct = (saidas / entradas * 100) if entradas > 0 else 0

    if pct > 80:
        orientacoes.append(('danger', '🔴', 'Gastos críticos',
            f'Suas saídas estão em {pct:.0f}% das entradas. Revise seus gastos urgentemente.'))
    elif pct > 65:
        orientacoes.append(('warn', '⚠️', 'Ritmo de gastos alto',
            f'Saídas em {pct:.0f}% das entradas. Tente reduzir gastos variáveis.'))
    else:
        orientacoes.append(('ok', '✅', 'Gastos sob controle',
            f'Saídas em {pct:.0f}% das entradas. Continue assim!'))

    if investivel > 500:
        orientacoes.append(('tip', '💡', 'Oportunidade de investimento',
            f'Você tem R$ {investivel:,.2f} disponíveis para investir. '
            f'No CDB 110% CDI renderiam ~R$ {investivel * 0.117 / 12:,.2f}/mês.'))

    # Transações do dia
    tx_html = ''
    if txs:
        for t in txs[:10]:
            color = '#00e676' if t['amount'] > 0 else '#ff4569'
            sinal = '+' if t['amount'] > 0 else '-'
            tx_html += f'''
            <tr>
              <td style="padding:8px 0;border-bottom:1px solid #1e1e2e;font-size:13px;color:#ccc">
                {t["description"]}
              </td>
              <td style="padding:8px 0;border-bottom:1px solid #1e1e2e;text-align:right;
                         font-size:13px;font-weight:600;color:{color}">
                {sinal} R$ {abs(t["amount"]):,.2f}
              </td>
            </tr>'''
    else:
        tx_html = '<tr><td colspan="2" style="color:#666;padding:12px 0;font-size:13px">Nenhuma movimentação ontem.</td></tr>'

    # Alertas HTML
    alert_colors = {
        'danger': ('#ff4569', 'rgba(255,69,105,0.08)', 'rgba(255,69,105,0.2)'),
        'warn':   ('#ffd600', 'rgba(255,214,0,0.08)',  'rgba(255,214,0,0.2)'),
        'ok':     ('#00e676', 'rgba(0,230,118,0.08)',  'rgba(0,230,118,0.2)'),
        'tip':    ('#00b1ea', 'rgba(0,177,234,0.08)',  'rgba(0,177,234,0.2)'),
    }
    orient_html = ''
    for kind, emoji, title, msg in orientacoes:
        c, bg, border = alert_colors.get(kind, alert_colors['tip'])
        orient_html += f'''
        <div style="background:{bg};border:1px solid {border};border-radius:10px;
                    padding:12px 16px;margin-bottom:10px">
          <div style="font-size:13px;font-weight:600;color:{c};margin-bottom:4px">
            {emoji} {title}
          </div>
          <div style="font-size:12px;color:#999;line-height:1.5">{msg}</div>
        </div>'''

    # Crypto HTML
    crypto_html = ''
    if crypto_data:
        coins = [
            ('bitcoin',     '₿',  'Bitcoin (BTC)'),
            ('ethereum',    '⟠',  'Ethereum (ETH)'),
            ('solana',      '◎',  'Solana (SOL)'),
            ('binancecoin', '🔶', 'BNB'),
        ]
        for cid, icon, name in coins:
            if cid not in crypto_data:
                continue
            price  = crypto_data[cid].get('brl', 0)
            change = crypto_data[cid].get('brl_24h_change', 0)
            up     = change >= 0
            color  = '#00e676' if up else '#ff4569'
            arrow  = '▲' if up else '▼'
            crypto_html += f'''
            <tr>
              <td style="padding:8px 0;border-bottom:1px solid #1e1e2e;font-size:13px;color:#ccc">
                {icon} {name}
              </td>
              <td style="padding:8px 0;border-bottom:1px solid #1e1e2e;text-align:right">
                <span style="font-size:13px;color:#eee">R$ {price:,.2f}</span>
                <span style="font-size:11px;color:{color};margin-left:6px">
                  {arrow} {abs(change):.2f}%
                </span>
              </td>
            </tr>'''

    # ── Seção BTC detalhada ───────────────────────────────
    btc_section_html = ''
    if crypto_data and 'bitcoin' in crypto_data:
        btc_price   = crypto_data['bitcoin'].get('brl', 0)
        btc_24h     = crypto_data['bitcoin'].get('brl_24h_change', 0)
        btc_7d      = crypto_data['bitcoin'].get('brl_7d_change', None)

        def _change_row(label, chg):
            up    = chg >= 0
            c     = '#00e676' if up else '#ff4569'
            arrow = '▲' if up else '▼'
            return (
                f'<tr>'
                f'<td style="padding:8px 0;border-bottom:1px solid #1e1e2e;font-size:13px;color:#ccc">{label}</td>'
                f'<td style="padding:8px 0;border-bottom:1px solid #1e1e2e;text-align:right;font-size:13px;font-weight:600;color:{c}">'
                f'{arrow} {abs(chg):.2f}%</td>'
                f'</tr>'
            )

        btc_rows = (
            f'<tr>'
            f'<td style="padding:8px 0;border-bottom:1px solid #1e1e2e;font-size:13px;color:#ccc">Preço atual (BRL)</td>'
            f'<td style="padding:8px 0;border-bottom:1px solid #1e1e2e;text-align:right;font-size:14px;font-weight:700;color:#eee">'
            f'R$ {btc_price:,.2f}</td>'
            f'</tr>'
        )
        btc_rows += _change_row('Variação 24h', btc_24h)
        if btc_7d is not None:
            btc_rows += _change_row('Variação 7d', btc_7d)

        # Posição do usuário
        btc_qtd_str   = db.get_config('btc_quantidade') or ''
        btc_medio_str = db.get_config('btc_preco_medio') or ''
        btc_alert_html = ''

        if btc_qtd_str:
            try:
                qtd   = float(btc_qtd_str)
                valor = qtd * btc_price
                btc_rows += (
                    f'<tr>'
                    f'<td style="padding:8px 0;border-bottom:1px solid #1e1e2e;font-size:13px;color:#ccc">Sua posição ({qtd} BTC)</td>'
                    f'<td style="padding:8px 0;border-bottom:1px solid #1e1e2e;text-align:right;font-size:13px;font-weight:600;color:#00b1ea">'
                    f'R$ {valor:,.2f}</td>'
                    f'</tr>'
                )
                if btc_medio_str:
                    medio   = float(btc_medio_str)
                    pnl     = (btc_price - medio) * qtd
                    pnl_pct = ((btc_price - medio) / medio * 100) if medio > 0 else 0
                    pnl_color = '#00e676' if pnl >= 0 else '#ff4569'
                    pnl_sinal = '+' if pnl >= 0 else ''
                    btc_rows += (
                        f'<tr>'
                        f'<td style="padding:8px 0;font-size:13px;color:#ccc">Lucro/Prejuízo</td>'
                        f'<td style="padding:8px 0;text-align:right;font-size:13px;font-weight:600;color:{pnl_color}">'
                        f'{pnl_sinal}R$ {pnl:,.2f} ({pnl_sinal}{pnl_pct:.2f}%)</td>'
                        f'</tr>'
                    )

                    # Verificar cruzamento de limiares para bloco de alerta visual
                    alerta_acima_str  = db.get_config('btc_alerta_acima') or ''
                    alerta_abaixo_str = db.get_config('btc_alerta_abaixo') or ''
                    alert_kind = None
                    alert_msg  = ''
                    if alerta_acima_str:
                        try:
                            if btc_price > float(alerta_acima_str):
                                alert_kind = 'warn'
                                alert_msg  = f'Preço acima do limite de R$ {float(alerta_acima_str):,.2f}'
                        except ValueError:
                            pass
                    if not alert_kind and alerta_abaixo_str:
                        try:
                            if btc_price < float(alerta_abaixo_str):
                                alert_kind = 'danger'
                                alert_msg  = f'Preço abaixo do limite de R$ {float(alerta_abaixo_str):,.2f}'
                        except ValueError:
                            pass
                    if alert_kind:
                        c, bg, border = alert_colors.get(alert_kind, alert_colors['warn'])
                        btc_alert_html = (
                            f'<div style="background:{bg};border:1px solid {border};border-radius:10px;'
                            f'padding:12px 16px;margin-top:12px">'
                            f'<div style="font-size:13px;font-weight:600;color:{c};margin-bottom:4px">⚠️ Alerta de preço</div>'
                            f'<div style="font-size:12px;color:#999;line-height:1.5">{alert_msg}</div>'
                            f'</div>'
                        )
            except (ValueError, ZeroDivisionError):
                pass

        btc_section_html = (
            f'<div style="background:#16161f;border:1px solid rgba(255,255,255,0.07);'
            f'border-radius:14px;padding:20px;margin-bottom:14px">'
            f'<div style="font-size:11px;text-transform:uppercase;letter-spacing:1px;color:#6b6b88;margin-bottom:14px">₿ Bitcoin — Posição detalhada</div>'
            f'<table style="width:100%;border-collapse:collapse">{btc_rows}</table>'
            f'{btc_alert_html}'
            f'</div>'
        )

    html = f'''<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#0e0e16;font-family:Arial,sans-serif">
<div style="max-width:580px;margin:0 auto;padding:32px 20px">

  <h2 style="color:#00b1ea;font-size:18px;margin-bottom:4px">
    📊 Resumo Financeiro — {date_label}
  </h2>
  <p style="color:#666;font-size:13px;margin-bottom:28px">
    Bom dia, Marcell! Aqui está seu resumo do dia anterior.
  </p>

  <!-- GASTOS DO DIA -->
  <div style="background:#16161f;border:1px solid rgba(255,255,255,0.07);
              border-radius:14px;padding:20px;margin-bottom:14px">
    <div style="font-size:11px;text-transform:uppercase;letter-spacing:1px;
                color:#6b6b88;margin-bottom:14px">💸 Movimentações de ontem</div>
    <table style="width:100%;border-collapse:collapse">{tx_html}</table>
    <div style="margin-top:12px;font-size:13px;color:#999">
      Total gasto: <span style="color:#ff4569;font-weight:600">R$ {total_day:,.2f}</span>
    </div>
  </div>

  <!-- SITUAÇÃO DO MÊS -->
  <div style="background:#16161f;border:1px solid rgba(255,255,255,0.07);
              border-radius:14px;padding:20px;margin-bottom:14px">
    <div style="font-size:11px;text-transform:uppercase;letter-spacing:1px;
                color:#6b6b88;margin-bottom:14px">💰 Situação do mês</div>
    <table style="width:100%;border-collapse:collapse">
      <tr>
        <td style="padding:7px 0;border-bottom:1px solid #1e1e2e;font-size:13px;color:#ccc">Entradas</td>
        <td style="padding:7px 0;border-bottom:1px solid #1e1e2e;text-align:right;
                   font-size:13px;font-weight:600;color:#00e676">R$ {entradas:,.2f}</td>
      </tr>
      <tr>
        <td style="padding:7px 0;border-bottom:1px solid #1e1e2e;font-size:13px;color:#ccc">Saídas</td>
        <td style="padding:7px 0;border-bottom:1px solid #1e1e2e;text-align:right;
                   font-size:13px;font-weight:600;color:#ff4569">R$ {saidas:,.2f}</td>
      </tr>
      <tr>
        <td style="padding:7px 0;border-bottom:1px solid #1e1e2e;font-size:13px;color:#ccc">Disponível</td>
        <td style="padding:7px 0;border-bottom:1px solid #1e1e2e;text-align:right;
                   font-size:13px;font-weight:600;color:#00b1ea">R$ {disponivel:,.2f}</td>
      </tr>
      <tr>
        <td style="padding:7px 0;font-size:13px;color:#ccc">Potencial investível (45%)</td>
        <td style="padding:7px 0;text-align:right;font-size:13px;
                   font-weight:600;color:#7c4dff">R$ {investivel:,.2f}</td>
      </tr>
    </table>
  </div>

  <!-- ORIENTAÇÕES -->
  <div style="background:#16161f;border:1px solid rgba(255,255,255,0.07);
              border-radius:14px;padding:20px;margin-bottom:14px">
    <div style="font-size:11px;text-transform:uppercase;letter-spacing:1px;
                color:#6b6b88;margin-bottom:14px">💡 Orientações</div>
    {orient_html}
  </div>

  <!-- CRYPTO -->
  {'<div style="background:#16161f;border:1px solid rgba(255,255,255,0.07);border-radius:14px;padding:20px;margin-bottom:14px"><div style="font-size:11px;text-transform:uppercase;letter-spacing:1px;color:#6b6b88;margin-bottom:14px">₿ Criptomoedas — Variação 24h</div><table style="width:100%;border-collapse:collapse">' + crypto_html + '</table></div>' if crypto_html else ''}

  <!-- BTC DETALHADO -->
  {btc_section_html}

  <!-- BTC ANÁLISE MB -->
  {btc_analysis_html}

  <div style="text-align:center;font-size:11px;color:#444;margin-top:24px">
    Dashboard Financeiro Pessoal · Marcell · Gerado automaticamente às 8:30<br/>
    <a href="https://financas.promoestoque.com.br" style="color:#00b1ea">
      Abrir dashboard
    </a>
  </div>

</div>
</body>
</html>'''

    return html


def build_btc_alert_email(price_brl: float, change_pct: float, motivo: str, change_period: str = '1h') -> str:
    """Monta e-mail de alerta de preço/variação de BTC."""
    btc_qtd_str   = db.get_config('btc_quantidade') or ''
    btc_medio_str = db.get_config('btc_preco_medio') or ''

    up    = change_pct >= 0
    color = '#00e676' if up else '#ff4569'
    arrow = '▲' if up else '▼'

    posicao_html = ''
    if btc_qtd_str:
        try:
            qtd    = float(btc_qtd_str)
            valor  = qtd * price_brl
            posicao_html = f'''
      <tr>
        <td style="padding:8px 0;border-bottom:1px solid #1e1e2e;font-size:13px;color:#ccc">Sua posição ({qtd} BTC)</td>
        <td style="padding:8px 0;border-bottom:1px solid #1e1e2e;text-align:right;font-size:13px;font-weight:600;color:#00b1ea">
          R$ {valor:,.2f}
        </td>
      </tr>'''
            if btc_medio_str:
                medio   = float(btc_medio_str)
                pnl     = (price_brl - medio) * qtd
                pnl_pct = ((price_brl - medio) / medio * 100) if medio > 0 else 0
                pnl_color = '#00e676' if pnl >= 0 else '#ff4569'
                pnl_sinal = '+' if pnl >= 0 else ''
                posicao_html += f'''
      <tr>
        <td style="padding:8px 0;font-size:13px;color:#ccc">Lucro/Prejuízo</td>
        <td style="padding:8px 0;text-align:right;font-size:13px;font-weight:600;color:{pnl_color}">
          {pnl_sinal}R$ {pnl:,.2f} ({pnl_sinal}{pnl_pct:.2f}%)
        </td>
      </tr>'''
        except (ValueError, ZeroDivisionError):
            pass

    html = f'''<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#0e0e16;font-family:Arial,sans-serif">
<div style="max-width:580px;margin:0 auto;padding:32px 20px">

  <h2 style="color:#ffd600;font-size:18px;margin-bottom:4px">
    ⚠️ Alerta BTC
  </h2>
  <p style="color:#666;font-size:13px;margin-bottom:28px">
    {motivo}
  </p>

  <div style="background:#16161f;border:1px solid rgba(255,255,255,0.07);border-radius:14px;padding:20px;margin-bottom:14px">
    <div style="font-size:11px;text-transform:uppercase;letter-spacing:1px;color:#6b6b88;margin-bottom:14px">₿ Bitcoin — Dados atuais</div>
    <table style="width:100%;border-collapse:collapse">
      <tr>
        <td style="padding:8px 0;border-bottom:1px solid #1e1e2e;font-size:13px;color:#ccc">Preço atual (BRL)</td>
        <td style="padding:8px 0;border-bottom:1px solid #1e1e2e;text-align:right;font-size:14px;font-weight:700;color:#eee">
          R$ {price_brl:,.2f}
        </td>
      </tr>
      <tr>
        <td style="padding:8px 0;border-bottom:1px solid #1e1e2e;font-size:13px;color:#ccc">Variação ({change_period})</td>
        <td style="padding:8px 0;border-bottom:1px solid #1e1e2e;text-align:right;font-size:13px;font-weight:600;color:{color}">
          {arrow} {abs(change_pct):.2f}%
        </td>
      </tr>
      {posicao_html}
    </table>
  </div>

  <div style="background:rgba(255,214,0,0.08);border:1px solid rgba(255,214,0,0.2);border-radius:10px;padding:12px 16px;margin-bottom:14px">
    <div style="font-size:13px;font-weight:600;color:#ffd600;margin-bottom:4px">⚠️ Motivo do alerta</div>
    <div style="font-size:12px;color:#999;line-height:1.5">{motivo}</div>
  </div>

  <div style="text-align:center;font-size:11px;color:#444;margin-top:24px">
    Dashboard Financeiro Pessoal · Marcell · Alerta automático<br/>
    <a href="https://financas.promoestoque.com.br" style="color:#00b1ea">Abrir dashboard</a>
  </div>

</div>
</body>
</html>'''
    return html


def _build_btc_analysis_section() -> str:
    """Monta seção HTML com análise BTC para o e-mail diário."""
    # Preço atual do MB
    import requests as req
    try:
        r       = req.get('https://www.mercadobitcoin.net/api/BTC/ticker/', timeout=10)
        ticker  = r.json().get('ticker', {})
        btc_now = float(ticker.get('last', 0))
    except Exception:
        btc_now = 0

    # Médias móveis do banco de dados
    history_7  = db.get_btc_price_history(7)
    history_30 = db.get_btc_price_history(30)
    ma7  = sum(r['price'] for r in history_7)  / len(history_7)  if history_7  else None
    ma30 = sum(r['price'] for r in history_30) / len(history_30) if history_30 else None

    # Fear & Greed index
    fg_value = None
    fg_label = ''
    try:
        fg_r    = req.get('https://api.alternative.me/fng/?limit=1', timeout=8)
        fg_data = fg_r.json().get('data', [{}])[0]
        fg_value = int(fg_data.get('value', 0))
        fg_label = fg_data.get('value_classification', '')
    except Exception:
        pass

    # Badge color para F&G
    if fg_value is not None:
        if fg_value < 25:
            fg_color = '#ff4569'
            fg_label_pt = 'Medo Extremo'
        elif fg_value < 45:
            fg_color = '#ff9100'
            fg_label_pt = 'Medo'
        elif fg_value < 55:
            fg_color = '#ffd600'
            fg_label_pt = 'Neutro'
        elif fg_value < 75:
            fg_color = '#a5d6a7'
            fg_label_pt = 'Ganância'
        else:
            fg_color = '#00e676'
            fg_label_pt = 'Ganância Extrema'
    else:
        fg_color    = '#6b6b88'
        fg_label_pt = 'N/D'

    SELIC_AA = 10.75

    # Dica inteligente
    dica = ''
    if fg_value is not None and fg_value < 25:
        dica = '💡 Fear &amp; Greed abaixo de 25 — possível ponto de acumulação.'
    elif ma30 and btc_now > 0 and ((btc_now - ma30) / ma30 * 100) > 20:
        dica = '⚠️ Preço mais de 20% acima da MA30 — mercado possivelmente sobreaquecido.'

    def _row(label, val_html):
        return (
            f'<tr>'
            f'<td style="padding:7px 0;border-bottom:1px solid #1e1e2e;font-size:13px;color:#ccc">{label}</td>'
            f'<td style="padding:7px 0;border-bottom:1px solid #1e1e2e;text-align:right">{val_html}</td>'
            f'</tr>'
        )

    rows = ''
    if btc_now:
        rows += _row('Preço atual (BRL)',
                     f'<span style="font-size:14px;font-weight:700;color:#eee">R$ {btc_now:,.2f}</span>')
    if ma7:
        above = btc_now >= ma7 if btc_now else True
        c = '#00e676' if above else '#ff4569'
        rows += _row('Média móvel 7d (MA7)',
                     f'<span style="font-size:13px;font-weight:600;color:{c}">R$ {ma7:,.2f}</span>')
    if ma30:
        above30 = btc_now >= ma30 if btc_now else True
        c30 = '#00e676' if above30 else '#ff4569'
        var30 = ((btc_now - ma30) / ma30 * 100) if btc_now else 0
        sign  = '+' if var30 >= 0 else ''
        rows += _row('Média móvel 30d (MA30)',
                     f'<span style="font-size:13px;font-weight:600;color:{c30}">R$ {ma30:,.2f} ({sign}{var30:.1f}%)</span>')

    if fg_value is not None:
        rows += _row('Fear &amp; Greed Index',
                     f'<span style="font-size:13px;font-weight:600;color:{fg_color}">{fg_value} — {fg_label_pt}</span>')

    rows += _row('SELIC (referência renda fixa)',
                 f'<span style="font-size:13px;color:#ccc">{SELIC_AA:.2f}% a.a.</span>')

    dica_html = ''
    if dica:
        dica_html = (
            f'<div style="background:rgba(0,177,234,0.07);border:1px solid rgba(0,177,234,0.2);'
            f'border-radius:8px;padding:10px 14px;margin-top:12px;font-size:12px;color:#999;line-height:1.5">'
            f'{dica}</div>'
        )

    return (
        f'<div style="background:#16161f;border:1px solid rgba(255,255,255,0.07);'
        f'border-radius:14px;padding:20px;margin-bottom:14px">'
        f'<div style="font-size:11px;text-transform:uppercase;letter-spacing:1px;color:#6b6b88;margin-bottom:14px">₿ Análise BTC — Mercado Bitcoin</div>'
        f'<table style="width:100%;border-collapse:collapse">{rows}</table>'
        f'{dica_html}'
        f'</div>'
    )


def send_daily_summary():
    to_email = db.get_config('email_destinatario') or 'marcellnicson@gmail.com'

    # Busca preços das cryptos (inclui 7d)
    crypto_data = {}
    try:
        import requests as req
        r = req.get(
            'https://api.coingecko.com/api/v3/simple/price'
            '?ids=bitcoin,ethereum,solana,binancecoin'
            '&vs_currencies=brl&include_24hr_change=true&include_7d_change=true',
            timeout=10
        )
        crypto_data = r.json()
    except Exception as e:
        print(f'[Email] Não foi possível buscar crypto: {e}')

    btc_analysis_html = ''
    try:
        btc_analysis_html = _build_btc_analysis_section()
    except Exception as e:
        print(f'[Email] Erro ao montar seção BTC: {e}')

    date_label = (datetime.utcnow() - timedelta(days=1)).strftime('%d/%m/%Y')
    subject    = f'📊 Resumo Financeiro — {date_label}'
    html_body  = build_daily_email(crypto_data, btc_analysis_html)

    return send_email(subject, html_body, to_email)
