import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timedelta, timezone

# --- Configs da Página ---
st.set_page_config(page_title="Ponto & Status (Período)", page_icon="🗓️", layout="wide")

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
    # Baixa até 50 páginas (buffer grande)
    while data.get('pages', {}).get('next') and pages < 50:
        pages += 1
        progress_bar.progress(pages / 50, text=f"Baixando histórico (Página {pages})...")
        url_next = data['pages']['next']
        r = requests.get(url_next, headers=headers)
        if r.status_code == 200:
            data = r.json()
            logs.extend(data.get('activity_logs', []))
        else: break
            
    progress_bar.progress(1.0, text="Processamento iniciado...")
    return logs

def processar_periodo(logs, admin_map, data_inicio_filtro, data_fim_filtro):
    eventos = []
    
    # 1. Extração
    for log in logs:
        if log.get('activity_type') == 'admin_away_mode_change':
            aid = log.get('performed_by', {}).get('id')
            ts = log.get('created_at')
            metadata = log.get('metadata', {})
            
            # true = Ausente, false = Online
            is_away = metadata.get('away_mode', False)
            
            # --- AJUSTE VISUAL: RECOLOCANDO OS EMOJIS ---
            label_status = "🔴 (Ausente)" if is_away else "🟢 (Online)"
            
            eventos.append({
                "Agente": admin_map.get(aid, "Desconhecido"),
                "Timestamp": ts,
                "DataHora": datetime.fromtimestamp(ts, tz=FUSO_BR),
                "Tipo": label_status
            })
            
    if not eventos: return pd.DataFrame(), pd.DataFrame()
    
    df = pd.DataFrame(eventos)
    df = df.sort_values(by=['Agente', 'Timestamp'])
    
    # 2. Cálculo Lógico (Pareamento)
    resumo_agentes = {}
    agentes_unicos = df['Agente'].unique()
    
    for agente in agentes_unicos:
        logs_agente = df[df['Agente'] == agente].sort_values('Timestamp')
        
        tempo_total_segundos = 0
        inicio_ausencia = None
        
        for index, row in logs_agente.iterrows():
            # --- AJUSTE LÓGICO: O IF TEM QUE BATER COM O TEXTO DO EMOJI ---
            if "🔴 (Ausente)" in row['Tipo']:
                inicio_ausencia = row['Timestamp']
            
            elif "🟢 (Online)" in row['Tipo'] and inicio_ausencia:
                # Fechou o par
                fim_ausencia = row['Timestamp']
                
                # Filtro de Data: Só conta se a volta foi dentro do período escolhido
                dt_evento_fim = datetime.fromtimestamp(fim_ausencia, tz=FUSO_BR).date()
                
                if dt_evento_fim >= data_inicio_filtro:
                    diff = fim_ausencia - inicio_ausencia
                    tempo_total_segundos += diff
                
                inicio_ausencia = None 

        # Salva totais
        minutos = tempo_total_segundos / 60
        resumo_agentes[agente] = {
            "Minutos Totais": round(minutos, 0),
            "Horas Totais": round(minutos/60, 2)
        }

    df_resumo = pd.DataFrame.from_dict(resumo_agentes, orient='index').reset_index()
    if not df_resumo.empty:
        df_resumo.columns = ['Agente', 'Minutos', 'Horas']
    
    return df, df_resumo

# --- Interface ---
st.title("🗓️ Calculadora de Ausência (Com Histórico)")
st.info("Este painel busca dados do dia anterior automaticamente para calcular ausências longas.")

with st.form("form_periodo"):
    datas = st.date_input(
        "Selecione o Período de Análise:",
        value=(datetime.now(), datetime.now()),
        format="DD/MM/YYYY"
    )
    btn = st.form_submit_button("Calcular Tempo Ausente")

if btn:
    if isinstance(datas, tuple):
        d_inicio = datas[0]
        d_fim = datas[1] if len(datas) > 1 else datas[0]
    else:
        d_inicio = d_fim = datas

    # Buffer de 1 dia para pegar o início da ausência (ontem)
    buffer_dias = 1 
    dt_api_start = datetime.combine(d_inicio - timedelta(days=buffer_dias), datetime.min.time()).replace(tzinfo=FUSO_BR)
    dt_api_end = datetime.combine(d_fim, datetime.max.time()).replace(tzinfo=FUSO_BR)
    
    ts_start = int(dt_api_start.timestamp())
    ts_end = int(dt_api_end.timestamp())

    st.caption(f"🔎 Buscando dados desde {dt_api_start.strftime('%d/%m %H:%M')}...")
    
    progresso = st.progress(0, text="Conectando...")
    admins = get_admin_names()
    
    logs_brutos = fetch_activity_logs(ts_start, ts_end, progresso)
    
    if logs_brutos:
        df_log, df_final = processar_periodo(logs_brutos, admins, d_inicio, d_fim)
        
        c1, c2 = st.columns(2)
        
        with c1:
            st.subheader("⏱️ Total de Ausência no Período")
            if not df_final.empty:
                st.dataframe(
                    df_final.sort_values('Horas', ascending=False), 
                    use_container_width=True, 
                    hide_index=True,
                    column_config={"Horas": st.column_config.NumberColumn("Horas", format="%.2f h")}
                )
            else:
                st.warning("Nenhum tempo de ausência contabilizado.")

        with c2:
            st.subheader("📜 Log Detalhado")
            if not df_log.empty:
                df_view = df_log.copy()
                df_view['DataHora'] = df_view['DataHora'].dt.strftime('%d/%m %H:%M')
                st.dataframe(df_view[['DataHora', 'Agente', 'Tipo']], use_container_width=True, hide_index=True)
            else:
                st.info("Sem eventos.")
                
    else:
        st.error("Não encontrei logs. Verifique o período.")
