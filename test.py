import requests

url = "https://datafacil.vercel.app/listado.json"
response = requests.get(url)
frases = response.json()

print(frases)
