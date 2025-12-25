import streamlit as st
import requests
import pandas as pd
import time
from datetime import datetime, timezone, timedelta, time as dt_time

# --- Configurações Iniciais ---
# Aqui eu defino o título da página e o ícone que vai aparecer na aba do navegador.
st.set_page_config(page_title="Painel de Qualidade (CSAT)", page_icon="⭐", layout="wide")

# Aqui é onde eu tento pegar as senhas de acesso (Token e App ID).
# Se eu estiver rodando na nuvem (Streamlit Cloud), ele pega dos 'secrets'.
# Se eu estiver rodando no meu computador (local), ele cai no 'except' e usa o token de teste.
try:
    TOKEN = st.secrets["INTERCOM_TOKEN"]
    APP_ID = st.secrets["INTERCOM_APP_ID"]
except:
    TOKEN = "SEU_TOKEN_AQUI"
    APP_ID = "SEU_APP_ID_AQUI"

# ID do time que eu quero monitorar e o cabeçalho padrão pra toda chamada de API.
TEAM_ID = 2975006
headers = {"Authorization": f"Bearer {TOKEN}", "Accept": "application/json"}
FUSO_BR = timezone(timedelta(hours=-3))

# --- Minhas Funções (Onde a mágica acontece) ---

def get_admin_names():
    """
    Ninguém decora ID de agente, né? (tipo '12345').
    Então essa função vai lá no Intercom e busca a lista de todos os agentes.
    Eu crio um dicionário {ID: Nome} pra poder trocar os códigos pelos nomes reais depois.
    """
    try:
        r = requests.get("https://api.intercom.io/admins", headers=headers)
        # Se der tudo certo (200), eu monto o dicionário. Se der erro, devolvo vazio.
        return {a['id']: a['name'] for a in r.json().get('admins', [])} if r.status_code == 200 else {}
    except: return {}

def fetch_csat_data(start_ts, end_ts, progress_bar):
    """
    Essa é a função que vai buscar os dados brutos na API.
    O pulo do gato aqui é o seguinte: eu não busco pela data de CRIAÇÃO do ticket.
    Eu busco pela data de ATUALIZAÇÃO (updated_at).
    
    Por que? Porque um ticket pode ter sido criado mês passado, mas o cliente avaliou hoje.
    Se eu buscasse por criação, eu perderia essa avaliação. Buscando por atualização, eu pego tudo que mexeu.
    """
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
        "pagination": {"per_page": 150} # O Intercom só manda 150 por vez, então vou ter que paginar.
    }
    
    todas_conversas = []
    
    # Faço a primeira chamada pra ver se tem algo.
    r = requests.post(url, json=payload, headers=headers)
    if r.status_code != 200: return []
    
    data = r.json()
    total_registros = data.get('total_count', 0)
    todas_conversas.extend(data.get('conversations', []))
    
    if total_registros == 0:
        progress_bar.progress(100, text="Não achei nada nesse período.")
        return []

    # Aqui eu entro num loop (while) pra ir buscando as próximas páginas até acabar.
    while data.get('pages', {}).get('next'):
        # Atualizo a barrinha pro usuário não achar que travou
        percentual = min(len(todas_conversas) / total_registros, 0.95)
        progress_bar.progress(percentual, text=f"Baixando... ({len(todas_conversas)} de {total_registros})")
        
        # Pego o ID da próxima página
        payload['pagination']['starting_after'] = data['pages']['next']['starting_after']
        r = requests.post(url, json=payload, headers=headers)
        
        if r.status_code == 200:
            data = r.json()
            todas_conversas.extend(data.get('conversations', []))
        else: break
            
    progress_bar.progress(1.0, text="Pronto! Tudo baixado.")
    return todas_conversas

def process_stats(conversas, start_ts, end_ts, admins_map):
    """
    Aqui é onde eu separo o joio do trigo.
    Eu baixei um monte de conversa que foi 'atualizada', mas nem todas têm nota.
    E algumas podem ter nota antiga. Eu preciso filtrar tudo isso.
    """
    stats = {}
    details_list = []
    time_pos, time_neu, time_neg = 0, 0, 0
    
    for c in conversas:
        aid = str(c.get('admin_assignee_id'))
        
        # Se não tem dono ou se o cliente não avaliou, eu pulo fora.
        if not aid or not c.get('conversation_rating'): continue
        
        rating_obj = c['conversation_rating']
        nota = rating_obj.get('rating')
        if nota is None: continue
        
        data_nota = rating_obj.get('created_at')
        if not data_nota: continue
        
        # AQUI É IMPORTANTE: Eu confirmo se a NOTA foi dada dentro do período que selecionei.
        # Se o ticket atualizou hoje mas a nota é de 2023, eu ignoro.
        if not (start_ts <= data_nota <= end_ts): continue

        # Se é a primeira vez que vejo esse agente, crio os contadores dele zerados.
        if aid not in stats: stats[aid] = {'pos':0, 'neu':0, 'neg':0, 'total':0}
        stats[aid]['total'] += 1
        
        # Classifico a nota pra ficar bonitinho com emoji
        label_nota = ""
        if nota >= 4:
            stats[aid]['pos'] += 1; time_pos += 1; label_nota = "😍 Positiva"
        elif nota == 3:
            stats[aid]['neu'] += 1; time_neu += 1; label_nota = "😐 Neutra"
        else:
            stats[aid]['neg'] += 1; time_neg += 1; label_nota = "😡 Negativa"

        # Aqui eu monto a linha da tabela detalhada com tudo que preciso
        nome_agente = admins_map.get(aid, "Desconhecido")
        dt_evento = datetime.fromtimestamp(data_nota, tz=FUSO_BR).strftime("%d/%m %H:%M")
        comentario = rating_obj.get('remark', '-') # Se não tiver comentário, põe um tracinho
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
    # Retorno 3 coisas: Estatisticas do agente, do time inteiro, e a lista detalhada pra tabela.
    return stats, {'pos': time_pos, 'neu': time_neu, 'neg': time_neg, 'total': total_time}, details_list

# --- Interface Visual (Front-end) ---

st.title("⭐ Painel de Qualidade (CSAT)")
st.caption("Selecione o período para visualizar os indicadores de qualidade da equipe.")

# Uso um formulário pra página não ficar recarregando toda hora que eu mexo na data.
with st.form("filtro_csat"):
    col1, col2 = st.columns([3, 1])
    with col1:
        periodo = st.date_input(
            "📅 Qual período você quer analisar?",
            value=(datetime.now().replace(day=1), datetime.now()), # Padrão: inicio do mês até hoje
            format="DD/MM/YYYY"
        )
    with col2:
        st.write("") 
        st.write("")
        submit_btn = st.form_submit_button("🔄 Buscar Dados", type="primary", use_container_width=True)

# --- Lógica de Memória (Session State) ---
# Isso aqui é pra quando eu filtrar um agente na tabela, os dados não sumirem.
# Eu guardo tudo na memória do navegador ('session_state').

if submit_btn:
    # Ajusto o horário pra pegar o dia completo (de 00:00:00 até 23:59:59)
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
        
    status_holder = st.empty()
    progress_bar = st.progress(0, text="Conectando no Intercom...")
    
    # 1. Busco os nomes e os dados brutos
    admins = get_admin_names()
    raw_data = fetch_csat_data(ts_start, ts_end, progress_bar)
    
    time.sleep(0.5)
    progress_bar.empty()
    
    # 2. Processo tudo
    stats_agentes, stats_time, lista_detalhada = process_stats(raw_data, ts_start, ts_end, admins)
    
    # 3. SALVO NA MEMÓRIA! Assim não preciso buscar de novo se mexer num filtro.
    st.session_state['dados_csat'] = {
        'stats_agentes': stats_agentes,
        'stats_time': stats_time,
        'lista_detalhada': lista_detalhada
    }

# --- Exibição dos Dados ---
# Só mostro algo se já tiver dados carregados na memória.
if 'dados_csat' in st.session_state:
    dados = st.session_state['dados_csat']
    stats_time = dados['stats_time']
    stats_agentes = dados['stats_agentes']
    lista_detalhada = dados['lista_detalhada']
    
    # Calculando as porcentagens pro painel geral
    total_time_csat = stats_time['total']
    csat_real_time = (stats_time['pos'] / total_time_csat * 100) if total_time_csat > 0 else 0
    
    total_valid_time = stats_time['pos'] + stats_time['neg']
    csat_adjusted_time = (stats_time['pos'] / total_valid_time * 100) if total_valid_time > 0 else 0

    st.markdown("---")
    
    # Mostrando os números grandes (KPIs)
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("CSAT Geral (Real)", f"{csat_real_time:.1f}%", f"{total_time_csat} avaliações")
    c2.metric("CSAT Ajustado", f"{csat_adjusted_time:.1f}%", "Sem neutras") 
    c3.metric("😍 Positivas", stats_time['pos'])
    c4.metric("😐 Neutras", stats_time['neu'])
    c5.metric("😡 Negativas", stats_time['neg'])
    
    st.markdown("---")

    # --- Tabela Resumo (Agrupada por Agente) ---
    if lista_detalhada:
        df_det = pd.DataFrame(lista_detalhada)
        
        # Faço um agrupamento simples pra somar quantas notas cada um teve
        resumo = df_det.groupby('Agente').agg(
            Total=('Nota', 'count'),
            Positivas=('Nota', lambda x: (x >= 4).sum()),
            Neutras=('Nota', lambda x: (x == 3).sum()),
            Negativas=('Nota', lambda x: (x <= 2).sum())
        ).reset_index()
        
        # Calculo as porcentagens individuais
        resumo['CSAT Ajustado'] = resumo.apply(lambda row: (row['Positivas'] / (row['Positivas'] + row['Negativas']) * 100) if (row['Positivas'] + row['Negativas']) > 0 else 0, axis=1)
        resumo['CSAT Real'] = resumo.apply(lambda row: (row['Positivas'] / row['Total'] * 100) if row['Total'] > 0 else 0, axis=1)
        
        # Formato pra ficar com % bonitinho
        resumo['CSAT Ajustado'] = resumo['CSAT Ajustado'].map('{:.1f}%'.format)
        resumo['CSAT Real'] = resumo['CSAT Real'].map('{:.1f}%'.format)
        
        # Renomeio as colunas pra usar os emojis
        resumo = resumo.rename(columns={'Positivas': '😍', 'Neutras': '😐', 'Negativas': '😡', 'Total': 'Avaliações'})
        
        st.subheader("Resumo por Agente")
        cols_order = ["Agente", "CSAT (Ajustado)", "CSAT (Real)", "Avaliações", "😍", "😐", "😡"]
        st.dataframe(resumo, use_container_width=True, hide_index=True, column_order=cols_order)

    st.divider()

    # --- Tabela Detalhada com Filtros ---
    st.subheader("🔎 Detalhamento das Avaliações")

    if lista_detalhada:
        df_detalhe = pd.DataFrame(lista_detalhada)

        # Aqui crio o filtro. Como os dados tão na memória, posso filtrar sem recarregar a API.
        todos_agentes = sorted(df_detalhe['Agente'].unique())
        agentes_selecionados = st.multiselect(
            "Filtrar por Agente:", 
            options=todos_agentes,
            placeholder="Selecione um ou mais agentes..."
        )

        # Se selecionou alguém, filtro a tabela. Se não, mostro tudo.
        if agentes_selecionados:
            df_detalhe = df_detalhe[df_detalhe['Agente'].isin(agentes_selecionados)]

        st.caption(f"Mostrando {len(df_detalhe)} avaliações.")
        
        # Configuro a tabela pra ter link clicável e barra de nota
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
    # Mensagem que aparece quando abre o painel pela primeira vez
    st.info("👆 Selecione as datas lá em cima e clique em 'Buscar Dados' pra começar.")
