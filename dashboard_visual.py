import streamlit as st
import requests
import pandas as pd
import time
from datetime import datetime, timezone, timedelta

# --- CONFIGURAÇÕES DA PÁGINA ---
# aqui eu configuro o nome que vai na aba do navegador e o icone
st.set_page_config(
    page_title="Monitor Intercom",
    page_icon="📊",
    layout="wide" # usa a tela toda pra caber as tabelas
)

# --- CONFIGURAÇÕES E SEGREDOS ---
# pegando as senhas do arquivo secrets pra nao deixar exposto no codigo
TOKEN = st.secrets["INTERCOM_TOKEN"]
APP_ID = st.secrets["INTERCOM_APP_ID"]
TEAM_ID = 2975006
META_AGENTES = 4 # numero minimo de gente que precisa ta logado

# esse cabeçalho é tipo o cracha pra entrar na api do intercom
headers = {
    "Authorization": f"Bearer {TOKEN}",
    "Accept": "application/json",
    "Content-Type": "application/json"
}

# --- FUNÇÕES ---

# funcao pra pegar a lista de admins e ver quem ta online ou ausente
def get_admin_details():
    try:
        url = "https://api.intercom.io/admins"
        response = requests.get(url, headers=headers)
        dados = {}
        if response.status_code == 200:
            for admin in response.json().get('admins', []):
                dados[admin['id']] = {
                    'name': admin['name'],
                    'is_away': admin.get('away_mode_enabled', False) # se tiver true é pq ta ausente
                }
        return dados
    except:
        return {} # se der pau, retorna vazio pra nao quebrar o painel

# aqui eu pego so os IDs de quem é do meu time especifico
def get_team_members(team_id):
    try:
        url = f"https://api.intercom.io/teams/{team_id}"
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            return response.json().get('admin_ids', [])
        return []
    except:
        return []

# conta quantos tickets o agente tem na mao agora (aberto ou pausado)
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

# funcao pra ver a fila de espera (tickets sem dono)
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
                # filtro aqui no python pq a api as vezes se perde com o NULL
                if conv.get('admin_assignee_id') is None:
                    detalhes_fila.append({
                        'id': conv['id'],
                        'created_at': conv['created_at']
                    })
        return detalhes_fila
    except:
        return []

# --- A FUNCAO PRINCIPAL QUE FAZ A MAGICA DAS ESTATISTICAS ---
# aqui eu busco tudo do dia e separo o que é recente (30min)
def get_daily_stats(team_id, minutos_recente=30):
    try:
        url = "https://api.intercom.io/conversations/search"
        
        # forçando o fuso do brasil pq o servidor é gringo e bagunça os horario
        fuso_br = timezone(timedelta(hours=-3))
        # pego a hora de agora no br e zero tudo pra saber quando foi a meia noite
        agora_br = datetime.now(fuso_br)
        meia_noite_br = agora_br.replace(hour=0, minute=0, second=0, microsecond=0)
        ts_hoje = int(meia_noite_br.timestamp())
        
        # calculo o timestamp de 30 minutos atras pra saber o corte de "recente"
        ts_corte_30min = int(time.time()) - (minutos_recente * 60)

        payload = {
            "query": {
                "operator": "AND",
                "value": [
                    {"field": "created_at", "operator": ">", "value": ts_hoje},
                    {"field": "team_assignee_id", "operator": "=", "value": team_id}
                ]
            },
            "sort": { "field": "created_at", "order": "descending" }, # ordeno pra pegar os novos primeiro
            "pagination": {"per_page": 150} # pego bastante pra garantir o dia todo
        }
        
        response = requests.post(url, json=payload, headers=headers)
        
        stats_dia = {}
        stats_30min = {}
        total_dia_geral = 0
        total_recente_geral = 0
        
        if response.status_code == 200:
            conversas = response.json().get('conversations', [])
            total_dia_geral = len(conversas)
            
            # passo um pente fino em cada conversa
            for conv in conversas:
                # se nao tiver id do admin, jogo pra conta da FILA
                admin_id = str(conv.get('admin_assignee_id')) if conv.get('admin_assignee_id') else "FILA"
                ts_conv = conv['created_at']
                
                # 1. somo no total do dia desse agente
                stats_dia[admin_id] = stats_dia.get(admin_id, 0) + 1
                
                # 2. se a hora da conversa for maior que o corte de 30min, é recente
                if ts_conv > ts_corte_30min:
                    stats_30min[admin_id] = stats_30min.get(admin_id, 0) + 1
                    total_recente_geral += 1
                    
        return total_dia_geral, total_recente_geral, stats_dia, stats_30min
    except:
        return 0, 0, {}, {}

# busca a lista historia lateral (as ultimas 10 que entraram)
def get_latest_conversations(team_id, limit=5):
    try:
        # de novo ajustando o fuso pra nao pegar coisa de ontem a noite como se fosse hoje
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

# --- INTERFACE VISUAL ---

st.title("📊 Monitoramento de Suporte - CS")
st.markdown("---")

placeholder = st.empty()
fuso_br = timezone(timedelta(hours=-3))

# container que engloba tudo
with placeholder.container():
    # 1. RODANDO AS FUNCOES DE COLETA
    # aqui que o python vai la no intercom buscar tudo
    ids_do_time = get_team_members(TEAM_ID)
    detalhes_admins = get_admin_details()
    fila_detalhada = get_team_queue_details(TEAM_ID)
    
    # pegando os totais do dia e recentes
    total_dia_geral, total_recente_geral, dict_stats_dia, dict_stats_30min = get_daily_stats(TEAM_ID, 30)
    
    # pegando as ultimas 10 pra lista lateral
    ultimas_conversas = get_latest_conversations(TEAM_ID, 10)

    # Contadores rapidos
    total_fila = len(fila_detalhada)
    agentes_online = 0
    
    tabela_dados = []
    
    # Loop pra montar a linha de cada agente na tabela
    for member_id in ids_do_time:
        sid = str(member_id)
        info = detalhes_admins.get(sid, {'name': f'ID {sid}', 'is_away': True})
        
        status_emoji = "🔴 Ausente" if info['is_away'] else "🟢 Online"
        if not info['is_away']: agentes_online += 1
        
        abertos = count_conversations(member_id, 'open')
        pausados = count_conversations(member_id, 'snoozed')
        
        # Pega os numeros que calculamos na funcao daily_stats
        total_dia = dict_stats_dia.get(sid, 0)
        recente_30 = dict_stats_30min.get(sid, 0)
        
        # Logica dos alertas visuais
        alerta_vol = "⚡" if recente_30 >= 3 else "" # raio se tiver muita entrada rapida
        alerta_abertos = "⚠️" if abertos >= 5 else "" # triangulo se tiver acumulando ticket

        tabela_dados.append({
            "Status": status_emoji,
            "Agente": info['name'],
            "Abertos": f"{abertos} {alerta_abertos}",
            "Total Dia": total_dia,
            "Últimos 30min": f"{recente_30} {alerta_vol}",
            "Pausados": pausados
        })

    # --- DESENHANDO OS CARDS DO TOPO ---
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric("Fila de Espera", total_fila, "Aguardando", delta_color="inverse")
    with col2:
        # mostro o total e o recente juntos pra facilitar a leitura
        st.metric("Volume (Dia / 30min)", f"{total_dia_geral} / {total_recente_geral}", "Conversas Hoje")
    with col3:
        st.metric("Agentes Online", agentes_online, f"Meta: {META_AGENTES}")
    with col4:
        agora = datetime.now(fuso_br).strftime("%H:%M:%S")
        st.metric("Última Atualização", agora)

    # --- ALERTAS CRITICOS ---
    # se tiver alguem na fila, grita em vermelho
    if total_fila > 0:
        st.error("🔥 **CRÍTICO: Clientes aguardando na fila!**")
        links_md = ""
        for item in fila_detalhada:
            c_id = item['id']
            # monto o link na mao pq o id a gente ja tem
            link = f"https://app.intercom.com/a/inbox/{APP_ID}/inbox/conversation/{c_id}"
            links_md += f"[Abrir Ticket #{c_id}]({link}) &nbsp;&nbsp; "
        st.markdown(links_md, unsafe_allow_html=True)
    
    # alerta se tiver pouca gente trabalhando
    if agentes_online < META_AGENTES:
        st.warning(f"⚠️ **Atenção:** Equipe abaixo da meta! Falta(m) {META_AGENTES - agentes_online} agente(s).")

    st.markdown("---")
    
    # --- AS DUAS COLUNAS DE BAIXO ---
    c_left, c_right = st.columns([2, 1])

    with c_left:
        st.subheader("Performance da Equipe")
        # exibindo a tabela principal
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
            # converto timestamp pra hora normal do brasil
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
                key="lista_historico" # esse key é importante pro streamlit nao se perder quando atualiza
            )
        else:
            st.info("Nenhuma conversa hoje.")

    # --- LEGENDA ---
    st.markdown("---")
    with st.expander("ℹ️ **Legenda e Regras do Painel** (Clique para expandir)"):
        st.markdown("""
        #### **Status do Agente**
        * 🟢 **Online:** Agente ativo no Intercom.
        * 🔴 **Ausente:** Agente ativou o modo "Ausente" (Away).

        #### **Ícones de Alerta**
        * ⚠️ **Sobrecarga (Triângulo):**
            * Indica que o agente tem **5 ou mais** tickets "Abertos" na caixa dele.
            * *Sugestão: Verificar se precisa de ajuda para finalizar.*
        
        * ⚡ **Alta Demanda (Raio):**
            * Indica que o agente recebeu **3 ou mais** novos tickets nos últimos **30 minutos**.
            * *Sugestão: O agente está recebendo uma rajada de atendimentos agora.*
        """)

# Recarrega a pagina a cada 60s
# troquei o while true pelo rerun pra limpar a memoria e nao travar o servidor gratis
time.sleep(60)
st.rerun()
