import streamlit as st
import pandas as pd
import requests
import time
import plotly.express as px
from datetime import datetime, timedelta
from io import BytesIO

# --- CONFIGURAÇÕES ---
st.set_page_config(page_title="Relatório de Atributos Intercom", page_icon="📊", layout="wide")

WORKSPACE_ID = "xwvpdtlu"

try:
    INTERCOM_ACCESS_TOKEN = st.secrets["INTERCOM_TOKEN"]
except:
    INTERCOM_ACCESS_TOKEN = st.sidebar.text_input("Intercom Token", type="password")

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
    
    # Força coluna Motivo 2
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

st.title(f"📊 Relatório de Atributos ({WORKSPACE_ID})")

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
    sugestao = ["Tipo de Atendimento", "Motivo de Contato", "Motivo 2 (Se houver)", "Status do atendimento"]
    padrao_existente = [c for c in sugestao if c in todas_colunas]
    
    cols_usuario = st.multiselect(
        "Selecione os atributos para análise:",
        options=[c for c in todas_colunas if c not in ["ID", "timestamp_real", "Data", "Data_Dia", "Link", "Qtd. Atributos", "Atendente"]],
        default=padrao_existente
    )

    if cols_usuario:
        df["Qtd. Atributos"] = df[cols_usuario].notna().sum(axis=1)
    else:
        df["Qtd. Atributos"] = 0

    # --- RESUMO EXECUTIVO ---
    st.markdown("### 📌 Resumo do Período")
    kpi1, kpi2, kpi3, kpi4 = st.columns(4)
    
    total_conv = len(df)
    preenchidos = df["Motivo de Contato"].notna().sum() if "Motivo de Contato" in df.columns else 0
    taxa_classif = (preenchidos / total_conv * 100) if total_conv > 0 else 0
    
    top_motivo = "N/A"
    if "Motivo de Contato" in df.columns:
        top = df["Motivo de Contato"].value_counts().head(1)
        if not top.empty: 
            # AQUI: Removi o [:20] para mostrar o texto inteiro
            top_motivo = f"{top.index[0]} ({top.values[0]})"

    resolvidos = 0
    if "Status do atendimento" in df.columns:
        resolvidos = df[df["Status do atendimento"] == "Resolvido"].shape[0]

    kpi1.metric("Total Conversas", total_conv)
    kpi2.metric("Classificados", f"{preenchidos}", f"{taxa_classif:.1f}%")
    kpi3.metric("Resolvidos", resolvidos)
    # Mostra o nome do motivo. O .split(">")[-1] pega só a parte final depois da seta. 
    # Se quiser mostrar TUDO (Categoria > Motivo), remova o .split... e deixe só top_motivo
    kpi4.metric("Principal Motivo", top_motivo.split(">")[-1].strip()) 

    st.divider()


    # --- ABAS DE ANÁLISE ---
    tab_grafico, tab_equipe, tab_cruzamento, tab_motivos, tab_tabela = st.tabs(["📊 Distribuição", "👥 Equipe", "🔀 Cruzamentos", "🔗 Motivo x Motivo", "📋 Detalhes & Export"])
    
    with tab_grafico:
        c1, c2 = st.columns([2, 1])
        with c1:
            if cols_usuario:
                graf_sel = st.selectbox("Atributo:", cols_usuario, key="sel_pie")
                df_pie = df[df[graf_sel].notna()]
                fig_pie = px.pie(df_pie, names=graf_sel, hole=0.4, title=f"Distribuição: {graf_sel}")
                fig_pie.update_traces(textposition='inside', textinfo='percent+label')
                fig_pie.update_layout(showlegend=False)
                st.plotly_chart(fig_pie, use_container_width=True)
            else:
                st.warning("Selecione atributos no topo.")
        with c2:
             if cols_usuario:
                 st.write("**Ranking:**")
                 st.dataframe(df[graf_sel].value_counts().head(10), use_container_width=True)

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
        cruzamento_agente = st.selectbox("Cruzar Atendente com:", ["Status do atendimento"] + cols_usuario)
        if cruzamento_agente in df.columns:
            df_agente_cross = df.dropna(subset=[cruzamento_agente])
            fig_ag = px.histogram(df_agente_cross, x="Atendente", color=cruzamento_agente, barmode="group", text_auto=True)
            st.plotly_chart(fig_ag, use_container_width=True)

    with tab_cruzamento:
        st.info("Relação entre os campos (Ex: Quais motivos são mais 'Resolvidos'?).")
        has_motivo = "Motivo de Contato" in df.columns
        has_status = "Status do atendimento" in df.columns
        has_tipo = "Tipo de Atendimento" in df.columns 
        
        if has_motivo and has_status:
            st.subheader("Status x Motivo")
            df_cross = df.dropna(subset=["Motivo de Contato", "Status do atendimento"])
            fig_cross = px.histogram(df_cross, y="Motivo de Contato", color="Status do atendimento", 
                                     barmode="stack", text_auto=True, height=600)
            fig_cross.update_layout(yaxis={'categoryorder':'total ascending'})
            st.plotly_chart(fig_cross, use_container_width=True)
        
        st.divider()

        if has_motivo and has_tipo:
            st.subheader("Tipo de Atendimento x Motivo")
            df_cross2 = df.dropna(subset=["Motivo de Contato", "Tipo de Atendimento"])
            fig_cross2 = px.histogram(df_cross2, y="Motivo de Contato", color="Tipo de Atendimento", 
                                     barmode="stack", text_auto=True, height=600)
            fig_cross2.update_layout(yaxis={'categoryorder':'total ascending'})
            st.plotly_chart(fig_cross2, use_container_width=True)

    with tab_motivos:
        st.markdown("### 🔗 Análise Unificada de Motivos")
        col_m1 = "Motivo de Contato"
        col_m2 = "Motivo 2 (Se houver)"
        if col_m1 in df.columns and col_m2 in df.columns:
            # 1. RANKING GLOBAL
            lista_geral = pd.concat([df[col_m1], df[col_m2]])
            ranking_global = lista_geral.value_counts().reset_index()
            ranking_global.columns = ["Motivo Unificado", "Incidência Total"]
            c_rank1, c_rank2 = st.columns([2, 1])
            with c_rank1:
                fig_global = px.bar(ranking_global.head(15), x="Incidência Total", y="Motivo Unificado", 
                                    orientation='h', text_auto=True, title="Top 15 Motivos (Somando Motivo 1 + 2)")
                fig_global.update_layout(yaxis={'categoryorder':'total ascending'})
                st.plotly_chart(fig_global, use_container_width=True)
            with c_rank2:
                st.dataframe(ranking_global, use_container_width=True, hide_index=True)
            st.divider()
            # 2. MATRIZ
            st.subheader("🧲 Matriz de Combinação")
            df_duplo = df.dropna(subset=[col_m1, col_m2])
            if not df_duplo.empty:
                fig_heat = px.density_heatmap(df_duplo, x=col_m2, y=col_m1, title="Mapa de Calor", color_continuous_scale="Blues")
                st.plotly_chart(fig_heat, use_container_width=True)
            else:
                st.warning("Nenhuma conversa com Motivo 1 e Motivo 2 preenchidos simultaneamente encontrada.")
        else:
            st.error("As colunas de Motivo 1 e Motivo 2 não foram encontradas.")

    with tab_tabela:
        c1, c2 = st.columns([3, 1])
        with c1:
            f1, f2 = st.columns(2)
            ocultar_vazios = f1.checkbox("Ocultar vazios", value=True)
            ver_complexas = f2.checkbox("🔥 Apenas complexas (2+ atributos)")
        with c2:
            excel_data = gerar_excel_multias(df, cols_usuario)
            st.download_button("📥 Baixar Excel", data=excel_data, file_name="relatorio_completo.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", type="primary")

        df_view = df.copy()
        if ocultar_vazios: df_view = df_view[df_view["Qtd. Atributos"] > 0]
        if ver_complexas: df_view = df_view[df_view["Qtd. Atributos"] >= 2]

        cols_display = ["Data", "Atendente", "Link", "Qtd. Atributos"] + cols_usuario
        cols_display = [c for c in cols_display if c in df_view.columns]

        st.dataframe(
            df_view[cols_display], 
            use_container_width=True,
            column_config={
                "Link": st.column_config.LinkColumn("Link", display_text="Abrir"),
                "Qtd. Atributos": st.column_config.ProgressColumn("Info", format="%d", min_value=0, max_value=len(cols_usuario))
            }
        )
