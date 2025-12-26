import streamlit as st
import requests
import pandas as pd
import plotly.express as px
from datetime import datetime, timedelta, timezone

# --- Configs da Página ---
st.set_page_config(page_title="Ponto & Status (Dinâmico)", page_icon="📊", layout="wide")

try:
    TOKEN = st.secrets["INTERCOM_TOKEN"]
except:
    TOKEN = "SEU_TOKEN_AQUI"

headers = {"Authorization": f"Bearer {TOKEN}", "Accept": "application/json"}
FUSO_BR = timezone(timedelta(hours=-3))

# --- Funções ---

def get_admin_names():
    try:
        r = requests.get("https://api.intercom.io/admins", headers=headers)
        return {a['id']: a['name'] for a in r.json().get('admins', [])} if r.status_code == 200 else {}
    except: return {}

def fetch_activity_logs(start_ts, end_ts, progress_bar):
    url = "https://api.intercom.io/admins/activity_logs"
    params = { "created_at_after": start_ts, "created_at_before": end_ts }
    logs = []
    
    r = requests.get(url, headers=headers, params=params)
    if r.status_code != 200: return []
    
    data = r.json()
    logs.extend(data.get('activity_logs', []))
    
    pages = 0
    while data.get('pages', {}).get('next') and pages < 40:
        pages += 1
        progress_bar.progress(pages / 40, text=f"Baixando histórico (Página {pages})...")
        url_next = data['pages']['next']
        r = requests.get(url_next, headers=headers)
        if r.status_code == 200:
            data = r.json()
            logs.extend(data.get('activity_logs', []))
        else: break
            
    progress_bar.progress(1.0, text="Processando dados...")
    return logs

def processar_ciclos(logs, admin_map, data_inicio_filtro):
    eventos = []
    
    for log in logs:
        if log.get('activity_type') == 'admin_away_mode_change':
            aid = log.get('performed_by', {}).get('id')
            ts = log.get('created_at')
            metadata = log.get('metadata', {})
            is_away = metadata.get('away_mode', False)
            
            eventos.append({
                "Agente": admin_map.get(aid, "Desconhecido"),
                "Timestamp": ts,
                "IsAway": is_away
            })
            
    if not eventos: return pd.DataFrame() # Retorna só o detalhado, resumo calculamos na hora
    
    df_raw = pd.DataFrame(eventos)
    df_raw = df_raw.sort_values(by=['Agente', 'Timestamp'])
    
    ciclos_fechados = []
    
    agentes_unicos = df_raw['Agente'].unique()
    
    for agente in agentes_unicos:
        logs_agente = df_raw[df_raw['Agente'] == agente].sort_values('Timestamp')
        inicio_ausencia = None
        
        for index, row in logs_agente.iterrows():
            if row['IsAway'] == True:
                inicio_ausencia = row['Timestamp']
            
            elif row['IsAway'] == False and inicio_ausencia:
                fim_ausencia = row['Timestamp']
                
                # Data da volta
                dt_volta_obj = datetime.fromtimestamp(fim_ausencia, tz=FUSO_BR)
                dt_volta_str = dt_volta_obj.strftime("%d/%m/%Y")
                dt_volta_date = dt_volta_obj.date()
                
                # Filtro de Data (ignora ausências velhas)
                if dt_volta_date >= data_inicio_filtro:
                    duracao_seg = fim_ausencia - inicio_ausencia
                    
                    ciclos_fechados.append({
                        "Agente": agente,
                        "Data": dt_volta_str, # Essencial para o filtro
                        "Início": datetime.fromtimestamp(inicio_ausencia, tz=FUSO_BR).strftime("%d/%m %H:%M"),
                        "Fim": datetime.fromtimestamp(fim_ausencia, tz=FUSO_BR).strftime("%d/%m %H:%M"),
                        "Duração (min)": round(duracao_seg/60, 0),
                        "Duração (h)": round(duracao_seg/3600, 2)
                    })
                
                inicio_ausencia = None 

    df_ciclos = pd.DataFrame(ciclos_fechados)
    return df_ciclos

# --- Interface ---
st.title("📊 Gráfico de Ausências (Totalmente Dinâmico)")
st.markdown("Filtre dias específicos e veja o **Gráfico e as Tabelas** se atualizarem.")

with st.form("form_periodo"):
    datas = st.date_input(
        "1. Selecione o Período Geral (API):",
        value=(datetime.now() - timedelta(days=2), datetime.now()),
        format="DD/MM/YYYY"
    )
    btn = st.form_submit_button("Buscar Dados")

# --- LÓGICA DE DADOS ---
if btn:
    if isinstance(datas, tuple):
        d_inicio = datas[0]
        d_fim = datas[1] if len(datas) > 1 else datas[0]
    else:
        d_inicio = d_fim = datas

    # Buffer de 3 dias
    buffer_dias = 3 
    dt_api_start = datetime.combine(d_inicio - timedelta(days=buffer_dias), datetime.min.time()).replace(tzinfo=FUSO_BR)
    dt_api_end = datetime.combine(d_fim, datetime.max.time()).replace(tzinfo=FUSO_BR)
    
    ts_start = int(dt_api_start.timestamp())
    ts_end = int(dt_api_end.timestamp())

    progresso = st.progress(0, text="Conectando API...")
    admins = get_admin_names()
    logs = fetch_activity_logs(ts_start, ts_end, progresso)
    
    if logs:
        # Processamos apenas a lista detalhada completa
        df_full = processar_ciclos(logs, admins, d_inicio)
        st.session_state['dados_status_v6'] = df_full
    else:
        st.error("Sem logs encontrados.")
        if 'dados_status_v6' in st.session_state:
            del st.session_state['dados_status_v6']

# --- EXIBIÇÃO INTERATIVA ---
if 'dados_status_v6' in st.session_state:
    df_full = st.session_state['dados_status_v6']
    
    if not df_full.empty:
        st.divider()
        
        # --- 2. FILTRO GLOBAL ---
        todas_datas = sorted(df_full['Data'].unique())
        
        col_f1, col_f2 = st.columns([1, 3])
        with col_f1:
            st.markdown("### 🔍 Filtrar Dias")
            st.caption("Selecione os dias para recalcular TUDO (Gráfico e Tabelas).")
            
        with col_f2:
            dias_selecionados = st.multiselect(
                "Dias visíveis:",
                options=todas_datas,
                default=todas_datas, 
                placeholder="Selecione os dias..."
            )
        
        # --- APLICANDO O FILTRO NA BASE ---
        if dias_selecionados:
            df_view = df_full[df_full['Data'].isin(dias_selecionados)]
        else:
            df_view = df_full # Se tirar tudo, mostra tudo (ou poderia mostrar vazio)

        if not df_view.empty:
            
            # --- RECÁLCULO DO RESUMO (Baseado no filtro) ---
            # Agrupa o DF filtrado para gerar os novos totais
            df_resumo_dinamico = df_view.groupby('Agente')['Duração (min)'].sum().reset_index()
            df_resumo_dinamico['Horas'] = round(df_resumo_dinamico['Duração (min)'] / 60, 2)
            df_resumo_dinamico = df_resumo_dinamico.sort_values('Horas', ascending=False)
            
            # --- GRÁFICO ---
            df_grouped_chart = df_view.groupby(['Data', 'Agente'])['Duração (h)'].sum().reset_index()
            
            fig = px.bar(
                df_grouped_chart, 
                x="Data", 
                y="Duração (h)", 
                color="Agente", 
                text="Duração (h)",
                title="Horas Totais (Filtrado)",
                barmode="group",
                color_discrete_sequence=px.colors.qualitative.Pastel
            )
            fig.update_traces(texttemplate='%{text:.1f}h', textposition='outside')
            st.plotly_chart(fig, use_container_width=True)
            
            st.divider()

            # --- TABELAS ATUALIZADAS ---
            tab1, tab2 = st.tabs(["⏱️ Resumo Total (Atualizado)", "📝 Detalhe dos Ciclos (Atualizado)"])
            
            with tab1:
                st.info(f"Mostrando totais para os dias: {', '.join(dias_selecionados)}")
                st.dataframe(
                    df_resumo_dinamico[['Agente', 'Horas', 'Duração (min)']], 
                    use_container_width=True, 
                    hide_index=True,
                    column_config={
                        "Horas": st.column_config.NumberColumn("Total Horas", format="%.2f h"),
                        "Duração (min)": st.column_config.NumberColumn("Total Minutos")
                    }
                )
                    
            with tab2:
                st.dataframe(
                    df_view[['Agente', 'Data', 'Início', 'Fim', 'Duração (min)']], 
                    use_container_width=True, 
                    hide_index=True
                )
        else:
            st.warning("Nenhum dado para os dias selecionados.")
            
    else:
        st.info("Nenhum ciclo de ausência encontrado no período baixado.")

elif not btn:
    st.info("👆 Selecione o período e clique em 'Buscar Dados'.")
