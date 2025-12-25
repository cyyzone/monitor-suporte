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

# IDs Específicos
TEAM_SUPORTE = 2975006
TEAM_CS_LEADS = 1972225
TARGET_TEAMS = [TEAM_SUPORTE, TEAM_CS_LEADS]

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

def fetch_search_results(payload, progress_bar, label_base):
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
            progress_bar.progress(pct, text=f"{label_base} ({len(results)} de {total})...")
            
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
st.markdown("Visão focada em **Novas Entradas (Inbound)** e **Leads Trabalhados**.")

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
    st.info("ℹ️ Excluindo tickets internos (Backoffice).")

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
    
    # -----------------------------------------------------
    # ESTRATÉGIA DE BUSCA "PENTE FINO"
    # -----------------------------------------------------
    # Buscamos TUDO que foi mexido (updated) no período nas caixas alvo.
    # Depois filtramos no Python para garantir precisão total.
    
    query_unified = {
        "query": {
            "operator": "AND",
            "value": [
                {"field": "updated_at", "operator": ">", "value": ts_start},
                {"field": "updated_at", "operator": "<", "value": ts_end},
                {"field": "team_assignee_id", "operator": "IN", "value": TARGET_TEAMS}
            ]
        },
        "pagination": {"per_page": 150}
    }
    
    raw_data = fetch_search_results(query_unified, progresso, "🔎 Analisando Conversas")
    
    progresso.progress(1.0, text="Aplicando filtros de negócio...")
    time.sleep(0.5)
    progresso.empty()

    # --- LISTAS FINAIS ---
    lista_inbound = []
    lista_csat = []
    
    count_ignored_admin = 0
    count_ignored_dates = 0
    
    for c in raw_data:
        # 1. FILTRO DE AUTOR (MATA BACKOFFICE/MANUAL)
        # Se quem começou foi 'admin', ignoramos totalmente.
        author_type = c.get('source', {}).get('author', {}).get('type')
        if author_type == 'admin':
            count_ignored_admin += 1
            continue

        # Dados Básicos
        c_created = c.get('created_at', 0)
        c_updated = c.get('updated_at', 0)
        team_id = int(c.get('team_assignee_id', 0) or 0)
        
        # 2. LÓGICA DE NEGÓCIO (O QUE ENTRA?)
        should_include = False
        status_label = ""
        
        # Regra A: Criado no Período (Normal Inbound)
        if ts_start <= c_created <= ts_end:
            should_include = True
            status_label = "🆕 Novo (Inbound)"
            
        # Regra B: Exceção CS/Leads (1972225)
        # Se não foi criado agora, MAS está na caixa de Leads e foi atualizado agora (atribuição manual)
        elif team_id == TEAM_CS_LEADS and (ts_start <= c_updated <= ts_end):
            should_include = True
            status_label = "🔄 Lead Transferido/Movido"
            
        else:
            count_ignored_dates += 1

        if should_include:
            dt_criacao = datetime.fromtimestamp(c_created, tz=FUSO_BR)
            aid = c.get('admin_assignee_id')
            nome_agente = admins.get(str(aid), "Sem Dono / Fila") if aid else "Sem Dono / Fila"
            tags = ", ".join([t['name'] for t in c.get('tags', {}).get('tags', [])])
            link_url = f"https://app.intercom.com/a/inbox/{APP_ID}/inbox/conversation/{c['id']}"
            
            lista_inbound.append({
                "DataIso": dt_criacao.date(),
                "Data Criação": dt_criacao.strftime("%d/%m %H:%M"),
                "Tipo": status_label,
                "Agente": nome_agente,
                "Tags": tags,
                "Link": link_url,
                "ID": c['id']
            })

        # 3. LÓGICA DE CSAT (SEPARADA)
        rating_obj = c.get('conversation_rating', {})
        if rating_obj and rating_obj.get('rating'):
            r_created = rating_obj.get('created_at', 0)
            if ts_start <= r_created <= ts_end:
                lista_csat.append(c)

    # --- VISUALIZAÇÃO ---
    tab_vol, tab_csat_view = st.tabs(["📊 Volume Real (Clientes)", "⭐ Qualidade (CSAT)"])

    with tab_vol:
        df = pd.DataFrame(lista_inbound)
        
        if not df.empty:
            total = len(df)
            novos = len(df[df['Tipo'].str.contains("Novo")])
            movidos = len(df[df['Tipo'].str.contains("Movido")])
            
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Volume Total (Clientes)", total, help="Apenas User/Lead. Ignora Backoffice.")
            c2.metric("🆕 Criados no Período", novos)
            c3.metric("🔄 Leads Puxados (CS)", movidos, help="Criados antes, mas trabalhados agora na caixa CS.")
            c4.metric("Agentes Ativos", df[df['Agente'] != "Sem Dono / Fila"]['Agente'].nunique())
            
            if count_ignored_admin > 0:
                st.caption(f"ℹ️ {count_ignored_admin} tickets de backoffice/manuais foram ocultados da contagem.")
            
            st.divider()
            
            # Gráficos
            g1, g2 = st.columns(2)
            with g1:
                st.subheader("📅 Entradas por Dia")
                # Agrupa pela data real
                vol_dia = df.groupby('DataIso').size().reset_index(name='Qtd')
                fig_dia = px.bar(vol_dia, x='DataIso', y='Qtd', text='Qtd', color='Qtd', color_continuous_scale='Blues')
                st.plotly_chart(fig_dia, use_container_width=True)
            
            with g2:
                st.subheader("🏆 Distribuição por Agente")
                vol_agente = df['Agente'].value_counts().reset_index()
                vol_agente.columns = ['Agente', 'Qtd']
                fig_ag = px.bar(vol_agente, x='Qtd', y='Agente', orientation='h', text='Qtd', color='Qtd', color_continuous_scale='Greens')
                fig_ag.update_layout(yaxis={'categoryorder':'total ascending'})
                st.plotly_chart(fig_ag, use_container_width=True)

            st.divider()
            with st.expander("🔎 Ver Lista Detalhada", expanded=True):
                st.data_editor(
                    df.sort_values(by=['DataIso', 'Tipo']),
                    column_config={
                        "Link": st.column_config.LinkColumn("Ticket", display_text="Abrir Conversa"),
                        "Tipo": st.column_config.TextColumn("Status", width="medium"),
                        "DataIso": None # Oculta coluna técnica
                    },
                    use_container_width=True, 
                    hide_index=True
                )
        else:
            st.warning("Nenhuma conversa de cliente encontrada nos critérios.")
            st.write(f"(Tickets ignorados por serem Backoffice/Admin: {count_ignored_admin})")

    with tab_csat_view:
        if lista_csat:
            stats = {}
            detalhes_csat = []
            
            # Processamento rápido CSAT
            time_pos, time_neu, time_neg = 0, 0, 0
            for c in lista_csat:
                aid = str(c.get('admin_assignee_id'))
                nota = c['conversation_rating']['rating']
                # Stats Agente
                if aid not in stats: stats[aid] = {'pos':0, 'neu':0, 'neg':0, 'total':0}
                stats[aid]['total'] += 1
                
                label_nota = ""
                if nota >= 4: 
                    stats[aid]['pos'] += 1; time_pos += 1; label_nota="😍 Positiva"
                elif nota == 3: 
                    stats[aid]['neu'] += 1; time_neu += 1; label_nota="😐 Neutra"
                else: 
                    stats[aid]['neg'] += 1; time_neg += 1; label_nota="😡 Negativa"
                
                # Lista Detalhada
                detalhes_csat.append({
                    "Data": datetime.fromtimestamp(c['conversation_rating']['created_at'], tz=FUSO_BR).strftime("%d/%m %H:%M"),
                    "Agente": admins.get(aid, "Desconhecido"),
                    "Nota": nota,
                    "Tipo": label_nota,
                    "Comentário": c['conversation_rating'].get('remark', '-'),
                    "Link": f"https://app.intercom.com/a/inbox/{APP_ID}/inbox/conversation/{c['id']}"
                })

            # KPIs
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
                st.subheader("🔎 Avaliações Detalhadas")
                st.data_editor(
                    pd.DataFrame(detalhes_csat),
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
