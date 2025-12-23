import streamlit as st
import requests
import pandas as pd
import time
from datetime import datetime, timezone

# --- CONFIGURAÇÕES DA PÁGINA ---
# config basica da pagina, titulo e icone pra ficar bonito
st.set_page_config(
    page_title="Monitor Intercom",
    page_icon="📊",
    layout="wide"
)

# --- CONFIGURAÇÕES ---
# pegando as senhas do arquivo de segredos pra nao vazar nada
TOKEN = st.secrets["INTERCOM_TOKEN"]
APP_ID = st.secrets["INTERCOM_APP_ID"]
TEAM_ID = 2975006
META_AGENTES = 4 # meta de quantos tem q ta online

# cabecalho padrao pra bater na api do intercom
headers = {
    "Authorization": f"Bearer {TOKEN}",
    "Accept": "application/json",
    "Content-Type": "application/json"
}

# --- FUNÇÕES ---

# busca quem sao os admins e se tao online ou no modo ausente
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
        return {} # se der erro retorna vazio pra nao quebrar

# pega so quem faz parte do time de suporte pelo ID da equipe
def get_team_members(team_id):
    try:
        url = f"https://api.intercom.io/teams/{team_id}"
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            return response.json().get('admin_ids', [])
        return []
    except:
        return []

# conta quantos tickets o caboclo tem na mao (aberto ou pausado)
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

# Modificada para retornar uma lista de objetos (ID e Data) em vez de apenas IDs
# --- SUBSTITUA APENAS ESSA FUNÇÃO ---
# essa funcao busca a fila... trago tudo que ta aberto no time
# e filtro aqui no python quem nao tem dono, eh mais garantido
def get_team_queue_details(team_id):
    try:
        url = "https://api.intercom.io/conversations/search"
        # Removemos o filtro de 'admin_assignee_id' do payload para garantir que a API traga tudo
        payload = {
            "query": {
                "operator": "AND",
                "value": [
                    {"field": "state", "operator": "=", "value": "open"},
                    {"field": "team_assignee_id", "operator": "=", "value": team_id}
                ]
            },
            "pagination": {"per_page": 60} # aumentei pra garantir q pega a lista toda
        }
        response = requests.post(url, json=payload, headers=headers)
        detalhes_fila = []
        if response.status_code == 200:
            for conv in response.json().get('conversations', []):
                # filtragem acontece AQUI, se nao tiver ID de admin, ta na fila
                if conv.get('admin_assignee_id') is None:
                    detalhes_fila.append({
                        'id': conv['id'],
                        'created_at': conv['created_at']
                    })
        return detalhes_fila
    except:
        return []

# ve a distribuicao recente pra ver quem ta pegando mto ticket
# ajuda a ver quem ta sobrecarregado nos ultimos minutos
def get_recent_distribution(team_id, minutos=30):
    try:
        url = "https://api.intercom.io/conversations/search"
        agora_timestamp = int(time.time())
        tempo_corte = agora_timestamp - (minutos * 60)
        
        payload = {
            "query": {
                "operator": "AND",
                "value": [
                    {"field": "created_at", "operator": ">", "value": tempo_corte},
                    {"field": "team_assignee_id", "operator": "=", "value": team_id}
                ]
            },
            "pagination": {"per_page": 60}
        }
        response = requests.post(url, json=payload, headers=headers)
        distribuicao = {}
        total_recente = 0
        if response.status_code == 200:
            conversas = response.json().get('conversations', [])
            total_recente = len(conversas)
            for conv in conversas:
                admin_id = conv.get('admin_assignee_id')
                key = str(admin_id) if admin_id is not None else "FILA"
                distribuicao[key] = distribuicao.get(key, 0) + 1
        return total_recente, distribuicao
    except:
        return 0, {}

# --- NOVA FUNÇÃO: Busca as últimas conversas do dia para mostrar atribuição ---
# pega as ultimas 5 que entraram hoje pra montar o historico ali do lado
def get_latest_conversations(team_id, limit=5):
    try:
        # Pega timestamp do início do dia de hoje (UTC)
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
            "sort": { "field": "created_at", "order": "descending" }, # ordem decrescente, do novo pro velho
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

# loop infinito pra ficar atualizando a tela sozinho
while True:
    with placeholder.container():
        # 1. Coleta de Dados - chama todas as funcoes la de cima
        ids_do_time = get_team_members(TEAM_ID)
        detalhes_admins = get_admin_details()
        
        # busca os dados da fila com id e data
        fila_detalhada = get_team_queue_details(TEAM_ID)
        
        total_entrada_30m, stats_distribuicao = get_recent_distribution(TEAM_ID, 30)
        
        # busca historico recente
        ultimas_conversas = get_latest_conversations(TEAM_ID, 5)

        # contadores gerais
        total_fila = len(fila_detalhada)
        agentes_online = 0
        
        # prepara a lista pra tabela principal
        tabela_dados = []
        
        for member_id in ids_do_time:
            sid = str(member_id)
            # se nao achar o nome, poe o id mesmo
            info = detalhes_admins.get(sid, {'name': f'ID {sid}', 'is_away': True})
            
            status_emoji = "🔴 Ausente" if info['is_away'] else "🟢 Online"
            if not info['is_away']: agentes_online += 1
            
            abertos = count_conversations(member_id, 'open')
            pausados = count_conversations(member_id, 'snoozed')
            entrada_recente = stats_distribuicao.get(sid, 0)
            
            # logica dos alertas: muito volume ou muito ticket aberto
            alerta_vol = "⚡" if entrada_recente >= 3 else ""
            alerta_abertos = "⚠️" if abertos >= 5 else ""

            tabela_dados.append({
                "Status": status_emoji,
                "Agente": info['name'],
                "Abertos": f"{abertos} {alerta_abertos}",
                "Entrada (últimos 30min)": f"{entrada_recente} {alerta_vol}",
                "Pausados": pausados
            })

        # --- LAYOUT SUPERIOR (CARDS) ---
        # divide a tela em 4 colunas pros numeros grandes
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.metric(label="Fila de Espera", value=total_fila, delta="Aguardando", delta_color="inverse")
        with col2:
            st.metric(label="Volume (30min)", value=total_entrada_30m, delta="Novos Tickets")
        with col3:
            delta_agentes = agentes_online - META_AGENTES
            st.metric(label="Agentes Online", value=agentes_online, delta=f"Meta: {META_AGENTES}", delta_color="normal")
        with col4:
            agora = datetime.now().strftime("%H:%M:%S")
            st.metric(label="Última Atualização", value=agora)

        # --- ÁREA DE ALERTAS E LINKS DA FILA ---
        # se tiver fila, mostra o erro vermelho e cria os links pra clicar
        if total_fila > 0:
            st.error("🔥 **CRÍTICO: Clientes aguardando na fila!**")
            
            links_md = ""
            for item in fila_detalhada:
                c_id = item['id']
                # monta o link pra ir direto pro ticket
                link = f"https://app.intercom.com/a/inbox/{APP_ID}/inbox/conversation/{c_id}"
                links_md += f"[Abrir Ticket #{c_id}]({link}) &nbsp;&nbsp; "
            
            st.markdown(links_md, unsafe_allow_html=True)
        
        # aviso se tiver pouca gente online
        if agentes_online < META_AGENTES:
            st.warning(f"⚠️ **Atenção:** Equipe abaixo da meta! Falta(m) {META_AGENTES - agentes_online} agente(s).")

        st.markdown("---")
        
        # --- COLUNAS: PERFORMANCE vs HISTÓRICO ---
        c_left, c_right = st.columns([2, 1])

        with c_left:
            st.subheader("Performance da Equipe")
            df = pd.DataFrame(tabela_dados)
            st.dataframe(df, use_container_width=True, hide_index=True)

        with c_right:
            st.subheader("Últimas Atribuições")
            hist_dados = []
            for conv in ultimas_conversas:
                # arruma a hora pra ficar legivel
                dt_obj = datetime.fromtimestamp(conv['created_at'])
                hora_fmt = dt_obj.strftime('%H:%M')
                
                # tenta achar o nome do agente, se nao tiver eh sem dono
                adm_id = conv.get('admin_assignee_id')
                nome_agente = "Sem Dono"
                if adm_id:
                    nome_agente = detalhes_admins.get(str(adm_id), {}).get('name', 'Desconhecido')
                
                # Link
                c_id = conv['id']
                link = f"https://app.intercom.com/a/inbox/{APP_ID}/inbox/conversation/{c_id}"
                
                hist_dados.append({
                    "Hora": hora_fmt,
                    "Agente": nome_agente,
                    "Link": link  # coluninha pro link funcionar
                })
            
            if hist_dados:
                df_hist = pd.DataFrame(hist_dados)
                
                # exibe tabela com o botao de link configurado
                st.data_editor(
                    df_hist,
                    column_config={
                        "Link": st.column_config.LinkColumn("Ticket", display_text="Abrir")
                    },
                    hide_index=True,
                    disabled=True, # so leitura, ninguem edita nada
                    use_container_width=True
                )
            else:
                st.info("Nenhuma conversa hoje.")

        time.sleep(60) # espera 1 minuto e roda tudo de novo