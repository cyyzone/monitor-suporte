import streamlit as st # O nosso "pedreiro" digital que constrói o site.
import pandas as pd # Biblioteca poderosa para manipulação de dados em tabelas.
import time # Para lidar com tempos e pausas.
import re # O "faxineiro" (Regex). Ele limpa textos sujos cheios de códigos estranhos.
from datetime import datetime, timezone, timedelta # A nossa "agenda" pra lidar com datas e fusos.
import os # Para verificar se o arquivo existe
import json # Para salvar o horário bonitinho

# Em vez de copiar e colar código, eu puxo as funções prontas do arquivo 'utils.py'.
# É como ter um assistente pessoal que já sabe checar senha e fazer API requests.
from utils import check_password, make_api_request, send_slack_alert 

# Defino o nome da aba no navegador e o ícone. Layout "wide" pra usar a tela toda.
st.set_page_config(page_title="Monitor Operacional", page_icon="🚀", layout="wide")
# Chamo o porteiro (função importada). Se não tiver a senha certa, o código PARA aqui.
if not check_password():
    st.stop()
# Tento pegar o ID do App no cofre secreto (.streamlit/secrets.toml).
try:
    APP_ID = st.secrets["INTERCOM_APP_ID"]
except KeyError:
    st.error("❌ Erro Crítico: 'INTERCOM_APP_ID' não encontrado no secrets.toml")
    st.stop()

TEAM_ID = 2975006 # ID do time de suporte no Intercom
META_AGENTES = 4 # Meta mínima de agentes online
FUSO_BR = timezone(timedelta(hours=-3)) # Fuso horário de Brasília (UTC-3)

# --- Funções de Busca (Mantidas iguais) ---
#Aqui usei o @st.cache_data pra não gastar API do Intercom à toa. O Python memoriza o resultado por 60 segundos (ttl=60).
@st.cache_data(ttl=60, show_spinner=False)
def get_admin_details(): # Pega detalhes dos admins (nome, away)
    url = "https://api.intercom.io/admins" 
    data = make_api_request("GET", url)
    dados = {}
    if data:
        for admin in data.get('admins', []): # Crio um dicionário (lista inteligente) com ID, Nome e se está "Ausente" (Away).
            dados[admin['id']] = {
                'name': admin['name'],
                'is_away': admin.get('away_mode_enabled', False)
            }
    return dados

@st.cache_data(ttl=60, show_spinner=False)
def get_team_members(team_id):
    url = f"https://api.intercom.io/teams/{team_id}" # Pergunto pro Intercom quem faz parte do time X.
    data = make_api_request("GET", url)
    if data: return data.get('admin_ids', []) # Retorno só a lista de IDs.
    return []

@st.cache_data(ttl=60, show_spinner=False)
def count_conversations(admin_id, state): # Essa função conta quantos tickets um agente tem num estado específico (ex: 'open').
    url = "https://api.intercom.io/conversations/search"
    payload = { # Monto o filtro: "Estado IGUAL a X" E "Agente IGUAL a Y".
        "query": {
            "operator": "AND",
            "value": [
                {"field": "state", "operator": "=", "value": state},
                {"field": "admin_assignee_id", "operator": "=", "value": admin_id}
            ]
        }
    }
    data = make_api_request("POST", url, json=payload)
    if data: return data.get('total_count', 0) # Retorno só o número total.
    return 0

@st.cache_data(ttl=60, show_spinner=False)
def get_team_queue_details(team_id):
    # Busco tickets que estão "open" no time, mas SEM agente (admin_assignee_id é nulo).
    # Isso significa que o cliente está esperando alguém pegar esse ticket.
    url = "https://api.intercom.io/conversations/search"
    payload = {
        "query": {
            "operator": "AND",
            "value": [
                {"field": "state", "operator": "=", "value": "open"},
                {"field": "team_assignee_id", "operator": "=", "value": team_id}
            ]
        },
        "pagination": {"per_page": 60}
    }
    data = make_api_request("POST", url, json=payload)
    detalhes_fila = [] # Retorno a lista desses tickets orfãos.
    if data:
        for conv in data.get('conversations', []):
            if conv.get('admin_assignee_id') is None:
                detalhes_fila.append({'id': conv['id']})
    return detalhes_fila

@st.cache_data(ttl=60, show_spinner=False)
def get_daily_stats(team_id, ts_inicio, minutos_recente=30): # Essa função é a mais inteligente. Ela calcula TUDO numa viagem só pra economizar API.
    url = "https://api.intercom.io/conversations/search"
    ts_corte_recente = int(time.time()) - (minutos_recente * 60) # Defino o corte de tempo: "Agora menos 30 minutos".

    payload = { # Monto o filtro: "Criado DEPOIS de X" E "Time IGUAL a Y".
        "query": {
            "operator": "AND",
            "value": [
                {"field": "created_at", "operator": ">", "value": ts_inicio},
                {"field": "team_assignee_id", "operator": "=", "value": team_id}
            ]
        },
        "pagination": {"per_page": 150} # Pego até 150 tickets pra garantir que pego tudo no período.
    }
    
    data = make_api_request("POST", url, json=payload) # Faço a requisição.
    
    stats_periodo = {} # Dicionários para guardar as estatísticas.
    stats_30min = {} # Estatísticas dos últimos 30 minutos.
    detalhes_por_agente = {}  # Detalhes dos tickets por agente.
    total_periodo = 0 # Total no período.
    total_recente = 0 # Total nos últimos 30 minutos.
    
    if data:
        conversas = data.get('conversations', []) # Pego a lista de conversas/tickets retornados.
        total_periodo = len(conversas) # Conto o total de tickets no período.
        for conv in conversas:  # Para cada conversa/ticket:
            aid = str(conv.get('admin_assignee_id')) if conv.get('admin_assignee_id') else "FILA" # Pego o ID do agente (ou "FILA" se não tiver).
            stats_periodo[aid] = stats_periodo.get(aid, 0) + 1 # Contabilizo no total do período.
            
            if aid not in detalhes_por_agente: detalhes_por_agente[aid] = [] # Inicializo a lista se não existir.
            
            detalhes_por_agente[aid].append({ # Guardo os detalhes do ticket.
                'id': conv['id'], # ID do ticket
                'created_at': conv['created_at'], # Timestamp de criação
                'link': f"https://app.intercom.com/a/inbox/{APP_ID}/inbox/conversation/{conv['id']}" # Link direto pro ticket
            })
            
            if conv['created_at'] > ts_corte_recente: # Se o ticket foi criado nos últimos 30 minutos:
                stats_30min[aid] = stats_30min.get(aid, 0) + 1 # Contabilizo no total recente.
                total_recente += 1 # Incremento o total recente.
                
    return total_periodo, total_recente, stats_periodo, stats_30min, detalhes_por_agente # Retorno tudo.

@st.cache_data(ttl=60, show_spinner=False) 
def get_latest_conversations(team_id, ts_inicio, limit=10): # Pega as últimas conversas/tickets criados no time.
    url = "https://api.intercom.io/conversations/search" # Endpoint de busca de conversas.
    payload = { # Filtro: "Criado DEPOIS de X" E "Time IGUAL a Y".
        "query": { # Monta o filtro de busca
            "operator": "AND", # Combina as condições
            "value": [ # Condições do filtro
                {"field": "created_at", "operator": ">", "value": ts_inicio}, # Criado depois do timestamp inicial
                {"field": "team_assignee_id", "operator": "=", "value": team_id} # Pertence ao time específico
            ]
        },
        "sort": { "field": "created_at", "order": "descending" }, # Ordena do mais recente para o mais antigo
        "pagination": {"per_page": limit} # Limita o número de resultados retornados
    }
    data = make_api_request("POST", url, json=payload) # Faz a requisição à API
    if data: return data.get('conversations', []) # Retorna a lista de conversas
    return []

# @st.fragment faz esse pedaço rodar sozinho a cada 60s sem piscar a tela inteira.
@st.fragment(run_every=60)
def atualizar_painel(): # Função principal que atualiza o painel.
    st.title("🚀 Monitor Operacional (Tempo Real)") #

    # --- MEMÓRIA DO ALERTA ---
    # Crio uma anotação na memória pra saber quando mandei o último Slack.
    # Assim não viro spammer mandando alerta a cada minuto.
    if "ultimo_alerta_ts" not in st.session_state: 
        st.session_state["ultimo_alerta_ts"] = 0 # Inicializo com zero (nunca mandei alerta).

    col_filtro, _ = st.columns([1, 3]) # Filtro de período (Hoje ou 48h)
    with col_filtro: 
        periodo_selecionado = st.radio(
            "📅 Período de Análise:", 
            ["Hoje (Desde 00:00)", "Últimas 48h"], 
            horizontal=True
        )

    st.markdown("---")

    now = datetime.now(FUSO_BR) # Defino o timestamp de início baseado na escolha (Meia-noite de hoje ou 48h atrás).
    if "Hoje" in periodo_selecionado: # Se escolheu "Hoje"
        ts_inicio = int(now.replace(hour=0, minute=0, second=0).timestamp())   # Timestamp de meia-noite de hoje
        texto_volume = "Volume (Dia / 30min)" # Texto do card muda conforme o período
    else: # Se escolheu "Últimas 48h"
        ts_inicio = int((now - timedelta(hours=48)).timestamp()) # Timestamp de 48h atrás
        texto_volume = "Volume (48h / 30min)" # Texto do card muda conforme o período

    # Mando minhas operárias (funções lá de cima) buscarem tudo.
    ids_time = get_team_members(TEAM_ID) # IDs dos agentes do time
    admins = get_admin_details() # Detalhes dos admins (nome, away)
    fila = get_team_queue_details(TEAM_ID) # Tickets na fila (sem dono)
    vol_periodo, vol_rec, stats_periodo, stats_rec, detalhes_agente = get_daily_stats(TEAM_ID, ts_inicio) # Estatísticas gerais
    ultimas = get_latest_conversations(TEAM_ID, ts_inicio, 10) # Últimas 10 conversas criadas
    # --- PROCESSAMENTO (O Julgamento) ---
    online = 0 # Contador de agentes online
    tabela = [] # Tabela que vai pro DataFrame
    
    lista_sobrecarga = [] # Lista negra de quem tá atolado
    lista_alta_demanda = [] # Lista de quem tá "on fire"
    
    for mid in ids_time: # Passo por cada membro do time...
        sid = str(mid) # ID como string pra facilitar o acesso no dicionário 
        info = admins.get(sid, {'name': f'ID {sid}', 'is_away': True}) # Pego os detalhes (ou coloco um genérico se não achar)
        
        if not info['is_away']: online += 1
        emoji = "🔴" if info['is_away'] else "🟢" # Defino o emoji: 🟢 Online ou 🔴 Ausente.
        
        abertos = count_conversations(mid, 'open') # Conto quantos tickets abertos o agente tem
        pausados = count_conversations(mid, 'snoozed') # Conto quantos tickets pausados o agente tem
        volume_recente = stats_rec.get(sid, 0) # Pego o volume recente (últimos 30min)
        
        # Regras de Alerta Visual:
        alerta = "⚠️" if abertos >= 5 else "" # 5+ tickets abertos? Perigo!
        raio = "⚡" if volume_recente >= 3 else "" # 3+ tickets em 30min? Tá com fila!
        
        # Se bateu nos limites, anoto o nome dele na lista negra pra mandar pro Slack.
        if abertos >= 5: # Sobrecarga Individual
            lista_sobrecarga.append(f"{info['name']} ({abertos})") # Nome + número de abertos
            
        if volume_recente >= 3: # Alta Demanda Recente
            lista_alta_demanda.append(f"{info['name']} ({volume_recente})") # Nome + número recente
        # Adiciono na tabela que vai aparecer na tela.
        tabela.append({
            "Status": emoji,
            "Agente": info['name'],
            "Abertos": f"{abertos} {alerta}",
            "Volume Período": stats_periodo.get(sid, 0),
            "Recente (30m)": f"{volume_recente} {raio}",
            "Pausados": pausados
        })
    # Ordeno a tabela pra ficar bonitinha (Alfabética e depois por Status).
    tabela = sorted(tabela, key=lambda x: x['Agente'])
    tabela = sorted(tabela, key=lambda x: x['Status'], reverse=True)

 # --- O FOFOQUEIRO (Slack Alert) ---
    msg_alerta = []
    
    # 1. Tem cliente na fila? É CRÍTICO! 🔥
    if len(fila) > 0:
        msg_alerta.append(f"🔥 *CRÍTICO:* Existem *{len(fila)} clientes* aguardando na fila!")
    
    # 2. Pouca gente online (Meta nao batida)
    if online < META_AGENTES:
        msg_alerta.append(f"⚠️ *ATENÇÃO:* Equipe abaixo da meta! Apenas *{online}/{META_AGENTES}* online.")

    # 3. Tem gente sobrecarregada? (Uso a lista que criei ali em cima)
    if lista_sobrecarga:
        nomes = ", ".join(lista_sobrecarga)
        msg_alerta.append(f"⚠️ *SOBRECARGA:* Agentes com 5+ tickets: {nomes}")

    # 4. Tem gente na correria?
    if lista_alta_demanda:
        nomes = ", ".join(lista_alta_demanda)
        msg_alerta.append(f"⚡ *ALTA DEMANDA:* Agentes a todo vapor (3+ em 30m): {nomes}")

    # --- O FOFOQUEIRO INTELIGENTE (Slack Alert com Arquivo) ---
    # Defino quem é o nosso "Mural de Avisos".
    ARQUIVO_CONTROLE = "ultimo_alerta.json" 
    TEMPO_RESFRIAMENTO = 600 # 10 minutos de paz.
    agora = time.time()
    
    # 1. TENTO LER O MURAL (Se ele existir)
    ultimo_envio_geral = 0
    if os.path.exists(ARQUIVO_CONTROLE):
        try:
            with open(ARQUIVO_CONTROLE, "r") as f:
                # O json.load traduz o texto do arquivo pra um dicionário Python.
                dados = json.load(f)
                ultimo_envio_geral = dados.get("timestamp", 0)
        except:
            # Se o arquivo estiver corrompido ou travado, eu ignoro e sigo a vida.
            pass 

    # 2. A HORA DA VERDADE
    # Tem mensagem? E (Agora - Última vez que alguém gritou) > 10 min?
    if msg_alerta and (agora - ultimo_envio_geral > TEMPO_RESFRIAMENTO):
        
        texto_final = "*🚨 Alerta Monitor Suporte*\n" + "\n".join(msg_alerta)
        
        # Mando o motoboy entregar!
        send_slack_alert(texto_final)
        
        # 3. ATUALIZO O MURAL
        # Escrevo no arquivo: "Gente, acabei de mandar alerta às 14:00!"
        # Assim, se outra pessoa estiver com o painel aberto, ela vai ler isso e não vai mandar de novo.
        try:
            with open(ARQUIVO_CONTROLE, "w") as f:
                json.dump({"timestamp": agora}, f)
        except Exception as e:
            print(f"Erro ao salvar arquivo de controle: {e}")
            
        st.toast("🔔 Alerta enviado para o Slack!", icon="📨")
    # ----------------------------------

    # --- VISUALIZAÇÃO (O que aparece na tela) ---
    c1, c2, c3, c4 = st.columns(4) # Crio 4 cards no topo com as métricas principais.
    c1.metric("Fila de Espera", len(fila), "Aguardando", delta_color="inverse") # Número de clientes na fila
    c2.metric(texto_volume, f"{vol_periodo} / {vol_rec}") # Volume no período e nos últimos 30min
    c3.metric("Agentes Online", online, f"Meta: {META_AGENTES}") # Agentes online vs meta
    c4.metric("Atualizado", datetime.now(FUSO_BR).strftime("%H:%M:%S")) # Hora da última atualização
    # Aviso gigante vermelho se tiver fila de espera.
    if len(fila) > 0: # Mostro o alerta de fila se tiver gente esperando.
        st.error("🔥 **CRÍTICO: Clientes aguardando na fila!**")
        links_md = "" # Crio links diretos pros tickets na fila.
        for item in fila: # Para cada ticket na fila...
            c_id = item['id'] # Pego o ID
            link = f"https://app.intercom.com/a/inbox/{APP_ID}/inbox/conversation/{c_id}" # Crio o link
            links_md += f"[Abrir Ticket #{c_id}]({link}) &nbsp;&nbsp; " # Adiciono ao markdown
        st.markdown(links_md, unsafe_allow_html=True) # Mostro os links na tela.
    # Aviso amarelo se a meta de agentes online não for batida.

    if online < META_AGENTES:
        st.warning(f"⚠️ **Atenção:** Equipe abaixo da meta!")

    st.markdown("---") # Divisor visual

    c_left, c_right = st.columns([2, 1]) # Divido a tela: Tabela da Equipe (Esq) e Últimos Tickets (Dir)

    with c_left: # Mostro a tabela de performance
        st.subheader("Performance da Equipe") # Título da seção
        st.dataframe( # DataFrame interativo
            pd.DataFrame(tabela),  # Dados da tabela
            use_container_width=True,  # Usa toda a largura disponível
            hide_index=True, # Esconde o índice
            column_order=["Status", "Agente", "Abertos", "Volume Período", "Recente (30m)", "Pausados"] # Ordem das colunas
        )
        
        st.markdown("---")
        st.subheader("🕵️ Detalhe dos Tickets por Agente") # Título da seção
        
        if len(ids_time) > 0: # Se tem agentes no time...
            cols = st.columns(3) # Crio 3 colunas pra distribuir os agentes
            ordem_nomes = [t['Agente'] for t in tabela] # Ordem dos nomes conforme a tabela acima
            
            ids_time_ordenados = sorted(ids_time, key=lambda mid: # Ordeno os IDs conforme a ordem dos nomes na tabela
                ordem_nomes.index(admins.get(str(mid), {}).get('name', '')) # Pego o índice do nome na lista de ordem
                if admins.get(str(mid), {}).get('name', '') in ordem_nomes else 999 # Se não achar, joga pro fim
            )

            for i, mid in enumerate(ids_time_ordenados): # Para cada membro do time...
                sid = str(mid) # ID como string
                nome = admins.get(sid, {}).get('name', 'Desconhecido') # Pego o nome
                tickets = detalhes_agente.get(sid, []) # Pego os tickets desse agente
                
                with cols[i % 3]: # Distribuo em 3 colunas
                    with st.expander(f"{nome} ({len(tickets)})"): # Expansível com o nome e número de tickets
                        if not tickets: # Se não tiver tickets...
                            st.caption("Sem tickets no período.") # Mostro mensagem
                        else:
                            tickets_sorted = sorted(tickets, key=lambda x: x['created_at'], reverse=True) # Ordeno os tickets por data (mais recentes primeiro)
                            for t in tickets_sorted: # Para cada ticket...
                                hora = datetime.fromtimestamp(t['created_at'], tz=FUSO_BR).strftime('%H:%M') # Formato da hora
                                st.markdown(f"⏰ **{hora}** - [Abrir #{t['id']}]({t['link']})") # Mostro a hora e o link pro ticket
        else:
            st.info("Nenhum agente encontrado no time.")

    with c_right: # Mostro as últimas atribuições
        st.subheader("Últimas Atribuições")
        hist_dados = [] # Lista pra guardar os dados formatados
        for conv in ultimas: # Para cada conversa/ticket...
            dt_obj = datetime.fromtimestamp(conv['created_at'], tz=FUSO_BR) # Converto o timestamp pra data/hora
            hora_fmt = dt_obj.strftime('%d/%m %H:%M') # Formato bonito de data/hora
            
            adm_id = conv.get('admin_assignee_id') # Pego o ID do agente atribuído
            nome_agente = "Sem Dono" # Padrão se não tiver dono
            if adm_id: # Se tiver dono, pego o nome
                nome_agente = admins.get(str(adm_id), {}).get('name', 'Desconhecido') # Nome do agente
            
            subject = conv.get('source', {}).get('subject', '') # Pego o assunto do ticket
            if not subject: # Se não tiver assunto, tento extrair do corpo
                body = conv.get('source', {}).get('body', '')
                # Aqui eu limpo o texto do ticket porque ele vem cheio de HTML feio.
                # O 're.sub' remove tudo que é <tag> e deixa só o texto.
                clean_body = re.sub(r'<[^>]+>', ' ', body).strip()
                if not clean_body and ('<img' in body or '<figure' in body):
                    subject = "📷 [Imagem/Anexo]"
                elif not clean_body:
                    subject = "(Sem texto)"
                else:
                    subject = clean_body[:60] + "..." if len(clean_body) > 60 else clean_body
            
            c_id = conv['id']
            link = f"https://app.intercom.com/a/inbox/{APP_ID}/inbox/conversation/{c_id}"
            
            hist_dados.append({ # Adiciono os dados formatados na lista
                "Data/Hora": hora_fmt,
                "Assunto": subject, 
                "Agente": nome_agente,
                "Link": link
            })
        
        if hist_dados: # Se tiver histórico, mostro na tabela
            st.data_editor( # DataFrame interativo
                pd.DataFrame(hist_dados), # Dados do histórico
                column_config={ # Configuro as colunas
                    "Link": st.column_config.LinkColumn("Ticket", display_text="Abrir"), # Link pro ticket
                    "Assunto": st.column_config.TextColumn("Resumo", width="large") # Resumo do assunto
                },
                hide_index=True, # Esconde o índice
                disabled=True, # Desabilita edição
                use_container_width=True, # Usa toda a largura disponível
                key=f"hist_{int(time.time())}"  # Chave única pra forçar atualização
            )
        else:
            st.info("Sem conversas no período.") # Mensagem se não tiver histórico

    st.markdown("---")
    with st.expander("ℹ️ **Legenda e Ações**"): # Legenda no final pra ninguém ficar perdido.
        st.markdown("""
        * 🟢/🔴 **Status:** Online ou Ausente (Away).
        * ⚠️ **Sobrecarga:** Agente com 5+ tickets abertos.
        * ⚡ **Alta Demanda:** Agente recebeu 3+ tickets em 30min.
        """)

atualizar_painel()






