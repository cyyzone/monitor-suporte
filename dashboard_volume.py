import streamlit as st
import pandas as pd
import plotly.express as px 
import time
from datetime import datetime, time as dt_time, timedelta, timezone
from collections import Counter
# Importa as funções seguras
from utils import check_password, make_api_request

# --- Configs da Página ---
st.set_page_config(page_title="Relatório de Suporte (Unificado)", page_icon="📈", layout="wide")

# 🔒 BLOQUEIO DE SEGURANÇA
if not check_password():
    st.stop()

# 🔑 RECUPERAÇÃO DE SEGREDOS (SEGURA)
try:
    # O token é pego automaticamente dentro do make_api_request, 
    # aqui pegamos só o APP_ID que é usado para gerar links
    APP_ID = st.secrets["INTERCOM_APP_ID"]
except KeyError:
    st.error("❌ Erro: Configure 'INTERCOM_APP_ID' no arquivo .streamlit/secrets.toml")
    st.stop()

# CONFIGURAÇÃO DOS TIMES
ID_SUPORTE = 2975006  
ID_CS_LEADS = 1972225 
TARGET_TEAMS = [ID_SUPORTE, ID_CS_LEADS]
FUSO_BR = timezone(timedelta(hours=-3)) 

# ==========================================
# 1. FUNÇÕES DE COLETA (Usando make_api_request)
# ==========================================

def get_admin_names():
    url = "https://api.intercom.io/admins"
    data = make_api_request("GET", url)
    if data:
        return {a['id']: a['name'] for a in data.get('admins', [])}
    return {}

def get_team_members_map():
    mapa = {}
    for tid in TARGET_TEAMS:
        url = f"https://api.intercom.io/teams/{tid}"
        data = make_api_request("GET", url)
        if data:
            admin_ids = data.get('admin_ids', [])
            for aid in admin_ids:
                mapa[str(aid)] = tid
    return mapa

def fetch_search_results(payload, progress_bar, label):
    url = "https://api.intercom.io/conversations/search"
    results = []
    
    # 1. Primeira chamada segura
    data = make_api_request("POST", url, json=payload)
    if not data: return []
    
    total = data.get('total_count', 0)
    results.extend(data.get('conversations', []))
    
    # 2. Paginação segura
    if total > 0:
        while data.get('pages', {}).get('next'):
            pct = min(len(results) / total, 0.99)
            progress_bar.progress(pct, text=f"{label} ({len(results)} de {total})...")
            
            payload['pagination']['starting_after'] = data['pages']['next']['starting_after']
            
            data = make_api_request("POST", url, json=payload)
            if data:
                results.extend(data.get('conversations', []))
            else: 
                break # Se falhar no meio, para para não travar
            
    return results

# ==========================================
# 2. INTERFACE
# ==========================================

st.title("📈 Relatório Unificado de Suporte")
st.markdown("Visão focada em **Inbound (Clientes)** com atribuição correta de **Agentes/Times**.")

with st.sidebar:
    st.header("⚙️ Configuração")
    with st.form("filtro_geral"):
        periodo = st.date_input(
            "📅 Período de Análise:",
            value=(datetime.now() - timedelta(days=7), datetime.now()), 
            format="DD/MM/YYYY"
        )
        st.write("")
        btn_gerar = st.form_submit_button("🔄 Gerar Relatório", type="primary", use_container_width=True)
    
    st.markdown("---")
    st.info("ℹ️ Filtro API: source.delivered_as = customer_initiated")

if btn_gerar:
    if isinstance(periodo, tuple):
        d_inicio, d_fim = periodo[0], periodo[1] if len(periodo) > 1 else periodo[0]
    else:
        d_inicio = d_fim = periodo

    dt_start = datetime.combine(d_inicio, dt_time.min).replace(tzinfo=FUSO_BR)
    dt_end = datetime.combine(d_fim, dt_time.max).replace(tzinfo=FUSO_BR)
    ts_start, ts_end = int(dt_start.timestamp()), int(dt_end.timestamp())

    progresso = st.progress(0, text="Mapeando Agentes e Times...")
    
    admins_names = get_admin_names()
    agent_team_map = get_team_members_map()
    agentes_ids = list(agent_team_map.keys())

    # Filtros da Query
    time_or_agent_filter = [{"field": "team_assignee_id", "operator": "IN", "value": TARGET_TEAMS}]
    if agentes_ids:
        time_or_agent_filter.append({"field": "admin_assignee_id", "operator": "IN", "value": agentes_ids})

    query_unified = {
        "query": {
            "operator": "AND",
            "value": [
                {"field": "updated_at", "operator": ">", "value": ts_start},
                {"field": "updated_at", "operator": "<", "value": ts_end},
                {"field": "source.delivered_as", "operator": "=", "value": "customer_initiated"},
                {"operator": "OR", "value": time_or_agent_filter}
            ]
        },
        "pagination": {"per_page": 150}
    }
    
    raw_data = fetch_search_results(query_unified, progresso, "🔎 Buscando Conversas...")
    
    progresso.progress(1.0, text="Classificando...")
    time.sleep(0.5)
    progresso.empty()

    # --- PROCESSAMENTO (Mantive sua lógica original) ---
    lista_inbound = []
    lista_csat = []
    todas_tags = []
    
    for c in raw_data:
        c_created = c.get('created_at', 0)
        
        # Lógica de Time/Agente
        team_id = int(c.get('team_assignee_id', 0) or 0)
        admin_id_str = str(c.get('admin_assignee_id', ''))
        if team_id == 0 and admin_id_str in agent_team_map:
            team_id = agent_team_map[admin_id_str]

        # Regras de Negócio
        is_valid_volume = False
        tipo_entrada = ""

        if team_id == ID_SUPORTE:
            if ts_start <= c_created <= ts_end:
                is_valid_volume = True; tipo_entrada = "Inbound (Suporte)"
        elif team_id == ID_CS_LEADS:
            is_valid_volume = True
            tipo_entrada = "Inbound (Lead Novo)" if ts_start <= c_created <= ts_end else "Lead Transferido/Movido"

        if is_valid_volume:
            dt_criacao = datetime.fromtimestamp(c_created, tz=FUSO_BR)
            aid = c.get('admin_assignee_id')
            nome_agente = admins_names.get(str(aid), "Sem Dono / Fila") if aid else "Sem Dono / Fila"
            
            tags_obj = c.get('tags', {}).get('tags', [])
            nomes_tags = [t['name'] for t in tags_obj]
            todas_tags.extend(nomes_tags)
            
            lista_inbound.append({
                "DataIso": dt_criacao.date(),
                "Data": dt_criacao.strftime("%d/%m %H:%M"),
                "Tipo": tipo_entrada,
                "Agente": nome_agente,
                "Tags": ", ".join(nomes_tags),
                "Link": f"https://app.intercom.com/a/inbox/{APP_ID}/inbox/conversation/{c['id']}",
                "ID": c['id']
            })

        # CSAT
        rating_obj = c.get('conversation_rating', {})
        if rating_obj and rating_obj.get('rating'):
            if ts_start <= rating_obj.get('created_at', 0) <= ts_end:
                lista_csat.append(c)

    # --- VISUALIZAÇÃO ---
    tab_vol, tab_csat_view = st.tabs(["📊 Volume & Tags", "⭐ Qualidade (CSAT)"])

    with tab_vol:
        df = pd.DataFrame(lista_inbound)
        if not df.empty:
            # Métricas
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("📬 Total Inbound", len(df))
            c2.metric("Suporte", len(df[df['Tipo'] == "Inbound (Suporte)"]))
            c3.metric("CS / Leads", len(df[df['Tipo'].str.contains("Lead") | df['Tipo'].str.contains("Movido")]))
            c4.metric("Agentes Ativos", df[df['Agente'] != "Sem Dono / Fila"]['Agente'].nunique())
            
            st.divider()
            
            # Gráficos e Tabelas (Mantidos igual ao original)
            g1, g2 = st.columns(2)
            with g1:
                vol_dia = df.groupby('DataIso').size().reset_index(name='Qtd')
                vol_dia['DataGrafico'] = vol_dia['DataIso'].apply(lambda x: x.strftime("%d/%m"))
                st.plotly_chart(px.bar(vol_dia, x='DataGrafico', y='Qtd', text='Qtd', title="Entradas por Dia"), use_container_width=True)
            
            with g2:
                vol_agente = df['Agente'].value_counts().reset_index(name='Qtd')
                st.plotly_chart(px.bar(vol_agente, x='Qtd', y='Agente', orientation='h', text='Qtd', title="Por Agente"), use_container_width=True)

            # Tabela
            st.dataframe(
                df.sort_values(by=['DataIso', 'Tipo']),
                column_config={"Link": st.column_config.LinkColumn("Ticket", display_text="Abrir")},
                use_container_width=True, hide_index=True
            )
        else:
            st.warning("Nenhuma conversa encontrada.")

    with tab_csat_view:
        if lista_csat:
            # (Lógica do CSAT simplificada aqui para caber, mas você já tem ela pronta no outro arquivo)
            st.info(f"Foram encontradas {len(lista_csat)} avaliações neste período.")
            # ... copie a lógica de exibição do CSAT se precisar detalhar aqui ...
        else:
            st.info("Nenhuma avaliação (CSAT) no período.")

else:
    st.info("👈 Selecione as datas e clique em 'Gerar Relatório'.")
