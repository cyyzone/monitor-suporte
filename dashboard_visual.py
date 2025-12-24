import streamlit as st
import requests
import pandas as pd
import time
import re
from collections import Counter
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

# --- FUNÇÕES ---

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

def get_latest_conversations(team_id, limit=10):
    try:
        fuso_br = timezone(timedelta(hours=-3))
        ts_hoje = int(datetime.now(fuso_br).replace(hour=0, minute=0, second=0).timestamp())

        url = "https://api.intercom.io/conversations/search"
        payload = {
            "query": {
                "operator": "AND",
                "value": [
                    {"field": "created_at", "operator": ">", "value": ts_hoje},
                    {"field": "team_assignee_id", "operator": "=", "value": team_id}
                ]
            },
            "sort": { "field": "created_at", "order": "descending" },
            "pagination": {"per_page": limit}
        }
        response = requests.post(url, json=payload, headers=headers)
        if response.status_code == 200:
            return response.json().get('conversations', [])
        return []
    except: return []

# --- NOVA FUNÇÃO: TENDÊNCIAS ---
def get_trending_topics(team_id):
    try:
        url = "https://api.intercom.io/conversations/search"
        # Pega conversas das ultimas 3 horas para ser bem "tempo real"
        payload = {
            "query": {
                "operator": "AND",
                "value": [
                    {"field": "created_at", "operator": ">", "value": int(time.time()) - 10800},
                    {"field": "team_assignee_id", "operator": "=", "value": team_id}
                ]
            },
            "sort": { "field": "created_at", "order": "descending" },
            "pagination": {"per_page": 50} 
        }
        
        response = requests.post(url, json=payload, headers=headers)
        if response.status_code != 200: return []
        
        conversas = response.json().get('conversations', [])
        todas_palavras = []
        
        # Stopwords (palavras para ignorar)
        ignorar = ["ola", "olá", "bom", "dia", "tarde", "noite", "gostaria", "queria", "estou", 
                   "esta", "está", "com", "para", "que", "uma", "um", "o", "a", "e", "do", "da", 
                   "em", "no", "na", "os", "as", "dos", "das", "por", "favor", "ajuda", "entendi",
                   "obrigado", "obrigada", "tudo", "bem", "como", "posso", "fazer", "pode", "ser",
                   "preciso", "sobre", "mas", "tem", "não", "nao", "pelo"]

        for conv in conversas:
            texto_html = conv.get('source', {}).get('body', '')
            if not texto_html: continue
            
            # Limpeza básica
            texto_limpo = re.sub(r'<[^>]+>', ' ', texto_html).lower()
            texto_limpo = re.sub(r'[^\w\s]', '', texto_limpo)
            
            palavras = texto_limpo.split()
            for p in palavras:
                if len(p) > 3 and p not in ignorar:
                    todas_palavras.append(p)
                    
        return Counter(todas_palavras).most_common(5)
    except: return []

# --- INTERFACE ---
st.title("🚀 Monitor Operacional (Tempo Real)")
st.markdown("---")

placeholder = st.empty()
fuso_br = timezone(timedelta(hours=-3))

with placeholder.container():
    # Coleta
    ids_time = get_team_members(TEAM_ID)
    admins = get_admin_details()
    fila = get_team_queue_details(TEAM_ID)
    vol_dia, vol_rec, stats_dia, stats_rec = get_daily_stats(TEAM_ID)
    ultimas = get_latest_conversations(TEAM_ID, 10)
    
    # Coleta de Tendências (Novo)
    top_assuntos = get_trending_topics(TEAM_ID)
    
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
    
    # Cards
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Fila de Espera", len(fila), "Aguardando", delta_color="inverse")
    c2.metric("Volume (Dia / 30min)", f"{vol_dia} / {vol_rec}")
    c3.metric("Agentes Online", online, f"Meta: {META_AGENTES}")
    c4.metric("Atualizado", datetime.now(fuso_br).strftime("%H:%M:%S"))
    
    # --- ÁREA DE TENDÊNCIAS (NOVO) ---
    if top_assuntos:
        st.markdown("##### 🔥 Assuntos do Momento (Termos Frequentes)")
        cols_topics = st.columns(5)
        for i, (termo, qtd) in enumerate(top_assuntos):
            cor = "red" if qtd >= 3 else "gray"
            cols_topics[i].markdown(f":{cor}[**{termo.upper()}**] ({qtd})")
        st.markdown("---")
    
    # Alertas
    if len(fila) > 0:
        st.error("🔥 **CRÍTICO: Clientes aguardando na fila!**")
        links_md = ""
        for item in fila:
            c_id = item['id']
            link = f"https://app.intercom.com/a/inbox/{APP_ID}/inbox/conversation/{c_id}"
            links_md += f"[Abrir Ticket #{c_id}]({link}) &nbsp;&nbsp; "
        st.markdown(links_md, unsafe_allow_html=True)

    if online < META_AGENTES:
        st.warning(f"⚠️ **Atenção:** Equipe abaixo da meta!")

    # Tabelas
    c_left, c_right = st.columns([2, 1])

    with c_left:
        st.subheader("Performance da Equipe")
        st.dataframe(
            pd.DataFrame(tabela), 
            use_container_width=True, 
            hide_index=True,
            column_order=["Status", "Agente", "Abertos", "Volume Dia", "Recente (30m)", "Pausados"]
        )

    with c_right:
        st.subheader("Últimas Atribuições")
        hist_dados = []
        for conv in ultimas:
            dt_obj = datetime.fromtimestamp(conv['created_at'], tz=fuso_br)
            hora_fmt = dt_obj.strftime('%H:%M')
            
            adm_id = conv.get('admin_assignee_id')
            nome_agente = "Sem Dono"
            if adm_id:
                nome_agente = admins.get(str(adm_id), {}).get('name', 'Desconhecido')
            
            # Tenta pegar assunto (subject) ou inicio do corpo para dar contexto na lista
            subject = conv.get('source', {}).get('subject', '')
            if not subject:
                body = conv.get('source', {}).get('body', '')
                clean_body = re.sub(r'<[^>]+>', ' ', body).strip()
                subject = clean_body[:30] + "..." if len(clean_body) > 30 else clean_body
            
            c_id = conv['id']
            link = f"https://app.intercom.com/a/inbox/{APP_ID}/inbox/conversation/{c_id}"
            
            hist_dados.append({
                "Hora": hora_fmt,
                "Assunto": subject, # Adicionei o assunto aqui também!
                "Agente": nome_agente,
                "Link": link
            })
        
        if hist_dados:
            st.data_editor(
                pd.DataFrame(hist_dados),
                column_config={
                    "Link": st.column_config.LinkColumn("Ticket", display_text="Abrir"),
                    "Assunto": st.column_config.TextColumn("Resumo", width="medium")
                },
                hide_index=True,
                disabled=True,
                use_container_width=True,
                key=f"hist_{int(time.time())}" 
            )
        else:
            st.info("Sem conversas hoje.")

    st.markdown("---")
    with st.expander("ℹ️ **Legenda e Sugestões de Ação**"):
        st.markdown("""
        #### **Status do Agente**
        * 🟢 **Online:** Agente ativo e disponível.
        * 🔴 **Ausente:** Agente em modo "Away".

        #### **Alertas e Sugestões**
        * ⚠️ **Sobrecarga (Triângulo):** Agente com **5 ou mais** tickets abertos. *Sugestão: Oferecer ajuda.*
        * ⚡ **Alta Demanda (Raio):** Agente recebeu **3 ou mais** tickets nos últimos 30min. *Sugestão: Pausar distribuição.*
        * 🔥 **Assuntos do Momento:** Termos mais repetidos nos últimos 50 tickets. Se aparecer "Erro" ou "Falha" em vermelho, verifique sistemas.
        """)

time.sleep(60)
st.rerun()






