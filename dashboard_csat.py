import streamlit as st
import requests
import pandas as pd
import time
from datetime import datetime, timezone, timedelta, time as dt_time

# --- CONFIGURAÇÕES ---
st.set_page_config(page_title="Painel de Qualidade (CSAT)", page_icon="⭐", layout="wide")

# Tenta pegar dos secrets, senão usa string vazia
try:
    TOKEN = st.secrets["INTERCOM_TOKEN"]
except:
    TOKEN = "SEU_TOKEN_AQUI"

TEAM_ID = 2975006
headers = {"Authorization": f"Bearer {TOKEN}", "Accept": "application/json"}

# --- FUNÇÕES ---

def get_admin_names():
    try:
        r = requests.get("https://api.intercom.io/admins", headers=headers)
        return {a['id']: a['name'] for a in r.json().get('admins', [])} if r.status_code == 200 else {}
    except: return {}

def fetch_csat_data(start_ts, end_ts, progress_bar, status_text):
    url = "https://api.intercom.io/conversations/search"
    
    # 1. Filtro: Conversas atualizadas no período (para pegar avaliações recentes em tickets velhos)
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
    
    # Primeira chamada para pegar o total (para a barra de progresso)
    r = requests.post(url, json=payload, headers=headers)
    if r.status_code != 200:
        return []
    
    data = r.json()
    total_registros = data.get('total_count', 0)
    todas_conversas.extend(data.get('conversations', []))
    
    # Se não tem nada, retorna
    if total_registros == 0:
        progress_bar.progress(100, text="Nenhum registro encontrado.")
        return []

    # Loop de Paginação
    pages_processed = 1
    while data.get('pages', {}).get('next'):
        # Atualiza Barra de Progresso (Estimativa baseada em páginas ou total carregado)
        percentual = min(len(todas_conversas) / total_registros, 0.95)
        progress_bar.progress(percentual, text=f"Baixando dados... ({len(todas_conversas)} de {total_registros})")
        
        payload['pagination']['starting_after'] = data['pages']['next']['starting_after']
        r = requests.post(url, json=payload, headers=headers)
        
        if r.status_code == 200:
            data = r.json()
            todas_conversas.extend(data.get('conversations', []))
            pages_processed += 1
        else:
            break
            
    progress_bar.progress(1.0, text="Processamento concluído!")
    return todas_conversas

def process_stats(conversas, start_ts, end_ts):
    stats = {}
    time_pos, time_neu, time_neg = 0, 0, 0
    
    for c in conversas:
        aid = str(c.get('admin_assignee_id'))
        
        # Ignora se não tem dono ou não tem avaliação
        if not aid or not c.get('conversation_rating'): continue
        
        rating_obj = c['conversation_rating']
        nota = rating_obj.get('rating')
        if nota is None: continue
        
        # FILTRO CRUCIAL: A avaliação (não o ticket) deve ter sido feita no período selecionado
        data_nota = rating_obj.get('created_at')
        if not data_nota: continue
        
        if not (start_ts <= data_nota <= end_ts):
            continue

        # Inicializa contador do agente
        if aid not in stats: stats[aid] = {'pos':0, 'neu':0, 'neg':0, 'total':0}
        
        stats[aid]['total'] += 1
        
        if nota >= 4:
            stats[aid]['pos'] += 1
            time_pos += 1
        elif nota == 3:
            stats[aid]['neu'] += 1
            time_neu += 1
        else:
            stats[aid]['neg'] += 1
            time_neg += 1
            
    total_time = time_pos + time_neu + time_neg
    return stats, {'pos': time_pos, 'neu': time_neu, 'neg': time_neg, 'total': total_time}

# --- INTERFACE ---
st.title("⭐ Painel de Qualidade (CSAT)")
st.caption("Filtre por data para visualizar a performance da equipe.")

# --- FORMULÁRIO (BLOQUEIO DE EXECUÇÃO) ---
with st.form("filtro_csat"):
    col1, col2 = st.columns([3, 1])
    
    with col1:
        # Seletor de Data Flexível
        periodo = st.date_input(
            "📅 Período de Análise:",
            value=(datetime.now().replace(day=1), datetime.now()), # Padrão: Começo do mês até hoje
            format="DD/MM/YYYY"
        )
    
    with col2:
        st.write("") # Espaçador visual
        st.write("")
        submit_btn = st.form_submit_button("🔄 Atualizar Dados", type="primary", use_container_width=True)

# --- LÓGICA DE EXECUÇÃO ---
if submit_btn:
    # 1. Tratamento de Datas (Início e Fim do dia)
    ts_start, ts_end = 0, 0
    if isinstance(periodo, tuple):
        if len(periodo) == 2:
            ts_start = int(datetime.combine(periodo[0], dt_time.min).timestamp())
            ts_end = int(datetime.combine(periodo[1], dt_time.max).timestamp())
        elif len(periodo) == 1:
            ts_start = int(datetime.combine(periodo[0], dt_time.min).timestamp())
            ts_end = int(datetime.combine(periodo[0], dt_time.max).timestamp())
    else:
        # Fallback para versão antiga do streamlit se retornar data única
        ts_start = int(datetime.combine(periodo, dt_time.min).timestamp())
        ts_end = int(datetime.combine(periodo, dt_time.max).timestamp())
        
    # 2. Busca e Progresso
    status_holder = st.empty()
    progress_bar = st.progress(0, text="Iniciando conexão...")
    
    admins = get_admin_names()
    raw_conversations = fetch_csat_data(ts_start, ts_end, progress_bar, status_holder)
    
    # Limpa barra após carregar
    time.sleep(0.5)
    progress_bar.empty()
    
    # 3. Processamento
    stats_agentes, stats_time = process_stats(raw_conversations, ts_start, ts_end)
    
    # --- RESULTADOS ---
    
    # Métricas do Time
    total_time_csat = stats_time['total']
    # CSAT Geral Padrão (Positivas / Total)
    csat_time = (stats_time['pos'] / total_time_csat * 100) if total_time_csat > 0 else 0

    st.markdown("---")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("CSAT Geral (Time)", f"{csat_time:.1f}%", f"{total_time_csat} avaliações")
    c2.metric("😍 Positivas (4-5)", stats_time['pos'])
    c3.metric("😐 Neutras (3)", stats_time['neu'])
    c4.metric("😡 Negativas (1-2)", stats_time['neg'])
    
    st.markdown("---")

    # Tabela Detalhada
    tabela = []
    for aid, s in stats_agentes.items():
        nome = admins.get(aid, "Desconhecido")
        
        # Cálculo 1: CSAT Ajustado (Ignora Neutras) -> (Pos / (Pos+Neg))
        valido = s['pos'] + s['neg']
        csat_ajustado = (s['pos'] / valido * 100) if valido > 0 else 0
        
        # Cálculo 2: CSAT Real (Considera Neutras) -> (Pos / Total)
        total_agente = s['total']
        csat_real = (s['pos'] / total_agente * 100) if total_agente > 0 else 0
        
        tabela.append({
            "Agente": nome,
            "CSAT (Ajustado)": f"{csat_ajustado:.1f}%",
            "CSAT (Real)": f"{csat_real:.1f}%", # Coluna solicitada
            "Avaliações": s['total'],
            "😍": s['pos'],
            "😐": s['neu'],
            "😡": s['neg']
        })

    if tabela:
        df = pd.DataFrame(tabela).sort_values("Avaliações", ascending=False)
        
        # Ordenação visual das colunas
        cols_order = ["Agente", "CSAT (Ajustado)", "CSAT (Real)", "Avaliações", "😍", "😐", "😡"]
        
        st.subheader("Detalhamento por Agente")
        st.dataframe(df, use_container_width=True, hide_index=True, column_order=cols_order)
    else:
        st.warning("⚠️ Nenhuma avaliação encontrada no período selecionado.")
        
    st.caption("""
    ℹ️ **Legenda:**
    * **CSAT (Ajustado):** Considera apenas opiniões polarizadas (Positivas vs Negativas). Ignora as neutras.
    * **CSAT (Real):** Percentual de clientes satisfeitos sobre o TOTAL de atendimentos (Positivas / Tudo).
    """)

else:
    # Mensagem inicial antes de clicar no botão
    st.info("👆 Selecione um período acima e clique em 'Atualizar Dados' para gerar o relatório.")
