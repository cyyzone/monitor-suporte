import streamlit as st
import requests
import time

def check_password():
    """Gerencia autenticação simples via secrets."""
    if "APP_PASSWORD" not in st.secrets:
        st.error("ERRO: Configure 'APP_PASSWORD' no arquivo .streamlit/secrets.toml")
        return False

    def password_entered():
        if st.session_state["password"] == st.secrets["APP_PASSWORD"]:
            st.session_state["password_correct"] = True
            del st.session_state["password"]
        else:
            st.session_state["password_correct"] = False

    if st.session_state.get("password_correct", False):
        return True

    st.text_input(
        "🔒 Digite a senha de acesso:", 
        type="password", 
        on_change=password_entered, 
        key="password"
    )
    
    if "password_correct" in st.session_state and not st.session_state["password_correct"]:
        st.error("😕 Senha incorreta.")

    return False

def make_api_request(method, url, json=None, params=None, max_retries=3):
    """
    Faz chamadas API seguras respeitando o Rate Limit do Intercom.
    Usa o header 'X-RateLimit-Reset' para espera inteligente.
    """
    token = st.secrets.get("INTERCOM_TOKEN", "")
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Content-Type": "application/json"
    }

    for attempt in range(max_retries):
        try:
            if method.upper() == "POST":
                response = requests.post(url, json=json, params=params, headers=headers)
            else:
                response = requests.get(url, params=params, headers=headers)
            
            if response.status_code == 200:
                return response.json()
            
            elif response.status_code == 429: # Rate Limit
                # Lógica Inteligente baseada na documentação do Intercom
                reset_time = response.headers.get("X-RateLimit-Reset")
                
                if reset_time:
                    try:
                        wait_seconds = int(reset_time) - int(time.time()) + 1 # +1s de margem
                    except ValueError:
                        wait_seconds = (2 ** attempt) + 1
                else:
                    # Fallback se o header não vier
                    wait_seconds = (2 ** attempt) + 1
                
                # Garante que não vamos esperar um tempo negativo
                wait_seconds = max(1, wait_seconds)

                st.toast(f"⏳ API cheia. Aguardando {wait_seconds}s para o reset...", icon="🛑")
                time.sleep(wait_seconds)
                continue
            
            else:
                # Log de erro para ajudar no debug (Melhoria de segurança)
                print(f"Erro API {response.status_code}: {response.text}")
                return None
                
        except Exception as e:
            print(f"Erro de Conexão: {e}")
            return None
            
    st.error("Falha na conexão com a API após várias tentativas.")
    return None
