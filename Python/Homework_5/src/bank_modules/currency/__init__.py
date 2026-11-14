from decimal import Decimal, ROUND_HALF_UP
from core.protocols import CurrencyAPI

class Plugin:
    name = 'currency'

    def initialize(self, ctx):
        self.rates = {k: Decimal(str(v)) for k, v in ctx.config.get('currency_rates', {'RUB': 1, 'USD': 90, 'EUR': 100}).items()}
        ctx.registry.provide(CurrencyAPI, self)

    def convert(self, amount, src, dst):
        if amount <= 0:
            raise ValueError('Amount must be positive')
        if src not in self.rates or dst not in self.rates:
            raise ValueError('Unknown currency')
        result = Decimal(amount) * self.rates[src] / self.rates[dst]
        return int(result.quantize(Decimal('1'), rounding=ROUND_HALF_UP))

    def register_commands(self, commands):
        commands.register('exchange-rate', 'exchange-rate USD EUR', lambda sess, a, b: f'{a}/{b}: {self.rates[a] / self.rates[b]:.4f}')
