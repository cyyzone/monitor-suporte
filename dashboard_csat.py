import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timezone, timedelta

# --- CONFIGURAÇÕES ---
st.set_page_config(page_title="Painel de Qualidade (CSAT)", page_icon="⭐", layout="wide")

TOKEN = st.secrets["INTERCOM_TOKEN"]
TEAM_ID = 2975006
headers = {"Authorization": f"Bearer {TOKEN}", "Accept": "application/json"}

# --- FUNÇÕES DE CSAT PESADAS ---

def get_admin_names():
    try:
        r = requests.get("https://api.intercom.io/admins", headers=headers)
        return {a['id']: a['name'] for a in r.json().get('admins', [])} if r.status_code == 200 else {}
    except: return {}

def get_csat_full_month(team_id):
    # Pega o dia 1 do mês
    fuso_br = timezone(timedelta(hours=-3))
    inicio_mes = int(datetime.now(fuso_br).replace(day=1, hour=0, minute=0, second=0).timestamp())
    
    url = "https://api.intercom.io/conversations/search"
    payload = {
        "query": {
            "operator": "AND",
            "value": [
                {"field": "created_at", "operator": ">", "value": inicio_mes},
                {"field": "team_assignee_id", "operator": "=", "value": team_id}
            ]
        },
        "pagination": {"per_page": 150}
    }
    
    todas_conversas = []
    placeholder_msg = st.empty()
    placeholder_msg.info("⏳ Baixando histórico do mês... (Isso pode levar alguns segundos)")
    
    # Busca até 10 páginas (1500 conversas)
    for i in range(10):
        r = requests.post(url, json=payload, headers=headers)
        if r.status_code == 200:
            data = r.json()
            todas_conversas.extend(data.get('conversations', []))
            if not data.get('pages', {}).get('next'): break
            payload['pagination']['starting_after'] = data['pages']['next']['starting_after']
        else: break
    
    placeholder_msg.empty() # Limpa mensagem
    
    # Processamento
    stats = {}
    time_pos, time_neu, time_neg = 0, 0, 0
    
    for c in todas_conversas:
        aid = str(c.get('admin_assignee_id'))
        if not aid or not c.get('conversation_rating'): continue
        
        nota = c['conversation_rating'].get('rating')
        if nota is None: continue
        
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
            
    return stats, {'pos': time_pos, 'neu': time_neu, 'neg': time_neg, 'total': len(todas_conversas)}

# --- INTERFACE ---
st.title("⭐ Painel de Qualidade (CSAT)")
st.caption("Visão acumulada do Mês Atual")

if st.button("🔄 Atualizar Dados Agora"):
    st.rerun()

admins = get_admin_names()
stats_agentes, stats_time = get_csat_full_month(TEAM_ID)

# Cálculo Geral Time
total_time = stats_time['pos'] + stats_time['neu'] + stats_time['neg']
csat_time = (stats_time['pos'] / total_time * 100) if total_time > 0 else 0

# Cards
c1, c2, c3, c4 = st.columns(4)
c1.metric("CSAT Global (Time)", f"{csat_time:.1f}%", "Considera Neutras")
c2.metric("Total Avaliações", total_time)
c3.metric("Positivas (4-5)", stats_time['pos'])
c4.metric("Neutras/Negativas", stats_time['neu'] + stats_time['neg'])

st.markdown("---")

# Tabela Detalhada
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
        "😍 Positivas": s['pos'],
        "😐 Neutras": s['neu'],
        "😡 Negativas": s['neg']
    })

df = pd.DataFrame(tabela).sort_values("Avaliações", ascending=False)
st.dataframe(df, use_container_width=True, hide_index=True)

st.info("ℹ️ **Nota:** O CSAT Ajustado dos agentes ignora avaliações Neutras (3). O CSAT Global do time considera tudo.")
