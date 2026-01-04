import streamlit as st
import pandas as pd
import time
from datetime import datetime, timezone, timedelta, time as dt_time
from utils import check_password, make_api_request

# --- Configurações Iniciais ---
st.set_page_config(page_title="Painel de Qualidade (CSAT)", page_icon="⭐", layout="wide")

# 🔒 BLOQUEIO DE SEGURANÇA
# Basico de seguranca: sem senha, nao passa daqui.
if not check_password():
    st.stop()

# 🔑 RECUPERAÇÃO DE SEGREDOS
# Pego o ID do app nos secrets. Se nao tiver la, aviso e paro tudo.
try:
    APP_ID = st.secrets["INTERCOM_APP_ID"]
except KeyError:
    st.error("❌ Erro: Configure 'INTERCOM_APP_ID' no arquivo .streamlit/secrets.toml")
    st.stop()

TEAM_IDS = [2975006, 1972225]
FUSO_BR = timezone(timedelta(hours=-3))

# --- Funções (Usando make_api_request) ---

@st.cache_data(ttl=60, show_spinner=False)
def get_admin_names():
    """Busco os nomes dos admins pra nao mostrar so o ID feio na tela."""
    url = "https://api.intercom.io/admins"
    data = make_api_request("GET", url)
    if data:
        # Faço um dicionario {id: nome} pra facilitar a busca depois
        return {a['id']: a['name'] for a in data.get('admins', [])}
    return {}

# Cache de 60s e sem spinner pra nao incomodar a UI
@st.cache_data(ttl=60, show_spinner=False)
def fetch_csat_data(start_ts, end_ts):
    """
    Aqui é onde eu baixo as conversas. 
    Tirei a barra de progresso daqui de dentro pro cache funcionar liso e nao dar erro de hash.
    """
    url = "https://api.intercom.io/conversations/search"
    payload = {
        "query": {
            "operator": "AND",
            "value": [
                {"field": "updated_at", "operator": ">", "value": start_ts},
                {"field": "updated_at", "operator": "<", "value": end_ts},
                {"field": "team_assignee_id", "operator": "IN", "value": TEAM_IDS}
            ]
        },
        "pagination": {"per_page": 150}
    }
    
    conversas = []
    
    # 1. Primeira chamada pra ver se tem algo
    data = make_api_request("POST", url, json=payload)
    if not data: return []
    
    total = data.get('total_count', 0)
    conversas.extend(data.get('conversations', []))
    
    # 2. Se tiver mais paginas, entro no loop pra baixar o resto
    if total > 0:
        while data.get('pages', {}).get('next'):
            # Pego o token da proxima pagina
            payload['pagination']['starting_after'] = data['pages']['next']['starting_after']
            data = make_api_request("POST", url, json=payload)
            
            if data:
                conversas.extend(data.get('conversations', []))
            else: 
                break
            
    return conversas

def process_stats(conversas, start_ts, end_ts, admins_map):
    """
    Essa funcao processa os dados brutos. 
    Separo o que é positiva, neutra e negativa e monto a lista detalhada.
    """
    stats = {}
    details_list = []
    time_pos, time_neu, time_neg = 0, 0, 0
    
    for c in conversas:
        aid = str(c.get('admin_assignee_id'))
        
        # Se nao tiver admin ou nota, pulo fora
        if not aid or not c.get('conversation_rating'): continue
        
        rating_obj = c['conversation_rating']
        nota = rating_obj.get('rating')
        if nota is None: continue
        
        data_nota = rating_obj.get('created_at')
        if not data_nota: continue
        
        # Garanto que a data da NOTA ta dentro do filtro (as vezes o ticket atualizou depois)
        if not (start_ts <= data_nota <= end_ts): continue

        if aid not in stats: stats[aid] = {'pos':0, 'neu':0, 'neg':0, 'total':0}
        stats[aid]['total'] += 1
        
        label_nota = ""
        # Classifico a nota (Regra: 4 e 5 é bom, 3 é meh, resto é ruim)
        if nota >= 4:
            stats[aid]['pos'] += 1; time_pos += 1; label_nota = "😍 Positiva"
        elif nota == 3:
            stats[aid]['neu'] += 1; time_neu += 1; label_nota = "😐 Neutra"
        else:
            stats[aid]['neg'] += 1; time_neg += 1; label_nota = "😡 Negativa"

        nome_agente = admins_map.get(aid, "Desconhecido")
        dt_evento = datetime.fromtimestamp(data_nota, tz=FUSO_BR).strftime("%d/%m %H:%M")
        comentario = rating_obj.get('remark', '-')
        link_url = f"https://app.intercom.com/a/inbox/{APP_ID}/inbox/conversation/{c['id']}"
        
        # Guardo tudo bonitinho pra tabela
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

with st.form("filtro_csat"):
    col1, col2 = st.columns([3, 1])
    with col1:
        periodo = st.date_input(
            "📅 Período:",
            value=(datetime.now().replace(day=1), datetime.now()),
            format="DD/MM/YYYY"
        )
    with col2:
        st.write("") 
        st.write("")
        submit_btn = st.form_submit_button("🔄 Buscar Dados", type="primary", use_container_width=True)

if submit_btn:
    ts_start, ts_end = 0, 0
    # Ajusto o timestamp pra pegar o dia inteiro (00:00 ate 23:59)
    if isinstance(periodo, tuple):
        d_im = periodo[0]
        d_fm = periodo[1] if len(periodo) > 1 else periodo[0]
        ts_start = int(datetime.combine(d_im, dt_time.min).timestamp())
        ts_end = int(datetime.combine(d_fm, dt_time.max).timestamp())
    else:
        ts_start = int(datetime.combine(periodo, dt_time.min).timestamp())
        ts_end = int(datetime.combine(periodo, dt_time.max).timestamp())
        
    status_holder = st.empty()
    
    # Tirei a progress bar visual daqui pq agora o processo é silencioso/cacheado
    # Se precisar de feedback visual, uso um spinner simples
    with st.spinner("Buscando avaliações no Intercom..."):
        admins = get_admin_names()
        # Chamo a funcao otimizada sem passar a barra de progresso
        raw_data = fetch_csat_data(ts_start, ts_end)
    
    # Processo os dados em memoria (isso é rapido, nao precisa de cache)
    stats_agentes, stats_time, lista_detalhada = process_stats(raw_data, ts_start, ts_end, admins)
    
    # Salvo no session_state pra nao perder se a tela recarregar
    st.session_state['dados_csat'] = {
        'stats_agentes': stats_agentes,
        'stats_time': stats_time,
        'lista_detalhada': lista_detalhada
    }

if 'dados_csat' in st.session_state:
    dados = st.session_state['dados_csat']
    stats_time = dados['stats_time']
    lista_detalhada = dados['lista_detalhada']
    
    # Calculo das metricas gerais do time
    total_time_csat = stats_time['total']
    csat_real_time = (stats_time['pos'] / total_time_csat * 100) if total_time_csat > 0 else 0
    
    # CSAT Ajustado ignora as neutras, o pessoal de CS gosta de ver assim
    total_valid_time = stats_time['pos'] + stats_time['neg']
    csat_adjusted_time = (stats_time['pos'] / total_valid_time * 100) if total_valid_time > 0 else 0

    st.markdown("---")
    
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("CSAT Geral (Real)", f"{csat_real_time:.1f}%", f"{total_time_csat} avaliações")
    c2.metric("CSAT Ajustado", f"{csat_adjusted_time:.1f}%", "Sem neutras") 
    c3.metric("😍 Positivas", stats_time['pos'])
    c4.metric("😐 Neutras", stats_time['neu'])
    c5.metric("😡 Negativas", stats_time['neg'])
    
    st.markdown("---")

    if lista_detalhada:
        df_det = pd.DataFrame(lista_detalhada)
        
        # Agrupo por agente pra fazer aquela tabela resumo bonita
        resumo = df_det.groupby('Agente').agg(
            Total=('Nota', 'count'),
            Positivas=('Nota', lambda x: (x >= 4).sum()),
            Neutras=('Nota', lambda x: (x == 3).sum()),
            Negativas=('Nota', lambda x: (x <= 2).sum())
        ).reset_index()
        
        # Recalculo o CSAT individual aqui
        resumo['CSAT Ajustado'] = resumo.apply(lambda row: (row['Positivas'] / (row['Positivas'] + row['Negativas']) * 100) if (row['Positivas'] + row['Negativas']) > 0 else 0, axis=1)
        resumo['CSAT Real'] = resumo.apply(lambda row: (row['Positivas'] / row['Total'] * 100) if row['Total'] > 0 else 0, axis=1)
        
        # Formato pra porcentagem
        resumo['CSAT Ajustado'] = resumo['CSAT Ajustado'].map('{:.1f}%'.format)
        resumo['CSAT Real'] = resumo['CSAT Real'].map('{:.1f}%'.format)
        
        resumo = resumo.rename(columns={'Positivas': '😍', 'Neutras': '😐', 'Negativas': '😡', 'Total': 'Avaliações'})
        
        st.subheader("Resumo por Agente")
        cols_order = ["Agente", "CSAT (Ajustado)", "CSAT (Real)", "Avaliações", "😍", "😐", "😡"]
        st.dataframe(resumo, use_container_width=True, hide_index=True, column_order=cols_order)

    st.divider()

    st.subheader("🔎 Detalhamento das Avaliações")

    if lista_detalhada:
        df_detalhe = pd.DataFrame(lista_detalhada)

        todos_agentes = sorted(df_detalhe['Agente'].unique())
        agentes_selecionados = st.multiselect(
            "Filtrar por Agente:", 
            options=todos_agentes,
            placeholder="Selecione..."
        )

        if agentes_selecionados:
            df_detalhe = df_detalhe[df_detalhe['Agente'].isin(agentes_selecionados)]

        st.caption(f"Mostrando {len(df_detalhe)} avaliações.")
        
        st.data_editor(
            df_detalhe,
            column_config={
                "Link": st.column_config.LinkColumn("Ticket", display_text="Abrir"),
                "Nota": st.column_config.NumberColumn("Nota", format="%d ⭐"),
                "Comentário": st.column_config.TextColumn("Obs. Cliente", width="medium")
            },
            use_container_width=True,
            hide_index=True
        )

else:
    st.info("👆 Selecione as datas lá em cima e clique em 'Buscar Dados' pra começar.")
