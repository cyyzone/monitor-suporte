import streamlit as st
import requests
import pandas as pd
import time
import re
from datetime import datetime, timezone, timedelta
from utils import check_password  

# --- Configs da Página ---
st.set_page_config(page_title="Monitor Operacional", page_icon="🚀", layout="wide")

# 🔒 BLOQUEIO DE SEGURANÇA ------------------------
if not check_password():
    st.stop()  # Para a execução do script aqui se não tiver senha
# -------------------------------------------------

# Tenta pegar as chaves do arquivo secrets (pra rodar na nuvem)
# Se não achar (rodando local), usa o que estiver hardcoded no except.
try:
    TOKEN = st.secrets["INTERCOM_TOKEN"]
    APP_ID = st.secrets["INTERCOM_APP_ID"]
except:
    TOKEN = "SEU_TOKEN_AQUI"
    APP_ID = "SEU_APP_ID_AQUI"

# ID do time e metas
TEAM_ID = 2975006
META_AGENTES = 4

headers = {
    "Authorization": f"Bearer {TOKEN}",
    "Accept": "application/json",
    "Content-Type": "application/json"
}

# --- Funções de Busca (API Intercom) ---

def get_admin_details():
    # Pega a lista de admins pra saber Nome e Status (Away/Online)
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
    # Descobre quem faz parte do time específico (TEAM_ID)
    try:
        url = f"https://api.intercom.io/teams/{team_id}"
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            return response.json().get('admin_ids', [])
        return []
    except: return []

def count_conversations(admin_id, state):
    # Conta quantos tickets estão em um estado específico (open, snoozed, etc) pra um agente
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
    # Pega os detalhes da fila (tickets sem dono atribuído ao time)
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
                # Garante que realmente não tem ninguém cuidando (admin_assignee_id é None)
                if conv.get('admin_assignee_id') is None:
                    detalhes_fila.append({'id': conv['id']})
        return detalhes_fila
    except: return []

def get_daily_stats(team_id, ts_inicio, minutos_recente=30):
    # ALTERADO: Agora retorna também a lista detalhada de tickets por agente
    try:
        url = "https://api.intercom.io/conversations/search"
        ts_corte_recente = int(time.time()) - (minutos_recente * 60)

        payload = {
            "query": {
                "operator": "AND",
                "value": [
                    {"field": "created_at", "operator": ">", "value": ts_inicio},
                    {"field": "team_assignee_id", "operator": "=", "value": team_id}
                ]
            },
            "pagination": {"per_page": 150} # Limite de 150 conversas na busca
        }
        
        response = requests.post(url, json=payload, headers=headers)
        stats_periodo = {}
        stats_30min = {}
        # NOVO: Dicionário para guardar a lista de links
        detalhes_por_agente = {} 
        
        total_periodo = 0
        total_recente = 0
        
        if response.status_code == 200:
            conversas = response.json().get('conversations', [])
            total_periodo = len(conversas)
            for conv in conversas:
                # Se tiver dono usa o ID, se não joga pra "FILA"
                aid = str(conv.get('admin_assignee_id')) if conv.get('admin_assignee_id') else "FILA"
                
                # Incrementa estatística geral
                stats_periodo[aid] = stats_periodo.get(aid, 0) + 1
                
                # NOVO: Guarda os detalhes do ticket na lista do agente
                if aid not in detalhes_por_agente:
                    detalhes_por_agente[aid] = []
                
                detalhes_por_agente[aid].append({
                    'id': conv['id'],
                    'created_at': conv['created_at'],
                    'link': f"https://app.intercom.com/a/inbox/{APP_ID}/inbox/conversation/{conv['id']}"
                })
                
                # Se for recente (últimos 30min), incrementa estatística recente
                if conv['created_at'] > ts_corte_recente:
                    stats_30min[aid] = stats_30min.get(aid, 0) + 1
                    total_recente += 1
                    
        # Retorna agora 5 valores (o último é a lista detalhada)
        return total_periodo, total_recente, stats_periodo, stats_30min, detalhes_por_agente
    except: return 0, 0, {}, {}, {}

def get_latest_conversations(team_id, ts_inicio, limit=10):
    # Pega as últimas X conversas pra mostrar na tabela lateral
    try:
        url = "https://api.intercom.io/conversations/search"
        payload = {
            "query": {
                "operator": "AND",
                "value": [
                    {"field": "created_at", "operator": ">", "value": ts_inicio},
                    {"field": "team_assignee_id", "operator": "=", "value": team_id}
                ]
            },
            "sort": { "field": "created_at", "order": "descending" }, # Do mais novo pro mais velho
            "pagination": {"per_page": limit}
        }
        response = requests.post(url, json=payload, headers=headers)
        if response.status_code == 200:
            return response.json().get('conversations', [])
        return []
    except: return []

# --- Interface Visual (Streamlit) ---
st.title("🚀 Monitor Operacional (Tempo Real)")

# Seletor pra alternar entre visão do dia ou visão de 48h
col_filtro, _ = st.columns([1, 3])
with col_filtro:
    periodo_selecionado = st.radio(
        "📅 Período de Análise:", 
        ["Hoje (Desde 00:00)", "Últimas 48h"], 
        horizontal=True
    )

st.markdown("---")

# Placeholder: é aqui que a mágica da atualização acontece sem duplicar componentes
placeholder = st.empty()
fuso_br = timezone(timedelta(hours=-3))

with placeholder.container():
    # Calcula o timestamp inicial baseado no filtro
    now = datetime.now(fuso_br)
    
    if "Hoje" in periodo_selecionado:
        ts_inicio = int(now.replace(hour=0, minute=0, second=0).timestamp())
        texto_volume = "Volume (Dia / 30min)"
    else:
        ts_inicio = int((now - timedelta(hours=48)).timestamp())
        texto_volume = "Volume (48h / 30min)"

    # --- Coleta de Dados ---
    # Chama todas as funções lá de cima
    ids_time = get_team_members(TEAM_ID)
    admins = get_admin_details()
    fila = get_team_queue_details(TEAM_ID)
    
    # ATENÇÃO: Agora recebemos 5 variáveis (detalhes_agente é a nova)
    vol_periodo, vol_rec, stats_periodo, stats_rec, detalhes_agente = get_daily_stats(TEAM_ID, ts_inicio)
    
    ultimas = get_latest_conversations(TEAM_ID, ts_inicio, 10)
    
    online = 0
    tabela = []
    
    # Monta a tabela de performance por agente
    for mid in ids_time:
        sid = str(mid)
        # Se não achar o nome, usa o ID mesmo e assume que tá away
        info = admins.get(sid, {'name': f'ID {sid}', 'is_away': True})
        
        if not info['is_away']: online += 1
        emoji = "🔴" if info['is_away'] else "🟢"
        
        abertos = count_conversations(mid, 'open')
        pausados = count_conversations(mid, 'snoozed')
        
        # Regrinhas visuais de alerta
        alerta = "⚠️" if abertos >= 5 else ""
        raio = "⚡" if stats_rec.get(sid, 0) >= 3 else ""
        
        tabela.append({
            "Status": emoji,
            "Agente": info['name'],
            "Abertos": f"{abertos} {alerta}",
            "Volume Período": stats_periodo.get(sid, 0),
            "Recente (30m)": f"{stats_rec.get(sid, 0)} {raio}",
            "Pausados": pausados
        })
    
    # --- Cards de Métricas ---
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Fila de Espera", len(fila), "Aguardando", delta_color="inverse")
    c2.metric(texto_volume, f"{vol_periodo} / {vol_rec}")
    c3.metric("Agentes Online", online, f"Meta: {META_AGENTES}")
    c4.metric("Atualizado", datetime.now(fuso_br).strftime("%H:%M:%S"))
    
    # Se tiver fila, grita na tela!
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

    st.markdown("---")

    # --- Área das Tabelas ---
    c_left, c_right = st.columns([2, 1])

    with c_left:
        st.subheader("Performance da Equipe")
        st.dataframe(
            pd.DataFrame(tabela), 
            use_container_width=True, 
            hide_index=True,
            column_order=["Status", "Agente", "Abertos", "Volume Período", "Recente (30m)", "Pausados"]
        )
        
        # --- NOVO: Seção de Detalhes por Agente ---
        st.markdown("---")
        st.subheader("🕵️ Detalhe dos Tickets por Agente")
        
        if len(ids_time) > 0:
            # Cria colunas para organizar os expanders (grid de 3 ou 4)
            cols = st.columns(3) 
            
            for i, mid in enumerate(ids_time):
                sid = str(mid)
                nome = admins.get(sid, {}).get('name', 'Desconhecido')
                # Pega a lista de tickets que salvamos na função
                tickets = detalhes_agente.get(sid, [])
                
                # Distribui os cards nas colunas
                with cols[i % 3]:
                    with st.expander(f"{nome} ({len(tickets)})"):
                        if not tickets:
                            st.caption("Sem tickets no período.")
                        else:
                            # Ordena do mais recente para o mais antigo
                            tickets_sorted = sorted(tickets, key=lambda x: x['created_at'], reverse=True)
                            for t in tickets_sorted:
                                hora = datetime.fromtimestamp(t['created_at'], tz=fuso_br).strftime('%H:%M')
                                st.markdown(f"⏰ **{hora}** - [Abrir #{t['id']}]({t['link']})")
        else:
            st.info("Nenhum agente encontrado no time.")


    with c_right:
        st.subheader("Últimas Atribuições")
        hist_dados = []
        for conv in ultimas:
            dt_obj = datetime.fromtimestamp(conv['created_at'], tz=fuso_br)
            hora_fmt = dt_obj.strftime('%d/%m %H:%M')
            
            adm_id = conv.get('admin_assignee_id')
            nome_agente = "Sem Dono"
            if adm_id:
                nome_agente = admins.get(str(adm_id), {}).get('name', 'Desconhecido')
            
            # Tenta pegar o Assunto
            subject = conv.get('source', {}).get('subject', '')
            if not subject:
                body = conv.get('source', {}).get('body', '')
                clean_body = re.sub(r'<[^>]+>', ' ', body).strip()
                
                if not clean_body and ('<img' in body or '<figure' in body):
                    subject = "📷 [Imagem/Anexo]"
                elif not clean_body:
                    subject = "(Sem texto)"
                else:
                    subject = clean_body[:60] + "..." if len(clean_body) > 60 else clean_body
            
            c_id = conv['id']
            link = f"https://app.intercom.com/a/inbox/{APP_ID}/inbox/conversation/{c_id}"
            
            hist_dados.append({
                "Data/Hora": hora_fmt,
                "Assunto": subject, 
                "Agente": nome_agente,
                "Link": link
            })
        
        if hist_dados:
            st.data_editor(
                pd.DataFrame(hist_dados),
                column_config={
                    "Link": st.column_config.LinkColumn("Ticket", display_text="Abrir"),
                    "Assunto": st.column_config.TextColumn("Resumo", width="large")
                },
                hide_index=True,
                disabled=True,
                use_container_width=True,
                key=f"hist_{int(time.time())}" 
            )
        else:
            st.info("Sem conversas no período.")

    st.markdown("---")
    with st.expander("ℹ️ **Legenda e Ações**"):
        st.markdown("""
        * 🟢/🔴 **Status:** Online ou Ausente (Away).
        * ⚠️ **Sobrecarga:** Agente com 5+ tickets abertos.
        * ⚡ **Alta Demanda:** Agente recebeu 3+ tickets em 30min.
        """)

# Loop de refresh: dorme 60s e recarrega a página inteira
time.sleep(60)
st.rerun()
# Loop de refresh: dorme 60s e recarrega a página inteira
time.sleep(60)
st.rerun()


