import time

import requests

from django.conf import settings


class AdapterEpaycoApi:
    base_url = settings.URL_EPAYCO_CONFIRM_SALE

    def __init__(self):
        pass

    def request_get(self, transaction_id):
        response = requests.get(str(self.base_url) + str(transaction_id))
        return response.json()