# Finança Dashboard

Dashboard financeiro pessoal integrado ao Mercado Pago via importação manual de extrato CSV.

## Stack

- **Backend:** Python 3 + Flask
- **Banco de dados:** SQLite3
- **Frontend:** HTML/CSS/JavaScript puro + Chart.js
- **Infra:** Nginx + systemd + Gunicorn

## Funcionalidades

- Importação de extrato CSV exportado pelo Mercado Pago
- Cards de saldo disponível, investível, entradas e saídas do mês
- Categorização automática das transações
- Gráficos de pizza (categorias) e barras (entradas vs saídas)
- Editar e deletar transações individualmente
- Lista de transações com filtro por mês
- Percentual investível configurável (padrão 45%)
- Preços de cripto ao vivo: BTC, ETH, SOL, BNB (CoinGecko)
- Resumo financeiro diário por e-mail (Gmail, 8h30 horário de Brasília)
- Login com senha protegida por hash

## Estrutura

```
financa-dashboard/
├── app.py               # Rotas Flask e lógica de importação CSV
├── database.py          # Wrapper SQLite (schema, queries)
├── scheduler.py         # Job de e-mail diário (APScheduler)
├── email_service.py     # Envio de resumo via Gmail SMTP
├── mercadopago.py       # Cliente MP (legado, não utilizado)
├── set_password.py      # CLI para configurar usuário/senha inicial
├── requirements.txt     # Dependências Python
├── financa.service      # Unidade systemd
├── nginx-financa.conf   # Config Nginx
├── setup.sh             # Script de instalação no servidor
└── templates/
    ├── dashboard.html   # SPA principal
    └── login.html       # Página de autenticação
```

## Banco de dados

```sql
config        -- chave/valor: gmail, senha app, percentual investível
transactions  -- id, external_id, description, amount, type, category, date_created
balances      -- histórico de saldos importados
```

## Categorias automáticas

Na importação do CSV, cada transação é categorizada pelo destinatário/propósito:

| Categoria | Exemplos de detecção |
|---|---|
| Rendimentos | "rendimento", "juros" |
| PIX | PIX sem categoria específica identificada |
| Alimentação | mercado, supermercado, iFood |
| Transporte | Uber, 99, combustível, pedágio |
| Saúde | plano de saúde, farmácia, médico |
| Lazer | Netflix, Spotify, cinema |
| Moradia | aluguel, condomínio, energia, internet |
| Cartão de Crédito | "cartão de crédito", "fatura cartão" |
| Financiamentos | Itaú, Banco Pan, "pagamento de conta" |
| Impostos | Receita Federal, INSS, IPTU, IPVA |
| Reserva | "reserva", "meta" |
| Outros | demais transações |

## Regras de negócio

- **Saldo disponível:** FINAL_BALANCE do último CSV importado
- **Investível:** `saldo × percentual` (padrão 45%, configurável)
- **Entradas:** soma de transações com `amount > 0` no mês ativo
- **Saídas:** soma de transações com `amount < 0` no mês ativo
- **Mês ativo:** mês atual; se vazio, usa o mês mais recente com dados
- **Deduplicação:** `external_id` único (REFERENCE_ID do CSV) — reimportar o mesmo CSV não duplica transações
- **Usuário:** sistema single-user, senha armazenada como hash bcrypt

## Formato do CSV (Mercado Pago)

Exportar em: Atividades → Baixar → CSV

```
INITIAL_BALANCE;CREDITS;DEBITS;FINAL_BALANCE
925,43;12.871,66;-10.988,94;2.808,15

RELEASE_DATE;TRANSACTION_TYPE;REFERENCE_ID;TRANSACTION_NET_AMOUNT;PARTIAL_BALANCE
01-03-2026;Pix recebido Fulano;148382131098;150,00;1.075,43
```

## Deploy

### Primeiro uso

```bash
bash setup.sh
python3 set_password.py
sudo systemctl start financa
```

### Atualização

```bash
cd /var/www/financa-dashboard
git pull origin main
sudo systemctl restart financa
```

## Configuração de e-mail

No dashboard → Configurar → E-mail:
1. Conta Gmail com autenticação de 2 fatores ativada
2. Gerar senha de app em: Conta Google → Segurança → Senhas de app
3. Preencher Gmail, senha de app e e-mail destinatário
