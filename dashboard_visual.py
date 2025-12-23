import streamlit as st
import requests
import pandas as pd
import time
from datetime import datetime, timezone, timedelta

# --- CONFIGURAÇÕES ---
st.set_page_config(page_title="Monitor Operacional", page_icon="🚀", layout="wide")

TOKEN = st.secrets["INTERCOM_TOKEN"]
APP_ID = st.secrets["INTERCOM_APP_ID"]
TEAM_ID = 2975006
META_AGENTES = 4

headers = {
    "Authorization": f"Bearer {TOKEN}",
    "Accept": "application/json",
    "Content-Type": "application/json"
}

# --- FUNÇÕES RÁPIDAS (OPERACIONAIS) ---

def get_admin_details():
    try:
        url = "https://api.intercom.io/admins"
        response = requests.get(url, headers=headers)
        dados = {}
        if response.status_code == 200:
            for admin in response.json().get('admins', []):
                dados[admin['id']] = {
                    'name': admin['name'],
                    'is_away': admin.get('away_mode_enabled', False)
                }
        return dados
    except: return {}

def get_team_members(team_id):
    try:
        url = f"https://api.intercom.io/teams/{team_id}"
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            return response.json().get('admin_ids', [])
        return []
    except: return []

def count_conversations(admin_id, state):
    try:
        url = "https://api.intercom.io/conversations/search"
        payload = {
            "query": {
                "operator": "AND",
                "value": [
                    {"field": "state", "operator": "=", "value": state},
                    {"field": "admin_assignee_id", "operator": "=", "value": admin_id}
                ]
            }
        }
        response = requests.post(url, json=payload, headers=headers)
        if response.status_code == 200:
            return response.json()['total_count']
        return 0
    except: return 0

def get_team_queue_details(team_id):
    try:
        url = "https://api.intercom.io/conversations/search"
        payload = {
            "query": {
                "operator": "AND",
                "value": [
                    {"field": "state", "operator": "=", "value": "open"},
                    {"field": "team_assignee_id", "operator": "=", "value": team_id}
                ]
            },
            "pagination": {"per_page": 60}
        }
        response = requests.post(url, json=payload, headers=headers)
        detalhes_fila = []
        if response.status_code == 200:
            for conv in response.json().get('conversations', []):
                if conv.get('admin_assignee_id') is None:
                    detalhes_fila.append({'id': conv['id']})
        return detalhes_fila
    except: return []

def get_daily_stats(team_id, minutos_recente=30):
    try:
        url = "https://api.intercom.io/conversations/search"
        fuso_br = timezone(timedelta(hours=-3))
        ts_hoje = int(datetime.now(fuso_br).replace(hour=0, minute=0, second=0).timestamp())
        ts_corte = int(time.time()) - (minutos_recente * 60)

        payload = {
            "query": {
                "operator": "AND",
                "value": [
                    {"field": "created_at", "operator": ">", "value": ts_hoje},
                    {"field": "team_assignee_id", "operator": "=", "value": team_id}
                ]
            },
            "pagination": {"per_page": 150}
        }
        
        response = requests.post(url, json=payload, headers=headers)
        stats_dia = {}
        stats_30min = {}
        total_dia = 0
        total_recente = 0
        
        if response.status_code == 200:
            conversas = response.json().get('conversations', [])
            total_dia = len(conversas)
            for conv in conversas:
                aid = str(conv.get('admin_assignee_id')) if conv.get('admin_assignee_id') else "FILA"
                stats_dia[aid] = stats_dia.get(aid, 0) + 1
                if conv['created_at'] > ts_corte:
                    stats_30min[aid] = stats_30min.get(aid, 0) + 1
                    total_recente += 1
        return total_dia, total_recente, stats_dia, stats_30min
    except: return 0, 0, {}, {}

# --- INTERFACE ---
st.title("🚀 Monitor Operacional (Tempo Real)")
st.markdown("---")

placeholder = st.empty()
fuso_br = timezone(timedelta(hours=-3))

with placeholder.container():
    ids_time = get_team_members(TEAM_ID)
    admins = get_admin_details()
    fila = get_team_queue_details(TEAM_ID)
    vol_dia, vol_rec, stats_dia, stats_rec = get_daily_stats(TEAM_ID)
    
    online = 0
    tabela = []
    
    for mid in ids_time:
        sid = str(mid)
        info = admins.get(sid, {'name': f'ID {sid}', 'is_away': True})
        
        if not info['is_away']: online += 1
        emoji = "🔴" if info['is_away'] else "🟢"
        
        abertos = count_conversations(mid, 'open')
        pausados = count_conversations(mid, 'snoozed')
        
        alerta = "⚠️" if abertos >= 5 else ""
        raio = "⚡" if stats_rec.get(sid, 0) >= 3 else ""
        
        tabela.append({
            "Status": emoji,
            "Agente": info['name'],
            "Abertos": f"{abertos} {alerta}",
            "Volume Dia": stats_dia.get(sid, 0),
            "Recente (30m)": f"{stats_rec.get(sid, 0)} {raio}",
            "Pausados": pausados
        })
        
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Fila", len(fila), delta_color="inverse")
    c2.metric("Volume Hoje", vol_dia)
    c3.metric("Online", online, f"Meta: {META_AGENTES}")
    c4.metric("Atualizado", datetime.now(fuso_br).strftime("%H:%M:%S"))
    
    if len(fila) > 0:
        st.error("🔥 **CRÍTICO: Fila!**")
        
    st.dataframe(pd.DataFrame(tabela), use_container_width=True, hide_index=True)

time.sleep(60)
st.rerun()

