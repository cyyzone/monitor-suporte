import streamlit as st
import requests
import pandas as pd
import time
from datetime import datetime, timezone, timedelta, time as dt_time

# --- Configs básicas ---
st.set_page_config(page_title="Painel de Qualidade (CSAT)", page_icon="⭐", layout="wide")

try:
    TOKEN = st.secrets["INTERCOM_TOKEN"]
    APP_ID = st.secrets["INTERCOM_APP_ID"]
except:
    TOKEN = "SEU_TOKEN_AQUI"
    APP_ID = "SEU_APP_ID_AQUI"

TEAM_ID = 2975006
headers = {"Authorization": f"Bearer {TOKEN}", "Accept": "application/json"}
FUSO_BR = timezone(timedelta(hours=-3))

# --- Funções ---

def get_admin_names():
    try:
        r = requests.get("https://api.intercom.io/admins", headers=headers)
        return {a['id']: a['name'] for a in r.json().get('admins', [])} if r.status_code == 200 else {}
    except: return {}

def fetch_csat_data(start_ts, end_ts, progress_bar):
    url = "https://api.intercom.io/conversations/search"
    
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
    if r.status_code != 200: return []
    
    data = r.json()
    total_registros = data.get('total_count', 0)
    todas_conversas.extend(data.get('conversations', []))
    
    if total_registros == 0:
        progress_bar.progress(100, text="Nenhum registro encontrado.")
        return []

    while data.get('pages', {}).get('next'):
        percentual = min(len(todas_conversas) / total_registros, 0.95)
        progress_bar.progress(percentual, text=f"Carregando... ({len(todas_conversas)} de {total_registros})")
        
        payload['pagination']['starting_after'] = data['pages']['next']['starting_after']
        r = requests.post(url, json=payload, headers=headers)
        
        if r.status_code == 200:
            data = r.json()
            todas_conversas.extend(data.get('conversations', []))
        else: break
            
    progress_bar.progress(1.0, text="Processamento concluído.")
    return todas_conversas

def process_stats(conversas, start_ts, end_ts, admins_map):
    stats = {}
    details_list = []
    time_pos, time_neu, time_neg = 0, 0, 0
    
    for c in conversas:
        aid = str(c.get('admin_assignee_id'))
        if not aid or not c.get('conversation_rating'): continue
        
        rating_obj = c['conversation_rating']
        nota = rating_obj.get('rating')
        if nota is None: continue
        
        data_nota = rating_obj.get('created_at')
        if not data_nota: continue
        
        # Filtro de Data da Nota
        if not (start_ts <= data_nota <= end_ts): continue

        # Stats
        if aid not in stats: stats[aid] = {'pos':0, 'neu':0, 'neg':0, 'total':0}
        stats[aid]['total'] += 1
        
        label_nota = ""
        if nota >= 4:
            stats[aid]['pos'] += 1; time_pos += 1; label_nota = "😍 Positiva"
        elif nota == 3:
            stats[aid]['neu'] += 1; time_neu += 1; label_nota = "😐 Neutra"
        else:
            stats[aid]['neg'] += 1; time_neg += 1; label_nota = "😡 Negativa"

        # Detalhes
        nome_agente = admins_map.get(aid, "Desconhecido")
        dt_evento = datetime.fromtimestamp(data_nota, tz=FUSO_BR).strftime("%d/%m %H:%M")
        comentario = rating_obj.get('remark', '-')
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
    return stats, {'pos': time_pos, 'neu': time_neu, 'neg': time_neg, 'total': total_time}, details_list

# --- Interface Visual ---
st.title("⭐ Painel de Qualidade (CSAT)")
st.caption("Selecione o período para visualizar os indicadores de qualidade da equipe.")

# Formulário
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

# LÓGICA DE PERSISTÊNCIA (SESSION STATE)
if submit_btn:
    # 1. Ajuste de Datas
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
        
    # 2. Busca e Salva no Session State
    status_holder = st.empty()
    progress_bar = st.progress(0, text="Conectando ao servidor...")
    
    admins = get_admin_names()
    raw_data = fetch_csat_data(ts_start, ts_end, progress_bar)
    
    time.sleep(0.5)
    progress_bar.empty()
    
    # Processa e guarda na memória
    stats_agentes, stats_time, lista_detalhada = process_stats(raw_data, ts_start, ts_end, admins)
    
    st.session_state['dados_csat'] = {
        'stats_agentes': stats_agentes,
        'stats_time': stats_time,
        'lista_detalhada': lista_detalhada
    }

# EXIBIÇÃO (Verifica se tem dados na memória)
if 'dados_csat' in st.session_state:
    dados = st.session_state['dados_csat']
    stats_time = dados['stats_time']
    stats_agentes = dados['stats_agentes']
    lista_detalhada = dados['lista_detalhada']
    
    # --- Cards ---
    total_time_csat = stats_time['total']
    csat_real_time = (stats_time['pos'] / total_time_csat * 100) if total_time_csat > 0 else 0
    total_valid_time = stats_time['pos'] + stats_time['neg']
    csat_adjusted_time = (stats_time['pos'] / total_valid_time * 100) if total_valid_time > 0 else 0

    st.markdown("---")
    
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("CSAT Geral (Real)", f"{csat_real_time:.1f}%", f"{total_time_csat} avaliações")
    c2.metric("CSAT Ajustado (Time)", f"{csat_adjusted_time:.1f}%", "Exclui neutras") 
    c3.metric("😍 Positivas", stats_time['pos'])
    c4.metric("😐 Neutras", stats_time['neu'])
    c5.metric("😡 Negativas", stats_time['neg'])
    
    st.markdown("---")

    # --- Tabela Resumo ---
    tabela = []
    for aid, s in stats_agentes.items():
        # Busca nome (pode precisar buscar de novo se recarregar a página, ou guardar nomes no state também)
        # Simplificação: Usando nome genérico ou buscando de novo se necessário. 
        # Idealmente o nome já vem processado.
        # Aqui, como processamos antes de salvar, os nomes não estão salvos. 
        # Vamos assumir que processamos o nome na lista detalhada, então vamos pegar de lá ou fazer lookup simples.
        # Mas para facilitar, vamos refazer o map se precisar, ou melhor:
        # A função process_stats já retornou dicionários prontos para uso, mas o nome do agente estava só na lista detalhada.
        # Pequeno ajuste: vamos pegar o nome da primeira ocorrência na lista detalhada se der.
        
        # Ajuste rápido: Recriar admin map é rápido.
        nome = "Agente" 
        # Procura nome na lista detalhada
        for item in lista_detalhada:
            # Isso é uma gambiarra leve, o ideal era salvar o admin_map no state, mas funciona.
            # O process_stats original já usava o map. Vamos apenas iterar o dicionário stats_agentes.
            pass

        # Recalcula CSATs
        valido = s['pos'] + s['neg']
        csat_ajustado = (s['pos'] / valido * 100) if valido > 0 else 0
        total_agente = s['total']
        csat_real = (s['pos'] / total_agente * 100) if total_agente > 0 else 0
        
        # Para pegar o nome correto, vamos varrer a lista detalhada filtrando por avaliações desse agente
        # (Ou fazemos uma chamada rápida de cache se os nomes sumirem, mas o streamlit deve manter se não reiniciarmos totalmente)
        # Na verdade, a lista `stats_agentes` tem o ID como chave. 
        # O jeito mais seguro sem chamar API de novo é olhar na `lista_detalhada`.
        
        nome_real = "Desconhecido"
        # Tenta achar um registro desse agente na lista
        # (Isso é computacionalmente barato para listas pequenas de dashboard)
        for det in lista_detalhada:
            # O process_stats não retornou o ID na lista detalhada, só o nome.
            # Então vamos confiar que o `stats_agentes` é a fonte da verdade numérica.
            # E vamos usar o `get_admin_names` novamente se precisar, mas ele tem cache interno do requests geralmente? Não.
            # Melhor: vamos salvar `admins_map` no session_state também na próxima vez.
            pass
            
    # Para corrigir o problema dos nomes sumindo no refresh sem chamar API de novo:
    # Vou refazer a estrutura da tabela resumo AGORA usando os dados da lista detalhada, que já tem nomes.
    
    if lista_detalhada:
        df_det = pd.DataFrame(lista_detalhada)
        # Agrupa por Nome do Agente
        resumo = df_det.groupby('Agente').agg(
            Total=('Nota', 'count'),
            Positivas=('Nota', lambda x: (x >= 4).sum()),
            Neutras=('Nota', lambda x: (x == 3).sum()),
            Negativas=('Nota', lambda x: (x <= 2).sum())
        ).reset_index()
        
        resumo['CSAT Ajustado'] = resumo.apply(lambda row: (row['Positivas'] / (row['Positivas'] + row['Negativas']) * 100) if (row['Positivas'] + row['Negativas']) > 0 else 0, axis=1)
        resumo['CSAT Real'] = resumo.apply(lambda row: (row['Positivas'] / row['Total'] * 100) if row['Total'] > 0 else 0, axis=1)
        
        # Formata
        resumo['CSAT Ajustado'] = resumo['CSAT Ajustado'].map('{:.1f}%'.format)
        resumo['CSAT Real'] = resumo['CSAT Real'].map('{:.1f}%'.format)
        
        # Renomeia colunas para ficar bonito (ícones)
        resumo = resumo.rename(columns={'Positivas': '😍', 'Neutras': '😐', 'Negativas': '😡', 'Total': 'Avaliações'})
        
        st.subheader("Resumo por Agente")
        cols_order = ["Agente", "CSAT (Ajustado)", "CSAT (Real)", "Avaliações", "😍", "😐", "😡"]
        st.dataframe(resumo, use_container_width=True, hide_index=True, column_order=cols_order)

    st.divider()

    # --- Detalhamento com Filtros (Onde dava o problema) ---
    st.subheader("🔎 Detalhamento das Avaliações")

    if lista_detalhada:
        df_detalhe = pd.DataFrame(lista_detalhada)

        # Filtro de Agente (Agora seguro pois os dados estão no state)
        todos_agentes = sorted(df_detalhe['Agente'].unique())
        agentes_selecionados = st.multiselect(
            "Filtrar por Agente:", 
            options=todos_agentes,
            placeholder="Selecione um ou mais agentes..."
        )

        # Aplica o filtro
        if agentes_selecionados:
            df_detalhe = df_detalhe[df_detalhe['Agente'].isin(agentes_selecionados)]

        st.caption(f"Exibindo {len(df_detalhe)} avaliações.")
        
        st.data_editor(
            df_detalhe,
            column_config={
                "Link": st.column_config.LinkColumn("Ver Conversa", display_text="Abrir Ticket"),
                "Nota": st.column_config.NumberColumn("Nota", format="%d ⭐"),
                "Comentário": st.column_config.TextColumn("Comentário", width="medium")
            },
            use_container_width=True,
            hide_index=True
        )

else:
    st.info("👆 Selecione o período acima e clique em 'Atualizar Dados' para gerar o relatório.")
