import streamlit as st
import requests
import pandas as pd
import plotly.express as px 
import time
from datetime import datetime, time as dt_time, timedelta, timezone
from collections import Counter

# --- Configs da Página ---
st.set_page_config(page_title="Relatório de Suporte (Unificado)", page_icon="📈", layout="wide")

# Credenciais
try:
    TOKEN = st.secrets["INTERCOM_TOKEN"]
    APP_ID = st.secrets["INTERCOM_APP_ID"]
except:
    TOKEN = "SEU_TOKEN_AQUI"
    APP_ID = "SEU_APP_ID_AQUI"

# CONFIGURAÇÃO DOS TIMES
TEAM_SUPORTE = 2975006
TEAM_CS_LEADS = 1972225
TARGET_TEAMS = [TEAM_SUPORTE, TEAM_CS_LEADS]

headers = {"Authorization": f"Bearer {TOKEN}", "Accept": "application/json"}
FUSO_BR = timezone(timedelta(hours=-3)) 

# ==========================================
# 1. FUNÇÕES DE COLETA ESPECIALIZADAS
# ==========================================

def get_admin_names():
    try:
        r = requests.get("https://api.intercom.io/admins", headers=headers)
        return {a['id']: a['name'] for a in r.json().get('admins', [])} if r.status_code == 200 else {}
    except: return {}

# Função Genérica de Paginação
def fetch_intercom_data(payload, progress_bar, label):
    url = "https://api.intercom.io/conversations/search"
    results = []
    
    r = requests.post(url, json=payload, headers=headers)
    if r.status_code != 200: return []
    
    data = r.json()
    total = data.get('total_count', 0)
    results.extend(data.get('conversations', []))
    
    if total > 0:
        while data.get('pages', {}).get('next'):
            # Barra de progresso visual
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
st.markdown("Visão segmentada: **Novos (Inbound)**, **Manuais (Outbound)** e **Leads/Transferidos**.")

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
    st.info(f"ℹ️ **Filtro Estrito:** Apenas IDs {TEAM_SUPORTE} e {TEAM_CS_LEADS}.")

if btn_gerar:
    # Ajuste de Datas
    if isinstance(periodo, tuple):
        d_inicio, d_fim = periodo[0], periodo[1] if len(periodo) > 1 else periodo[0]
    else:
        d_inicio = d_fim = periodo

    dt_start = datetime.combine(d_inicio, dt_time.min).replace(tzinfo=FUSO_BR)
    dt_end = datetime.combine(d_fim, dt_time.max).replace(tzinfo=FUSO_BR)
    ts_start, ts_end = int(dt_start.timestamp()), int(dt_end.timestamp())

    progresso = st.progress(0, text="Iniciando coletas separadas...")
    admins = get_admin_names()
    
    # ---------------------------------------------------------
    # BUSCA 1: TICKETS CRIADOS NO PERÍODO (Inbound + Manual)
    # ---------------------------------------------------------
    # Filtro: created_at no período E está nos times alvo.
    query_created = {
        "query": {
            "operator": "AND",
            "value": [
                {"field": "created_at", "operator": ">", "value": ts_start},
                {"field": "created_at", "operator": "<", "value": ts_end},
                {"field": "team_assignee_id", "operator": "IN", "value": TARGET_TEAMS}
            ]
        },
        "pagination": {"per_page": 150}
    }
    raw_created = fetch_intercom_data(query_created, progresso, "📥 Buscando Tickets Novos")
    
    # ---------------------------------------------------------
    # BUSCA 2: LEADS TRANSFERIDOS (Exceção CS/Lead)
    # ---------------------------------------------------------
    # Lógica: Tickets que foram ATUALIZADOS no período, estão na caixa 1972225, 
    # MAS foram criados ANTES do período (vieram de Presales/Outros).
    query_moved = {
        "query": {
            "operator": "AND",
            "value": [
                {"field": "updated_at", "operator": ">", "value": ts_start},
                {"field": "updated_at", "operator": "<", "value": ts_end},
                {"field": "created_at", "operator": "<", "value": ts_start}, # Criado ANTES
                {"field": "team_assignee_id", "operator": "=", "value": TEAM_CS_LEADS} # Só na caixa de Leads
            ]
        },
        "pagination": {"per_page": 150}
    }
    raw_moved = fetch_intercom_data(query_moved, progresso, "🔄 Buscando Transferências de Leads")

    # ---------------------------------------------------------
    # BUSCA 3: CSAT (Avaliações no Período)
    # ---------------------------------------------------------
    query_csat = {
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
    raw_csat = fetch_intercom_data(query_csat, progresso, "⭐ Buscando Avaliações")
    
    progresso.progress(1.0, text="Processando e separando...")
    time.sleep(0.5)
    progresso.empty()

    # --- PROCESSAMENTO DOS DADOS (SEPARAÇÃO NOS BALDES) ---
    
    lista_inbound = []  # Novos (Clientes)
    lista_manual = []   # Novos (Manuais)
    lista_moved = []    # Leads Transferidos
    
    # Processa CRIADOS (Busca 1)
    for c in raw_created:
        # Verifica Autor
        author_type = c.get('source', {}).get('author', {}).get('type')
        
        # Monta objeto limpo
        dt_criacao = datetime.fromtimestamp(c['created_at'], tz=FUSO_BR)
        aid = c.get('admin_assignee_id')
        nome_agente = admins.get(str(aid), "Sem Dono / Fila") if aid else "Sem Dono / Fila"
        link_url = f"https://app.intercom.com/a/inbox/{APP_ID}/inbox/conversation/{c['id']}"
        tags = ", ".join([t['name'] for t in c.get('tags', {}).get('tags', [])])
        
        item = {
            "DataIso": dt_criacao.date(),
            "Data": dt_criacao.strftime("%d/%m %H:%M"),
            "Agente": nome_agente,
            "Tags": tags,
            "Link": link_url,
            "ID": c['id'],
            "Origem": "Cliente (Inbound)" if author_type != "admin" else "Manual (Outbound)"
        }
        
        if author_type == "admin":
            lista_manual.append(item)
        else:
            lista_inbound.append(item)

    # Processa MOVIDOS (Busca 2)
    for c in raw_moved:
        dt_criacao = datetime.fromtimestamp(c['created_at'], tz=FUSO_BR)
        aid = c.get('admin_assignee_id')
        nome_agente = admins.get(str(aid), "Sem Dono / Fila") if aid else "Sem Dono / Fila"
        link_url = f"https://app.intercom.com/a/inbox/{APP_ID}/inbox/conversation/{c['id']}"
        tags = ", ".join([t['name'] for t in c.get('tags', {}).get('tags', [])])
        
        # Check duplo: Garante que não pegamos conversas "mortas" que só receberam nota
        # O ideal seria verificar se houve mensagem, mas updated_at + filtro de time já é um bom indício de movimentação recente
        
        item = {
            "Data Criação Orig": dt_criacao.strftime("%d/%m/%Y"), # Mostra que é antigo
            "Agente Atual": nome_agente,
            "Tags": tags,
            "Link": link_url,
            "ID": c['id'],
            "Origem": "Lead Transferido/Movido"
        }
        lista_moved.append(item)

    # Processa CSAT (Busca 3)
    data_csat_proc = []
    for c in raw_csat:
        rating_obj = c.get('conversation_rating', {})
        if rating_obj and rating_obj.get('rating'):
            # Filtro DATA DA NOTA
            r_created = rating_obj.get('created_at', 0)
            if ts_start <= r_created <= ts_end:
                data_csat_proc.append(c)


    # --- EXIBIÇÃO ---
    tab_vol, tab_csat_view = st.tabs(["📊 Volume (Novos, Manuais e Leads)", "⭐ Qualidade (CSAT)"])

    with tab_vol:
        # Métricas de Topo
        total_inbound = len(lista_inbound)
        total_manual = len(lista_manual)
        total_moved = len(lista_moved)
        
        c1, c2, c3 = st.columns(3)
        c1.metric("📬 Novos Tickets (Inbound)", total_inbound, help="Clientes que entraram em contato neste período.")
        c2.metric("✍️ Abertos Manualmente", total_manual, help="Tickets abertos pelos agentes (Outbound) neste período.")
        c3.metric("🔄 Leads Transferidos", total_moved, help="Tickets antigos (ex: Presales) que chegaram na caixa 1972225 neste período.")
        
        st.divider()
        
        # Tabelas Separadas para Clareza
        
        c_t1, c_t2 = st.columns(2)
        
        with c_t1:
            st.subheader("📬 Detalhe: Inbound (Clientes)")
            if lista_inbound:
                df_in = pd.DataFrame(lista_inbound)
                st.dataframe(
                    df_in[['Data', 'Agente', 'Tags', 'Link']], 
                    column_config={"Link": st.column_config.LinkColumn("Ticket", display_text="Abrir")},
                    use_container_width=True, hide_index=True, height=300
                )
            else:
                st.info("Sem tickets inbound no período.")
                
        with c_t2:
            st.subheader("✍️ Detalhe: Manuais (Agentes)")
            if lista_manual:
                df_man = pd.DataFrame(lista_manual)
                st.dataframe(
                    df_man[['Data', 'Agente', 'Tags', 'Link']], 
                    column_config={"Link": st.column_config.LinkColumn("Ticket", display_text="Abrir")},
                    use_container_width=True, hide_index=True, height=300
                )
            else:
                st.info("Sem tickets manuais no período.")

        st.divider()
        st.subheader(f"🔄 Leads/Tickets Transferidos (Caixa {TEAM_CS_LEADS})")
        st.caption("Tickets criados ANTES do período selecionado, mas que tiveram atividade/movimentação nesta caixa AGORA.")
        
        if lista_moved:
            df_mov = pd.DataFrame(lista_moved)
            st.dataframe(
                df_mov, 
                column_config={"Link": st.column_config.LinkColumn("Ticket", display_text="Abrir")},
                use_container_width=True, hide_index=True
            )
        else:
            st.info("Nenhum lead transferido/antigo movimentado encontrado.")


    with tab_csat_view:
        if data_csat_proc:
            stats = {}
            lista_detalhada_csat = [] 
            time_pos, time_neu, time_neg = 0, 0, 0
            
            for c in data_csat_proc:
                aid = str(c.get('admin_assignee_id'))
                rating_obj = c['conversation_rating']
                nota = rating_obj.get('rating')
                data_nota = rating_obj.get('created_at')

                if aid not in stats: stats[aid] = {'pos':0, 'neu':0, 'neg':0, 'total':0}
                stats[aid]['total'] += 1
                
                emoji_nota = ""
                if nota >= 4:
                    stats[aid]['pos'] += 1; time_pos += 1; emoji_nota = "😍 Positiva"
                elif nota == 3:
                    stats[aid]['neu'] += 1; time_neu += 1; emoji_nota = "😐 Neutra"
                else:
                    stats[aid]['neg'] += 1; time_neg += 1; emoji_nota = "😡 Negativa"
                
                nome_agente = admins.get(aid, "Desconhecido")
                dt_evento = datetime.fromtimestamp(data_nota, tz=FUSO_BR).strftime("%d/%m %H:%M")
                tags_str = ", ".join([t['name'] for t in c.get('tags', {}).get('tags', [])])
                comentario = rating_obj.get('remark', '-')
                link_url = f"https://app.intercom.com/a/inbox/{APP_ID}/inbox/conversation/{c['id']}"
                
                lista_detalhada_csat.append({
                    "Data": dt_evento, "Agente": nome_agente, "Nota": nota,
                    "Tipo": emoji_nota, "Tags": tags_str, "Comentário": comentario, "Link": link_url
                })

            total_time = time_pos + time_neu + time_neg
            
            if total_time > 0:
                csat_real = (time_pos / total_time * 100)
                total_valid = time_pos + time_neg
                csat_adj = (time_pos / total_valid * 100) if total_valid > 0 else 0
                
                c1, c2, c3, c4, c5 = st.columns(5)
                c1.metric("CSAT Geral", f"{csat_real:.1f}%", f"{total_time} avaliações")
                c2.metric("CSAT Ajustado", f"{csat_adj:.1f}%", "Sem neutras")
                c3.metric("😍 Positivas", time_pos)
                c4.metric("😐 Neutras", time_neu)
                c5.metric("😡 Negativas", time_neg)
                
                st.divider()
                
                tabela_agentes = []
                for aid, s in stats.items():
                    nome = admins.get(aid, "Desconhecido")
                    valido = s['pos'] + s['neg']
                    adj = (s['pos'] / valido * 100) if valido > 0 else 0
                    real = (s['pos'] / s['total'] * 100) if s['total'] > 0 else 0
                    tabela_agentes.append({
                        "Agente": nome, "CSAT (Ajustado)": f"{adj:.1f}%", "CSAT (Real)": f"{real:.1f}%",
                        "Total": s['total'], "😍": s['pos'], "😐": s['neu'], "😡": s['neg']
                    })
                
                df_resumo = pd.DataFrame(tabela_agentes).sort_values("Total", ascending=False)
                st.subheader("🏆 Performance por Agente")
                st.dataframe(df_resumo, use_container_width=True, hide_index=True)
                
                st.divider()
                st.subheader("🔎 Detalhamento dos Tickets")
                
                df_detalhe = pd.DataFrame(lista_detalhada_csat)
                st.data_editor(
                    df_detalhe,
                    column_config={
                        "Link": st.column_config.LinkColumn("Ticket", display_text="Abrir"),
                        "Nota": st.column_config.NumberColumn("Nota", format="%d ⭐")
                    }, use_container_width=True, hide_index=True
                )
        else:
            st.warning("Nenhuma avaliação encontrada.")
else:
    st.info("👈 Selecione as datas na barra lateral e clique em 'Gerar Relatório'.")
