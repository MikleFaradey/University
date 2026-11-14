class Registry:

    def __init__(self):
        self._services = {}

    def provide(self, contract, implementation):
        if contract in self._services:
            raise RuntimeError(f'Duplicate service: {contract.__name__}')
        self._services[contract] = implementation

    def get(self, contract):
        try:
            return self._services[contract]
        except KeyError:
            raise RuntimeError(f'Missing service: {contract.__name__}') from None

    def optional(self, contract):
        return self._services.get(contract)
