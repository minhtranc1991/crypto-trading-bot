import time
import hmac
import base64
import requests

class OkxAPI:
    def __init__(self, config):
        self.api_key = config['API_KEY']
        self.secret_key = config['API_SECRET']
        self.base_url = 'https://www.okx.com/api/v5'
        self.headers = {
            'Content-Type': 'application/json',
            'OK-ACCESS-KEY': self.api_key,
            'OK-ACCESS-SIGN': '',
            'OK-ACCESS-TIMESTAMP': '',
            'OK-ACCESS-PASSPHRASE': '',
            'OK-ACCESS-PASSPHRASE': '',
        }

    def get_account(self):
        url = f'{self.base_url}/account/balance'
        timestamp = str(int(time.time()))
        method = 'GET'
        sign = self.sign(timestamp, method, url)
        self.headers['OK-ACCESS-TIMESTAMP'] = timestamp
        self.headers['OK-ACCESS-SIGN'] = sign
        response = requests.get(url, headers=self.headers)
        return response.json()

    def sign(self, timestamp, method, url, body=''):
        message = timestamp + method + url + body
        mac = hmac.new(bytes(self.secret_key, encoding='utf8'), bytes(message, encoding='utf-8'), digestmod='sha256')
        d = mac.digest()
        return base64.b64encode(d).decode()
    
    def get_all_tickers(self, market_type):
        '''
        Lấy tất cả ticker cho loại thị trường được chỉ định, ví dụ "SPOT".
        '''
        # Xác định endpoint và tham số truy vấn
        url = f'{self.base_url}/market/tickers'
        params = {'instType': market_type}

        # Tạo chuỗi query để đưa vào ký tên (sign)
        from urllib.parse import urlencode
        query_string = urlencode(params)
        full_url = f'{url}?{query_string}' if query_string else url

        # Sinh timestamp và ký tên cho yêu cầu
        timestamp = str(int(time.time()))
        method = 'GET'
        sign = self.sign(timestamp, method, full_url)

        # Cập nhật header với timestamp và chữ ký
        self.headers['OK-ACCESS-TIMESTAMP'] = timestamp
        self.headers['OK-ACCESS-SIGN'] = sign

        # Gửi request GET với tham số truy vấn
        response = requests.get(url, headers=self.headers, params=params)
        response = response.json().get('data', [])
        return response
    
    def get_all_funding_rates(self):

        url = f'{self.base_url}/public/funding-rate'
        response = requests.get(url)
        if response.status_code == 200:
            return response.json().get('data', [])