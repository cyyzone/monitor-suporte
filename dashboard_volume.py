import streamlit as st
import requests
import pandas as pd
import plotly.express as px 
import time
from datetime import datetime, time as dt_time, timedelta, timezone
from collections import Counter

# --- Configs da Página ---
st.set_page_config(page_title="Relatório de Suporte (Unificado)", page_icon="📈", layout="wide")

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
# 1. FUNÇÕES DE COLETA
# ==========================================

def get_admin_names():
    try:
        r = requests.get("https://api.intercom.io/admins", headers=headers)
        return {a['id']: a['name'] for a in r.json().get('admins', [])} if r.status_code == 200 else {}
    except: return {}

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
st.markdown("Visão focada em **Novas Entradas de Clientes (Inbound)** com análise de **Tags** e **Qualidade**.")

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
    st.info("ℹ️ Excluindo tickets internos (Admin).")

if btn_gerar:
    # Datas
    if isinstance(periodo, tuple):
        d_inicio, d_fim = periodo[0], periodo[1] if len(periodo) > 1 else periodo[0]
    else:
        d_inicio = d_fim = periodo

    dt_start = datetime.combine(d_inicio, dt_time.min).replace(tzinfo=FUSO_BR)
    dt_end = datetime.combine(d_fim, dt_time.max).replace(tzinfo=FUSO_BR)
    ts_start, ts_end = int(dt_start.timestamp()), int(dt_end.timestamp())

    progresso = st.progress(0, text="Conectando API...")
    admins = get_admin_names()
    
    # ------------------------------------------------------------------
    # ESTRATÉGIA: Filtro DIRETO NA API (customer_initiated)
    # ------------------------------------------------------------------
    query_unified = {
        "query": {
            "operator": "AND",
            "value": [
                {"field": "updated_at", "operator": ">", "value": ts_start},
                {"field": "updated_at", "operator": "<", "value": ts_end},
                {"field": "team_assignee_id", "operator": "IN", "value": TARGET_TEAMS},
                {"field": "source.delivered_as", "operator": "=", "value": "customer_initiated"} 
            ]
        },
        "pagination": {"per_page": 150}
    }
    
    raw_data = fetch_search_results(query_unified, progresso, "🔎 Buscando Conversas de Clientes")
    
    progresso.progress(1.0, text="Classificando dados...")
    time.sleep(0.5)
    progresso.empty()

    # --- PROCESSAMENTO ---
    lista_inbound = []
    lista_csat = []
    todas_tags = [] # Lista para acumular as tags
    
    count_out_date_support = 0 
    
    for c in raw_data:
        # Dados
        c_created = c.get('created_at', 0)
        c_updated = c.get('updated_at', 0)
        team_id = int(c.get('team_assignee_id', 0) or 0)
        
        # --- 1. LÓGICA DE VOLUME ---
        is_valid_volume = False
        tipo_entrada = ""

        # CAIXA SUPORTE (2975006) -> Apenas Novos
        if team_id == ID_SUPORTE:
            if ts_start <= c_created <= ts_end:
                is_valid_volume = True
                tipo_entrada = "Inbound (Suporte)"
            else:
                count_out_date_support += 1

        # CAIXA CS/LEADS (1972225) -> Novos OU Movidos
        elif team_id == ID_CS_LEADS:
            is_valid_volume = True
            if ts_start <= c_created <= ts_end:
                tipo_entrada = "Inbound (Lead Novo)"
            else:
                tipo_entrada = "Lead Transferido/Movido"

        if is_valid_volume:
            dt_criacao = datetime.fromtimestamp(c_created, tz=FUSO_BR)
            aid = c.get('admin_assignee_id')
            nome_agente = admins.get(str(aid), "Sem Dono / Fila") if aid else "Sem Dono / Fila"
            
            # Coleta Tags
            tags_obj = c.get('tags', {}).get('tags', [])
            nomes_tags = [t['name'] for t in tags_obj]
            todas_tags.extend(nomes_tags) # Acumula para o gráfico
            
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

        # --- 2. LÓGICA DE CSAT ---
        rating_obj = c.get('conversation_rating', {})
        if rating_obj and rating_obj.get('rating'):
            r_created = rating_obj.get('created_at', 0)
            if ts_start <= r_created <= ts_end:
                lista_csat.append(c)

    # --- VISUALIZAÇÃO ---
    tab_vol, tab_csat_view = st.tabs(["📊 Volume & Tags", "⭐ Qualidade (CSAT)"])

    # ==========================================
    # ABA 1: VOLUME E TAGS
    # ==========================================
    with tab_vol:
        df = pd.DataFrame(lista_inbound)
        
        if not df.empty:
            total = len(df)
            suporte = len(df[df['Tipo'] == "Inbound (Suporte)"])
            leads = len(df[df['Tipo'].str.contains("Lead") | df['Tipo'].str.contains("Movido")])
            
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("📬 Total Recebido", total, help="Soma de Inbound User + Lead.")
            c2.metric("Suporte (2975006)", suporte)
            c3.metric("CS / Leads (1972225)", leads)
            c4.metric("Agentes Ativos", df[df['Agente'] != "Sem Dono / Fila"]['Agente'].nunique())
            
            st.divider()
            
            # Gráficos Linha 1
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
            
            # --- NOVO: GRÁFICO DE TAGS ---
            st.subheader("🏷️ Top Assuntos (Tags)")
            if todas_tags:
                contagem_tags = Counter(todas_tags)
                df_tags = pd.DataFrame(contagem_tags.items(), columns=['Tag', 'Qtd']).sort_values('Qtd', ascending=False).head(15)
                fig_tags = px.bar(
                    df_tags, x='Qtd', y='Tag', orientation='h', 
                    text='Qtd', color='Qtd', color_continuous_scale='Viridis'
                )
                fig_tags.update_layout(yaxis={'categoryorder':'total ascending'})
                st.plotly_chart(fig_tags, use_container_width=True)
            else:
                st.info("Nenhuma tag identificada nos tickets deste período.")

            st.divider()
            
            # --- TABELA COM FILTROS ---
            st.subheader("🔎 Detalhamento das Conversas")
            
            # Filtro de Agente
            agentes_disponiveis = df['Agente'].unique()
            filtro_agente = st.multiselect("Filtrar por Agente:", options=agentes_disponiveis, placeholder="Selecione um ou mais agentes...")
            
            # Aplica filtro
            df_exibicao = df.copy()
            if filtro_agente:
                df_exibicao = df_exibicao[df_exibicao['Agente'].isin(filtro_agente)]
            
            st.caption(f"Exibindo {len(df_exibicao)} conversas.")
            st.data_editor(
                df_exibicao.sort_values(by=['DataIso', 'Tipo']),
                column_config={
                    "Link": st.column_config.LinkColumn("Ticket", display_text="Abrir Conversa"),
                    "Tipo": st.column_config.TextColumn("Origem", width="medium"),
                    "DataIso": None
                },
                use_container_width=True, 
                hide_index=True
            )
        else:
            st.warning("Nenhuma conversa encontrada.")
            if count_out_date_support > 0:
                st.caption(f"ℹ️ {count_out_date_support} conversas antigas de suporte receberam mensagens, mas não contam como 'Novas'.")

    # ==========================================
    # ABA 2: CSAT
    # ==========================================
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
                    "Agente": admins.get(aid, "Desconhecido"),
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
                
                # --- TABELA CSAT COM FILTROS ---
                st.subheader("🔎 Avaliações Detalhadas")
                
                df_csat = pd.DataFrame(detalhes_csat)
                
                # Filtros
                col_f1, col_f2 = st.columns(2)
                with col_f1:
                    filtro_agente_csat = st.multiselect("Filtrar Agente:", df_csat['Agente'].unique(), key="f_agente_csat")
                with col_f2:
                    filtro_tipo_csat = st.multiselect("Filtrar Nota:", df_csat['Tipo'].unique(), key="f_tipo_csat")
                
                # Aplica
                df_view_csat = df_csat.copy()
                if filtro_agente_csat:
                    df_view_csat = df_view_csat[df_view_csat['Agente'].isin(filtro_agente_csat)]
                if filtro_tipo_csat:
                    df_view_csat = df_view_csat[df_view_csat['Tipo'].isin(filtro_tipo_csat)]
                
                st.data_editor(
                    df_view_csat,
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
