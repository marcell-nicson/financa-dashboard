import requests
from datetime import datetime, timezone

MP_BASE = 'https://api.mercadopago.com'
TIMEOUT = 15


class MercadoPagoClient:
    def __init__(self, token: str):
        self.token = token
        self.headers = {'Authorization': f'Bearer {token}'}

    def _get(self, path: str, params: dict = None):
        try:
            r = requests.get(
                MP_BASE + path,
                headers=self.headers,
                params=params,
                timeout=TIMEOUT
            )
            r.raise_for_status()
            return r.json()
        except requests.HTTPError as e:
            print(f'[MP] HTTP {e.response.status_code} em {path}')
            return None
        except Exception as e:
            print(f'[MP] Erro em {path}: {e}')
            return None

    def get_user(self):
        return self._get('/users/me')

    def fetch_movements(self, limit=50):
        now = datetime.now(timezone.utc)
        begin = datetime(now.year, now.month, 1, tzinfo=timezone.utc)

        data = self._get('/v1/account/movements/search', params={
            'limit': limit,
            'offset': 0,
            'begin_date': begin.isoformat(),
            'end_date': now.isoformat(),
        })

        if data and 'results' in data:
            return data['results']
        return []

    def fetch_balance(self):
        """Tenta extrair saldo do usuário ou dos movimentos."""
        user = self.get_user()
        if user:
            # Alguns planos expõem o saldo direto no perfil
            available = user.get('available_balance') or user.get('balance')
            if available is not None:
                return float(available)

        # Fallback: calcula pelo saldo dos movimentos do mês
        movements = self.fetch_movements(limit=200)
        total = sum(float(m.get('amount', 0)) for m in movements)
        return total
