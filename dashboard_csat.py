import streamlit as st
import requests
import pandas as pd
import time
from datetime import datetime, timezone, timedelta, time as dt_time

# --- Configs básicas pra rodar ---
st.set_page_config(page_title="Painel de Qualidade (CSAT)", page_icon="⭐", layout="wide")

# Tenta pegar o token dos secrets. Se der ruim, usa o hardcoded.
try:
    TOKEN = st.secrets["INTERCOM_TOKEN"]
except:
    TOKEN = "SEU_TOKEN_AQUI"

TEAM_ID = 2975006
headers = {"Authorization": f"Bearer {TOKEN}", "Accept": "application/json"}

# --- Funções que buscam os dados ---

def get_admin_names():
    # Busca a lista de agentes pra gente trocar ID por Nome na tabela
    try:
        r = requests.get("https://api.intercom.io/admins", headers=headers)
        return {a['id']: a['name'] for a in r.json().get('admins', [])} if r.status_code == 200 else {}
    except: return {}

def fetch_csat_data(start_ts, end_ts, progress_bar, status_text):
    url = "https://api.intercom.io/conversations/search"
    
    # O pulo do gato aqui: busco por 'updated_at'. 
    # Assim garanto que pego tickets velhos que receberam nota agora.
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
    
    # Faço a primeira chamada só pra ver o tamanho da lista (total_count)
    r = requests.post(url, json=payload, headers=headers)
    if r.status_code != 200:
        return []
    
    data = r.json()
    total_registros = data.get('total_count', 0)
    todas_conversas.extend(data.get('conversations', []))
    
    # Se não tem nada, já aviso e saio
    if total_registros == 0:
        progress_bar.progress(100, text="Nenhum registro encontrado.")
        return []

    # Loop pra ir paginando (o Intercom entrega de 150 em 150)
    pages_processed = 1
    while data.get('pages', {}).get('next'):
        # Atualiza a barrinha pro usuário ver que tá rodando
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

def process_stats(conversas, start_ts, end_ts):
    stats = {}
    time_pos, time_neu, time_neg = 0, 0, 0
    
    for c in conversas:
        aid = str(c.get('admin_assignee_id'))
        
        # Se não tem dono ou não tem nota, nem perde tempo
        if not aid or not c.get('conversation_rating'): continue
        
        rating_obj = c['conversation_rating']
        nota = rating_obj.get('rating')
        if nota is None: continue
        
        # Filtro importante: A nota TEM que ter sido dada dentro do período selecionado.
        data_nota = rating_obj.get('created_at')
        if not data_nota: continue
        
        if not (start_ts <= data_nota <= end_ts):
            continue

        # Cria o dicionário do agente se for a primeira vez que ele aparece
        if aid not in stats: stats[aid] = {'pos':0, 'neu':0, 'neg':0, 'total':0}
        
        stats[aid]['total'] += 1
        
        # Classifica a nota (1-5)
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

# --- Interface Visual ---
st.title("⭐ Painel de Qualidade (CSAT)")
st.caption("Selecione o período para visualizar os indicadores de qualidade da equipe.")

# Formulário pra segurar a execução.
with st.form("filtro_csat"):
    col1, col2 = st.columns([3, 1])
    
    with col1:
        # Seletor de data
        periodo = st.date_input(
            "📅 Período de Análise:",
            value=(datetime.now().replace(day=1), datetime.now()), # Padrão: inicio do mês até hoje
            format="DD/MM/YYYY"
        )
    
    with col2:
        st.write("") 
        st.write("")
        # Botão de ação
        submit_btn = st.form_submit_button("🔄 Atualizar Dados", type="primary", use_container_width=True)

# Se clicou no botão, executa a lógica
if submit_btn:
    # 1. Arruma os timestamps (garante o dia inteiro, de 00:00 até 23:59)
    ts_start, ts_end = 0, 0
    if isinstance(periodo, tuple):
        if len(periodo) == 2:
            ts_start = int(datetime.combine(periodo[0], dt_time.min).timestamp())
            ts_end = int(datetime.combine(periodo[1], dt_time.max).timestamp())
        elif len(periodo) == 1:
            # Caso selecione apenas um dia
            ts_start = int(datetime.combine(periodo[0], dt_time.min).timestamp())
            ts_end = int(datetime.combine(periodo[0], dt_time.max).timestamp())
    else:
        # Fallback de segurança
        ts_start = int(datetime.combine(periodo, dt_time.min).timestamp())
        ts_end = int(datetime.combine(periodo, dt_time.max).timestamp())
        
    # 2. Chama as funções de busca
    status_holder = st.empty()
    progress_bar = st.progress(0, text="Conectando ao servidor...")
    
    admins = get_admin_names()
    raw_conversations = fetch_csat_data(ts_start, ts_end, progress_bar, status_holder)
    
    # Limpa a barra
    time.sleep(0.5)
    progress_bar.empty()
    
    # 3. Calcula as estatísticas
    stats_agentes, stats_time = process_stats(raw_conversations, ts_start, ts_end)
    
    # --- Monta os Indicadores (Cards) ---
    
    # CSAT Geral Real (Considerando as neutras)
    total_time_csat = stats_time['total']
    csat_real_time = (stats_time['pos'] / total_time_csat * 100) if total_time_csat > 0 else 0

    # CSAT Ajustado do Time (Sem as neutras)
    total_valid_time = stats_time['pos'] + stats_time['neg']
    csat_adjusted_time = (stats_time['pos'] / total_valid_time * 100) if total_valid_time > 0 else 0

    st.markdown("---")
    
    # 5 Colunas para os indicadores
    c1, c2, c3, c4, c5 = st.columns(5)
    
    c1.metric("CSAT Geral (Real)", f"{csat_real_time:.1f}%", f"{total_time_csat} avaliações")
    c2.metric("CSAT Ajustado (Time)", f"{csat_adjusted_time:.1f}%", "Exclui neutras") 
    c3.metric("😍 Positivas (4-5)", stats_time['pos'])
    c4.metric("😐 Neutras (3)", stats_time['neu'])
    c5.metric("😡 Negativas (1-2)", stats_time['neg'])
    
    st.markdown("---")

    # Monta a Tabela Detalhada
    tabela = []
    for aid, s in stats_agentes.items():
        nome = admins.get(aid, "Desconhecido")
        
        # Cálculo 1: CSAT Ajustado (Agente) - Ignora Neutras
        valido = s['pos'] + s['neg']
        csat_ajustado = (s['pos'] / valido * 100) if valido > 0 else 0
        
        # Cálculo 2: CSAT Real (Agente) - Considera tudo
        total_agente = s['total']
        csat_real = (s['pos'] / total_agente * 100) if total_agente > 0 else 0
        
        tabela.append({
            "Agente": nome,
            "CSAT (Ajustado)": f"{csat_ajustado:.1f}%",
            "CSAT (Real)": f"{csat_real:.1f}%", 
            "Avaliações": s['total'],
            "😍": s['pos'],
            "😐": s['neu'],
            "😡": s['neg']
        })

    if tabela:
        df = pd.DataFrame(tabela).sort_values("Avaliações", ascending=False)
        
        # Organiza as colunas na ordem de visualização
        cols_order = ["Agente", "CSAT (Ajustado)", "CSAT (Real)", "Avaliações", "😍", "😐", "😡"]
        
        st.subheader("Detalhamento por Agente")
        st.dataframe(df, use_container_width=True, hide_index=True, column_order=cols_order)
    else:
        st.warning("Nenhuma avaliação encontrada para o período selecionado.")
        
    st.caption("""
    ℹ️ **Legenda:**
    * **CSAT Ajustado:** Considera apenas avaliações Positivas e Negativas (exclui Neutras do cálculo).
    * **CSAT Real:** Representa o percentual de clientes satisfeitos em relação ao total de atendimentos (inclui Neutras).
    """)

else:
    # Mensagem de espera inicial
    st.info("👆 Selecione o período acima e clique em 'Atualizar Dados' para gerar o relatório.")
