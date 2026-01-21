import streamlit as st 
import requests
import time
import plotly.express as px
from datetime import datetime, timedelta
from io import BytesIO

# --- IMPORTAÇÃO DO UTILS ---
try: #  Tenta importar a função de verificação de senha
    from utils import check_password
except ImportError: # Se falhar, exibe uma mensagem de erro e para a execução
    st.error("Arquivo utils.py não encontrado. Certifique-se de que ele está na mesma pasta.")
    st.stop()

# --- CONFIGURAÇÕES ---
# Configura o nome da aba no navegador e o icone.
st.set_page_config(page_title="Relatório de Atributos Intercom", page_icon="📊", layout="wide")

# --- BLOQUEIO DE SENHA ---
if not check_password(): #  Se a senha não for correta, para a execução
    st.stop()

WORKSPACE_ID = "xwvpdtlu" # Substitua pelo ID do seu workspace Intercom
# --- AUTENTICAÇÃO INTERCOM ---
try:
    INTERCOM_ACCESS_TOKEN = st.secrets["INTERCOM_TOKEN"]
except:
    INTERCOM_ACCESS_TOKEN = st.sidebar.text_input("Intercom Token", type="password")

if not INTERCOM_ACCESS_TOKEN:
    st.warning("⚠️ Configure o Token para continuar.")
    st.stop()

HEADERS = { # Cabeçalhos para autenticação na API do Intercom
    "Authorization": f"Bearer {INTERCOM_ACCESS_TOKEN}",
    "Accept": "application/json"
}

# --- FUNÇÕES ---
#
@st.cache_data(ttl=3600) # Cacheia o resultado por 1 hora
def get_attribute_definitions(): # Busca os nomes bonitos dos atributos
    """Busca os nomes bonitos dos atributos"""
    url = "https://api.intercom.io/data_attributes"
    params = {"model": "conversation"}
    try:
        r = requests.get(url, headers=HEADERS, params=params) # Requisição GET com parâmetros
        return {item['name']: item['label'] for item in r.json().get('data', [])}
    except:
        return {}

@st.cache_data(ttl=3600) # Cacheia o resultado por 1 hora
def get_all_admins(): # Busca a lista de todos os agentes (ID -> Nome)
    """Busca a lista de todos os agentes (ID -> Nome)"""
    url = "https://api.intercom.io/admins"
    try:
        r = requests.get(url, headers=HEADERS) # Requisição GET
        return {str(a['id']): a['name'] for a in r.json().get('admins', [])}
    except:
        return {}

@st.cache_data(ttl=300, show_spinner=False) # Cacheia o resultado por 5 minutos
def fetch_conversations(start_date, end_date, team_ids=None): # Busca conversas no período e times especificados
    url = "https://api.intercom.io/conversations/search"
    ts_start = int(datetime.combine(start_date, datetime.min.time()).timestamp()) # Início do dia
    ts_end = int(datetime.combine(end_date, datetime.max.time()).timestamp()) # Fim do dia
    
    query_rules = [
        {"field": "created_at", "operator": ">", "value": ts_start}, # Início do período
        {"field": "created_at", "operator": "<", "value": ts_end} # Fim do período
    ]
    
    if team_ids:
        query_rules.append({"field": "team_assignee_id", "operator": "IN", "value": team_ids}) # Filtra por times se fornecido

    payload = {
        "query": {"operator": "AND", "value": query_rules}, # Regras de consulta
        "pagination": {"per_page": 150}
    }
    
    conversas = [] # Lista para armazenar conversas
    has_more = True # Controle de paginação
    status_text = st.empty() # Espaço para status de download
     # Loop: enquanto tiver paginas, continua buscando.
    while has_more:
        try:
            resp = requests.post(url, headers=HEADERS, json=payload)
            data = resp.json()
            batch = data.get('conversations', [])
            conversas.extend(batch)
            status_text.caption(f"📥 Baixando... {len(conversas)} conversas encontradas.")
            
            if data.get('pages', {}).get('next'):
                payload['pagination']['starting_after'] = data['pages']['next']['starting_after']
                time.sleep(0.1)
            else:
                has_more = False
        except Exception as e:
            st.error(f"Erro: {e}")
            break
            
    status_text.empty()
    return conversas

def process_data(conversas, mapping, admin_map):
    rows = []
    for c in conversas:
        link = f"https://app.intercom.com/a/inbox/{WORKSPACE_ID}/inbox/conversation/{c['id']}"
        
        # Pega nome do atendente
        admin_id = c.get('admin_assignee_id')
        if admin_id:
            assignee_name = admin_map.get(str(admin_id), f"ID {admin_id}")
        else:
            assignee_name = "Não atribuído"

        row = {
            "ID": c['id'],
            "timestamp_real": c['created_at'], 
            "Data": datetime.fromtimestamp(c['created_at']).strftime("%d/%m/%Y %H:%M"),
            "Data_Dia": datetime.fromtimestamp(c['created_at']).strftime("%Y-%m-%d"),
            "Atendente": assignee_name,
            "Link": link
        }
        
        attrs = c.get('custom_attributes', {})
        for key, value in attrs.items():
            nome_bonito = mapping.get(key)
            if nome_bonito:
                row[nome_bonito] = value
            else:
                row[key] = value
        rows.append(row)
    
    df = pd.DataFrame(rows)
    
    # Força coluna Motivo 2 se não existir
    coluna_teimosa = "Motivo 2 (Se houver)"
    if not df.empty and coluna_teimosa not in df.columns:
        df[coluna_teimosa] = None 

    if not df.empty:
        df = df.sort_values(by="timestamp_real", ascending=True)
        df = df.reset_index(drop=True)
        
    return df

def gerar_excel_multias(df, colunas_selecionadas):
    output = BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        
        # 1. Abas de Totais
        for col in colunas_selecionadas:
            if col in df.columns and col not in ["Data", "Link", "ID", "Qtd. Atributos"]:
                try:
                    resumo = df[col].value_counts().reset_index()
                    resumo.columns = [col, 'Quantidade']
                    nome_aba = col[:30].replace(":", "").replace("/", "-").replace("?", "").replace("*", "").replace("(", "").replace(")", "")
                    resumo.to_excel(writer, index=False, sheet_name=nome_aba)
                    writer.sheets[nome_aba].set_column('A:A', 50)
                except Exception as e:
                    pass

        # 2. Aba Base Completa
        cols_finais = ["Data", "Atendente", "Link", "Qtd. Atributos"] + [c for c in colunas_selecionadas if c not in ["Data", "Link", "Qtd. Atributos"]]
        cols_existentes = [c for c in cols_finais if c in df.columns]
        
        df[cols_existentes].to_excel(writer, index=False, sheet_name='Base Completa')
        writer.sheets['Base Completa'].set_column('A:A', 18) 
        
    return output.getvalue()

# --- INTERFACE ---

st.title(f"📊 Relatório de Atributos")

with st.sidebar:
    st.header("Filtros")
    if st.button("🧹 Limpar Cache"):
        st.cache_data.clear()
        st.success("Cache limpo!")

    data_hoje = datetime.now()
    periodo = st.date_input("Período", (data_hoje - timedelta(days=7), data_hoje), format="DD/MM/YYYY")
    team_input = st.text_input("IDs dos Times:", value="9156876")
    btn_run = st.button("🚀 Gerar Dados", type="primary")

if btn_run:
    start, end = periodo
    ids_times = [int(x.strip()) for x in team_input.split(",") if x.strip().isdigit()] if team_input else None
    
    with st.spinner("Analisando dados..."):
        mapa = get_attribute_definitions()
        admins_map = get_all_admins()
        raw = fetch_conversations(start, end, ids_times)
        
        if raw:
            df = process_data(raw, mapa, admins_map)
            st.session_state['df_final'] = df
            st.success(f"Sucesso! {len(df)} conversas carregadas.")
        else:
            st.warning("Nenhum dado encontrado.")

if 'df_final' in st.session_state:
    df = st.session_state['df_final']
    
    st.divider()
    
    # --- SELEÇÃO DE COLUNAS ---
    todas_colunas = list(df.columns)
    
    # Define o nome exato da nova coluna
    COL_EXPANSAO = "Expansão (Passagem de bastão para CSM)"
    
    # Adicionei o nome exato na sugestão
    sugestao = ["Tipo de Atendimento", COL_EXPANSAO, "Motivo de Contato", "Motivo 2 (Se houver)", "Status do atendimento"]
    padrao_existente = [c for c in sugestao if c in todas_colunas]
    
    cols_usuario = st.multiselect(
        "Selecione os atributos para análise:",
        options=[c for c in todas_colunas if c not in ["ID", "timestamp_real", "Data", "Data_Dia", "Link", "Qtd. Atributos", "Atendente"]],
        default=padrao_existente
    )

    # --- CÁLCULO DE COMPLEXIDADE ---
    if cols_usuario:
        # Colunas que NÃO devem contar pontos de complexidade
        ignorar_na_conta = ["Status do atendimento", "Tipo de Atendimento", "Atendente", "Data", "Data_Dia", "Link", "timestamp_real", "ID"]
        
        # Cria uma lista apenas com as colunas que REALMENTE importam para a contagem
        cols_para_contar = [c for c in cols_usuario if c not in ignorar_na_conta]
        
        # Calcula a soma apenas nessas colunas
        if cols_para_contar:
            df["Qtd. Atributos"] = df[cols_para_contar].notna().sum(axis=1)
        else:
            df["Qtd. Atributos"] = 0
    else:
        df["Qtd. Atributos"] = 0

    # --- RESUMO EXECUTIVO ---
    st.markdown("### 📌 Resumo do Período")
    
   
    # [1, 1, 1, 1.5] dá mais espaço para a última coluna (Principal Motivo)
    kpi1, kpi2, kpi3, kpi4 = st.columns([1, 1, 1, 1.5])
    
    total_conv = len(df)
    preenchidos = df["Motivo de Contato"].notna().sum() if "Motivo de Contato" in df.columns else 0
    taxa_classif = (preenchidos / total_conv * 100) if total_conv > 0 else 0
    
    top_motivo = "N/A"
    if "Motivo de Contato" in df.columns:
        top = df["Motivo de Contato"].value_counts().head(1)
        if not top.empty: 
            top_motivo = f"{top.index[0]} ({top.values[0]})"

    resolvidos = 0
    if "Status do atendimento" in df.columns:
        resolvidos = df[df["Status do atendimento"] == "Resolvido"].shape[0]

    # KPIs Padrão
    kpi1.metric("Total Conversas", total_conv)
    kpi2.metric("Classificados", f"{preenchidos}", f"{taxa_classif:.1f}%")
    kpi3.metric("Resolvidos", resolvidos)
    
    # KPI Personalizado (HTML) para diminuir a fonte
    motivo_texto = top_motivo.split(">")[-1].strip()
    kpi4.markdown(f"""
    <div style="font-size: 14px; color: #6c757d; margin-bottom: 4px;">Principal Motivo</div>
    <div style="font-size: 20px; font-weight: 600; color: #31333F; line-height: 1.2;">
        {motivo_texto}
    </div>
    """, unsafe_allow_html=True)

    st.divider()

    # --- ABAS DE ANÁLISE ---
    tab_grafico, tab_equipe, tab_cruzamento, tab_motivos, tab_tabela = st.tabs(["📊 Distribuição", "👥 Equipe", "🔀 Cruzamentos", "🔗 Motivo x Motivo", "📋 Detalhes & Export"])
    
    with tab_grafico:
        c1, c2 = st.columns([2, 1])
        with c1:
            if cols_usuario:
                graf_sel = st.selectbox("Atributo:", cols_usuario, key="sel_bar")
                
                df_clean = df[df[graf_sel].notna()]
                contagem = df_clean[graf_sel].value_counts().reset_index()
                contagem.columns = ["Opção", "Quantidade"]
                
                fig_bar = px.bar(
                    contagem, 
                    x="Opção", 
                    y="Quantidade", 
                    text_auto=True,
                    title=f"Distribuição: {graf_sel}"
                )
                
                fig_bar.update_layout(xaxis={'categoryorder':'total descending'})
                st.plotly_chart(fig_bar, use_container_width=True)
            else:
                st.warning("Selecione atributos no topo.")
        with c2:
             if cols_usuario:
                 st.write("**Ranking Completo:**")
                 st.dataframe(df[graf_sel].value_counts(), use_container_width=True)

    with tab_equipe:
        st.subheader("Performance do Time")
        vol_por_agente = df['Atendente'].value_counts().reset_index()
        vol_por_agente.columns = ['Agente', 'Volume']
        c1, c2 = st.columns([2, 1])
        c1.plotly_chart(px.bar(vol_por_agente, x='Agente', y='Volume', title="Volume de Conversas por Agente", text_auto=True), use_container_width=True)
        c2.write("Ranking:")
        c2.dataframe(vol_por_agente, hide_index=True, use_container_width=True)
        st.divider()
        st.subheader("🕵️ Detalhe por Agente")
        
        
        # Cria uma lista começando com "Status", adiciona os outros, e remove duplicados mantendo a ordem.
        opcoes_cruzamento = ["Status do atendimento"] + [c for c in cols_usuario if c != "Status do atendimento"]
        
        cruzamento_agente = st.selectbox("Cruzar Atendente com:", opcoes_cruzamento)
        
        if cruzamento_agente in df.columns:
            df_agente_cross = df.dropna(subset=[cruzamento_agente])
            fig_ag = px.histogram(df_agente_cross, x="Atendente", color=cruzamento_agente, barmode="group", text_auto=True)
            st.plotly_chart(fig_ag, use_container_width=True)

    with tab_cruzamento:
        st.info("Relação entre os campos.")
        has_motivo = "Motivo de Contato" in df.columns
        has_status = "Status do atendimento" in df.columns
        has_tipo = "Tipo de Atendimento" in df.columns
        has_expansao = COL_EXPANSAO in df.columns
        
        # 1. Status x Motivo
        if has_motivo and has_status:
            st.subheader("Status x Motivo")
            df_cross = df.dropna(subset=["Motivo de Contato", "Status do atendimento"])
            fig_cross = px.histogram(df_cross, y="Motivo de Contato", color="Status do atendimento", 
                                     barmode="stack", text_auto=True, height=600)
            fig_cross.update_layout(yaxis={'categoryorder':'total ascending'})
            st.plotly_chart(fig_cross, use_container_width=True)
            st.divider()

        # 2. Tipo x Motivo
        if has_motivo and has_tipo:
            st.subheader("Tipo de Atendimento x Motivo")
            df_cross2 = df.dropna(subset=["Motivo de Contato", "Tipo de Atendimento"])
            fig_cross2 = px.histogram(df_cross2, y="Motivo de Contato", color="Tipo de Atendimento", 
                                     barmode="stack", text_auto=True, height=600)
            fig_cross2.update_layout(yaxis={'categoryorder':'total ascending'})
            st.plotly_chart(fig_cross2, use_container_width=True)
            st.divider()

        # 3. Expansão x Motivo
        if has_motivo and has_expansao:
            st.subheader(f"{COL_EXPANSAO} x Motivo")
            df_cross3 = df.dropna(subset=["Motivo de Contato", COL_EXPANSAO])
            fig_cross3 = px.histogram(df_cross3, y="Motivo de Contato", color=COL_EXPANSAO, 
                                     barmode="stack", text_auto=True, height=600)
            fig_cross3.update_layout(yaxis={'categoryorder':'total ascending'})
            st.plotly_chart(fig_cross3, use_container_width=True)

    with tab_motivos:
        st.markdown("### 🔗 Análise Unificada de Motivos")
        col_m1 = "Motivo de Contato"
        col_m2 = "Motivo 2 (Se houver)"
        
        if col_m1 in df.columns and col_m2 in df.columns:
            lista_geral = pd.concat([df[col_m1], df[col_m2]])
            ranking_global = lista_geral.value_counts().reset_index()
            ranking_global.columns = ["Motivo Unificado", "Incidência Total"]
            ranking_global = ranking_global.sort_values(by="Incidência Total", ascending=True)
            
            c_rank1, c_rank2 = st.columns([2, 1])
            with c_rank1:
                # Altura dinâmica
                altura_dinamica = max(400, len(ranking_global) * 30)
                
                fig_global = px.bar(ranking_global, x="Incidência Total", y="Motivo Unificado", 
                                    orientation='h', text_auto=True, 
                                    title="Todos os Motivos (Somando Motivo 1 + 2)",
                                    height=altura_dinamica)
                fig_global.update_layout(yaxis={'type': 'category'})
                st.plotly_chart(fig_global, use_container_width=True)
            with c_rank2:
                st.dataframe(ranking_global.sort_values(by="Incidência Total", ascending=False), use_container_width=True, hide_index=True)
        else:
            st.error("As colunas de Motivo 1 e Motivo 2 não foram encontradas.")

    with tab_tabela:
        # --- Topo: Checkboxes e Botão de Exportar ---
        c1, c2 = st.columns([3, 1])
        with c1:
            f1, f2 = st.columns(2)
            ocultar_vazios = f1.checkbox("Ocultar vazios", value=True)
            ver_complexas = f2.checkbox("🔥 Apenas complexas (2+ atributos)")
        with c2:
            excel_data = gerar_excel_multias(df, cols_usuario)
            st.download_button("📥 Baixar Excel", data=excel_data, file_name="relatorio_completo.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", type="primary")

        # --- Base Inicial de Dados ---
        df_view = df.copy()
        
        # Aplica filtros de checkbox
        if ocultar_vazios: df_view = df_view[df_view["Qtd. Atributos"] > 0]
        if ver_complexas: df_view = df_view[df_view["Qtd. Atributos"] >= 2]

        # --- FILTROS EM CASCATA ---
        st.divider()
        st.caption("🔎 Filtros Avançados (Cascata)")
        
        # NÍVEL 1
        col_f1, col_v1 = st.columns(2)
        with col_f1:
            idx_tipo = 0
            if "Tipo de Atendimento" in cols_usuario:
                idx_tipo = cols_usuario.index("Tipo de Atendimento") + 1
            coluna_1 = st.selectbox("1º Filtro (Principal):", ["(Todos)"] + cols_usuario, index=idx_tipo)
        
        with col_v1:
            if coluna_1 != "(Todos)":
                opcoes_1 = df_view[coluna_1].dropna().unique()
                valores_1 = st.multiselect(f"Selecione valores em '{coluna_1}':", options=opcoes_1)
                if valores_1:
                    df_view = df_view[df_view[coluna_1].isin(valores_1)]

        # NÍVEL 2
        if coluna_1 != "(Todos)":
            st.markdown("⬇️ *E dentro destes resultados...*")
            col_f2, col_v2 = st.columns(2)
            
            with col_f2:
                cols_restantes = [c for c in cols_usuario if c != coluna_1]
                idx_motivo = 0
                if "Motivo de Contato" in cols_restantes:
                    idx_motivo = cols_restantes.index("Motivo de Contato") + 1
                coluna_2 = st.selectbox("2º Filtro (Refinamento):", ["(Nenhum)"] + cols_restantes, index=idx_motivo)

            with col_v2:
                if coluna_2 != "(Nenhum)":
                    opcoes_2 = df_view[coluna_2].dropna().unique()
                    valores_2 = st.multiselect(f"Selecione valores em '{coluna_2}':", options=opcoes_2)
                    if valores_2:
                        df_view = df_view[df_view[coluna_2].isin(valores_2)]

        # --- Exibição da Tabela ---
        st.divider()
        st.write(f"**Resultados encontrados:** {len(df_view)}")
        
        cols_display = ["Data", "Atendente", "Link"] + cols_usuario
        cols_display = [c for c in cols_display if c in df_view.columns]

        st.dataframe(
            df_view[cols_display], 
            use_container_width=True,
            column_config={
                "Link": st.column_config.LinkColumn("Link", display_text="Abrir")
            }
        )
