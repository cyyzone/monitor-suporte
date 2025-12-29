import streamlit as st
import pandas as pd
import time
import re
from datetime import datetime, timezone, timedelta

# Importamos as funções de segurança e API do arquivo utils.py
# (Isso mantém o código limpo e centraliza a lógica de retry/conexão lá)
from utils import check_password, make_api_request

# --- Configs da Página ---
st.set_page_config(page_title="Monitor Operacional", page_icon="🚀", layout="wide")

# 🔒 BLOQUEIO DE SEGURANÇA
# Verifica a senha antes de carregar qualquer coisa. Se falhar, o app para aqui.
if not check_password():
    st.stop()

# --- Configuração de Segredos ---
# Garante que temos as credenciais necessárias antes de tentar conectar
try:
    APP_ID = st.secrets["INTERCOM_APP_ID"]
except KeyError:
    st.error("❌ Erro Crítico: 'INTERCOM_APP_ID' não encontrado no secrets.toml")
    st.stop()

# Constantes do Projeto
TEAM_ID = 2975006
META_AGENTES = 4
FUSO_BR = timezone(timedelta(hours=-3))

# --- Funções de Busca (Otimizadas com Cache) ---

# O decorador @st.cache_data é o segredo da performance aqui.
# ttl=60: Guarda o resultado por 60 segundos. Isso evita bater no limite da API do Intercom.
# show_spinner=False: Remove aquele aviso "Running..." da tela para deixar a UI limpa.

@st.cache_data(ttl=60, show_spinner=False)
def get_admin_details():
    """Busca lista de admins para mapear ID -> Nome e Status (Online/Ausente)."""
    url = "https://api.intercom.io/admins"
    data = make_api_request("GET", url)
    
    dados = {}
    if data:
        for admin in data.get('admins', []):
            dados[admin['id']] = {
                'name': admin['name'],
                'is_away': admin.get('away_mode_enabled', False)
            }
    return dados

@st.cache_data(ttl=60, show_spinner=False)
def get_team_members(team_id):
    """Busca apenas os IDs dos membros do time de suporte."""
    url = f"https://api.intercom.io/teams/{team_id}"
    data = make_api_request("GET", url)
    if data:
        return data.get('admin_ids', [])
    return []

@st.cache_data(ttl=60, show_spinner=False)
def count_conversations(admin_id, state):
    """Conta quantos tickets um agente tem em um estado específico (ex: 'open')."""
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
    data = make_api_request("POST", url, json=payload)
    if data:
        return data.get('total_count', 0)
    return 0

@st.cache_data(ttl=60, show_spinner=False)
def get_team_queue_details(team_id):
    """
    Monitora a fila de espera.
    Retorna a lista de tickets que estão no time mas sem nenhum agente (admin) atribuído.
    """
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
    data = make_api_request("POST", url, json=payload)
    detalhes_fila = []
    if data:
        for conv in data.get('conversations', []):
            # Validação extra: só conta se realmente não tiver dono
            if conv.get('admin_assignee_id') is None:
                detalhes_fila.append({'id': conv['id']})
    return detalhes_fila

@st.cache_data(ttl=60, show_spinner=False)
def get_daily_stats(team_id, ts_inicio, minutos_recente=30):
    """
    Faz o trabalho pesado: baixa conversas do período e calcula estatísticas.
    Retorna: Volume total, volume recente (30min) e detalhes para lista.
    """
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
        "pagination": {"per_page": 150}
    }
    
    data = make_api_request("POST", url, json=payload)
    
    stats_periodo = {}
    stats_30min = {}
    detalhes_por_agente = {} 
    total_periodo = 0
    total_recente = 0
    
    if data:
        conversas = data.get('conversations', [])
        total_periodo = len(conversas)
        for conv in conversas:
            aid = str(conv.get('admin_assignee_id')) if conv.get('admin_assignee_id') else "FILA"
            
            # Contagem geral
            stats_periodo[aid] = stats_periodo.get(aid, 0) + 1
            
            # Organiza dados para os "Expanders" de detalhe
            if aid not in detalhes_por_agente:
                detalhes_por_agente[aid] = []
            
            detalhes_por_agente[aid].append({
                'id': conv['id'],
                'created_at': conv['created_at'],
                'link': f"https://app.intercom.com/a/inbox/{APP_ID}/inbox/conversation/{conv['id']}"
            })
            
            # Contagem de tickets quentes (últimos 30 min)
            if conv['created_at'] > ts_corte_recente:
                stats_30min[aid] = stats_30min.get(aid, 0) + 1
                total_recente += 1
                
    return total_periodo, total_recente, stats_periodo, stats_30min, detalhes_por_agente

@st.cache_data(ttl=60, show_spinner=False)
def get_latest_conversations(team_id, ts_inicio, limit=10):
    """Pega apenas as últimas conversas para exibir na tabela de log (canto direito)."""
    url = "https://api.intercom.io/conversations/search"
    payload = {
        "query": {
            "operator": "AND",
            "value": [
                {"field": "created_at", "operator": ">", "value": ts_inicio},
                {"field": "team_assignee_id", "operator": "=", "value": team_id}
            ]
        },
        "sort": { "field": "created_at", "order": "descending" },
        "pagination": {"per_page": limit}
    }
    data = make_api_request("POST", url, json=payload)
    if data:
        return data.get('conversations', [])
    return []

# --- Interface Visual com Auto-Refresh ---

# @st.fragment: Permite que apenas essa função recarregue a cada 60s,
# sem piscar a página inteira ou perder o estado de outros componentes.
@st.fragment(run_every=60)
def atualizar_painel():
    st.title("🚀 Monitor Operacional (Tempo Real)")

    # Filtro de tempo simples para alternar visões
    col_filtro, _ = st.columns([1, 3])
    with col_filtro:
        periodo_selecionado = st.radio(
            "📅 Período de Análise:", 
            ["Hoje (Desde 00:00)", "Últimas 48h"], 
            horizontal=True
        )

    st.markdown("---")

    # Define o ponto de partida do tempo (Hoje 00:00 ou 48h atrás)
    now = datetime.now(FUSO_BR)
    if "Hoje" in periodo_selecionado:
        ts_inicio = int(now.replace(hour=0, minute=0, second=0).timestamp())
        texto_volume = "Volume (Dia / 30min)"
    else:
        ts_inicio = int((now - timedelta(hours=48)).timestamp())
        texto_volume = "Volume (48h / 30min)"

    # --- Coleta de Dados ---
    # Único spinner visível para o usuário saber que estamos buscando dados novos
    with st.spinner("Sincronizando com Intercom..."):
        ids_time = get_team_members(TEAM_ID)
        admins = get_admin_details()
        fila = get_team_queue_details(TEAM_ID)
        
        # Chama as funções cacheadas
        vol_periodo, vol_rec, stats_periodo, stats_rec, detalhes_agente = get_daily_stats(TEAM_ID, ts_inicio)
        ultimas = get_latest_conversations(TEAM_ID, ts_inicio, 10)
    
    online = 0
    tabela = []
    
    # Monta a tabela principal cruzando dados dos agentes com os tickets
    for mid in ids_time:
        sid = str(mid)
        info = admins.get(sid, {'name': f'ID {sid}', 'is_away': True})
        
        if not info['is_away']: online += 1
        emoji = "🔴" if info['is_away'] else "🟢"
        
        abertos = count_conversations(mid, 'open')
        pausados = count_conversations(mid, 'snoozed')
        
        # Regras de Negócio / Alertas Visuais
        alerta = "⚠️" if abertos >= 5 else ""      # Muita coisa aberta
        raio = "⚡" if stats_rec.get(sid, 0) >= 3 else "" # Pico de trabalho recente
        
        tabela.append({
            "Status": emoji,
            "Agente": info['name'],
            "Abertos": f"{abertos} {alerta}",
            "Volume Período": stats_periodo.get(sid, 0),
            "Recente (30m)": f"{stats_rec.get(sid, 0)} {raio}",
            "Pausados": pausados
        })
    
    # --- KPIs e Métricas Superiores ---
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Fila de Espera", len(fila), "Aguardando", delta_color="inverse")
    c2.metric(texto_volume, f"{vol_periodo} / {vol_rec}")
    c3.metric("Agentes Online", online, f"Meta: {META_AGENTES}")
    c4.metric("Atualizado", datetime.now(FUSO_BR).strftime("%H:%M:%S"))
    
    # Alerta visual grande se tiver fila
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

    # --- Divisão da Tela: Tabela Equipe (Esq) vs Histórico (Dir) ---
    c_left, c_right = st.columns([2, 1])

    with c_left:
        st.subheader("Performance da Equipe")
        st.dataframe(
            pd.DataFrame(tabela), 
            use_container_width=True, 
            hide_index=True,
            column_order=["Status", "Agente", "Abertos", "Volume Período", "Recente (30m)", "Pausados"]
        )
        
        # Detalhes expansíveis por agente
        st.markdown("---")
        st.subheader("🕵️ Detalhe dos Tickets por Agente")
        
        if len(ids_time) > 0:
            cols = st.columns(3) 
            for i, mid in enumerate(ids_time):
                sid = str(mid)
                nome = admins.get(sid, {}).get('name', 'Desconhecido')
                tickets = detalhes_agente.get(sid, [])
                
                with cols[i % 3]:
                    with st.expander(f"{nome} ({len(tickets)})"):
                        if not tickets:
                            st.caption("Sem tickets no período.")
                        else:
                            tickets_sorted = sorted(tickets, key=lambda x: x['created_at'], reverse=True)
                            for t in tickets_sorted:
                                hora = datetime.fromtimestamp(t['created_at'], tz=FUSO_BR).strftime('%H:%M')
                                st.markdown(f"⏰ **{hora}** - [Abrir #{t['id']}]({t['link']})")
        else:
            st.info("Nenhum agente encontrado no time.")

    with c_right:
        st.subheader("Últimas Atribuições")
        hist_dados = []
        for conv in ultimas:
            dt_obj = datetime.fromtimestamp(conv['created_at'], tz=FUSO_BR)
            hora_fmt = dt_obj.strftime('%d/%m %H:%M')
            
            adm_id = conv.get('admin_assignee_id')
            nome_agente = "Sem Dono"
            if adm_id:
                nome_agente = admins.get(str(adm_id), {}).get('name', 'Desconhecido')
            
            # Tenta limpar o HTML do body para mostrar um resumo limpo
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
        
        # Key dinâmico garante que a tabela se redesenhe se os dados mudarem
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

# --- Execução Principal ---
atualizar_painel()
