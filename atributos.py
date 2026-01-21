import streamlit as st 
import pandas as pd
import requests
import time
import plotly.express as px
from datetime import datetime, timedelta
from io import BytesIO

# --- IMPORTAÇÃO DO UTILS ---
try:
    from utils import check_password
except ImportError:
    st.error("Arquivo utils.py não encontrado. Certifique-se de que ele está na mesma pasta.")
    st.stop()

# --- CONFIGURAÇÕES ---
st.set_page_config(page_title="Relatório de Atributos Intercom", page_icon="📊", layout="wide")

# --- BLOQUEIO DE SENHA ---
if not check_password():
    st.stop()

WORKSPACE_ID = "xwvpdtlu"

# --- AUTENTICAÇÃO INTERCOM ---
try:
    INTERCOM_ACCESS_TOKEN = st.secrets["INTERCOM_TOKEN"]
except:
    INTERCOM_ACCESS_TOKEN = st.sidebar.text_input(
        "Intercom Token", 
        type="password", 
        key="meu_token_fixo"
    )

if not INTERCOM_ACCESS_TOKEN:
    st.warning("⚠️ Configure o Token para continuar.")
    st.stop()

HEADERS = {
    "Authorization": f"Bearer {INTERCOM_ACCESS_TOKEN}",
    "Accept": "application/json"
}

# --- FUNÇÕES ---

@st.cache_data(ttl=3600)
def get_attribute_definitions():
    """Busca os nomes bonitos dos atributos"""
    url = "https://api.intercom.io/data_attributes"
    params = {"model": "conversation"}
    try:
        r = requests.get(url, headers=HEADERS, params=params)
        return {item['name']: item['label'] for item in r.json().get('data', [])}
    except:
        return {}

@st.cache_data(ttl=3600)
def get_all_admins():
    """Busca a lista de todos os agentes (ID -> Nome)"""
    url = "https://api.intercom.io/admins"
    try:
        r = requests.get(url, headers=HEADERS)
        return {str(a['id']): a['name'] for a in r.json().get('admins', [])}
    except:
        return {}

@st.cache_data(ttl=300, show_spinner=False)
def fetch_conversations(start_date, end_date, team_ids=None):
    url = "https://api.intercom.io/conversations/search"
    ts_start = int(datetime.combine(start_date, datetime.min.time()).timestamp())
    ts_end = int(datetime.combine(end_date, datetime.max.time()).timestamp())
    
    query_rules = [
        {"field": "created_at", "operator": ">", "value": ts_start},
        {"field": "created_at", "operator": "<", "value": ts_end}
    ]
    
    if team_ids:
        query_rules.append({"field": "team_assignee_id", "operator": "IN", "value": team_ids})

    payload = {
        "query": {"operator": "AND", "value": query_rules},
        "pagination": {"per_page": 150}
    }
    
    conversas = []
    has_more = True
    status_text = st.empty()
    
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

        # --- CORREÇÃO AQUI ---
        # O 'or {}' garante que se vier None, virará um dicionário vazio
        rating_data = c.get('conversation_rating') or {}
        
        csat_score = rating_data.get('rating') 
        csat_comment = rating_data.get('remark')
        # -----------------------------

        row = {
            "ID": c['id'],
            "timestamp_real": c['created_at'], 
            "Data": datetime.fromtimestamp(c['created_at']).strftime("%d/%m/%Y %H:%M"),
            "Data_Dia": datetime.fromtimestamp(c['created_at']).strftime("%Y-%m-%d"),
            "Atendente": assignee_name,
            "Link": link,
            "CSAT Nota": csat_score,
            "CSAT Comentario": csat_comment
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
            
            # --- ALTERAÇÃO AQUI ---
            # Em vez de st.success() solto na tela, usamos toast (notificação) ou sidebar
            # Isso evita que o layout "pule" quando a mensagem sumir.
            try:
                st.toast(f"✅ Sucesso! {len(df)} conversas carregadas.")
            except:
                st.sidebar.success(f"✅ Sucesso! {len(df)} conversas carregadas.")
            # ----------------------
            
        else:
            st.warning("Nenhum dado encontrado.")

if 'df_final' in st.session_state:
    df = st.session_state['df_final']
    
    st.divider()
    
    # --- SELEÇÃO DE COLUNAS ---
    todas_colunas = list(df.columns)
    
    COL_EXPANSAO = "Expansão (Passagem de bastão para CSM)"
    sugestao = ["Tipo de Atendimento", COL_EXPANSAO, "Motivo de Contato", "Motivo 2 (Se houver)", "Status do atendimento"]
    padrao_existente = [c for c in sugestao if c in todas_colunas]
    
    cols_usuario = st.multiselect(
        "Selecione os atributos para análise:",
        options=[c for c in todas_colunas if c not in ["ID", "timestamp_real", "Data", "Data_Dia", "Link", "Qtd. Atributos", "Atendente"]],
        default=padrao_existente,
        key="seletor_colunas_principal"
    )

    # --- CÁLCULO DE COMPLEXIDADE ---
    if cols_usuario:
        ignorar_na_conta = ["Status do atendimento", "Tipo de Atendimento", "Atendente", "Data", "Data_Dia", "Link", "timestamp_real", "ID"]
        cols_para_contar = [c for c in cols_usuario if c not in ignorar_na_conta]
        
        if cols_para_contar:
            df["Qtd. Atributos"] = df[cols_para_contar].notna().sum(axis=1)
        else:
            df["Qtd. Atributos"] = 0
    else:
        df["Qtd. Atributos"] = 0

    # --- RESUMO EXECUTIVO ---
    st.markdown("### 📌 Resumo do Período")
    
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

    kpi1.metric("Total Conversas", total_conv)
    kpi2.metric("Classificados", f"{preenchidos}", f"{taxa_classif:.1f}%")
    kpi3.metric("Resolvidos", resolvidos)
    
    motivo_texto = top_motivo.split(">")[-1].strip()
    kpi4.markdown(f"""
    <div style="font-size: 14px; color: #6c757d; margin-bottom: 4px;">Principal Motivo</div>
    <div style="font-size: 20px; font-weight: 600; color: #31333F; line-height: 1.2;">
        {motivo_texto}
    </div>
    """, unsafe_allow_html=True)

    st.divider()

    # --- ABAS DE ANÁLISE ---
    tab_grafico, tab_equipe, tab_cruzamento, tab_motivos, tab_csat, tab_tabela = st.tabs(["📊 Distribuição", "👥 Equipe", "🔀 Cruzamentos", "🔗 Motivo x Motivo", "⭐ CSAT", "📋 Detalhes & Export"])

    with tab_csat:
        st.header("Análise de Satisfação (CSAT)")
        
        # Filtra apenas quem tem nota
        df_csat = df.dropna(subset=["CSAT Nota"])
        
        if df_csat.empty:
            st.info("Nenhuma avaliação de CSAT encontrada neste período.")
        else:
            # Métricas Gerais
            media_geral = df_csat["CSAT Nota"].mean()
            qtd_avaliacoes = len(df_csat)
            
            k1, k2 = st.columns(2)
            k1.metric("Média Geral CSAT", f"{media_geral:.2f}/5.0")
            k2.metric("Total de Avaliações", qtd_avaliacoes)
            
            st.divider()
            
            # Gráfico 1: Média de CSAT por Motivo
            if "Motivo de Contato" in df.columns:
                st.subheader("Média de CSAT por Motivo")
                
                # Agrupa por motivo e calcula média
                csat_por_motivo = df_csat.groupby("Motivo de Contato")["CSAT Nota"].mean().reset_index()
                csat_por_motivo = csat_por_motivo.sort_values(by="CSAT Nota", ascending=True) # Piores primeiro
                
                fig_csat_avg = px.bar(
                    csat_por_motivo, 
                    x="CSAT Nota", 
                    y="Motivo de Contato", 
                    orientation='h',
                    text_auto='.2f',
                    title="Média de Nota por Motivo (Do pior para o melhor)",
                    color="CSAT Nota",
                    color_continuous_scale="RdYlGn", # Escala Vermelho-Amarelo-Verde
                    range_color=[1, 5]               # Trava a escala: 1 é sempre vermelho, 5 é sempre verde
                )
                    
                fig_csat_avg.update_layout(coloraxis_showscale=False) 
                    
                st.plotly_chart(fig_csat_avg, use_container_width=True)
                st.divider()
                
                # Gráfico 2: Volume de Avaliações por Motivo (Cruzamento)
                st.subheader("Volume de Avaliações por Nota e Motivo")
                
                df_csat["Nota Label"] = df_csat["CSAT Nota"].astype(int).astype(str)
                
                # --- CÁLCULO DE PORCENTAGEM PARA O CSAT ---
                csat_grouped = df_csat.groupby(["Motivo de Contato", "Nota Label"]).size().reset_index(name='Qtd')
                csat_grouped['Total_Motivo'] = csat_grouped.groupby("Motivo de Contato")['Qtd'].transform('sum')
                csat_grouped['Label_Pct'] = csat_grouped.apply(
                    lambda x: f"{x['Qtd']} ({(x['Qtd']/x['Total_Motivo']*100):.0f}%)", axis=1
                )
                
                fig_csat_vol = px.bar(
                    csat_grouped, 
                    x="Qtd", # Para barras horizontais empilhadas, X é a quantidade
                    y="Motivo de Contato", 
                    color="Nota Label", 
                    text="Label_Pct",
                    orientation='h', # Barras deitadas facilitam a leitura dos textos
                    category_orders={"Nota Label": ["1", "2", "3", "4", "5"]},
                    color_discrete_map={"1": "#FF4B4B", "2": "#FF8C00", "3": "#FFD700", "4": "#9ACD32", "5": "#008000"}
                )
                fig_csat_vol.update_layout(yaxis={'categoryorder':'total ascending'})
                st.plotly_chart(fig_csat_vol, use_container_width=True)

            else:
                st.warning("Coluna 'Motivo de Contato' não encontrada para cruzar.")
                
    with tab_grafico:
        c1, c2 = st.columns([2, 1])
        with c1:
            if cols_usuario:
                graf_sel = st.selectbox("Atributo:", cols_usuario, key="sel_bar")
                
                df_clean = df[df[graf_sel].notna()]
                contagem = df_clean[graf_sel].value_counts().reset_index()
                contagem.columns = ["Opção", "Quantidade"]
                
                # --- CÓDIGO NOVO COMEÇA AQUI ---
                
                # 1. Calculamos o total de registros visíveis
                total_registros = contagem["Quantidade"].sum()
                
                # 2. Criamos uma coluna nova com o texto formatado: "145 (73.2%)"
                contagem["Texto_Label"] = contagem["Quantidade"].apply(
                    lambda x: f"{x} ({(x / total_registros * 100):.1f}%)"
                )
                
                fig_bar = px.bar(
                    contagem, 
                    x="Opção", 
                    y="Quantidade", 
                    text="Texto_Label", # Trocamos 'text_auto=True' pela nossa coluna personalizada
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
        
        # --- GRÁFICO 1: RANKING GERAL COM PORCENTAGEM ---
        vol_por_agente = df['Atendente'].value_counts().reset_index()
        vol_por_agente.columns = ['Agente', 'Volume']
        
        total_geral_agentes = vol_por_agente['Volume'].sum()
        vol_por_agente['Label'] = vol_por_agente['Volume'].apply(
            lambda x: f"{x} ({(x/total_geral_agentes*100):.1f}%)"
        )
        
        c1, c2 = st.columns([2, 1])
        c1.plotly_chart(
            px.bar(vol_por_agente, x='Agente', y='Volume', title="Volume de Conversas por Agente", text='Label'), 
            use_container_width=True
        )
        
        c2.write("Ranking:")
        c2.dataframe(vol_por_agente[['Agente', 'Volume']], hide_index=True, use_container_width=True)
        
        st.divider()
        st.subheader("🕵️ Detalhe por Agente")
        
        opcoes_cruzamento = ["Status do atendimento"] + [c for c in cols_usuario if c != "Status do atendimento"]
        cruzamento_agente = st.selectbox("Cruzar Atendente com:", opcoes_cruzamento, key="sel_cruzamento_agente")
        
        if cruzamento_agente in df.columns:
            df_agente_cross = df.dropna(subset=[cruzamento_agente])
            
            # --- GRÁFICO 2: DETALHE COLORIDO COM PORCENTAGEM ---
            # Agrupamos para calcular a porcentagem DENTRO da barra de cada agente
            agrupado = df_agente_cross.groupby(["Atendente", cruzamento_agente]).size().reset_index(name='Qtd')
            
            # Calcula o total de cada agente para saber quanto aquele pedacinho representa do total dele
            agrupado['Total_Agente'] = agrupado.groupby("Atendente")['Qtd'].transform('sum')
            
            # Cria a etiqueta: "10 (20%)"
            agrupado['Label'] = agrupado.apply(
                lambda x: f"{x['Qtd']} ({(x['Qtd'] / x['Total_Agente'] * 100):.1f}%)", axis=1
            )
            
            fig_ag = px.bar(
                agrupado, 
                x="Atendente", 
                y="Qtd", 
                color=cruzamento_agente, 
                text="Label",
                title=f"Distribuição de {cruzamento_agente} por Agente"
            )
            st.plotly_chart(fig_ag, use_container_width=True)

    with tab_cruzamento:
        st.info("Relação entre os campos (Porcentagem relativa ao total da barra).")
        has_motivo = "Motivo de Contato" in df.columns
        has_status = "Status do atendimento" in df.columns
        has_tipo = "Tipo de Atendimento" in df.columns
        has_expansao = COL_EXPANSAO in df.columns
        
        # Função auxiliar para gerar gráfico empilhado com %
        def plot_empilhado_pct(df_input, col_y, col_color, title):
            # 1. Conta
            grouped = df_input.groupby([col_y, col_color]).size().reset_index(name='Qtd')
            # 2. Calcula total da barra (para a %)
            grouped['Total_Grupo'] = grouped.groupby(col_y)['Qtd'].transform('sum')
            # 3. Formata texto
            grouped['Label'] = grouped.apply(lambda x: f"{x['Qtd']} ({(x['Qtd']/x['Total_Grupo']*100):.0f}%)", axis=1)
            # 4. Plota
            fig = px.bar(grouped, y=col_y, x='Qtd', color=col_color, text='Label', orientation='h', title=title, height=600)
            fig.update_layout(yaxis={'categoryorder':'total ascending'})
            return fig

        if has_motivo and has_status:
            st.subheader("Status x Motivo")
            df_cross = df.dropna(subset=["Motivo de Contato", "Status do atendimento"])
            fig1 = plot_empilhado_pct(df_cross, "Motivo de Contato", "Status do atendimento", "Status por Motivo")
            st.plotly_chart(fig1, use_container_width=True)
            st.divider()

        if has_motivo and has_tipo:
            st.subheader("Tipo de Atendimento x Motivo")
            df_cross2 = df.dropna(subset=["Motivo de Contato", "Tipo de Atendimento"])
            fig2 = plot_empilhado_pct(df_cross2, "Motivo de Contato", "Tipo de Atendimento", "Tipo por Motivo")
            st.plotly_chart(fig2, use_container_width=True)
            st.divider()

        if has_motivo and has_expansao:
            st.subheader(f"{COL_EXPANSAO} x Motivo")
            df_cross3 = df.dropna(subset=["Motivo de Contato", COL_EXPANSAO])
            fig3 = plot_empilhado_pct(df_cross3, "Motivo de Contato", COL_EXPANSAO, "Expansão por Motivo")
            st.plotly_chart(fig3, use_container_width=True)

    with tab_motivos:
        st.markdown("### 🔗 Análise Unificada de Motivos")
        col_m1 = "Motivo de Contato"
        col_m2 = "Motivo 2 (Se houver)"
        
        if col_m1 in df.columns and col_m2 in df.columns:
            lista_geral = pd.concat([df[col_m1], df[col_m2]])
            ranking_global = lista_geral.value_counts().reset_index()
            ranking_global.columns = ["Motivo Unificado", "Incidência Total"]
            ranking_global = ranking_global.sort_values(by="Incidência Total", ascending=True)
            
            # CÁLCULO DA PORCENTAGEM
            total_motivos = ranking_global["Incidência Total"].sum()
            ranking_global["Label"] = ranking_global["Incidência Total"].apply(
                lambda x: f"{x} ({(x/total_motivos*100):.1f}%)"
            )
            
            c_rank1, c_rank2 = st.columns([2, 1])
            with c_rank1:
                altura_dinamica = max(400, len(ranking_global) * 30)
                
                fig_global = px.bar(
                    ranking_global, 
                    x="Incidência Total", 
                    y="Motivo Unificado", 
                    orientation='h', 
                    text="Label", # Usamos nossa etiqueta nova
                    title="Todos os Motivos (Somando Motivo 1 + 2)",
                    height=altura_dinamica
                )
                fig_global.update_layout(yaxis={'type': 'category'})
                st.plotly_chart(fig_global, use_container_width=True)
            with c_rank2:
                st.dataframe(ranking_global.sort_values(by="Incidência Total", ascending=False)[["Motivo Unificado", "Incidência Total"]], use_container_width=True, hide_index=True)
        else:
            st.error("As colunas de Motivo 1 e Motivo 2 não foram encontradas.")

    with tab_tabela:
        if "CSAT Nota" not in df.columns:
            st.warning("⚠️ As colunas de CSAT não aparecem porque os dados na memória são antigos.")
            st.info("👉 Clique em 'Limpar Cache' e depois em 'Gerar Dados' para atualizar.")
            st.stop() # Para a execução aqui até você atualizar
        c1, c2 = st.columns([3, 1])
        with c1:
            f1, f2 = st.columns(2)
            ocultar_vazios = f1.checkbox("Ocultar vazios", value=True, key="chk_ocultar_vazios")
            ver_complexas = f2.checkbox("🔥 Apenas complexas (2+ atributos)", key="chk_ver_complexas")
        with c2:
            excel_data = gerar_excel_multias(df, cols_usuario)
            st.download_button("📥 Baixar Excel", data=excel_data, file_name="relatorio_completo.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", type="primary")

        df_view = df.copy()
        
        if ocultar_vazios: df_view = df_view[df_view["Qtd. Atributos"] > 0]
        if ver_complexas: df_view = df_view[df_view["Qtd. Atributos"] >= 2]

        st.divider()
        st.caption("🔎 Filtros Avançados (Cascata)")
        
        # NÍVEL 1
        col_f1, col_v1 = st.columns(2)
        with col_f1:
            # ALTERAÇÃO AQUI: Index fixo em 0 para iniciar sempre como "(Todos)"
            coluna_1 = st.selectbox(
                "1º Filtro (Principal):", 
                ["(Todos)"] + cols_usuario, 
                index=0, 
                key="filtro_coluna_1"
            )
        
        with col_v1:
            if coluna_1 != "(Todos)":
                opcoes_1 = sorted(df_view[coluna_1].astype(str).unique().tolist())
                valores_1 = st.multiselect(f"Selecione valores em '{coluna_1}':", options=opcoes_1, key="filtro_valores_1")
                if valores_1:
                    df_view = df_view[df_view[coluna_1].astype(str).isin(valores_1)]

        # NÍVEL 2
        if coluna_1 != "(Todos)":
            st.markdown("⬇️ *E dentro destes resultados...*")
            col_f2, col_v2 = st.columns(2)
            
            with col_f2:
                # Remove a coluna já usada no nível 1 das opções do nível 2
                cols_restantes = [c for c in cols_usuario if c != coluna_1]
                
                # Mantém o padrão "(Nenhum)" (index 0) para não expandir automaticamente
                coluna_2 = st.selectbox(
                    "2º Filtro (Refinamento):", 
                    ["(Nenhum)"] + cols_restantes, 
                    index=0, 
                    key="filtro_coluna_2"
                )

            with col_v2:
                if coluna_2 != "(Nenhum)":
                    opcoes_2 = sorted(df_view[coluna_2].astype(str).unique().tolist())
                    
                    # A chave dinâmica garante que o widget se recrie corretamente se a coluna mudar
                    key_dinamica = f"filtro_valores_v2_{coluna_2}"
                    
                    valores_2 = st.multiselect(f"Selecione valores em '{coluna_2}':", options=opcoes_2, key=key_dinamica)
                    if valores_2:
                         df_view = df_view[df_view[coluna_2].astype(str).isin(valores_2)]

        # --- Exibição da Tabela ---
        st.divider()
        st.write(f"**Resultados encontrados:** {len(df_view)}")
        
        # Lista de colunas que você quer que apareçam SEMPRE
        fixas = ["Data", "Atendente", "CSAT Nota", "CSAT Comentario", "Link"]
        
        # Garante que elas existem no DataFrame antes de tentar mostrar
        fixas_existentes = [c for c in fixas if c in df_view.columns]
        
        # Remove duplicatas caso você também tenha selecionado elas no filtro
        extras = [c for c in cols_usuario if c not in fixas_existentes]
        
        cols_display = fixas_existentes + extras

        st.dataframe(
            df_view[cols_display], 
            use_container_width=True,
            column_config={
                "Link": st.column_config.LinkColumn("Link", display_text="🔗 Abrir"),
                "CSAT Nota": st.column_config.NumberColumn("CSAT", format="%d ⭐"), # Formatação bonitinha opcional
                "CSAT Comentario": st.column_config.TextColumn("Comentário", width="medium")
            }
        )
