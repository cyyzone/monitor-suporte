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

        # --- CAPTURA DO CSAT ---
        rating_data = c.get('conversation_rating') or {}
        csat_score = rating_data.get('rating') 
        csat_comment = rating_data.get('remark')
        
        # --- NOVO: CAPTURA DE TEMPOS (SLA) ---
        stats = c.get('statistics') or {}
        
        # Tempo para primeira resposta (em segundos) -> Converter para minutos
        time_reply_sec = stats.get('time_to_admin_reply')
        time_reply_min = round(time_reply_sec / 60, 1) if time_reply_sec else None
        
        # Tempo total para resolução (em segundos) -> Converter para minutos
        time_close_sec = stats.get('time_to_close')
        time_close_min = round(time_close_sec / 60, 1) if time_close_sec else None
        # -----------------------------

        row = {
            "ID": c['id'],
            "timestamp_real": c['created_at'], 
            "Data": datetime.fromtimestamp(c['created_at']).strftime("%d/%m/%Y %H:%M"),
            "Data_Dia": datetime.fromtimestamp(c['created_at']).strftime("%Y-%m-%d"),
            "Atendente": assignee_name,
            "Link": link,
            "CSAT Nota": csat_score,
            "CSAT Comentario": csat_comment,
            "Tempo Resposta (min)": time_reply_min,
            "Tempo Resolução (min)": time_close_min
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
        # Adicionei colunas de tempo na exportação
        cols_fixas = ["Data", "Atendente", "Tempo Resposta (min)", "Tempo Resolução (min)", "CSAT Nota", "CSAT Comentario", "Link", "Qtd. Atributos"]
        cols_extras = [c for c in colunas_selecionadas if c not in cols_fixas]
        cols_finais = cols_fixas + cols_extras
        
        cols_existentes = [c for c in cols_finais if c in df.columns]
        
        df[cols_existentes].to_excel(writer, index=False, sheet_name='Base Completa')
        writer.sheets['Base Completa'].set_column('A:A', 18) 
        
    return output.getvalue()

# --- INTERFACE ---

st.title(f"📊 Relatório de Atributos + SLA")

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
    
    with st.spinner("Analisando dados atuais e passados..."):
        mapa = get_attribute_definitions()
        admins_map = get_all_admins()
        
        # 1. Busca Período Atual
        raw = fetch_conversations(start, end, ids_times)
        
        # 2. Busca Período Anterior (Para Delta)
        # Calcula quantos dias tem no intervalo selecionado
        delta_days = (end - start).days + 1
        prev_end = start - timedelta(days=1)
        prev_start = prev_end - timedelta(days=delta_days - 1)
        
        raw_prev = fetch_conversations(prev_start, prev_end, ids_times)
        
        if raw:
            df = process_data(raw, mapa, admins_map)
            df_prev = process_data(raw_prev, mapa, admins_map) if raw_prev else pd.DataFrame()
            
            st.session_state['df_final'] = df
            st.session_state['df_prev'] = df_prev # Salva o anterior na memória tbm
            
            try:
                st.toast(f"✅ Sucesso! {len(df)} conversas carregadas.")
            except:
                st.sidebar.success(f"✅ Sucesso! {len(df)} conversas carregadas.")
            
        else:
            st.warning("Nenhum dado encontrado para o período selecionado.")

if 'df_final' in st.session_state:
    df = st.session_state['df_final']
    df_prev = st.session_state.get('df_prev', pd.DataFrame())
    
    st.divider()
    
    # --- SELEÇÃO DE COLUNAS ---
    todas_colunas = list(df.columns)
    
    COL_EXPANSAO = "Expansão (Passagem de bastão para CSM)"
    sugestao = ["Tipo de Atendimento", COL_EXPANSAO, "Motivo de Contato", "Motivo 2 (Se houver)", "Status do atendimento"]
    padrao_existente = [c for c in sugestao if c in todas_colunas]
    
    cols_usuario = st.multiselect(
        "Selecione os atributos para análise:",
        options=[c for c in todas_colunas if c not in ["ID", "timestamp_real", "Data", "Data_Dia", "Link", "Qtd. Atributos", "Atendente", "CSAT Nota", "CSAT Comentario", "Tempo Resposta (min)", "Tempo Resolução (min)"]],
        default=padrao_existente,
        key="seletor_colunas_principal"
    )

    # --- CÁLCULO DE COMPLEXIDADE ---
    if cols_usuario:
        ignorar_na_conta = ["Status do atendimento", "Tipo de Atendimento", "Atendente", "Data", "Data_Dia", "Link", "timestamp_real", "ID", "CSAT Nota", "CSAT Comentario", "Tempo Resposta (min)", "Tempo Resolução (min)"]
        cols_para_contar = [c for c in cols_usuario if c not in ignorar_na_conta]
        
        if cols_para_contar:
            df["Qtd. Atributos"] = df[cols_para_contar].notna().sum(axis=1)
        else:
            df["Qtd. Atributos"] = 0
    else:
        df["Qtd. Atributos"] = 0

    # --- RESUMO EXECUTIVO COM DELTA ---
    st.markdown("### 📌 Resumo do Período")
    
    kpi1, kpi2, kpi3, kpi4 = st.columns(4)
    
    # KPIs Atuais
    total_conv = len(df)
    preenchidos = df["Motivo de Contato"].notna().sum() if "Motivo de Contato" in df.columns else 0
    taxa_classif = (preenchidos / total_conv * 100) if total_conv > 0 else 0
    
    # KPIs Anteriores (Para Delta)
    total_conv_prev = len(df_prev)
    preenchidos_prev = df_prev["Motivo de Contato"].notna().sum() if "Motivo de Contato" in df_prev.columns else 0
    
    # Cálculos de Delta
    delta_total = total_conv - total_conv_prev
    delta_preenchidos = preenchidos - preenchidos_prev
    
    resolvidos = 0
    resolvidos_prev = 0
    if "Status do atendimento" in df.columns:
        resolvidos = df[df["Status do atendimento"] == "Resolvido"].shape[0]
    if not df_prev.empty and "Status do atendimento" in df_prev.columns:
        resolvidos_prev = df_prev[df_prev["Status do atendimento"] == "Resolvido"].shape[0]
    
    delta_resolvidos = resolvidos - resolvidos_prev
    
    # KPI 4: Tempo Médio de Resolução
    tempo_medio = df["Tempo Resolução (min)"].mean() if "Tempo Resolução (min)" in df.columns else 0
    tempo_medio_prev = df_prev["Tempo Resolução (min)"].mean() if not df_prev.empty and "Tempo Resolução (min)" in df_prev.columns else 0
    delta_tempo = tempo_medio - tempo_medio_prev # Se aumentou é vermelho (ruim), mas o streamlit trata delta positivo como verde padrão. Vamos inverter a cor manualmente se der.

    kpi1.metric("Total Conversas", total_conv, delta=delta_total)
    kpi2.metric("Classificados", f"{preenchidos}", delta=delta_preenchidos)
    kpi3.metric("Resolvidos", resolvidos, delta=delta_resolvidos)
    kpi4.metric("Tempo Médio Resolução", f"{tempo_medio:.1f} min", delta=f"{delta_tempo:.1f} min", delta_color="inverse") # inverse: se subir fica vermelho

    st.divider()

    # --- ABAS DE ANÁLISE ---
    tab_grafico, tab_equipe, tab_cruzamento, tab_motivos, tab_csat, tab_tempo, tab_tabela = st.tabs(["📊 Distribuição", "👥 Equipe", "🔀 Cruzamentos", "🔗 Motivo x Motivo", "⭐ CSAT", "⏱️ Tempo & SLA", "📋 Detalhes & Export"])

    # ... [ABAS EXISTENTES] ... 
    # (Mantendo o código otimizado que já fizemos)

    with tab_grafico:
        c1, c2 = st.columns([2, 1])
        with c1:
            if cols_usuario:
                graf_sel = st.selectbox("Atributo:", cols_usuario, key="sel_bar")
                df_clean = df[df[graf_sel].notna()]
                contagem = df_clean[graf_sel].value_counts().reset_index()
                contagem.columns = ["Opção", "Quantidade"]
                total_registros = contagem["Quantidade"].sum()
                contagem["Texto_Label"] = contagem["Quantidade"].apply(lambda x: f"{x} ({(x / total_registros * 100):.1f}%)")
                altura_dinamica = max(400, 150 + (len(contagem) * 35))
                fig_bar = px.bar(contagem, x="Quantidade", y="Opção", text="Texto_Label", title=f"Distribuição: {graf_sel}", orientation='h', height=altura_dinamica)
                fig_bar.update_layout(yaxis={'categoryorder':'total ascending'})
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
        total_geral_agentes = vol_por_agente['Volume'].sum()
        vol_por_agente['Label'] = vol_por_agente['Volume'].apply(lambda x: f"{x} ({(x/total_geral_agentes*100):.1f}%)")
        c1, c2 = st.columns([2, 1])
        c1.plotly_chart(px.bar(vol_por_agente, x='Agente', y='Volume', title="Volume de Conversas por Agente", text='Label'), use_container_width=True)
        c2.dataframe(vol_por_agente[['Agente', 'Volume']], hide_index=True, use_container_width=True)
        st.divider()
        st.subheader("🕵️ Detalhe por Agente")
        opcoes_cruzamento = ["Status do atendimento"] + [c for c in cols_usuario if c != "Status do atendimento"]
        cruzamento_agente = st.selectbox("Cruzar Atendente com:", opcoes_cruzamento, key="sel_cruzamento_agente")
        if cruzamento_agente in df.columns:
            df_agente_cross = df.dropna(subset=[cruzamento_agente])
            agrupado = df_agente_cross.groupby(["Atendente", cruzamento_agente]).size().reset_index(name='Qtd')
            agrupado['Total_Agente'] = agrupado.groupby("Atendente")['Qtd'].transform('sum')
            agrupado['Label'] = agrupado.apply(lambda x: f"{x['Qtd']} ({(x['Qtd'] / x['Total_Agente'] * 100):.1f}%)", axis=1)
            fig_ag = px.bar(agrupado, x="Atendente", y="Qtd", color=cruzamento_agente, text="Label", title=f"Distribuição de {cruzamento_agente} por Agente")
            st.plotly_chart(fig_ag, use_container_width=True)

    with tab_cruzamento:
        def plot_empilhado_pct(df_input, col_y, col_color, title):
            grouped = df_input.groupby([col_y, col_color]).size().reset_index(name='Qtd')
            grouped['Total_Grupo'] = grouped.groupby(col_y)['Qtd'].transform('sum')
            grouped['Label'] = grouped.apply(lambda x: f"{x['Qtd']} ({(x['Qtd']/x['Total_Grupo']*100):.0f}%)", axis=1)
            qtd_categorias_y = grouped[col_y].nunique()
            altura = max(500, 100 + (qtd_categorias_y * 30))
            fig = px.bar(grouped, y=col_y, x='Qtd', color=col_color, text='Label', orientation='h', title=title, height=altura)
            fig.update_layout(yaxis={'categoryorder':'total ascending'})
            return fig
        if "Motivo de Contato" in df.columns and "Status do atendimento" in df.columns:
            st.plotly_chart(plot_empilhado_pct(df.dropna(subset=["Motivo de Contato", "Status do atendimento"]), "Motivo de Contato", "Status do atendimento", "Status por Motivo"), use_container_width=True)
        if "Motivo de Contato" in df.columns and "Tipo de Atendimento" in df.columns:
            st.plotly_chart(plot_empilhado_pct(df.dropna(subset=["Motivo de Contato", "Tipo de Atendimento"]), "Motivo de Contato", "Tipo de Atendimento", "Tipo por Motivo"), use_container_width=True)
        if "Motivo de Contato" in df.columns and COL_EXPANSAO in df.columns:
            st.plotly_chart(plot_empilhado_pct(df.dropna(subset=["Motivo de Contato", COL_EXPANSAO]), "Motivo de Contato", COL_EXPANSAO, "Expansão por Motivo"), use_container_width=True)

    with tab_motivos:
        col_m1, col_m2 = "Motivo de Contato", "Motivo 2 (Se houver)"
        if col_m1 in df.columns and col_m2 in df.columns:
            ranking_global = pd.concat([df[col_m1], df[col_m2]]).value_counts().reset_index()
            ranking_global.columns = ["Motivo Unificado", "Incidência Total"]
            total_motivos = ranking_global["Incidência Total"].sum()
            ranking_global["Label"] = ranking_global["Incidência Total"].apply(lambda x: f"{x} ({(x/total_motivos*100):.1f}%)")
            c_rank1, c_rank2 = st.columns([2, 1])
            with c_rank1:
                fig_global = px.bar(ranking_global, x="Incidência Total", y="Motivo Unificado", orientation='h', text="Label", height=max(500, 100 + (len(ranking_global) * 30)))
                fig_global.update_layout(yaxis={'categoryorder':'total ascending'})
                st.plotly_chart(fig_global, use_container_width=True)
            with c_rank2:
                st.dataframe(ranking_global, use_container_width=True, hide_index=True)

    with tab_csat:
        # (Código CSAT mantido igual)
        if "CSAT Nota" not in df.columns:
             st.warning("Gere os dados novamente.")
        else:
            df_csat = df.dropna(subset=["CSAT Nota"])
            if df_csat.empty:
                st.info("Sem CSAT.")
            else:
                k1, k2 = st.columns(2)
                k1.metric("Média Geral CSAT", f"{df_csat['CSAT Nota'].mean():.2f}/5.0")
                k2.metric("Total de Avaliações", len(df_csat))
                if "Motivo de Contato" in df.columns:
                    csat_por_motivo = df_csat.groupby("Motivo de Contato")["CSAT Nota"].mean().reset_index().sort_values("CSAT Nota")
                    fig_csat_avg = px.bar(csat_por_motivo, x="CSAT Nota", y="Motivo de Contato", orientation='h', text_auto='.2f', color="CSAT Nota", color_continuous_scale="RdYlGn", range_color=[1, 5])
                    fig_csat_avg.update_layout(coloraxis_showscale=False)
                    st.plotly_chart(fig_csat_avg, use_container_width=True)

    # --- NOVA ABA: TEMPO & SLA ---
    with tab_tempo:
        st.header("⏱️ Análise de Tempo e SLA")
        
        # Filtra dados com tempo de resolução
        df_tempo = df.dropna(subset=["Tempo Resolução (min)"])
        
        if df_tempo.empty:
            st.warning("Não há dados de tempo de resolução disponíveis (As conversas podem estar abertas ou a API não retornou as estatísticas).")
        else:
            # Cards de Resumo
            t1, t2, t3 = st.columns(3)
            med_resol = df_tempo["Tempo Resolução (min)"].mean()
            med_resp = df_tempo["Tempo Resposta (min)"].mean()
            
            t1.metric("Tempo Médio de Resolução", f"{med_resol:.1f} min")
            t2.metric("Tempo Médio 1ª Resposta", f"{med_resp:.1f} min")
            t3.metric("Conversas com dados de tempo", len(df_tempo))
            
            st.divider()
            
            # Gráfico 1: Quem é mais rápido? (Média de tempo por Agente)
            st.subheader("⚡ Velocidade por Agente (Tempo de Resolução)")
            tempo_agente = df_tempo.groupby("Atendente")["Tempo Resolução (min)"].mean().reset_index().sort_values("Tempo Resolução (min)")
            
            fig_time_agente = px.bar(
                tempo_agente, 
                x="Tempo Resolução (min)", 
                y="Atendente", 
                orientation='h', 
                text_auto='.1f',
                title="Média de Minutos para Resolver (Menor é melhor)"
            )
            st.plotly_chart(fig_time_agente, use_container_width=True)
            
            # Gráfico 2: Qual motivo demora mais?
            if "Motivo de Contato" in df.columns:
                st.divider()
                st.subheader("🐢 Motivos mais demorados")
                tempo_motivo = df_tempo.groupby("Motivo de Contato")["Tempo Resolução (min)"].mean().reset_index().sort_values("Tempo Resolução (min)", ascending=False)
                
                # Altura dinâmica
                h_motivo = max(400, 100 + (len(tempo_motivo) * 30))
                
                fig_time_motivo = px.bar(
                    tempo_motivo, 
                    x="Tempo Resolução (min)", 
                    y="Motivo de Contato", 
                    orientation='h', 
                    text_auto='.1f',
                    height=h_motivo,
                    title="Média de Minutos por Motivo (Maior é mais complexo)"
                )
                fig_time_motivo.update_layout(yaxis={'categoryorder':'total ascending'})
                st.plotly_chart(fig_time_motivo, use_container_width=True)

    with tab_tabela:
        if "CSAT Nota" not in df.columns:
            st.warning("⚠️ Cache antigo. Limpe o cache.")
            st.stop()
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
        # Filtros e Tabela (mantidos igual ao último código funcional)
        st.write(f"**Resultados encontrados:** {len(df_view)}")
        
        fixas = ["Data", "Atendente", "Tempo Resolução (min)", "CSAT Nota", "Link"]
        fixas_existentes = [c for c in fixas if c in df_view.columns]
        extras = [c for c in cols_usuario if c not in fixas_existentes]
        cols_display = fixas_existentes + extras

        st.dataframe(
            df_view[cols_display], 
            use_container_width=True,
            column_config={
                "Link": st.column_config.LinkColumn("Link", display_text="🔗 Abrir"),
                "CSAT Nota": st.column_config.NumberColumn("CSAT", format="%d ⭐"),
                "Tempo Resolução (min)": st.column_config.NumberColumn("Tempo (min)", format="%.1f min")
            }
        )
