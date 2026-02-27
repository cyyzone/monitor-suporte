import streamlit as st
import pandas as pd
import requests
from requests.auth import HTTPBasicAuth
from datetime import datetime, timedelta
from utils import check_password, make_api_request

st.set_page_config(page_title="Relatório de Telefonia", page_icon="📞", layout="wide")

if not check_password():
    st.stop()

st.title("📞 Relatório de Telefonia da Equipe")
st.markdown("Selecione o período para contabilizar as ligações atendidas por cada agente.")

# --- MAPEAMENTO AIRCALL (Email -> ID Intercom para pegar o nome visual) ---
AGENTS_MAP = {
    "rhayslla.junca@produttivo.com.br": "5281911",
    "douglas.david@produttivo.com.br": "5586698",
    "aline.souza@produttivo.com.br": "5717251",
    "heloisa.atm.slv@produttivo.com.br": "7455039",
    "danielle.ghesini@produttivo.com.br": "7628368",
    "jenyffer.souza@produttivo.com.br": "8115775",
    "marcelo.misugi@produttivo.com.br": "8126602"
}

# --- Busca de Nomes ---
@st.cache_data(ttl=300, show_spinner=False)
def get_admin_details():
    url = "https://api.intercom.io/admins" 
    data = make_api_request("GET", url)
    dados = {}
    if data:
        for admin in data.get('admins', []):
            dados[str(admin['id'])] = admin['name']
    return dados

# --- Função de Busca Aircall ---
def buscar_dados_aircall(ts_inicio, ts_fim):
    if "AIRCALL_ID" not in st.secrets or "AIRCALL_TOKEN" not in st.secrets:
        st.error("Credenciais do Aircall não configuradas nos secrets.")
        return {}, 0
        
    url = "https://api.aircall.io/v1/calls"
    auth = HTTPBasicAuth(st.secrets["AIRCALL_ID"], st.secrets["AIRCALL_TOKEN"])
    
    params = {
        "from": ts_inicio,
        "to": ts_fim,
        "order": "desc",
        "per_page": 50,
        "direction": "inbound" 
    }
    
    ligacoes_por_agente = {}
    total_ligacoes = 0
    page = 1
    
    while True:
        params['page'] = page
        try:
            response = requests.get(url, auth=auth, params=params)
            if response.status_code != 200: break
                
            data = response.json()
            calls = data.get('calls', [])
            if not calls: break
                
            for call in calls:
                emails_envolvidos = set()
                
                # Identifica quem atendeu ou recebeu transferência
                for campo in ['user', 'transferred_by', 'transferred_to']:
                    obj = call.get(campo)
                    if obj and isinstance(obj, dict) and obj.get('email'):
                        emails_envolvidos.add(obj.get('email').lower())
                        
                for u in call.get('users', []):
                    if isinstance(u, dict) and u.get('email'):
                        emails_envolvidos.add(u['email'].lower())
                
                # Mantém apenas os emails da equipe mapeada
                emails_da_equipa = [e for e in emails_envolvidos if e in AGENTS_MAP]
                
                if not emails_da_equipa: continue 

                status = call.get('status')
                if status == 'done':
                    total_ligacoes += 1
                    for email in emails_da_equipa:
                        intercom_id = AGENTS_MAP[email]
                        ligacoes_por_agente[intercom_id] = ligacoes_por_agente.get(intercom_id, 0) + 1
                        
            if data.get('meta', {}).get('next_page_link'):
                page += 1
            else:
                break
        except Exception as e:
            print(f"Erro Aircall: {e}")
            break
            
    return ligacoes_por_agente, total_ligacoes

# --- Filtros de Data na Tela ---
col1, col2, col3 = st.columns([1, 1, 2])
with col1:
    data_inicio = st.date_input("Data de Início", datetime.today() - timedelta(days=7))
with col2:
    data_fim = st.date_input("Data Final", datetime.today())
with col3:
    st.write("")
    st.write("")
    gerar_relatorio = st.button("Gerar Relatório", type="primary")

st.markdown("---")

# --- Processamento e Exibição ---
if gerar_relatorio:
    # Formata para pegar do primeiro minuto do dia inicial ao último minuto do dia final
    ts_start = int(datetime.combine(data_inicio, datetime.min.time()).timestamp())
    ts_end = int(datetime.combine(data_fim, datetime.max.time()).timestamp())
    
    with st.spinner("Buscando histórico de Ligações na API do Aircall..."):
        
        ligacoes_aircall, total_lig = buscar_dados_aircall(ts_start, ts_end)
        admins = get_admin_details()
        
        stats_agentes = []
        
        # Iteramos pelo mapa inteiro para garantir que todos apareçam na tabela,
        # mesmo quem teve 0 ligações no período.
        for email, adm_id in AGENTS_MAP.items():
            qtd = ligacoes_aircall.get(adm_id, 0)
            stats_agentes.append({
                "Agente": admins.get(adm_id, f"ID {adm_id}"),
                "📞 Ligações (Atendidas)": qtd
            })

        if stats_agentes:
            df = pd.DataFrame(stats_agentes)
            
            # Exibe os totais gerais
            c1, c2 = st.columns(2)
            c1.metric("Total de Ligações da Equipe", total_lig)
            c2.metric("Período Analisado", f"{data_inicio.strftime('%d/%m')} até {data_fim.strftime('%d/%m')}")
            
            st.markdown("### 👥 Produtividade por Agente")
            
            # Ordena do maior para o menor volume de ligações
            df = df.sort_values(by="📞 Ligações (Atendidas)", ascending=False)
            
            st.dataframe(
                df,
                use_container_width=True,
                hide_index=True
            )
            
        else:
            st.warning("Nenhuma ligação encontrada para o time neste período.")
