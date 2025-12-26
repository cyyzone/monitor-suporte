import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timedelta, timezone

# --- Configs da Página ---
st.set_page_config(page_title="Ponto & Status", page_icon="🕵️", layout="wide")

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
    # Buffer de segurança (até 30 páginas para não demorar demais)
    while data.get('pages', {}).get('next') and pages < 30:
        pages += 1
        progress_bar.progress(pages / 30, text=f"Baixando histórico (Página {pages})...")
        url_next = data['pages']['next']
        r = requests.get(url_next, headers=headers)
        if r.status_code == 200:
            data = r.json()
            logs.extend(data.get('activity_logs', []))
        else: break
            
    progress_bar.progress(1.0, text="Analisando continuidade...")
    return logs

def processar_ciclos(logs, admin_map, data_inicio_filtro):
    eventos = []
    
    # 1. Transforma JSON em Lista Organizada
    for log in logs:
        if log.get('activity_type') == 'admin_away_mode_change':
            aid = log.get('performed_by', {}).get('id')
            ts = log.get('created_at')
            metadata = log.get('metadata', {})
            
            # true = Ausente (SAIU), false = Online (VOLTOU)
            is_away = metadata.get('away_mode', False)
            
            eventos.append({
                "Agente": admin_map.get(aid, "Desconhecido"),
                "Timestamp": ts,
                "IsAway": is_away
            })
            
    if not eventos: return pd.DataFrame(), pd.DataFrame()
    
    df_raw = pd.DataFrame(eventos)
    # Ordena rigorosamente por Agente e Tempo
    df_raw = df_raw.sort_values(by=['Agente', 'Timestamp'])
    
    ciclos_fechados = []
    resumo_horas = {}
    
    agentes_unicos = df_raw['Agente'].unique()
    
    for agente in agentes_unicos:
        logs_agente = df_raw[df_raw['Agente'] == agente].sort_values('Timestamp')
        
        inicio_ausencia = None
        tempo_acumulado_segundos = 0
        
        for index, row in logs_agente.iterrows():
            # AÇÃO: FICOU AUSENTE
            if row['IsAway'] == True:
                inicio_ausencia = row['Timestamp']
            
            # AÇÃO: VOLTOU ONLINE
            elif row['IsAway'] == False:
                # Se encontrou um "Voltou", ele precisa ter um "Início" guardado (mesmo que seja de ontem)
                if inicio_ausencia:
                    fim_ausencia = row['Timestamp']
                    
                    # --- FILTRO IMPORTANTE ---
                    # Só mostramos se a volta aconteceu dentro do período selecionado
                    # (Ou seja, ignora ausências antigas que já terminaram semana passada)
                    dt_volta = datetime.fromtimestamp(fim_ausencia, tz=FUSO_BR).date()
                    
                    if dt_volta >= data_inicio_filtro:
                        duracao_seg = fim_ausencia - inicio_ausencia
                        tempo_acumulado_segundos += duracao_seg
                        
                        # Adiciona na tabela de detalhes
                        ciclos_fechados.append({
                            "Agente": agente,
                            "Início Ausência": datetime.fromtimestamp(inicio_ausencia, tz=FUSO_BR).strftime("%d/%m %H:%M"),
                            "Fim Ausência": datetime.fromtimestamp(fim_ausencia, tz=FUSO_BR).strftime("%d/%m %H:%M"),
                            "Duração": f"{round(duracao_seg/60, 0):.0f} min"
                        })
                    
                    inicio_ausencia = None # Reseta o ciclo

        # Totais do Agente
        if tempo_acumulado_segundos > 0:
            minutos = tempo_acumulado_segundos / 60
            resumo_horas[agente] = {
                "Horas Totais": round(minutos/60, 2),
                "Minutos Totais": round(minutos, 0)
            }

    # Formata DataFrames para exibição
    df_ciclos = pd.DataFrame(ciclos_fechados)
    
    df_totais = pd.DataFrame.from_dict(resumo_horas, orient='index').reset_index()
    if not df_totais.empty:
        df_totais.columns = ['Agente', 'Horas', 'Minutos']

    return df_ciclos, df_totais

# --- Interface ---
st.title("🕵️ Ponto & Status (Análise de Ciclo)")
st.markdown("Identifica quando o agente **Saiu** (mesmo ontem) e quando **Voltou** (hoje).")

with st.form("form_periodo"):
    datas = st.date_input(
        "Selecione o dia para ver as voltas/ausências:",
        value=(datetime.now(), datetime.now()),
        format="DD/MM/YYYY"
    )
    btn = st.form_submit_button("Calcular")

if btn:
    if isinstance(datas, tuple):
        d_inicio = datas[0]
        d_fim = datas[1] if len(datas) > 1 else datas[0]
    else:
        d_inicio = d_fim = datas

    # --- BUFFER DE SEGURANÇA (3 DIAS) ---
    # Buscamos 3 dias para trás para pegar o "Início" que ficou pendente
    buffer_dias = 3 
    dt_api_start = datetime.combine(d_inicio - timedelta(days=buffer_dias), datetime.min.time()).replace(tzinfo=FUSO_BR)
    dt_api_end = datetime.combine(d_fim, datetime.max.time()).replace(tzinfo=FUSO_BR)
    
    ts_start = int(dt_api_start.timestamp())
    ts_end = int(dt_api_end.timestamp())

    st.caption(f"🔎 Analisando histórico desde {dt_api_start.strftime('%d/%m')} para encontrar a origem das ausências...")
    
    progresso = st.progress(0, text="Conectando...")
    admins = get_admin_names()
    logs = fetch_activity_logs(ts_start, ts_end, progresso)
    
    if logs:
        df_detalhado, df_resumo = processar_ciclos(logs, admins, d_inicio)
        
        tab1, tab2 = st.tabs(["⏱️ Resumo Geral", "📝 Ciclos Detalhados (Início -> Fim)"])
        
        with tab1:
            if not df_resumo.empty:
                st.dataframe(
                    df_resumo.sort_values('Horas', ascending=False), 
                    use_container_width=True, 
                    hide_index=True,
                    column_config={"Horas": st.column_config.NumberColumn("Total Horas", format="%.2f h")}
                )
            else:
                st.warning("Nenhum ciclo de ausência fechado neste período.")
                
        with tab2:
            st.write("Aqui você vê exatamente que horas ele saiu (pode ser ontem) e que horas voltou (hoje).")
            if not df_detalhado.empty:
                st.dataframe(
                    df_detalhado, 
                    use_container_width=True, 
                    hide_index=True
                )
            else:
                st.info("Sem dados detalhados.")
    else:
        st.error("Sem logs encontrados.")
