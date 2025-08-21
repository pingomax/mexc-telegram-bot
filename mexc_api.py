import logging

class MexcAPI:
    def __init__(self, api_key, api_secret):
        self.api_key = api_key
        self.api_secret = api_secret

    def place_order(self, signal, usdt, leverage):
        logging.info(f"Executando ordem: sinal={signal}, usdt={usdt}, leverage={leverage}")
        # Aqui implementaria integração real com MEXC usando API REST
        return {"status": "ok", "usdt": usdt, "leverage": leverage}
