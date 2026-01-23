import streamlit as st # pip install streamlit
import requests # pip install requests
import json # Biblioteca padrão
import utils
import time # Biblioteca padrão
from datetime import datetime, timedelta, time as dtime # Biblioteca padrão
from collections import defaultdict # Biblioteca padrão

# --- 1. CONFIGURAÇÕES VISUAIS 
st.set_page_config(page_title="Analise de atendimento", page_icon="📅", layout="wide")
# 🔒 BLOQUEIO DE SEGURANÇA
# O app para aqui se a senha não estiver correta.
if not utils.check_password():
    st.stop()
# --- 2. INICIALIZAÇÃO DO STATE ---
if 'tickets_encontrados' not in st.session_state: # Inicializa a lista de tickets encontrados
    st.session_state['tickets_encontrados'] = [] # Lista vazia inicial
if 'analises_ia' not in st.session_state: # Inicializa o dicionário de análises IA
    st.session_state['analises_ia'] = {} # Dicionário vazio inicial

# --- 3. CONSTANTES E CREDENCIAIS ---
try:
    INTERCOM_APP_ID = st.secrets["INTERCOM_APP_ID"]
    APP_PASSWORD = st.secrets["APP_PASSWORD"] # Senha de app (ex: email)
    GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
except FileNotFoundError:
    st.error("⚠️ Arquivo de segredos (.streamlit/secrets.toml) não encontrado!")
    st.stop()
except KeyError as e:
    st.error(f"⚠️ A chave secreta {e} não foi configurada nos secrets!")
    st.stop()


# IDs dos times de suporte
SEUS_TIMES_SUPORTE = ['2975006', '1972225', '8833404', '9156876']

# --- 4. FUNÇÕES HELPER (Auxiliares) ---

# Cache para evitar chamadas repetidas na API de usuários
users_cache = {} 
# Busca o ID da empresa pelo nome ou ID direto.
def buscar_id_intercom_da_empresa(termo_busca):
    """Busca o ID da empresa usando o utils (Motoboy)."""
    termo_limpo = str(termo_busca).strip()
    
    # 1. Busca Direta por ID
    url_direct = "https://api.intercom.io/companies"
    # O utils já trata o Header e o Token pra gente!
    dados = utils.make_api_request("GET", url_direct, params={"company_id": termo_limpo})
    
    if dados: # Se o motoboy trouxe algo...
        if 'type' in dados and dados['type'] == 'company':
            return dados['id'], dados['name']
        if 'data' in dados and len(dados['data']) > 0:
            empresa = dados['data'][0]
            return empresa['id'], empresa['name']

    # 2. Busca por Nome (Search API)
    url_search = "https://api.intercom.io/companies/search"
    payload = {
        "query": {
            "operator": "AND",
            "value": [{"field": "name", "operator": "=", "value": termo_limpo}]
        }
    }
    # Aqui usamos POST
    dados_search = utils.make_api_request("POST", url_search, json=payload)
    
    if dados_search and dados_search.get('total_count', 0) > 0:
        empresa = dados_search['data'][0]
        return empresa['id'], empresa['name']

    return None, None

def buscar_historico_completo(conversation_id):
    """Busca histórico usando utils."""
    url = f"https://api.intercom.io/conversations/{conversation_id}"
    params = {"display_as": "plaintext"}
    
    # O utils cuida dos erros 429 e conexão
    dados = utils.make_api_request("GET", url, params=params)
    
    if not dados: return "Erro ao baixar conversa (API)."

    try:
        source = dados.get('source', {})
        texto_inicial = str(source.get('body') or "").replace('<p>', '').replace('</p>', '\n')
        dialogo = [f"CLIENTE (Início): {texto_inicial}"]
        
        partes = dados.get('conversation_parts', {}).get('conversation_parts', [])
        for parte in partes:
            if parte.get('part_type') != 'comment': continue
            autor = "ATENDENTE" if parte.get('author', {}).get('type') == 'admin' else "CLIENTE"
            corpo = str(parte.get('body') or "").replace('<p>', '').replace('</p>', '\n')
            if corpo.strip(): dialogo.append(f"{autor}: {corpo}")
            
        return "\n\n".join(dialogo) if dialogo else "Conversa vazia."
    except Exception as e: return f"Erro processamento: {str(e)}"

def consultar_ia_gemma_premium(historico_conversa):
    """Envia o histórico para a IA analisar."""
    if "SUA_CHAVE" in AI_API_KEY: return {"erro": "⚠️ Configure a API Key."}
    prompt_sistema = "Você é um analisador Sênior de Customer Success. Seja formal e objetivo."
    prompt_usuario = f"""
    Analise esta conversa:
    ---
    {historico_conversa}
    ---
    Gere um ÚNICO JSON válido:
    {{
        "resumo": "Resumo em 20 palavras",
        "pontos_fortes": ["A", "B"],
        "pontos_fracos": ["A", "B"],
        "sentimento_cliente": "positivo/neutro/negativo",
        "risco_churn": "baixo/médio/alto/confirmado",
        "status_conclusao": "resolvido/falta_de_contato/em_andamento",
        "relatorio_narrativo": "Texto corrido de 2 parágrafos explicando a interação."
    }}
    """
    modelo = "gemma-3-12b-it" 
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent?key={AI_API_KEY}"
    try:
        response = requests.post(url, json={"contents": [{"parts": [{"text": prompt_sistema + "\n" + prompt_usuario}]}]}, headers={"Content-Type": "application/json"})
        if response.status_code == 200:
            texto_bruto = response.json()['candidates'][0]['content']['parts'][0]['text']
            texto_limpo = texto_bruto.replace("```json", "").replace("```", "").strip()
            try: return json.loads(texto_limpo)
            except: return {"erro": "Erro JSON", "raw": texto_bruto}
        return {"erro": f"Erro Google: {response.status_code}"}
    except Exception as e: return {"erro": f"Erro Conexão: {str(e)}"}

def obter_empresa_do_usuario_cached(user_id):
    """Cache simples usando o utils para buscar empresa do usuário."""
    if user_id in users_cache:
        return users_cache[user_id]
    
    url = f"https://api.intercom.io/contacts/{user_id}"
    
    # CORREÇÃO: Usamos utils.make_api_request em vez de requests.get direto
    # Não precisa mais de HEADERS_INTERCOM aqui
    dados = utils.make_api_request("GET", url)
    
    if dados:
        companies = dados.get('companies', {}).get('data', [])
        if companies:
            comp_id = str(companies[0]['id'])
            users_cache[user_id] = comp_id
            return comp_id
            
    users_cache[user_id] = None 
    return None

# --- 5. FUNÇÃO PRINCIPAL DE BUSCA (CORE) ---
@st.cache_data(ttl=300, show_spinner=False)
def carregar_tickets_por_periodo(inicio_date, fim_date, id_empresa_intercom=None, nome_empresa_fixo=None, texto_filtro_fallback=None, ignorar_times=False, _ui_progress=None):
    ts_inicio = int(datetime.combine(inicio_date, dtime.min).timestamp())
    ts_fim = int(datetime.combine(fim_date, dtime.max).timestamp())
    
    stats = {
        "baixados": 0, "aprovados": 0,
        "ignorados_time": 0, "ignorados_mkt": 0, 
        "ignorados_empresa": 0, "salvos_pelo_usuario": 0 
    }
    conversas_dict = {}
    users_cache.clear()

    url_search = "https://api.intercom.io/conversations/search"
    
    query_filters = [
        {"field": "created_at", "operator": ">", "value": ts_inicio}, 
        {"field": "created_at", "operator": "<", "value": ts_fim}     
    ]
    payload = {
        "query": {"operator": "AND", "value": query_filters},
        "pagination": {"per_page": 50},
        "sort": {"field": "updated_at", "order": "descending"}
    }
    
    paginando = True
    total_estimado = 0 

    while paginando:
        # CORREÇÃO: Aqui removemos toda a lógica manual de Rate Limit e HEADERS_INTERCOM
        # O utils.make_api_request já faz tudo isso pra gente.
        dados = utils.make_api_request("POST", url_search, json=payload)

        if not dados: # Se falhou, paramos.
            break
            
        # --- Atualização da Barra Visual ---
        if _ui_progress:
            barra, texto_info = _ui_progress
            if total_estimado == 0: total_estimado = dados.get('total_count', 0)
            
            baixados_agora = stats["baixados"] + len(dados.get('conversations', []))
            
            if total_estimado > 0:
                percentual = min(1.0, baixados_agora / total_estimado)
                barra.progress(percentual)
                texto_info.info(f"📥 Baixando... {baixados_agora}/{total_estimado}")

        lista = dados.get('conversations', [])
        if not lista: break
        
        for c in lista:
            stats["baixados"] += 1
            
            # 1. Filtro de Empresa (Híbrido)
            if id_empresa_intercom:
                aprovado_empresa = False
                # A. Explícito
                comps = c.get('companies', {}).get('companies', [])
                ids_comps = [str(comp.get('id')) for comp in comps]
                if str(id_empresa_intercom) in ids_comps:
                    aprovado_empresa = True
                
                # B. Implícito (Usuário)
                if not aprovado_empresa:
                    author = c.get('source', {}).get('author', {})
                    if author.get('type') == 'user':
                        user_id = author.get('id')
                        if user_id:
                            id_user_emp = obter_empresa_do_usuario_cached(user_id)
                            if str(id_user_emp) == str(id_empresa_intercom):
                                aprovado_empresa = True
                                stats["salvos_pelo_usuario"] += 1

                if not aprovado_empresa:
                    stats["ignorados_empresa"] += 1
                    continue

            # 2. Filtro de Time
            team_id = str(c.get('team_assignee_id') or c.get('assignee', {}).get('id') or "")
            if not ignorar_times and team_id not in [str(t) for t in SEUS_TIMES_SUPORTE]:
                stats["ignorados_time"] += 1
                continue 

            # 3. Filtro de Tags
            tags = [t['name'].lower() for t in c.get('tags', {}).get('tags', [])]
            if any(p in str(tags) for p in ['mkt', 'trial', 'cadência', 'bot']):
                stats["ignorados_mkt"] += 1
                continue

            conversas_dict[c['id']] = c
            stats["aprovados"] += 1
        
        # Paginação
        pages = dados.get('pages', {})
        next_page = pages.get('next')
        if next_page and 'starting_after' in next_page:
            payload['pagination']['starting_after'] = next_page['starting_after']
        else:
            paginando = False
    
    # Processamento Final (Manteve igual)
    dados_proc = []
    if conversas_dict:
        for c in conversas_dict.values():
            author = c.get('source', {}).get('author', {})
            if author.get('type') not in ['user', 'lead']: continue
            dados_proc.append({
                "id": c['id'],
                "cliente": nome_empresa_fixo if nome_empresa_fixo else author.get('name', 'Desconhecido'),
                "autor_nome": author.get('name', 'Sem Nome'),
                "autor_email": author.get('email', 'Sem E-mail'),
                "status": c.get('state', 'unknown'),
                "id_interno": id_empresa_intercom,
                "tags": [t['name'] for t in c.get('tags', {}).get('tags', [])],
                "preview": (c.get('source', {}).get('body') or "")[0:100].replace('<p>', '').replace('</p>', ''),
                "link": f"https://app.intercom.com/a/inbox/{INTERCOM_APP_ID}/inbox/conversation/{c['id']}",
                "updated_at": c['updated_at'],
                "created_at": c['created_at']
            })
    
    dados_proc.sort(key=lambda x: x['updated_at'], reverse=True)
    return dados_proc, stats

# --- 6. INTERFACE DE USUÁRIO (UI) ---

st.title("📆 Buscar conversas")

# Container lateral sem st.form para permitir interação dinâmica
# --- BARRA LATERAL (Nova Lógica) ---
with st.sidebar:
    st.header("Controle de Dados")
    
    # 1. BOTÃO RESET (Limpar tudo)
    if st.button("🗑️ Limpar Tela / Nova Busca", type="secondary", help="Limpa os resultados da tela e reseta filtros"):
        st.session_state['tickets_encontrados'] = []
        st.session_state['analises_ia'] = {}
        st.rerun()
    
    st.divider()

    # 2. FILTROS GERAIS (Servem tanto para o Banco quanto para API)
    st.subheader("Filtros")
    
    # Data
    hoje = datetime.now()
    data_padrao_inicio = hoje - timedelta(days=7) 
    periodo = st.date_input("Período de Análise", (data_padrao_inicio, hoje), format="DD/MM/YYYY")
    
    # Empresa (Input único)
    filtro_empresa_input = st.text_input(
        "ID da Empresa (Intercom)", 
        placeholder="Ex: 123456",
        help="Obrigatório para buscar na API. Opcional para ler do Banco (traz tudo se vazio)."
    )

    st.divider()

    # 3. AÇÕES (Botões)
    
    # Ação A: Banco de Dados (Prioridade)
    st.markdown("### ⚡ Modo Rápido")
    btn_carregar_banco = st.button("📂 Carregar do Banco de Dados", type="primary", use_container_width=True)
    st.caption("Consulta tickets já salvos no MongoDB.")

    st.divider()

    # Ação B: API (Sincronização)
    st.markdown("### ☁️ Modo Sincronização")
    st.caption("Baixa dados novos do Intercom e atualiza o Banco.")
    btn_sincronizar = st.button("🔄 Baixar da API e Salvar", use_container_width=True)


# --- LÓGICA: BOTÃO CARREGAR DO BANCO (MongoDB) ---
if btn_carregar_banco:
    termo = filtro_empresa_input.strip() if filtro_empresa_input else None
    
    with st.spinner("Lendo banco de dados..."):
        # 1. Busca TUDO o que tem no banco correspondente ao texto (ignora data por enquanto)
        todos_tickets = utils.carregar_tickets_mongo(termo)
        
        # 2. Diagnóstico (Mostra pro usuário o que aconteceu)
        if not todos_tickets:
            st.warning(f"O Banco de dados não retornou nada para a busca: '{termo or 'Vazio'}'")
            st.stop()
            
        st.toast(f"Banco retornou {len(todos_tickets)} registros brutos.", icon="💾")

        # 3. Filtro de Data (Python) - Vamos fazer com tratamento de erro
        tickets_filtrados = []
        
        if isinstance(periodo, tuple) and len(periodo) == 2:
            dt_ini, dt_fim = periodo
            # Converte para timestamp (início do dia inicial, fim do dia final)
            ts_ini = int(datetime.combine(dt_ini, dtime.min).timestamp())
            ts_fim = int(datetime.combine(dt_fim, dtime.max).timestamp())
            
            for t in todos_tickets:
                # Proteção caso o ticket não tenha data
                data_ticket = t.get('updated_at', 0)
                if ts_ini <= data_ticket <= ts_fim:
                    tickets_filtrados.append(t)
            
            # DIAGNÓSTICO DE DATA
            removidos = len(todos_tickets) - len(tickets_filtrados)
            if removidos > 0:
                st.caption(f"⚠️ Atenção: **{removidos}** tickets foram escondidos pelo filtro de data ({dt_ini.strftime('%d/%m')} a {dt_fim.strftime('%d/%m')}).")
        else:
            tickets_filtrados = todos_tickets

    # 4. Atualiza a tela
    st.session_state['tickets_encontrados'] = tickets_filtrados
    
    if not tickets_filtrados:
        st.error("Nenhum ticket restou após o filtro de data! Tente aumentar o período na barra lateral.")
    else:
        st.success(f"✅ Mostrando {len(tickets_filtrados)} tickets.")
        time.sleep(1)
        st.rerun()


# --- LÓGICA: BOTÃO SINCRONIZAR (API -> Mongo) ---
if btn_sincronizar:
    # 1. Validação de Segurança
    if not filtro_empresa_input:
        st.error("⚠️ Para baixar da API, o **ID da Empresa** é obrigatório!")
        st.stop()
        
    if not (isinstance(periodo, tuple) and len(periodo) == 2):
        st.error("⚠️ Selecione uma data inicial e final.")
        st.stop()

    data_inicio, data_fim = periodo

    # 2. Validação da Empresa (Check Rápido)
    with st.status("🕵️ Validando empresa...", expanded=True) as status:
        id_oficial, nome_oficial = buscar_id_intercom_da_empresa(filtro_empresa_input)
        
        if not id_oficial:
            status.update(label="❌ Empresa não encontrada!", state="error")
            st.error(f"ID inválido: '{filtro_empresa_input}'")
            st.stop()
        
        status.update(label=f"✅ Confirmado: {nome_oficial}", state="complete")

    # 3. Download (Processo Pesado)
    st.info(f"Iniciando download de tickets: **{nome_oficial}**")
    
    # Barras de progresso visual
    barra_progresso = st.progress(0)
    texto_status = st.empty()
    
    # Limpa cache da função para garantir dados frescos
    carregar_tickets_por_periodo.clear()
    
    try:
        # Busca na API
        novos_tickets, stats = carregar_tickets_por_periodo(
            data_inicio, data_fim, 
            id_empresa_intercom=id_oficial,
            nome_empresa_fixo=nome_oficial,
            texto_filtro_fallback=None,
            _ui_progress=(barra_progresso, texto_status)
        )
        
        # 4. Salvar no MongoDB
        if novos_tickets:
            texto_status.text("💾 Salvando dados no MongoDB Atlas...")
            qtd_salva = utils.salvar_lote_tickets_mongo(novos_tickets)
            
            barra_progresso.progress(100)
            st.success(f"🎉 Sucesso! {len(novos_tickets)} baixados da API. {qtd_salva} atualizados no Banco.")
            
            # Recarrega do banco para garantir que a visualização está igual ao salvo
            st.session_state['tickets_encontrados'] = utils.carregar_tickets_mongo(id_oficial)
            
            time.sleep(2)
            st.rerun()
        else:
            barra_progresso.empty()
            st.warning("Nenhum ticket encontrado neste período na API.")
            
    except Exception as e:
        st.error(f"Erro durante a sincronização: {e}")

# --- 7. EXIBIÇÃO DOS RESULTADOS ---
dados = st.session_state['tickets_encontrados']

if dados:
    grupos_empresa = defaultdict(list)
    for ticket in dados:
        chave = (ticket['id_interno'], ticket['cliente'])
        grupos_empresa[chave].append(ticket)
    
   # --- CÁLCULO INTELIGENTE DE RISCO ---
    def checar_risco(ticket):
        # 1. Verifica TAGS (Critério antigo)
        tags_ticket = [str(t).lower() for t in ticket['tags']]
        if any(termo in str(tags_ticket) for termo in ['cancel', 'churn', 'rescisão']):
            return True
        
        # 2. Verifica IA (Critério novo)
        if ticket['id'] in st.session_state['analises_ia']:
            analise = st.session_state['analises_ia'][ticket['id']]
            # Se a IA disse que o risco é Alto ou Confirmado
            risco_ia = analise.get('risco_churn', '').lower()
            if risco_ia in ['alto', 'confirmado']:
                return True
        
        return False

    total_risco = sum(1 for t in dados if checar_risco(t))

    # --- EXIBIÇÃO ---
    c1, c2, c3 = st.columns(3)
    c1.metric("Tickets Encontrados", len(dados))
    c2.metric("Clientes", len(grupos_empresa))
    
    # Agora o risco muda de cor se for maior que zero
    c3.metric(
        "Risco Detectado", 
        total_risco, 
        delta="Atenção" if total_risco > 0 else None, 
        delta_color="inverse"
    )
    
    st.write("") #
    st.divider() # Uma linha para separar

    # --- 🤖 ÁREA DE ANÁLISE EM LOTE (NOVA FUNCIONALIDADE) ---
    col_batch_btn, col_batch_info = st.columns([1, 4])
    
    # Filtra apenas os tickets que AINDA NÃO foram analisados para economizar
    tickets_pendentes = [t for t in dados if t['id'] not in st.session_state['analises_ia']]
    
    if col_batch_btn.button(f"✨ Analisar {len(tickets_pendentes)} Tickets Pendentes"):
        if not tickets_pendentes:
            st.warning("Todos os tickets listados já foram analisados!")
        else:
            barra_ia = col_batch_info.progress(0)
            status_ia = st.empty()
            
            total = len(tickets_pendentes)
            
            for i, ticket in enumerate(tickets_pendentes):
                ticket_id = ticket['id']
                
                # Atualiza Status Visual
                status_ia.markdown(f"🤖 Analisando ticket **{i+1}/{total}**: `{ticket_id}` ...")
                barra_ia.progress((i + 1) / total)
                
                try:
                    # 1. Busca histórico
                    hist = buscar_historico_completo(ticket_id)
                    
                    # 2. Consulta IA
                    resultado = consultar_ia_gemma_premium(hist)
                    
                    # 3. Salva na sessão
                    st.session_state['analises_ia'][ticket_id] = resultado
                    
                    # 4. PAUSA DE SEGURANÇA (Evita erro 429 do Google)
                    time.sleep(2) 
                    
                except Exception as e:
                    st.error(f"Erro ao analisar {ticket_id}: {e}")
            
            status_ia.success("✅ Análise em lote concluída!")
            time.sleep(1)
            st.rerun() # Recarrega a página para mostrar os resultados
    # ---------------------------------------------------------

    groups_sorted = sorted(grupos_empresa.items(), key=lambda x: x[0][1])

    for (id_empresa, nome_empresa), lista_tickets in groups_sorted:
         expandido = True if filtro_empresa_input else False
         with st.expander(f"🏢 {nome_empresa} (ID: {id_empresa}) - {len(lista_tickets)} tickets", expanded=expandido):
            for item in lista_tickets:
                
                # Ícones de Status
                raw_status = item.get('status', 'unknown')
                status_fmt = {
                    'open': "🟢 **Aberto**",
                    'closed': "🔴 **Encerrado**",
                    'snoozed': "🟡 **Adiado** (Snoozed)"
                }.get(raw_status, f"⚪ {raw_status}")

                # Formatação das datas
                dt_criacao = datetime.fromtimestamp(item['created_at']).strftime('%d/%m %H:%M')
                dt_update = datetime.fromtimestamp(item['updated_at']).strftime('%d/%m %H:%M')

                st.markdown(f"""
                **Ticket:** `{item['id']}` | ✨ Criado em: **{dt_criacao}** | {status_fmt}  
                *Última interação: {dt_update}* 👤 **{item['autor_nome']}** (`{item['autor_email']}`)
                """)
                
                col_conteudo, col_acao = st.columns([4, 1])
                
                # Coluna Esquerda: Conteúdo e IA
                with col_conteudo:
                    st.caption(f"Preview: {item['preview']}...")
                    if item['tags']: st.caption(f"🏷️ {', '.join(item['tags'])}")
                    
                    ticket_id = item['id']
                    res = st.session_state['analises_ia'].get(ticket_id)
                    
                    if res:
                        if "erro" in res: 
                            st.error(res['erro'])
                        else:
                            k1, k2, k3 = st.columns(3)
                            risco = res.get('risco_churn', 'baixo').lower()
                            cor_risco = "inverse" if risco in ["alto", "confirmado"] else ("off" if risco == "médio" else "normal")
                            
                            k1.metric("Risco", risco.upper(), delta_color=cor_risco)
                            k2.metric("Sentimento", res.get('sentimento_cliente', 'N/A').capitalize())
                            k3.metric("Status", res.get('status_conclusao', 'N/A').replace('_', ' ').title())
                            
                            if "relatorio_narrativo" in res: st.info(res['relatorio_narrativo'])
                    else:
                        if st.button("✨ Analisar com IA", key=f"btn_{ticket_id}"):
                            with st.spinner("Analisando..."):
                                hist = buscar_historico_completo(ticket_id)
                                st.session_state['analises_ia'][ticket_id] = consultar_ia_gemma_premium(hist)
                                st.rerun()
                
                # Coluna Direita: Link
                with col_acao:
                    st.link_button("Abrir Intercom", item['link'])
                st.divider()

elif not dados and 'botao_buscar' in locals():
    st.info("Nenhuma conversa encontrada.")
else:
    st.info("👈 Utilize os filtros na barra lateral para iniciar.")
