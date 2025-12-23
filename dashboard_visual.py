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

# --- CONFIGURAÇÕES E SEGREDOS ---
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

def get_daily_stats(team_id, minutos_recente=30):
    try:
        url = "https://api.intercom.io/conversations/search"
        
        fuso_br = timezone(timedelta(hours=-3))
        agora_br = datetime.now(fuso_br)
        meia_noite_br = agora_br.replace(hour=0, minute=0, second=0, microsecond=0)
        ts_hoje = int(meia_noite_br.timestamp())
        
        ts_corte_30min = int(time.time()) - (minutos_recente * 60)

        payload = {
            "query": {
                "operator": "AND",
                "value": [
                    {"field": "created_at", "operator": ">", "value": ts_hoje},
                    {"field": "team_assignee_id", "operator": "=", "value": team_id}
                ]
            },
            "sort": { "field": "created_at", "order": "descending" },
            "pagination": {"per_page": 150}
        }
        
        response = requests.post(url, json=payload, headers=headers)
        
        stats_dia = {}
        stats_30min = {}
        total_dia_geral = 0
        total_recente_geral = 0
        
        if response.status_code == 200:
            conversas = response.json().get('conversations', [])
            total_dia_geral = len(conversas)
            
            for conv in conversas:
                admin_id = str(conv.get('admin_assignee_id')) if conv.get('admin_assignee_id') else "FILA"
                ts_conv = conv['created_at']
                
                stats_dia[admin_id] = stats_dia.get(admin_id, 0) + 1
                
                if ts_conv > ts_corte_30min:
                    stats_30min[admin_id] = stats_30min.get(admin_id, 0) + 1
                    total_recente_geral += 1
                    
        return total_dia_geral, total_recente_geral, stats_dia, stats_30min
    except:
        return 0, 0, {}, {}

def get_latest_conversations(team_id, limit=5):
    try:
        fuso_br = timezone(timedelta(hours=-3))
        hoje = datetime.now(fuso_br).replace(hour=0, minute=0, second=0, microsecond=0)
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

# --- FUNÇÕES DE CSAT (CORRIGIDA) ---

def get_month_start_timestamp():
    fuso_br = timezone(timedelta(hours=-3))
    agora = datetime.now(fuso_br)
    primeiro_dia = agora.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return int(primeiro_dia.timestamp())

def get_csat_stats(team_id, start_timestamp):
    try:
        url = "https://api.intercom.io/conversations/search"
        payload = {
            "query": {
                "operator": "AND",
                "value": [
                    {"field": "created_at", "operator": ">", "value": start_timestamp},
                    {"field": "team_assignee_id", "operator": "=", "value": team_id}
                ]
            },
            "pagination": {"per_page": 150}
        }
        
        conversas_totais = []
        
        # Aumentei o range para 10 (10 x 150 = 1500 conversas de limite)
        # Isso cobre seus 835 tickets com folga.
        for _ in range(10):
            response = requests.post(url, json=payload, headers=headers)
            if response.status_code == 200:
                data = response.json()
                lista = data.get('conversations', [])
                conversas_totais.extend(lista)
                
                # Verifica se tem próxima página
                pages = data.get('pages', {})
                next_page = pages.get('next')
                if next_page:
                    payload['pagination']['starting_after'] = next_page.get('starting_after')
                else:
                    break # Acabaram as páginas antes do limite de 10
            else:
                break
        
        stats_agente = {}
        global_pos = 0
        global_neu = 0
        global_neg = 0

        for conv in conversas_totais:
            admin_id = str(conv.get('admin_assignee_id'))
            if not admin_id: continue 
            
            # Verifica se tem avaliação válida
            rating_obj = conv.get('conversation_rating')
            if not rating_obj or not isinstance(rating_obj, dict): 
                continue 
            
            nota = rating_obj.get('rating')
            if nota is None: continue

            if admin_id not in stats_agente:
                stats_agente[admin_id] = {'pos': 0, 'neu': 0, 'neg': 0, 'total': 0}
            
            stats_agente[admin_id]['total'] += 1
            
            if nota >= 4:
                stats_agente[admin_id]['pos'] += 1
                global_pos += 1
            elif nota == 3:
                stats_agente[admin_id]['neu'] += 1
                global_neu += 1
            else:
                stats_agente[admin_id]['neg'] += 1
                global_neg += 1
                    
        return stats_agente, {'pos': global_pos, 'neu': global_neu, 'neg': global_neg}
    except Exception as e:
        print(f"Erro CSAT: {e}")
        return {}, {'pos': 0, 'neu': 0, 'neg': 0}

# --- INTERFACE VISUAL ---

st.title("📊 Monitoramento de Suporte - CS")
st.markdown("---")

placeholder = st.empty()
fuso_br = timezone(timedelta(hours=-3))

with placeholder.container():
    # 1. RODANDO AS FUNCOES DE COLETA
    ids_do_time = get_team_members(TEAM_ID)
    detalhes_admins = get_admin_details()
    fila_detalhada = get_team_queue_details(TEAM_ID)
    
    total_dia_geral, total_recente_geral, dict_stats_dia, dict_stats_30min = get_daily_stats(TEAM_ID, 30)
    
    # --- CSAT ---
    meia_noite_hoje = int(datetime.now(fuso_br).replace(hour=0, minute=0, second=0).timestamp())
    inicio_mes = get_month_start_timestamp()

    # Buscando dados (com limite de 10 páginas para pegar tudo)
    csat_hoje_stats, time_hoje_stats = get_csat_stats(TEAM_ID, meia_noite_hoje)
    csat_mes_stats, time_mes_stats = get_csat_stats(TEAM_ID, inicio_mes)

    ultimas_conversas = get_latest_conversations(TEAM_ID, 10)

    total_fila = len(fila_detalhada)
    agentes_online = 0
    tabela_dados = []
    
    # --- CÁLCULO DOS KPIs DO TIME (GERAL) ---
    def calc_csat_padrao(stats):
        total = stats['pos'] + stats['neu'] + stats['neg']
        if total > 0:
            return (stats['pos'] / total) * 100
        return 0

    csat_time_hoje = calc_csat_padrao(time_hoje_stats)
    csat_time_mes = calc_csat_padrao(time_mes_stats)

    # Loop principal dos agentes
    for member_id in ids_do_time:
        sid = str(member_id)
        info = detalhes_admins.get(sid, {'name': f'ID {sid}', 'is_away': True})
        
        status_emoji = "🔴 Ausente" if info['is_away'] else "🟢 Online"
        if not info['is_away']: agentes_online += 1
        
        abertos = count_conversations(member_id, 'open')
        pausados = count_conversations(member_id, 'snoozed')
        total_dia = dict_stats_dia.get(sid, 0)
        recente_30 = dict_stats_30min.get(sid, 0)
        
        # --- CÁLCULO DO CSAT AGENTE ---
        dados_h = csat_hoje_stats.get(sid, {'pos':0, 'neu':0, 'neg':0, 'total':0})
        
        # Regra do Agente: Ignora Neutras
        total_valido = dados_h['pos'] + dados_h['neg']
        if total_valido > 0:
            nota_agente = (dados_h['pos'] / total_valido) * 100
            # MUDANÇA AQUI: .1f para uma casa decimal
            txt_csat_agente = f"{nota_agente:.1f}%" 
        else:
            txt_csat_agente = "-"

        # CSAT Mês do Agente (Ajustado)
        dados_m = csat_mes_stats.get(sid, {'pos':0, 'neu':0, 'neg':0, 'total':0})
        total_valido_m = dados_m['pos'] + dados_m['neg']
        if total_valido_m > 0:
            nota_agente_mes = (dados_m['pos'] / total_valido_m) * 100
            # MUDANÇA AQUI: .1f para uma casa decimal
            txt_csat_mes = f"{nota_agente_mes:.1f}% ({dados_m['total']})"
        else:
            txt_csat_mes = "-"

        alerta_vol = "⚡" if recente_30 >= 3 else "" 
        alerta_abertos = "⚠️" if abertos >= 5 else "" 

        tabela_dados.append({
            "Status": status_emoji,
            "Agente": info['name'],
            "Abertos": f"{abertos} {alerta_abertos}",
            "Total Dia": total_dia,
            "CSAT Hoje (Ajustado)": txt_csat_agente,
            "CSAT Mês (Ajustado)": txt_csat_mes,
            "Últimos 30min": f"{recente_30} {alerta_vol}",
            "Pausados": pausados
        })

    # --- CARDS DO TOPO ---
    col1, col2, col3, col4, col5 = st.columns(5)
    
    with col1:
        st.metric("Fila de Espera", total_fila, "Aguardando", delta_color="inverse")
    with col2:
        st.metric("Volume (Dia)", total_dia_geral, "Tickets")
    with col3:
        # MUDANÇA AQUI: .1f para mostrar 97.6%
        st.metric("CSAT Time (Dia/Mês)", f"{csat_time_hoje:.1f}% / {csat_time_mes:.1f}%", "Inclui Neutras")
    with col4:
        st.metric("Agentes Online", agentes_online, f"Meta: {META_AGENTES}")
    with col5:
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
        st.warning(f"⚠️ **Atenção:** Equipe abaixo da meta!")

    st.markdown("---")
    
    # --- TABELA PRINCIPAL ---
    c_left, c_right = st.columns([2, 1])

    with c_left:
        st.subheader("Performance Individual")
        cols_order = ["Status", "Agente", "Abertos", "Total Dia", "CSAT Hoje (Ajustado)", "CSAT Mês (Ajustado)", "Últimos 30min", "Pausados"]
        
        st.dataframe(
            pd.DataFrame(tabela_dados), 
            use_container_width=True, 
            hide_index=True,
            column_order=cols_order
        )

    with c_right:
        st.subheader("Últimas Atribuições")
        hist_dados = []
        for conv in ultimas_conversas:
            dt_obj = datetime.fromtimestamp(conv['created_at'], tz=fuso_br)
            hora_fmt = dt_obj.strftime('%H:%M')
            
            adm_id = conv.get('admin_assignee_id')
            nome_agente = detalhes_admins.get(str(adm_id), {}).get('name', 'Sem Dono')
            
            c_id = conv['id']
            link = f"https://app.intercom.com/a/inbox/{APP_ID}/inbox/conversation/{c_id}"
            
            hist_dados.append({"Hora": hora_fmt, "Agente": nome_agente, "Link": link})
        
        if hist_dados:
            st.data_editor(
                pd.DataFrame(hist_dados),
                column_config={"Link": st.column_config.LinkColumn("Ticket", display_text="Abrir")},
                hide_index=True, disabled=True, use_container_width=True, key="lista_historico"
            )
        else:
            st.info("Nenhuma conversa hoje.")

    st.markdown("---")
    # --- LEGENDA UNIFICADA ---
    with st.expander("ℹ️ **Legenda Completa** (Clique para expandir)"):
        st.markdown("""
        #### **Status e Ícones**
        * 🟢/🔴 **Status:** Indica se o agente está Online ou em modo "Away".
        * ⚠️ **Sobrecarga:** Agente com **5 ou mais** tickets abertos.
        * ⚡ **Alta Demanda:** Agente recebeu **3 ou mais** tickets novos em 30min.

        #### **Regras do CSAT**
        * **CSAT Agente (Ajustado):** A fórmula é `Positivas / (Positivas + Negativas)`. **Ignora as avaliações Neutras (3)** para não prejudicar a nota individual.
        * **CSAT Time (Geral):** A fórmula é `Positivas / Total de Avaliações`. **Considera as Neutras**, o que reflete a satisfação global da empresa.
        """)

time.sleep(60)
st.rerun()
