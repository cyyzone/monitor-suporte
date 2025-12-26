import streamlit as st
import requests
import pandas as pd
import plotly.express as px
from datetime import datetime, timedelta, timezone

# --- Configs da Página ---
st.set_page_config(page_title="Ponto & Status (Gráfico)", page_icon="📊", layout="wide")

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
    # Buffer de segurança
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
    
    # 1. Extração
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
            
    if not eventos: return pd.DataFrame(), pd.DataFrame()
    
    df_raw = pd.DataFrame(eventos)
    df_raw = df_raw.sort_values(by=['Agente', 'Timestamp'])
    
    ciclos_fechados = []
    resumo_horas = {}
    
    agentes_unicos = df_raw['Agente'].unique()
    
    for agente in agentes_unicos:
        logs_agente = df_raw[df_raw['Agente'] == agente].sort_values('Timestamp')
        
        inicio_ausencia = None
        tempo_acumulado_segundos = 0
        
        for index, row in logs_agente.iterrows():
            if row['IsAway'] == True:
                inicio_ausencia = row['Timestamp']
            
            elif row['IsAway'] == False and inicio_ausencia:
                fim_ausencia = row['Timestamp']
                
                # Data da volta (para agrupar no gráfico)
                dt_volta_obj = datetime.fromtimestamp(fim_ausencia, tz=FUSO_BR)
                dt_volta_str = dt_volta_obj.strftime("%d/%m/%Y")
                dt_volta_date = dt_volta_obj.date()
                
                # Filtro de Data (ignora ausências velhas)
                if dt_volta_date >= data_inicio_filtro:
                    duracao_seg = fim_ausencia - inicio_ausencia
                    tempo_acumulado_segundos += duracao_seg
                    
                    ciclos_fechados.append({
                        "Agente": agente,
                        "Data": dt_volta_str, # Usado no gráfico
                        "Início": datetime.fromtimestamp(inicio_ausencia, tz=FUSO_BR).strftime("%d/%m %H:%M"),
                        "Fim": datetime.fromtimestamp(fim_ausencia, tz=FUSO_BR).strftime("%d/%m %H:%M"),
                        "Duração (min)": round(duracao_seg/60, 0),
                        "Duração (h)": round(duracao_seg/3600, 2)
                    })
                
                inicio_ausencia = None 

        # Totais Gerais
        if tempo_acumulado_segundos > 0:
            minutos = tempo_acumulado_segundos / 60
            resumo_horas[agente] = {
                "Horas Totais": round(minutos/60, 2),
                "Minutos Totais": round(minutos, 0)
            }

    df_ciclos = pd.DataFrame(ciclos_fechados)
    df_totais = pd.DataFrame.from_dict(resumo_horas, orient='index').reset_index()
    if not df_totais.empty:
        df_totais.columns = ['Agente', 'Horas', 'Minutos']

    return df_ciclos, df_totais

# --- Interface ---
st.title("📊 Gráfico de Ausências (Com Filtro)")
st.markdown("Analise o tempo de ausência dia a dia e filtre conforme necessário.")

with st.form("form_periodo"):
    datas = st.date_input(
        "Selecione o Período Geral:",
        value=(datetime.now() - timedelta(days=2), datetime.now()),
        format="DD/MM/YYYY"
    )
    btn = st.form_submit_button("Gerar Relatório")

# --- LÓGICA DE PERSISTÊNCIA (SESSION STATE) ---
if btn:
    # 1. Busca os Dados
    if isinstance(datas, tuple):
        d_inicio = datas[0]
        d_fim = datas[1] if len(datas) > 1 else datas[0]
    else:
        d_inicio = d_fim = datas

    # Buffer de 3 dias para pegar inícios pendentes
    buffer_dias = 3 
    dt_api_start = datetime.combine(d_inicio - timedelta(days=buffer_dias), datetime.min.time()).replace(tzinfo=FUSO_BR)
    dt_api_end = datetime.combine(d_fim, datetime.max.time()).replace(tzinfo=FUSO_BR)
    
    ts_start = int(dt_api_start.timestamp())
    ts_end = int(dt_api_end.timestamp())

    progresso = st.progress(0, text="Conectando API...")
    admins = get_admin_names()
    logs = fetch_activity_logs(ts_start, ts_end, progresso)
    
    # 2. Processa e Salva no State
    if logs:
        df_detalhado, df_resumo = processar_ciclos(logs, admins, d_inicio)
        st.session_state['dados_status'] = {
            'detalhado': df_detalhado,
            'resumo': df_resumo
        }
    else:
        st.error("Sem logs encontrados.")
        if 'dados_status' in st.session_state:
            del st.session_state['dados_status'] # Limpa se der erro

# --- EXIBIÇÃO (Fora do if btn) ---
if 'dados_status' in st.session_state:
    dados = st.session_state['dados_status']
    df_detalhado = dados['detalhado']
    df_resumo = dados['resumo']
    
    # --- GRÁFICO ---
    if not df_detalhado.empty:
        st.divider()
        
        # 1. Filtro de Dias para o Gráfico (Agora funciona!)
        todas_datas = sorted(df_detalhado['Data'].unique())
        st.subheader("📈 Análise Visual")
        
        dias_selecionados = st.multiselect(
            "Filtrar dias no gráfico:",
            options=todas_datas,
            default=todas_datas, 
            placeholder="Selecione os dias..."
        )
        
        # Filtra baseado na seleção
        if dias_selecionados:
            df_chart = df_detalhado[df_detalhado['Data'].isin(dias_selecionados)]
        else:
            df_chart = df_detalhado # Se desmarcar tudo, mostra tudo (ou nada, como preferir)
        
        if not df_chart.empty:
            df_grouped = df_chart.groupby(['Data', 'Agente'])['Duração (h)'].sum().reset_index()
            
            fig = px.bar(
                df_grouped, 
                x="Data", 
                y="Duração (h)", 
                color="Agente", 
                text="Duração (h)",
                title="Horas Totais de Ausência por Dia",
                barmode="group",
                color_discrete_sequence=px.colors.qualitative.Pastel
            )
            fig.update_traces(texttemplate='%{text:.1f}h', textposition='outside')
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Nenhum dado para os dias selecionados.")
            
        st.divider()

    # --- TABELAS ---
    tab1, tab2 = st.tabs(["⏱️ Resumo Total", "📝 Detalhe dos Ciclos"])
    
    with tab1:
        if not df_resumo.empty:
            st.dataframe(
                df_resumo.sort_values('Horas', ascending=False), 
                use_container_width=True, 
                hide_index=True,
                column_config={"Horas": st.column_config.NumberColumn("Total Horas", format="%.2f h")}
            )
        else:
            st.warning("Nenhuma ausência contabilizada.")
            
    with tab2:
        if not df_detalhado.empty:
            st.dataframe(
                df_detalhado[['Agente', 'Data', 'Início', 'Fim', 'Duração (min)']], 
                use_container_width=True, 
                hide_index=True
            )
        else:
            st.info("Sem dados detalhados.")

elif not btn:
    st.info("👆 Selecione o período e clique em 'Gerar Relatório'.")
