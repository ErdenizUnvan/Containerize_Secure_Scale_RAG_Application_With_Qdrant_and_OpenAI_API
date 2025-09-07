#login fonksiyonu yap
import requests
import urllib3
from getpass import getpass
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

username=input('username: ')
print('password yaz: ')
password=getpass()
#print(password)

def get_token(username,password):
    try:
        login_data = {
        'username': f'{username}',
        'password': f'{password}',
        }

        headers = {'Content-Type': 'application/json'}

        # Kullanıcı adı ve şifreyi JSON olarak gönderiyoruz
        login_url = "https://10.1.100.45:8443/login"  # Login endpoint'iniz

        response = requests.post(login_url,
                                 headers=headers,
                                 json=login_data,
                                verify=False)
        if response.status_code==200:
            return response.json().get('access_token')
        else:
            return False
    except Exception as e:
        return False


token=get_token(username,password)

if not token:
    print('wrong token')
else:
    while True:
        try:
            post_url = "https://10.1.100.45:8443/chat"
            headers = {
                'Authorization': f'Bearer {token}'  # JWT token'ı yetkilendirme için header'a eklenir
            }
            prompt=input('prompt: ')
            prompt=prompt.lower()
            if not prompt or prompt.isspace():
                print('write sth')

            elif 'quit' in prompt:
                break

            new_data = {
                'query': prompt}

            post_response = requests.post(post_url, headers=headers, json=new_data,verify=False)

            print(post_response.json())
        except Exception as e:
            print(f'exception :{str(e)}')
