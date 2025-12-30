import requests

# URL que você copiou da imagem 2
url = "https://hooks.zapier.com/hooks/catch/24662173/uw2modt/"

# O dado falso só pra testar
payload = {
    "text": "🚨 TESTE DE CONEXÃO: O Python conseguiu falar com o Zapier com sucesso!"
}

print("Enviando teste...")
try:
    r = requests.post(url, json=payload)
    print(f"Status: {r.status_code}")
    print("✅ Sucesso! Agora volte no Zapier e clique em 'Test trigger'.")
except Exception as e:
    print(f"❌ Erro: {e}")
