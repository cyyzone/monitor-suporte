import streamlit as st
import pandas as pd
import time
from datetime import datetime, timedelta
from utils import check_password, make_api_request

st.set_page_config(page_title="Relatório Produtividade", page_icon="📊", layout="wide")

if not check_password():
    st.stop()

st.title("📊 Relatório de Produtividade da Equipe")
st.markdown("Selecione o período para contabilizar os tickets trabalhados por cada agente.")

# --- Dicionários e Buscas Básicas ---
@st.cache_data(ttl=300, show_spinner=False)
def get_admin_details():
    url = "https://api.intercom.io/admins" 
    data = make_api_request("GET", url)
    dados = {}
    if data:
        for admin in data.get('admins', []):
            dados[str(admin['id'])] = admin['name']
    return dados

# --- Função de Busca do Relatório ---
def buscar_dados_produtividade(ts_inicio, ts_fim):
    url = "https://api.intercom.io/conversations/search"
    payload = {
        "query": {
            "operator": "AND",
            "value": [
                {"field": "updated_at", "operator": ">", "value": ts_inicio},
                {"field": "updated_at", "operator": "<", "value": ts_fim}
            ]
        },
        "pagination": {"per_page": 100}
    }
    
    todas_conversas = []
    
    # Loop de paginação para buscar todo o histórico do período
    while True:
        data = make_api_request("POST", url, json=payload)
        if not data:
            break
            
        conversas = data.get('conversations', [])
        todas_conversas.extend(conversas)
        
        paginacao = data.get('pages', {})
        if paginacao.get('next'):
            payload['pagination']['starting_after'] = paginacao['next']['starting_after']
        else:
            break
            
    return todas_conversas

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

# --- Processamento dos Dados ---
if gerar_relatorio:
    # Ajusta os horários para pegar o dia completo (00:00 até 23:59)
    ts_start = int(datetime.combine(data_inicio, datetime.min.time()).timestamp())
    ts_end = int(datetime.combine(data_fim, datetime.max.time()).timestamp())
    
    with st.spinner("Buscando histórico na API do Intercom. Isso pode levar alguns segundos..."):
        conversas_periodo = buscar_dados_produtividade(ts_start, ts_end)
        admins = get_admin_details()
        
        stats_agentes = {}
        
        for conv in conversas_periodo:
            estado = conv.get('state')
            dono_final = str(conv.get('admin_assignee_id')) if conv.get('admin_assignee_id') else "FILA"
            
            # Pega a lista de todos os agentes que enviaram alguma mensagem neste ticket
            teammates_ativos = conv.get('teammates', {}).get('admins', [])
            ids_envolvidos = [str(t.get('id')) for t in teammates_ativos]
            
            for adm_id in ids_envolvidos:
                if adm_id not in stats_agentes:
                    stats_agentes[adm_id] = {
                        "Agente": admins.get(adm_id, f"ID {adm_id}"),
                        "Recebeu / Atuou": 0,
                        "Resolveu": 0,
                        "Transferiu": 0
                    }
                
                # Regra 1: Se o ID dele está nos envolvidos, ele atuou no ticket
                stats_agentes[adm_id]["Recebeu / Atuou"] += 1
                
                # Regra 2: Se o ticket está fechado e ele é o dono final, ele resolveu
                if estado == 'closed' and dono_final == adm_id:
                    stats_agentes[adm_id]["Resolveu"] += 1
                
                # Regra 3: Se ele atuou, mas o dono final é outra pessoa (ou a fila), ele transferiu
                elif dono_final != adm_id:
                    stats_agentes[adm_id]["Transferiu"] += 1

        # Transforma os dados em uma tabela para visualização
        if stats_agentes:
            df = pd.DataFrame(list(stats_agentes.values()))
            
            # Exibe os totais gerais no topo
            c1, c2, c3 = st.columns(3)
            c1.metric("Total de Tickets Trabalhados", len(conversas_periodo))
            c2.metric("Total de Resoluções", df["Resolveu"].sum())
            c3.metric("Total de Transferências", df["Transferiu"].sum())
            
            st.markdown("### 👥 Detalhamento por Agente")
            
            # Ordena por quem resolveu mais tickets
            df = df.sort_values(by="Resolveu", ascending=False)
            
            st.dataframe(
                df,
                use_container_width=True,
                hide_index=True
            )
            
        else:
            st.warning("Nenhuma atividade encontrada neste período.")
