import streamlit as st
import requests
import pandas as pd
import time
from datetime import datetime, timezone, timedelta

# --- CONFIGURAÇÕES DA PÁGINA ---
st.set_page_config(
    page_title="Monitor Intercom",
    page_icon="📊",
    layout="wide"
)

# --- CONFIGURAÇÕES ---
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
    except:
        return {}

def get_team_members(team_id):
    try:
        url = f"https://api.intercom.io/teams/{team_id}"
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            return response.json().get('admin_ids', [])
        return []
    except:
        return []

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
    except:
        return 0

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
                    detalhes_fila.append({
                        'id': conv['id'],
                        'created_at': conv['created_at']
                    })
        return detalhes_fila
    except:
        return []

# --- NOVA FUNÇÃO OTIMIZADA ---
def get_daily_stats(team_id, minutos_recente=30):
    try:
        url = "https://api.intercom.io/conversations/search"
        
        # Define o fuso BR
        fuso_br = timezone(timedelta(hours=-3))
        # Pega a meia-noite do Brasil
        hoje = datetime.now(fuso_br).replace(hour=0, minute=0, second=0, microsecond=0)
        
        # Define o corte de 30 minutos atras
        agora_timestamp = int(time.time())
        ts_corte_30min = agora_timestamp - (minutos_recente * 60)

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
        total_recente_geral = 0
        
        if response.status_code == 200:
            conversas = response.json().get('conversations', [])
            
            for conv in conversas:
                admin_id = str(conv.get('admin_assignee_id')) if conv.get('admin_assignee_id') else "FILA"
                ts_conv = conv['created_at']
                
                # 1. Contabiliza para o Total do Dia
                stats_dia[admin_id] = stats_dia.get(admin_id, 0) + 1
                
                # 2. Verifica se é dos últimos 30 min
                if ts_conv > ts_corte_30min:
                    stats_30min[admin_id] = stats_30min.get(admin_id, 0) + 1
                    total_recente_geral += 1
                    
        return total_recente_geral, stats_dia, stats_30min
    except:
        return 0, {}, {}

def get_latest_conversations(team_id, limit=5):
    try:
        hoje = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        ts_hoje = int(hoje.timestamp())

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
    except:
        return []

# --- INTERFACE VISUAL ---

st.title("📊 Monitoramento de Suporte - CS")
st.markdown("---")

placeholder = st.empty()
fuso_br = timezone(timedelta(hours=-3))

with placeholder.container():
    # 1. Coleta de Dados
    ids_do_time = get_team_members(TEAM_ID)
    detalhes_admins = get_admin_details()
    fila_detalhada = get_team_queue_details(TEAM_ID)
    
    # Chama a função nova que traz os dois dados
    total_entrada_30m, dict_stats_dia, dict_stats_30min = get_daily_stats(TEAM_ID, 30)
    
    ultimas_conversas = get_latest_conversations(TEAM_ID, 5)

    # Contadores Gerais
    total_fila = len(fila_detalhada)
    agentes_online = 0
    
    tabela_dados = []
    
    for member_id in ids_do_time:
        sid = str(member_id)
        info = detalhes_admins.get(sid, {'name': f'ID {sid}', 'is_away': True})
        
        status_emoji = "🔴 Ausente" if info['is_away'] else "🟢 Online"
        if not info['is_away']: agentes_online += 1
        
        abertos = count_conversations(member_id, 'open')
        pausados = count_conversations(member_id, 'snoozed')
        
        # Pega os dados calculados
        total_dia = dict_stats_dia.get(sid, 0)
        recente_30 = dict_stats_30min.get(sid, 0)
        
        alerta_vol = "⚡" if recente_30 >= 3 else ""
        alerta_abertos = "⚠️" if abertos >= 5 else ""

        tabela_dados.append({
            "Status": status_emoji,
            "Agente": info['name'],
            "Abertos": f"{abertos} {alerta_abertos}",
            "Total Dia": total_dia,
            "Últimos 30min": f"{recente_30} {alerta_vol}",
            "Pausados": pausados
        })

    # --- LAYOUT SUPERIOR ---
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric("Fila de Espera", total_fila, "Aguardando", delta_color="inverse")
    with col2:
        st.metric("Volume (30min)", total_entrada_30m, "Novos Tickets")
    with col3:
        st.metric("Agentes Online", agentes_online, f"Meta: {META_AGENTES}")
    with col4:
        agora = datetime.now(fuso_br).strftime("%H:%M:%S")
        st.metric("Última Atualização", agora)

    # --- ALERTAS ---
    if total_fila > 0:
        st.error("🔥 **CRÍTICO: Clientes aguardando na fila!**")
        links_md = ""
        for item in fila_detalhada:
            c_id = item['id']
            link = f"https://app.intercom.com/a/inbox/{APP_ID}/inbox/conversation/{c_id}"
            links_md += f"[Abrir Ticket #{c_id}]({link}) &nbsp;&nbsp; "
        st.markdown(links_md, unsafe_allow_html=True)
    
    if agentes_online < META_AGENTES:
        st.warning(f"⚠️ **Atenção:** Equipe abaixo da meta! Falta(m) {META_AGENTES - agentes_online} agente(s).")

    st.markdown("---")
    
    # --- COLUNAS ---
    c_left, c_right = st.columns([2, 1])

    with c_left:
        st.subheader("Performance da Equipe")
        # Mostra a tabela com as novas colunas
        st.dataframe(
            pd.DataFrame(tabela_dados), 
            use_container_width=True, 
            hide_index=True,
            column_order=["Status", "Agente", "Abertos", "Total Dia", "Últimos 30min", "Pausados"]
        )

    with c_right:
        st.subheader("Últimas Atribuições")
        hist_dados = []
        for conv in ultimas_conversas:
            dt_obj = datetime.fromtimestamp(conv['created_at'], tz=fuso_br)
            hora_fmt = dt_obj.strftime('%H:%M')
            
            adm_id = conv.get('admin_assignee_id')
            nome_agente = "Sem Dono"
            if adm_id:
                nome_agente = detalhes_admins.get(str(adm_id), {}).get('name', 'Desconhecido')
            
            c_id = conv['id']
            link = f"https://app.intercom.com/a/inbox/{APP_ID}/inbox/conversation/{c_id}"
            
            hist_dados.append({
                "Hora": hora_fmt,
                "Agente": nome_agente,
                "Link": link
            })
        
        if hist_dados:
            st.data_editor(
                pd.DataFrame(hist_dados),
                column_config={"Link": st.column_config.LinkColumn("Ticket", display_text="Abrir")},
                hide_index=True,
                disabled=True,
                use_container_width=True,
                key="lista_historico" # O RG da tabela que evita o erro de duplicação
            )
        else:
            st.info("Nenhuma conversa hoje.")

# Pausa e recarrega a página inteira
time.sleep(60)
st.rerun()




