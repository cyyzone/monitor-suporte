import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timezone, timedelta

# --- CONFIGURAÇÕES ---
st.set_page_config(page_title="Painel de Qualidade (CSAT)", page_icon="⭐", layout="wide")

TOKEN = st.secrets["INTERCOM_TOKEN"]
TEAM_ID = 2975006
headers = {"Authorization": f"Bearer {TOKEN}", "Accept": "application/json"}

# --- FUNÇÕES DE DADOS ---

def get_admin_names():
    try:
        r = requests.get("https://api.intercom.io/admins", headers=headers)
        return {a['id']: a['name'] for a in r.json().get('admins', [])} if r.status_code == 200 else {}
    except: return {}

def get_csat_clean_data(team_id):
    # Define o início do mês atual
    fuso_br = timezone(timedelta(hours=-3))
    dt_inicio = datetime.now(fuso_br).replace(day=1, hour=0, minute=0, second=0)
    ts_inicio_mes = int(dt_inicio.timestamp())
    
    url = "https://api.intercom.io/conversations/search"
    
    # CORREÇÃO 1: Busco por 'updated_at' em vez de 'created_at'.
    # Isso traz conversas antigas que receberam avaliação neste mês.
    payload = {
        "query": {
            "operator": "AND",
            "value": [
                {"field": "updated_at", "operator": ">", "value": ts_inicio_mes},
                {"field": "team_assignee_id", "operator": "=", "value": team_id}
            ]
        },
        "pagination": {"per_page": 150}
    }
    
    todas_conversas = []
    placeholder_msg = st.empty()
    placeholder_msg.info("⏳ Buscando avaliações... (Analisando tickets atualizados)")
    
    # Busca até 10 páginas (garantia de ler tudo)
    for i in range(10):
        r = requests.post(url, json=payload, headers=headers)
        if r.status_code == 200:
            data = r.json()
            todas_conversas.extend(data.get('conversations', []))
            if not data.get('pages', {}).get('next'): break
            payload['pagination']['starting_after'] = data['pages']['next']['starting_after']
        else: break
    
    placeholder_msg.empty() 
    
    # Processamento
    stats = {}
    time_pos, time_neu, time_neg = 0, 0, 0
    
    for c in todas_conversas:
        aid = str(c.get('admin_assignee_id'))
        # Se não tem dono ou não tem nota, pula
        if not aid or not c.get('conversation_rating'): continue
        
        rating_obj = c['conversation_rating']
        nota = rating_obj.get('rating')
        if nota is None: continue
        
        # CORREÇÃO 2: Verifico se a DATA DA NOTA é deste mês.
        # Se a nota for antiga (ticket atualizado por outro motivo), ignora.
        data_nota = rating_obj.get('created_at')
        if data_nota and data_nota < ts_inicio_mes:
            continue

        # Inicializa agente se não existir
        if aid not in stats: stats[aid] = {'pos':0, 'neu':0, 'neg':0, 'total':0}
        
        stats[aid]['total'] += 1
        
        if nota >= 4:
            stats[aid]['pos'] += 1
            time_pos += 1
        elif nota == 3:
            stats[aid]['neu'] += 1
            time_neu += 1
        else:
            stats[aid]['neg'] += 1
            time_neg += 1
            
    return stats, {'pos': time_pos, 'neu': time_neu, 'neg': time_neg, 'total': time_pos + time_neu + time_neg}

# --- INTERFACE ---
st.title("⭐ Painel de Qualidade (CSAT)")
st.caption("Visão acumulada do Mês Atual (Inclui tickets antigos avaliados agora)")

if st.button("🔄 Atualizar Dados Agora"):
    st.rerun()

admins = get_admin_names()
stats_agentes, stats_time = get_csat_clean_data(TEAM_ID)

# --- CÁLCULOS DO TIME ---
total_time_csat = stats_time['total']
csat_time = (stats_time['pos'] / total_time_csat * 100) if total_time_csat > 0 else 0

# Cards do Topo
c1, c2, c3, c4 = st.columns(4)
c1.metric("CSAT Geral (Time)", f"{csat_time:.1f}%", f"{total_time_csat} avaliações")
c2.metric("😍 Positivas (4-5)", stats_time['pos'])
c3.metric("😐 Neutras (3)", stats_time['neu'])
c4.metric("😡 Negativas (1-2)", stats_time['neg'])

st.markdown("---")

# --- TABELA DETALHADA ---
tabela = []
for aid, s in stats_agentes.items():
    nome = admins.get(aid, "Desconhecido")
    
    # CSAT Ajustado (Sem Neutras)
    valido = s['pos'] + s['neg']
    csat_ajustado = (s['pos'] / valido * 100) if valido > 0 else 0
    
    tabela.append({
        "Agente": nome,
        "CSAT (Ajustado)": f"{csat_ajustado:.1f}%",
        "Avaliações": s['total'],
        "😍": s['pos'],
        "😐": s['neu'],
        "😡": s['neg']
    })

if tabela:
    # Ordena por quem tem mais avaliações
    df = pd.DataFrame(tabela).sort_values("Avaliações", ascending=False)
    st.dataframe(df, use_container_width=True, hide_index=True)
else:
    st.info("Nenhuma avaliação encontrada neste mês.")

st.markdown("---")
st.caption("ℹ️ **Nota:** O CSAT Geral considera todas as notas. O CSAT Ajustado dos agentes ignora as Neutras.")
