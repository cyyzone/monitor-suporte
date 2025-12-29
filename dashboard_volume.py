import streamlit as st
import requests
import pandas as pd
import plotly.express as px 
import time
from datetime import datetime, time as dt_time, timedelta, timezone
from collections import Counter
from utils import check_password

# --- Configs da Página ---
st.set_page_config(page_title="Relatório de Suporte (Unificado)", page_icon="📈", layout="wide")

# 🔒 BLOQUEIO DE SEGURANÇA ------------------------
if not check_password():
    st.stop()  # Para a execução do script aqui se não tiver senha
# -------------------------------------------------
try:
    TOKEN = st.secrets["INTERCOM_TOKEN"]
    APP_ID = st.secrets["INTERCOM_APP_ID"]
except:
    TOKEN = "SEU_TOKEN_AQUI"
    APP_ID = "SEU_APP_ID_AQUI"

# CONFIGURAÇÃO DOS TIMES
ID_SUPORTE = 2975006  
ID_CS_LEADS = 1972225 
TARGET_TEAMS = [ID_SUPORTE, ID_CS_LEADS]

headers = {"Authorization": f"Bearer {TOKEN}", "Accept": "application/json"}
FUSO_BR = timezone(timedelta(hours=-3)) 

# ==========================================
# 1. FUNÇÕES DE COLETA E MAPEAMENTO
# ==========================================

def get_admin_names():
    try:
        r = requests.get("https://api.intercom.io/admins", headers=headers)
        return {a['id']: a['name'] for a in r.json().get('admins', [])} if r.status_code == 200 else {}
    except: return {}

def get_team_members_map():
    """
    Retorna um dicionário mapeando ID_AGENTE -> ID_TIME.
    Ex: {'12345': 2975006, '67890': 1972225}
    Isso serve para saber de qual time é o agente, caso o ticket esteja sem time.
    """
    mapa = {}
    for tid in TARGET_TEAMS:
        try:
            r = requests.get(f"https://api.intercom.io/teams/{tid}", headers=headers)
            if r.status_code == 200:
                admin_ids = r.json().get('admin_ids', [])
                for aid in admin_ids:
                    mapa[str(aid)] = tid
        except: pass
    return mapa

def fetch_search_results(payload, progress_bar, label):
    url = "https://api.intercom.io/conversations/search"
    results = []
    
    r = requests.post(url, json=payload, headers=headers)
    if r.status_code != 200: return []
    
    data = r.json()
    total = data.get('total_count', 0)
    results.extend(data.get('conversations', []))
    
    if total > 0:
        while data.get('pages', {}).get('next'):
            pct = min(len(results) / total, 0.99)
            progress_bar.progress(pct, text=f"{label} ({len(results)} de {total})...")
            
            payload['pagination']['starting_after'] = data['pages']['next']['starting_after']
            r = requests.post(url, json=payload, headers=headers)
            if r.status_code == 200:
                data = r.json()
                results.extend(data.get('conversations', []))
            else: break
            
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
    st.caption("🔗 **Acesso Rápido:**")
    st.markdown("🚀 [Painel Tempo Real (Operacional)](https://dashboardvisualpy.streamlit.app)")
    st.markdown("⭐ [Painel Focado em CSAT](https://dashboardcsatpy.streamlit.app)")
    st.info("ℹ️ Filtro API: source.delivered_as = customer_initiated")

if btn_gerar:
    # Datas
    if isinstance(periodo, tuple):
        d_inicio, d_fim = periodo[0], periodo[1] if len(periodo) > 1 else periodo[0]
    else:
        d_inicio = d_fim = periodo

    dt_start = datetime.combine(d_inicio, dt_time.min).replace(tzinfo=FUSO_BR)
    dt_end = datetime.combine(d_fim, dt_time.max).replace(tzinfo=FUSO_BR)
    ts_start, ts_end = int(dt_start.timestamp()), int(dt_end.timestamp())

    progresso = st.progress(0, text="Mapeando Agentes e Times...")
    
    # 1. Mapeamento Prévio (Vital para corrigir a atribuição)
    admins_names = get_admin_names()
    agent_team_map = get_team_members_map() # Sabe quem é de qual time
    
    # Lista de IDs de agentes para incluir na busca (caso o ticket esteja sem time)
    agentes_ids = list(agent_team_map.keys())

    # ------------------------------------------------------------------
    # ESTRATÉGIA DE BUSCA HÍBRIDA
    # Busca por Time OU por Agente desses times
    # + Filtro de Cliente (Inbound)
    # ------------------------------------------------------------------
    
    # Critério de "Pertencimento": Ou está na caixa do time, OU está com um agente do time
    time_or_agent_filter = [
        {"field": "team_assignee_id", "operator": "IN", "value": TARGET_TEAMS}
    ]
    if agentes_ids:
        time_or_agent_filter.append({"field": "admin_assignee_id", "operator": "IN", "value": agentes_ids})

    query_unified = {
        "query": {
            "operator": "AND",
            "value": [
                {"field": "updated_at", "operator": ">", "value": ts_start},
                {"field": "updated_at", "operator": "<", "value": ts_end},
                {"field": "source.delivered_as", "operator": "=", "value": "customer_initiated"},
                {
                    "operator": "OR",
                    "value": time_or_agent_filter
                }
            ]
        },
        "pagination": {"per_page": 150}
    }
    
    raw_data = fetch_search_results(query_unified, progresso, "🔎 Buscando Conversas...")
    
    progresso.progress(1.0, text="Classificando e calculando...")
    time.sleep(0.5)
    progresso.empty()

    # --- PROCESSAMENTO ---
    lista_inbound = []
    lista_csat = []
    todas_tags = []
    
    for c in raw_data:
        c_created = c.get('created_at', 0)
        c_updated = c.get('updated_at', 0)
        
        # Identificação Inteligente do Time
        # 1. Tenta pegar o time direto do ticket
        team_id = int(c.get('team_assignee_id', 0) or 0)
        
        # 2. Se não tiver time (0), tenta descobrir pelo Agente (admin_assignee_id)
        # Isso resolve o problema de tickets atribuídos direto para "Gilson"
        admin_id_str = str(c.get('admin_assignee_id', ''))
        if team_id == 0 and admin_id_str in agent_team_map:
            team_id = agent_team_map[admin_id_str]

        # --- LÓGICA DE NEGÓCIO POR CAIXA ---
        is_valid_volume = False
        tipo_entrada = ""

        # CAIXA SUPORTE
        if team_id == ID_SUPORTE:
            # Só conta como volume se foi CRIADO no período
            if ts_start <= c_created <= ts_end:
                is_valid_volume = True
                tipo_entrada = "Inbound (Suporte)"

        # CAIXA CS/LEADS
        elif team_id == ID_CS_LEADS:
            # Conta se foi CRIADO ou MOVIDO (Updated) no período
            is_valid_volume = True
            if ts_start <= c_created <= ts_end:
                tipo_entrada = "Inbound (Lead Novo)"
            else:
                tipo_entrada = "Lead Transferido/Movido"

        if is_valid_volume:
            dt_criacao = datetime.fromtimestamp(c_created, tz=FUSO_BR)
            aid = c.get('admin_assignee_id')
            nome_agente = admins_names.get(str(aid), "Sem Dono / Fila") if aid else "Sem Dono / Fila"
            
            tags_obj = c.get('tags', {}).get('tags', [])
            nomes_tags = [t['name'] for t in tags_obj]
            todas_tags.extend(nomes_tags)
            
            link_url = f"https://app.intercom.com/a/inbox/{APP_ID}/inbox/conversation/{c['id']}"
            
            lista_inbound.append({
                "DataIso": dt_criacao.date(),
                "Data": dt_criacao.strftime("%d/%m %H:%M"),
                "Tipo": tipo_entrada,
                "Agente": nome_agente,
                "Tags": ", ".join(nomes_tags),
                "Link": link_url,
                "ID": c['id']
            })

        # --- CSAT (Independente de Volume) ---
        rating_obj = c.get('conversation_rating', {})
        if rating_obj and rating_obj.get('rating'):
            r_created = rating_obj.get('created_at', 0)
            if ts_start <= r_created <= ts_end:
                lista_csat.append(c)

    # --- VISUALIZAÇÃO ---
    tab_vol, tab_csat_view = st.tabs(["📊 Volume & Tags", "⭐ Qualidade (CSAT)"])

    # ABA 1: VOLUME
    with tab_vol:
        df = pd.DataFrame(lista_inbound)
        
        if not df.empty:
            total = len(df)
            suporte = len(df[df['Tipo'] == "Inbound (Suporte)"])
            leads = len(df[df['Tipo'].str.contains("Lead") | df['Tipo'].str.contains("Movido")])
            
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("📬 Total Inbound (Clientes)", total)
            c2.metric("Suporte (2975006)", suporte)
            c3.metric("CS / Leads (1972225)", leads)
            c4.metric("Agentes Ativos", df[df['Agente'] != "Sem Dono / Fila"]['Agente'].nunique())
            
            st.divider()
            
            # Gráficos
            g1, g2 = st.columns(2)
            with g1:
                st.subheader("📅 Entradas por Dia")
                vol_dia = df.groupby('DataIso').size().reset_index(name='Qtd')
                vol_dia['DataGrafico'] = vol_dia['DataIso'].apply(lambda x: x.strftime("%d/%m"))
                fig_dia = px.bar(vol_dia, x='DataGrafico', y='Qtd', text='Qtd', color='Qtd', color_continuous_scale='Blues')
                st.plotly_chart(fig_dia, use_container_width=True)
            
            with g2:
                st.subheader("🏆 Distribuição por Agente")
                vol_agente = df['Agente'].value_counts().reset_index()
                vol_agente.columns = ['Agente', 'Qtd']
                fig_ag = px.bar(vol_agente, x='Qtd', y='Agente', orientation='h', text='Qtd', color='Qtd', color_continuous_scale='Greens')
                fig_ag.update_layout(yaxis={'categoryorder':'total ascending'})
                st.plotly_chart(fig_ag, use_container_width=True)

            st.divider()
            
            # Tags
            st.subheader("🏷️ Top Assuntos (Tags)")
            if todas_tags:
                contagem_tags = Counter(todas_tags)
                df_tags = pd.DataFrame(contagem_tags.items(), columns=['Tag', 'Qtd']).sort_values('Qtd', ascending=False).head(15)
                fig_tags = px.bar(df_tags, x='Qtd', y='Tag', orientation='h', text='Qtd', color='Qtd', color_continuous_scale='Viridis')
                fig_tags.update_layout(yaxis={'categoryorder':'total ascending'})
                st.plotly_chart(fig_tags, use_container_width=True)
            else:
                st.info("Nenhuma tag identificada.")

            st.divider()
            
            # Tabela Detalhada com Filtros
            st.subheader("🔎 Lista de Conversas")
            
            agentes_disp = df['Agente'].unique()
            f_agente = st.multiselect("Filtrar Agente:", agentes_disp)
            
            df_show = df.copy()
            if f_agente:
                df_show = df_show[df_show['Agente'].isin(f_agente)]
            
            st.caption(f"Exibindo {len(df_show)} registros.")
            st.data_editor(
                df_show.sort_values(by=['DataIso', 'Tipo']),
                column_config={
                    "Link": st.column_config.LinkColumn("Ticket", display_text="Abrir"),
                    "Tipo": st.column_config.TextColumn("Origem", width="medium"),
                    "DataIso": None
                },
                use_container_width=True, hide_index=True
            )
        else:
            st.warning("Nenhuma conversa encontrada.")

    # ABA 2: CSAT
    with tab_csat_view:
        if lista_csat:
            stats = {}
            detalhes_csat = []
            
            time_pos, time_neu, time_neg = 0, 0, 0
            for c in lista_csat:
                aid = str(c.get('admin_assignee_id'))
                nota = c['conversation_rating']['rating']
                
                if aid not in stats: stats[aid] = {'pos':0, 'neu':0, 'neg':0, 'total':0}
                stats[aid]['total'] += 1
                
                label_nota = ""
                if nota >= 4: 
                    stats[aid]['pos'] += 1; time_pos += 1; label_nota="😍 Positiva"
                elif nota == 3: 
                    stats[aid]['neu'] += 1; time_neu += 1; label_nota="😐 Neutra"
                else: 
                    stats[aid]['neg'] += 1; time_neg += 1; label_nota="😡 Negativa"
                
                detalhes_csat.append({
                    "Data": datetime.fromtimestamp(c['conversation_rating']['created_at'], tz=FUSO_BR).strftime("%d/%m %H:%M"),
                    "Agente": admins_names.get(aid, "Desconhecido"),
                    "Nota": nota,
                    "Tipo": label_nota,
                    "Comentário": c['conversation_rating'].get('remark', '-'),
                    "Link": f"https://app.intercom.com/a/inbox/{APP_ID}/inbox/conversation/{c['id']}"
                })

            total_csat = time_pos + time_neu + time_neg
            if total_csat > 0:
                csat_real = (time_pos / total_csat) * 100
                total_valid = time_pos + time_neg
                csat_adj = (time_pos / total_valid * 100) if total_valid > 0 else 0
                
                k1, k2, k3, k4 = st.columns(4)
                k1.metric("CSAT Geral", f"{csat_real:.1f}%", f"{total_csat} avaliações")
                k2.metric("CSAT Ajustado", f"{csat_adj:.1f}%", "Sem neutras")
                k3.metric("😍 Positivas", time_pos)
                k4.metric("😡 Negativas", time_neg)
                
                st.divider()
                
                # Tabela CSAT com Filtros
                st.subheader("🔎 Detalhes das Avaliações")
                df_csat = pd.DataFrame(detalhes_csat)
                
                fc1, fc2 = st.columns(2)
                with fc1: f_ag_csat = st.multiselect("Filtrar Agente:", df_csat['Agente'].unique(), key="f_csat_ag")
                with fc2: f_tp_csat = st.multiselect("Filtrar Nota:", df_csat['Tipo'].unique(), key="f_csat_tp")
                
                df_show_csat = df_csat.copy()
                if f_ag_csat: df_show_csat = df_show_csat[df_show_csat['Agente'].isin(f_ag_csat)]
                if f_tp_csat: df_show_csat = df_show_csat[df_show_csat['Tipo'].isin(f_tp_csat)]
                
                st.data_editor(
                    df_show_csat,
                    column_config={
                        "Link": st.column_config.LinkColumn("Ver", display_text="Abrir"),
                        "Nota": st.column_config.NumberColumn("Nota", format="%d ⭐")
                    },
                    use_container_width=True, hide_index=True
                )
        else:
            st.info("Nenhuma avaliação (CSAT) no período.")

else:
    st.info("👈 Selecione as datas na barra lateral e clique em 'Gerar Relatório'.")
