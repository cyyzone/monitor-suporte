import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timezone, timedelta

# --- CONFIGURAÇÕES ---
st.set_page_config(page_title="Painel de Qualidade (CSAT & SLA)", page_icon="⭐", layout="wide")

TOKEN = st.secrets["INTERCOM_TOKEN"]
TEAM_ID = 2975006
headers = {"Authorization": f"Bearer {TOKEN}", "Accept": "application/json"}

# --- FUNÇÕES UTILITÁRIAS ---

def formatar_tempo(segundos):
    if not segundos or segundos <= 0: return "-"
    m, s = divmod(segundos, 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{int(h)}h {int(m)}m"
    return f"{int(m)}m"

# --- FUNÇÕES DE DADOS ---

def get_admin_names():
    try:
        r = requests.get("https://api.intercom.io/admins", headers=headers)
        return {a['id']: a['name'] for a in r.json().get('admins', [])} if r.status_code == 200 else {}
    except: return {}

def get_full_month_data(team_id):
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
    placeholder_msg.info("⏳ Baixando histórico do mês... (Pode levar alguns segundos)")
    
    # Busca até 10 páginas (1500 conversas)
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
    
    # Acumuladores globais
    global_tempos = []
    time_pos, time_neu, time_neg = 0, 0, 0
    
    for c in todas_conversas:
        aid = str(c.get('admin_assignee_id'))
        if not aid: continue
        
        if aid not in stats: 
            stats[aid] = {'pos':0, 'neu':0, 'neg':0, 'total':0, 'tempos': []}
        
        # --- 1. Lógica de CSAT ---
        rating = c.get('conversation_rating')
        if rating and rating.get('rating'):
            nota = rating.get('rating')
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
        
        # --- 2. Lógica de Tempo de Resposta ---
        # O campo 'time_to_admin_reply' vem em segundos dentro de 'statistics'
        estatisticas = c.get('statistics', {})
        tempo_resposta = estatisticas.get('time_to_admin_reply')
        
        if tempo_resposta and tempo_resposta > 0:
            stats[aid]['tempos'].append(tempo_resposta)
            global_tempos.append(tempo_resposta)
            
    return stats, {
        'pos': time_pos, 'neu': time_neu, 'neg': time_neg, 
        'total_csat': time_pos + time_neu + time_neg,
        'tempos': global_tempos
    }

# --- INTERFACE ---
st.title("⭐ Painel de Qualidade & SLA")
st.caption("Visão acumulada do Mês Atual")

if st.button("🔄 Atualizar Dados Agora"):
    st.rerun()

admins = get_admin_names()
stats_agentes, stats_time = get_full_month_data(TEAM_ID)

# --- CÁLCULOS DO TIME ---

# 1. CSAT Geral
total_time_csat = stats_time['total_csat']
csat_time = (stats_time['pos'] / total_time_csat * 100) if total_time_csat > 0 else 0

# 2. Mediana Tempo Geral
if stats_time['tempos']:
    mediana_time_seg = pd.Series(stats_time['tempos']).median()
    txt_mediana_time = formatar_tempo(mediana_time_seg)
else:
    txt_mediana_time = "-"

# Cards
c1, c2, c3, c4 = st.columns(4)
c1.metric("CSAT Global", f"{csat_time:.1f}%", f"{total_time_csat} avaliações")
c2.metric("Tempo 1ª Resposta (Mediana)", txt_mediana_time, "SLA do Time")
c3.metric("Positivas", stats_time['pos'])
c4.metric("Neutras/Negativas", stats_time['neu'] + stats_time['neg'])

st.markdown("---")

# --- TABELA DETALHADA ---
tabela = []
for aid, s in stats_agentes.items():
    nome = admins.get(aid, "Desconhecido")
    
    # CSAT Ajustado (Sem Neutras)
    valido = s['pos'] + s['neg']
    csat_ajustado = (s['pos'] / valido * 100) if valido > 0 else 0
    
    # Mediana Individual
    if s['tempos']:
        mediana_seg = pd.Series(s['tempos']).median()
        txt_mediana = formatar_tempo(mediana_seg)
    else:
        txt_mediana = "-"
    
    tabela.append({
        "Agente": nome,
        "CSAT (Ajustado)": f"{csat_ajustado:.1f}%",
        "Mediana 1ª Resp.": txt_mediana, # Nova Coluna
        "Avaliações": s['total'],
        "Atendimentos": len(s['tempos']), # Qtd de tickets com resposta contada
        "😍": s['pos'],
        "😐": s['neu'],
        "😡": s['neg']
    })

if tabela:
    df = pd.DataFrame(tabela).sort_values("Atendimentos", ascending=False)
    st.dataframe(df, use_container_width=True, hide_index=True)
else:
    st.info("Nenhum dado encontrado para o mês atual.")

st.markdown("---")
st.caption("ℹ️ **Nota:** A Mediana de Tempo considera apenas a primeira resposta do agente. O CSAT Ajustado ignora avaliações neutras.")
