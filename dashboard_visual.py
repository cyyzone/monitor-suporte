import streamlit as st
import pandas as pd
import time
import re
from datetime import datetime, timezone, timedelta

# Importei a nova função send_slack_alert do utils
from utils import check_password, make_api_request, send_slack_alert 

# --- Configs da Página ---
st.set_page_config(page_title="Monitor Operacional", page_icon="🚀", layout="wide")

if not check_password():
    st.stop()

try:
    APP_ID = st.secrets["INTERCOM_APP_ID"]
except KeyError:
    st.error("❌ Erro Crítico: 'INTERCOM_APP_ID' não encontrado no secrets.toml")
    st.stop()

TEAM_ID = 2975006
META_AGENTES = 4
FUSO_BR = timezone(timedelta(hours=-3))

# --- Funções de Busca (Mantidas iguais) ---
@st.cache_data(ttl=60, show_spinner=False)
def get_admin_details():
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
    url = f"https://api.intercom.io/teams/{team_id}"
    data = make_api_request("GET", url)
    if data: return data.get('admin_ids', [])
    return []

@st.cache_data(ttl=60, show_spinner=False)
def count_conversations(admin_id, state):
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
    if data: return data.get('total_count', 0)
    return 0

@st.cache_data(ttl=60, show_spinner=False)
def get_team_queue_details(team_id):
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
            if conv.get('admin_assignee_id') is None:
                detalhes_fila.append({'id': conv['id']})
    return detalhes_fila

@st.cache_data(ttl=60, show_spinner=False)
def get_daily_stats(team_id, ts_inicio, minutos_recente=30):
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
            stats_periodo[aid] = stats_periodo.get(aid, 0) + 1
            
            if aid not in detalhes_por_agente: detalhes_por_agente[aid] = []
            
            detalhes_por_agente[aid].append({
                'id': conv['id'],
                'created_at': conv['created_at'],
                'link': f"https://app.intercom.com/a/inbox/{APP_ID}/inbox/conversation/{conv['id']}"
            })
            
            if conv['created_at'] > ts_corte_recente:
                stats_30min[aid] = stats_30min.get(aid, 0) + 1
                total_recente += 1
                
    return total_periodo, total_recente, stats_periodo, stats_30min, detalhes_por_agente

@st.cache_data(ttl=60, show_spinner=False)
def get_latest_conversations(team_id, ts_inicio, limit=10):
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
    if data: return data.get('conversations', [])
    return []

# --- Interface Visual com Auto-Refresh ---

@st.fragment(run_every=60)
def atualizar_painel():
    st.title("🚀 Monitor Operacional (Tempo Real)")

    # ⚡ ALERTA SLACK: Inicializa variavel de controle de tempo na sessão
    if "ultimo_alerta_ts" not in st.session_state:
        st.session_state["ultimo_alerta_ts"] = 0

    col_filtro, _ = st.columns([1, 3])
    with col_filtro:
        periodo_selecionado = st.radio(
            "📅 Período de Análise:", 
            ["Hoje (Desde 00:00)", "Últimas 48h"], 
            horizontal=True
        )

    st.markdown("---")

    now = datetime.now(FUSO_BR)
    if "Hoje" in periodo_selecionado:
        ts_inicio = int(now.replace(hour=0, minute=0, second=0).timestamp())
        texto_volume = "Volume (Dia / 30min)"
    else:
        ts_inicio = int((now - timedelta(hours=48)).timestamp())
        texto_volume = "Volume (48h / 30min)"

    # Coleta de Dados
    ids_time = get_team_members(TEAM_ID)
    admins = get_admin_details()
    fila = get_team_queue_details(TEAM_ID)
    vol_periodo, vol_rec, stats_periodo, stats_rec, detalhes_agente = get_daily_stats(TEAM_ID, ts_inicio)
    ultimas = get_latest_conversations(TEAM_ID, ts_inicio, 10)
    
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
            "Volume Período": stats_periodo.get(sid, 0),
            "Recente (30m)": f"{stats_rec.get(sid, 0)} {raio}",
            "Pausados": pausados
        })
    
    tabela = sorted(tabela, key=lambda x: x['Agente'])
    tabela = sorted(tabela, key=lambda x: x['Status'], reverse=True)

    # --- LÓGICA DE ALERTA DO SLACK ---
    # Definição das condições criticas
    msg_alerta = []
    
    # 1. Fila com gente esperando
    if len(fila) > 0:
        msg_alerta.append(f"🔥 *CRÍTICO:* Existem *{len(fila)} clientes* aguardando na fila!")
    
    # 2. Pouca gente online (Meta nao batida)
    if online < META_AGENTES:
        msg_alerta.append(f"⚠️ *ATENÇÃO:* Equipe abaixo da meta! Apenas *{online}/{META_AGENTES}* online.")

    # 3. Verifica se pode enviar (Cooldown de 30 minutos = 1800 segundos)
    agora = time.time()
    TEMPO_RESFRIAMENTO = 600 

    if msg_alerta and (agora - st.session_state["ultimo_alerta_ts"] > TEMPO_RESFRIAMENTO):
        # Monta a mensagem bonita pro Slack
        texto_final = "*🚨 Alerta Monitor Suporte*\n" + "\n".join(msg_alerta) + f"\nLink: https://dashboardvisualpy.streamlit.app/"
        
        send_slack_alert(texto_final)
        
        # Atualiza o relogio
        st.session_state["ultimo_alerta_ts"] = agora
        st.toast("🔔 Alerta enviado para o Slack!", icon="📨")
    # ----------------------------------

    # >>>>> CÓDIGO DE DEBUG INSERIDO AQUI <<<<<
    st.divider()
    with st.expander("🛠️ Debug Técnico do Alerta", expanded=True):
        st.write(f"**Condição Fila:** {len(fila)} > 0? {'SIM' if len(fila)>0 else 'NÃO'}")
        st.write(f"**Condição Meta:** {online} < {META_AGENTES}? {'SIM' if online < META_AGENTES else 'NÃO'}")
        st.write(f"**Lista de Alertas Gerada:** {msg_alerta}")
        
        # Cálculo do tempo
        tempo_passado = time.time() - st.session_state["ultimo_alerta_ts"]
        tempo_restante = 1800 - tempo_passado
        
        c_debug1, c_debug2 = st.columns(2)
        with c_debug1:
            if tempo_restante > 0:
                st.warning(f"⏳ **Em Resfriamento:** Faltam {int(tempo_restante/60)}min para permitir novo envio.")
            else:
                st.success("✅ **Pronto para envio:** O sistema enviará assim que detectar erro.")
        
        with c_debug2:
            if st.button("🚨 FORÇAR ENVIO AGORA (Resetar Timer)"):
                st.session_state["ultimo_alerta_ts"] = 0
                st.rerun()
    st.divider()
    # >>>>> FIM DO DEBUG <<<<<

    # Cards do Topo
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Fila de Espera", len(fila), "Aguardando", delta_color="inverse")
    c2.metric(texto_volume, f"{vol_periodo} / {vol_rec}")
    c3.metric("Agentes Online", online, f"Meta: {META_AGENTES}")
    c4.metric("Atualizado", datetime.now(FUSO_BR).strftime("%H:%M:%S"))
    
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

    c_left, c_right = st.columns([2, 1])

    with c_left:
        st.subheader("Performance da Equipe")
        st.dataframe(
            pd.DataFrame(tabela), 
            use_container_width=True, 
            hide_index=True,
            column_order=["Status", "Agente", "Abertos", "Volume Período", "Recente (30m)", "Pausados"]
        )
        
        st.markdown("---")
        st.subheader("🕵️ Detalhe dos Tickets por Agente")
        
        if len(ids_time) > 0:
            cols = st.columns(3) 
            ordem_nomes = [t['Agente'] for t in tabela]
            
            ids_time_ordenados = sorted(ids_time, key=lambda mid: 
                ordem_nomes.index(admins.get(str(mid), {}).get('name', '')) 
                if admins.get(str(mid), {}).get('name', '') in ordem_nomes else 999
            )

            for i, mid in enumerate(ids_time_ordenados):
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

atualizar_painel()



