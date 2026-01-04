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

TEAM_IDS = [2975006, 1972225]  # IDs dos times que quero monitorar
FUSO_BR = timezone(timedelta(hours=-3)) # Fuso horario de Brasilia

# As Operárias (Funções de Busca)

@st.cache_data(ttl=60, show_spinner=False) # Cache de 60s e sem spinner pra nao incomodar a UI
def get_admin_names(): 
    """Busco os nomes dos admins pra nao mostrar so o ID feio (tipo '12345') na tela."""
    url = "https://api.intercom.io/admins"
    data = make_api_request("GET", url) # Mando o motoboy buscar.
    if data:
        # Aqui faço uma mágica chamada "Dict Comprehension".
        # Transformo a lista bagunçada em um dicionário simples: {ID: "Nome da Pessoa"}.
        # Assim, quando eu tiver o ID 123, eu troco por "Maria" instantaneamente.
        return {a['id']: a['name'] for a in data.get('admins', [])}
    return {}

# Cache de 60s e sem spinner pra nao incomodar a UI
@st.cache_data(ttl=60, show_spinner=False)
def fetch_csat_data(start_ts, end_ts):
    """
    Aqui é onde eu baixo as conversas. 
    Recebo a data de início e fim (em números/timestamp) e retorno a lista de conversas.
    """
    url = "https://api.intercom.io/conversations/search"
    # Monto o filtro da busca:
    # 1. Atualizado DEPOIS da data de início.
    # 2. Atualizado ANTES da data de fim.
    # 3. Pertence ao time TEAM_ID.
    payload = {
        "query": {
            "operator": "AND",
            "value": [
                {"field": "updated_at", "operator": ">", "value": start_ts},
                {"field": "updated_at", "operator": "<", "value": end_ts},
                {"field": "team_assignee_id", "operator": "=", "value": TEAM_ID}
            ]
        },
        "pagination": {"per_page": 150} # Peço pacotes grandes de 150 conversas.
    }
    
    conversas = [] # Minha sacola vazia.
    
    # 1. Primeira chamada pra ver se tem algo
    data = make_api_request("POST", url, json=payload) # Mando o motoboy buscar.
    if not data: return [] # Se der ruim, retorno vazio.
    
    total = data.get('total_count', 0) # Vejo quantas conversas tem no total.
    conversas.extend(data.get('conversations', [])) # Pego as primeiras conversas.
    
    # Se tiver mais que 150 conversas, o Intercom manda um token de "próxima página".
    if total > 0: # Se tiver algo pra pegar
        while data.get('pages', {}).get('next'): # Enquanto tiver próxima página
            time.sleep(0.2)  # Pequena pausa pra não bombardear a API
            # Pego o token da proxima pagina
            payload['pagination']['starting_after'] = data['pages']['next']['starting_after'] # Atualizo o payload
            data = make_api_request("POST", url, json=payload) # Mando o motoboy buscar de novo.
            
            if data: # Se veio algo, adiciono na sacola
                conversas.extend(data.get('conversations', [])) # Adiciono as conversas novas
            else:  # Se der ruim, paro o loop
                break # Quebro o loop se der ruim
            
    return conversas # Retorno tudo que peguei

def process_stats(conversas, start_ts, end_ts, admins_map): #
    """
    Essa função pega a sacola de conversas bruta e transforma em números bonitos (KPIs).
    Ela não precisa de cache porque rodar na memória do Python é muito rápido.
    Separo o que é positiva, neutra e negativa e monto a lista detalhada.
    """
    stats = {} # Estatísticas por agente
    details_list = [] # Lista detalhada de avaliações
    time_pos, time_neu, time_neg = 0, 0, 0 # Contadores do time todo
    
    for c in conversas: # Para cada conversa na sacola
        aid = str(c.get('admin_assignee_id')) # ID do agente (quem atendeu)
        
        # Filtro de Qualidade:
        # Se não tem dono (aid) OU não tem nota (conversation_rating), ignoro.
        if not aid or not c.get('conversation_rating'): continue
        
        rating_obj = c['conversation_rating'] # Objeto da avaliação
        nota = rating_obj.get('rating') # Nota numérica (1 a 5)
        if nota is None: continue # Sem nota numérica? Pulo.
        
        data_nota = rating_obj.get('created_at')
        if not data_nota: continue
        
        # TRUQUE IMPORTANTE:
        # A conversa pode ter sido atualizada hoje, mas a nota foi dada mês passado.
        # Aqui eu garanto que a NOTA foi dada dentro do período escolhido.
        if not (start_ts <= data_nota <= end_ts): continue
        # Inicializo o placar do agente se for a primeira vez que vejo ele.
        if aid not in stats: stats[aid] = {'pos':0, 'neu':0, 'neg':0, 'total':0} # Estatísticas iniciais
        stats[aid]['total'] += 1 # Incremento o total de avaliações do agente
        
        label_nota = "" # Rótulo da nota (Positiva, Neutra, Negativa)
        # Classifico a nota (Regra: 4 e 5 é bom, 3 é meh, resto é ruim)
        if nota >= 4: # Se a nota for 4 ou 5
            stats[aid]['pos'] += 1; time_pos += 1; label_nota = "😍 Positiva" 
        elif nota == 3: # Se a nota for 3
            stats[aid]['neu'] += 1; time_neu += 1; label_nota = "😐 Neutra" 
        else: # Se a nota for 1 ou 2
            stats[aid]['neg'] += 1; time_neg += 1; label_nota = "😡 Negativa"

        nome_agente = admins_map.get(aid, "Desconhecido") # Nome do agente ou "Desconhecido"
        dt_evento = datetime.fromtimestamp(data_nota, tz=FUSO_BR).strftime("%d/%m %H:%M") # Data formatada
        comentario = rating_obj.get('remark', '-') # Comentário do cliente ou "-"
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
            
    total_time = time_pos + time_neu + time_neg # Total geral do time
    return stats, {'pos': time_pos, 'neu': time_neu, 'neg': time_neg, 'total': total_time}, details_list # Retorno as estatísticas

# --- Interface Visual ---

st.title("⭐ Painel de Qualidade (CSAT)")
st.caption("Selecione o período para visualizar os indicadores de qualidade da equipe.")
# Crio um formulário pro filtro não rodar a cada clique, só quando apertar o botão.
with st.form("filtro_csat"):
    col1, col2 = st.columns([3, 1]) # Duas colunas: uma maior pro input, outra pro botão
    with col1:
        periodo = st.date_input( # Input de data. Padrão: do dia 1º desse mês até hoje.
            "📅 Período:",
            value=(datetime.now().replace(day=1), datetime.now()), # Valor padrão: mês atual
            format="DD/MM/YYYY"
        )
    with col2:
        # Espacinhos pra alinhar o botão com o input.
        st.write("") 
        st.write("")
        submit_btn = st.form_submit_button("🔄 Buscar Dados", type="primary", use_container_width=True)

if submit_btn:
    ts_start, ts_end = 0, 0
    # Ajuste de Datas: O date_input devolve só o dia (ex: 2023-10-01).
    # Aqui eu transformo em timestamp exato: 2023-10-01 00:00:00 até 2023-10-01 23:59:59.
    if isinstance(periodo, tuple): #Se selecionou início e fim...
        d_im = periodo[0] # Data inicial
        d_fm = periodo[1] if len(periodo) > 1 else periodo[0] # Data final
         # Converto pra timestamp com hora certa
        ts_start = int(datetime.combine(d_im, dt_time.min).timestamp()) # Início do dia
        ts_end = int(datetime.combine(d_fm, dt_time.max).timestamp()) # Fim do dia
    else: # Se selecionou só um dia...
        ts_start = int(datetime.combine(periodo, dt_time.min).timestamp()) # Início do dia
        ts_end = int(datetime.combine(periodo, dt_time.max).timestamp()) # Fim do dia
        
    status_holder = st.empty() # Placeholder pra status/progresso
    
   # Mostro um spinner rodando enquanto busco.
    with st.spinner("Buscando avaliações no Intercom..."):
        admins = get_admin_names()
        # Chamo a funcao otimizada sem passar a barra de progresso
        raw_data = fetch_csat_data(ts_start, ts_end) # Baixo os dados brutos.
    
    # Processo os dados em memoria (isso é rapido, nao precisa de cache)
    stats_agentes, stats_time, lista_detalhada = process_stats(raw_data, ts_start, ts_end, admins)
    
    #SALVO NA MEMÓRIA (Session State)
    # Isso é crucial! Se eu não salvar aqui, qualquer clique na tela faria os dados sumirem.
    st.session_state['dados_csat'] = { # Salvando tudo que preciso
        'stats_agentes': stats_agentes, # Estatísticas por agente
        'stats_time': stats_time, # Estatísticas do time todo
        'lista_detalhada': lista_detalhada # Lista detalhada de avaliações
    }

if 'dados_csat' in st.session_state: # Se já tenho dados na memória
    dados = st.session_state['dados_csat'] # Recupero os dados salvos
    stats_time = dados['stats_time'] # Estatísticas do time
    lista_detalhada = dados['lista_detalhada'] # Lista detalhada
    
    # Calculo das metricas gerais do time
    total_time_csat = stats_time['total']
    # CSAT Real: (Positivas / Total de Avaliações) * 100
    csat_real_time = (stats_time['pos'] / total_time_csat * 100) if total_time_csat > 0 else 0
    
    # CSAT Ajustado: (Positivas / (Positivas + Negativas)) * 100
    # Muita gente de CS prefere assim porque ignora quem votou "Neutro" (nem amou, nem odiou).
    total_valid_time = stats_time['pos'] + stats_time['neg']
    csat_adjusted_time = (stats_time['pos'] / total_valid_time * 100) if total_valid_time > 0 else 0

    st.markdown("---")
    # Mostro os cartões com os números grandes (Métricas).
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("CSAT Geral (Real)", f"{csat_real_time:.1f}%", f"{total_time_csat} avaliações")
    c2.metric("CSAT Ajustado", f"{csat_adjusted_time:.1f}%", "Sem neutras") 
    c3.metric("😍 Positivas", stats_time['pos'])
    c4.metric("😐 Neutras", stats_time['neu'])
    c5.metric("😡 Negativas", stats_time['neg'])
    
    st.markdown("---")
# --- TABELA DE RESUMO POR AGENTE ---
    if lista_detalhada: 
        df_det = pd.DataFrame(lista_detalhada)
        
        # Agrupamento Mágico:
        # Junto tudo por "Agente" e conto quantas notas cada tipo teve.
        resumo = df_det.groupby('Agente').agg(
            Total=('Nota', 'count'), # Total de avaliações
            Positivas=('Nota', lambda x: (x >= 4).sum()), # Notas 4 e 5 # Lambda é uma micro-função: conta se nota >= 4.
            Neutras=('Nota', lambda x: (x == 3).sum()), # Nota 3
            Negativas=('Nota', lambda x: (x <= 2).sum()) # Notas 1 e 2
        ).reset_index()
        
        # Calculo o CSAT individual de cada agente dentro da tabela.
        # Uso 'apply' para passar linha por linha fazendo a conta.
        resumo['CSAT Ajustado'] = resumo.apply(lambda row: (row['Positivas'] / (row['Positivas'] + row['Negativas']) * 100) if (row['Positivas'] + row['Negativas']) > 0 else 0, axis=1)
        resumo['CSAT Real'] = resumo.apply(lambda row: (row['Positivas'] / row['Total'] * 100) if row['Total'] > 0 else 0, axis=1)
        
        # Formato pra ficar bonito (ex: 95.5%).
        resumo['CSAT Ajustado'] = resumo['CSAT Ajustado'].map('{:.1f}%'.format)
        resumo['CSAT Real'] = resumo['CSAT Real'].map('{:.1f}%'.format)
        # Troco os nomes das colunas pra emojis.
        resumo = resumo.rename(columns={'Positivas': '😍', 'Neutras': '😐', 'Negativas': '😡', 'Total': 'Avaliações'})
        
        st.subheader("Resumo por Agente")
        cols_order = ["Agente", "CSAT (Ajustado)", "CSAT (Real)", "Avaliações", "😍", "😐", "😡"] # Defino a ordem das colunas.
        st.dataframe(resumo, use_container_width=True, hide_index=True, column_order=cols_order)

    st.divider()
# --- TABELA DE DETALHES (FILTRÁVEL) ---
    st.subheader("🔎 Detalhamento das Avaliações")

    if lista_detalhada:
        df_detalhe = pd.DataFrame(lista_detalhada)
# Crio um filtro multiselect pra  escolher quais agentes quer ver.
        todos_agentes = sorted(df_detalhe['Agente'].unique())
        agentes_selecionados = st.multiselect(
            "Filtrar por Agente:", 
            options=todos_agentes,
            placeholder="Selecione..."
        )

        if agentes_selecionados: # Se selecionou alguém, filtro a tabela.
            df_detalhe = df_detalhe[df_detalhe['Agente'].isin(agentes_selecionados)]

        st.caption(f"Mostrando {len(df_detalhe)} avaliações.")
        # st.data_editor é uma tabela interativa.
        # Aqui eu configuro as colunas especiais (Link clicável, Nota com estrela).
        st.data_editor(
            df_detalhe, # DataFrame com os dados
            column_config={ # Configurações especiais pras colunas
                "Link": st.column_config.LinkColumn("Ticket", display_text="Abrir"), # Coluna de link
                "Nota": st.column_config.NumberColumn("Nota", format="%d ⭐"), # Coluna de nota com estrela
                "Comentário": st.column_config.TextColumn("Obs. Cliente", width="medium") # Coluna de comentário com largura média
            },
            use_container_width=True, # Usa toda a largura disponível
            hide_index=True # Esconde o índice padrão
        )

else: # Se não tem dados na memória, peço pra buscar.
    st.info("👆 Selecione as datas lá em cima e clique em 'Buscar Dados' pra começar.")
