import streamlit as st
import requests
import pandas as pd
import time
from datetime import datetime, timezone, timedelta, time as dt_time

# --- Configs básicas pra rodar ---
st.set_page_config(page_title="Painel de Qualidade (CSAT)", page_icon="⭐", layout="wide")

# Tenta pegar as chaves. Se der ruim, usa o hardcoded.
try:
    TOKEN = st.secrets["INTERCOM_TOKEN"]
    APP_ID = st.secrets["INTERCOM_APP_ID"]
except:
    TOKEN = "SEU_TOKEN_AQUI"
    APP_ID = "SEU_APP_ID_AQUI"

TEAM_ID = 2975006
headers = {"Authorization": f"Bearer {TOKEN}", "Accept": "application/json"}
FUSO_BR = timezone(timedelta(hours=-3))

# --- Funções que buscam os dados ---

def get_admin_names():
    # Busca a lista de agentes pra gente trocar ID por Nome na tabela
    try:
        r = requests.get("https://api.intercom.io/admins", headers=headers)
        return {a['id']: a['name'] for a in r.json().get('admins', [])} if r.status_code == 200 else {}
    except: return {}

def fetch_csat_data(start_ts, end_ts, progress_bar, status_text):
    url = "https://api.intercom.io/conversations/search"
    
    # Busca por 'updated_at' para pegar tickets avaliados recentemente
    payload = {
        "query": {
            "operator": "AND",
            "value": [
                {"field": "updated_at", "operator": ">", "value": start_ts},
                {"field": "updated_at", "operator": "<", "value": end_ts},
                {"field": "team_assignee_id", "operator": "=", "value": TEAM_ID}
            ]
        },
        "pagination": {"per_page": 150}
    }
    
    todas_conversas = []
    
    r = requests.post(url, json=payload, headers=headers)
    if r.status_code != 200:
        return []
    
    data = r.json()
    total_registros = data.get('total_count', 0)
    todas_conversas.extend(data.get('conversations', []))
    
    if total_registros == 0:
        progress_bar.progress(100, text="Nenhum registro encontrado.")
        return []

    # Loop de paginação
    pages_processed = 1
    while data.get('pages', {}).get('next'):
        percentual = min(len(todas_conversas) / total_registros, 0.95)
        progress_bar.progress(percentual, text=f"Carregando dados... ({len(todas_conversas)} de {total_registros})")
        
        payload['pagination']['starting_after'] = data['pages']['next']['starting_after']
        r = requests.post(url, json=payload, headers=headers)
        
        if r.status_code == 200:
            data = r.json()
            todas_conversas.extend(data.get('conversations', []))
            pages_processed += 1
        else:
            break
            
    progress_bar.progress(1.0, text="Processamento concluído.")
    return todas_conversas

def process_stats(conversas, start_ts, end_ts, admins_map):
    stats = {}
    details_list = [] # Lista para guardar os detalhes linha a linha
    
    time_pos, time_neu, time_neg = 0, 0, 0
    
    for c in conversas:
        aid = str(c.get('admin_assignee_id'))
        
        if not aid or not c.get('conversation_rating'): continue
        
        rating_obj = c['conversation_rating']
        nota = rating_obj.get('rating')
        if nota is None: continue
        
        data_nota = rating_obj.get('created_at')
        if not data_nota: continue
        
        if not (start_ts <= data_nota <= end_ts):
            continue

        # --- Estatísticas Agregadas (Cards) ---
        if aid not in stats: stats[aid] = {'pos':0, 'neu':0, 'neg':0, 'total':0}
        stats[aid]['total'] += 1
        
        label_nota = ""
        if nota >= 4:
            stats[aid]['pos'] += 1; time_pos += 1; label_nota = "😍 Positiva"
        elif nota == 3:
            stats[aid]['neu'] += 1; time_neu += 1; label_nota = "😐 Neutra"
        else:
            stats[aid]['neg'] += 1; time_neg += 1; label_nota = "😡 Negativa"

        # --- Detalhamento (Tabela Nova) ---
        nome_agente = admins_map.get(aid, "Desconhecido")
        dt_evento = datetime.fromtimestamp(data_nota, tz=FUSO_BR).strftime("%d/%m %H:%M")
        comentario = rating_obj.get('remark', '-') # Pega o comentário se houver
        link_url = f"https://app.intercom.com/a/inbox/{APP_ID}/inbox/conversation/{c['id']}"
        
        details_list.append({
            "Data": dt_evento,
            "Agente": nome_agente,
            "Nota": nota,
            "Tipo": label_nota,
            "Comentário": comentario,
            "Link": link_url
        })
            
    total_time = time_pos + time_neu + time_neg
    
    # Retorna: Stats por agente, Stats do Time, Lista Detalhada
    return stats, {'pos': time_pos, 'neu': time_neu, 'neg': time_neg, 'total': total_time}, details_list

# --- Interface Visual ---
st.title("⭐ Painel de Qualidade (CSAT)")
st.caption("Selecione o período para visualizar os indicadores de qualidade da equipe.")

# Formulário pra segurar a execução.
with st.form("filtro_csat"):
    col1, col2 = st.columns([3, 1])
    
    with col1:
        periodo = st.date_input(
            "📅 Período de Análise:",
            value=(datetime.now().replace(day=1), datetime.now()), 
            format="DD/MM/YYYY"
        )
    
    with col2:
        st.write("") 
        st.write("")
        submit_btn = st.form_submit_button("🔄 Atualizar Dados", type="primary", use_container_width=True)

if submit_btn:
    # 1. Arruma os timestamps
    ts_start, ts_end = 0, 0
    if isinstance(periodo, tuple):
        if len(periodo) == 2:
            ts_start = int(datetime.combine(periodo[0], dt_time.min).timestamp())
            ts_end = int(datetime.combine(periodo[1], dt_time.max).timestamp())
        elif len(periodo) == 1:
            ts_start = int(datetime.combine(periodo[0], dt_time.min).timestamp())
            ts_end = int(datetime.combine(periodo[0], dt_time.max).timestamp())
    else:
        ts_start = int(datetime.combine(periodo, dt_time.min).timestamp())
        ts_end = int(datetime.combine(periodo, dt_time.max).timestamp())
        
    # 2. Busca Dados
    status_holder = st.empty()
    progress_bar = st.progress(0, text="Conectando ao servidor...")
    
    admins = get_admin_names()
    raw_conversations = fetch_csat_data(ts_start, ts_end, progress_bar, status_holder)
    
    time.sleep(0.5)
    progress_bar.empty()
    
    # 3. Processa
    # Agora recebemos 3 retornos: stats_agentes, stats_time e lista_detalhada
    stats_agentes, stats_time, lista_detalhada = process_stats(raw_conversations, ts_start, ts_end, admins)
    
    # --- Cards ---
    total_time_csat = stats_time['total']
    csat_real_time = (stats_time['pos'] / total_time_csat * 100) if total_time_csat > 0 else 0
    total_valid_time = stats_time['pos'] + stats_time['neg']
    csat_adjusted_time = (stats_time['pos'] / total_valid_time * 100) if total_valid_time > 0 else 0

    st.markdown("---")
    
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("CSAT Geral (Real)", f"{csat_real_time:.1f}%", f"{total_time_csat} avaliações")
    c2.metric("CSAT Ajustado (Time)", f"{csat_adjusted_time:.1f}%", "Exclui neutras") 
    c3.metric("😍 Positivas (4-5)", stats_time['pos'])
    c4.metric("😐 Neutras (3)", stats_time['neu'])
    c5.metric("😡 Negativas (1-2)", stats_time['neg'])
    
    st.markdown("---")

    # --- Tabela Resumo (Agentes) ---
    tabela = []
    for aid, s in stats_agentes.items():
        nome = admins.get(aid, "Desconhecido")
        valido = s['pos'] + s['neg']
        csat_ajustado = (s['pos'] / valido * 100) if valido > 0 else 0
        total_agente = s['total']
        csat_real = (s['pos'] / total_agente * 100) if total_agente > 0 else 0
        
        tabela.append({
            "Agente": nome,
            "CSAT (Ajustado)": f"{csat_ajustado:.1f}%",
            "CSAT (Real)": f"{csat_real:.1f}%", 
            "Avaliações": s['total'],
            "😍": s['pos'], "😐": s['neu'], "😡": s['neg']
        })

    if tabela:
        df = pd.DataFrame(tabela).sort_values("Avaliações", ascending=False)
        cols_order = ["Agente", "CSAT (Ajustado)", "CSAT (Real)", "Avaliações", "😍", "😐", "😡"]
        st.subheader("Resumo por Agente")
        st.dataframe(df, use_container_width=True, hide_index=True, column_order=cols_order)
    else:
        st.warning("Nenhuma avaliação encontrada para o período selecionado.")

    st.divider()

    # --- NOVA SEÇÃO: Detalhamento com Filtros ---
    st.subheader("🔎 Detalhamento das Avaliações")

    if lista_detalhada:
        df_detalhe = pd.DataFrame(lista_detalhada)

        # Filtro de Agente
        todos_agentes = df_detalhe['Agente'].unique()
        agentes_selecionados = st.multiselect(
            "Filtrar por Agente:", 
            options=todos_agentes,
            placeholder="Selecione um ou mais agentes..."
        )

        # Aplica o filtro se houver seleção
        if agentes_selecionados:
            df_detalhe = df_detalhe[df_detalhe['Agente'].isin(agentes_selecionados)]

        st.caption(f"Exibindo {len(df_detalhe)} avaliações.")
        
        # Exibe com link clicável
        st.data_editor(
            df_detalhe,
            column_config={
                "Link": st.column_config.LinkColumn(
                    "Ver Conversa", 
                    display_text="Abrir Ticket"
                ),
                "Nota": st.column_config.NumberColumn(
                    "Nota",
                    format="%d ⭐"
                ),
                "Comentário": st.column_config.TextColumn(
                    "Comentário do Cliente",
                    width="medium"
                )
            },
            use_container_width=True,
            hide_index=True
        )

    else:
        st.info("Não há dados detalhados para exibir.")

else:
    st.info("👆 Selecione o período acima e clique em 'Atualizar Dados' para gerar o relatório.")
