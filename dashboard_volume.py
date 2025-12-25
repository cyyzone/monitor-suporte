import streamlit as st
import requests
import pandas as pd
import plotly.express as px 
import time
from datetime import datetime, time as dt_time, timedelta, timezone
from collections import Counter

# --- Configs da Página ---
st.set_page_config(page_title="Relatório de Suporte (Unificado)", page_icon="📈", layout="wide")

# Tenta pegar as chaves
try:
    TOKEN = st.secrets["INTERCOM_TOKEN"]
    APP_ID = st.secrets["INTERCOM_APP_ID"]
except:
    TOKEN = "SEU_TOKEN_AQUI"
    APP_ID = "SEU_APP_ID_AQUI"

# LISTA DE TIMES
TEAM_IDS = [2975006, 1972225]

headers = {"Authorization": f"Bearer {TOKEN}", "Accept": "application/json"}
FUSO_BR = timezone(timedelta(hours=-3)) 

# ==========================================
# 1. FUNÇÕES DE COLETA (SEPARADAS PARA PRECISÃO)
# ==========================================

def get_admin_names():
    try:
        r = requests.get("https://api.intercom.io/admins", headers=headers)
        return {a['id']: a['name'] for a in r.json().get('admins', [])} if r.status_code == 200 else {}
    except: return {}

# --- Busca de VOLUME ---
# Regra: Tickets CRIADOS no período (independente de quando terminaram)
def fetch_volume_data(start_ts, end_ts, progress_bar):
    url = "https://api.intercom.io/conversations/search"
    todas_conversas = []
    
    for i, t_id in enumerate(TEAM_IDS):
        payload = {
            "query": {
                "operator": "AND",
                "value": [
                    {"field": "created_at", "operator": ">", "value": start_ts},
                    {"field": "created_at", "operator": "<", "value": end_ts},
                    {"field": "team_assignee_id", "operator": "=", "value": t_id}
                ]
            },
            "pagination": {"per_page": 150}
        }
        
        r = requests.post(url, json=payload, headers=headers)
        if r.status_code != 200: continue
        
        data = r.json()
        total_time = data.get('total_count', 0)
        conversas_time = data.get('conversations', [])
        
        if total_time > 0:
            while data.get('pages', {}).get('next'):
                baixados = len(conversas_time)
                progress_bar.progress(0, text=f"📥 Volume (Time {t_id}): {baixados} de {total_time}...")
                
                payload['pagination']['starting_after'] = data['pages']['next']['starting_after']
                r = requests.post(url, json=payload, headers=headers)
                if r.status_code == 200:
                    data = r.json()
                    conversas_time.extend(data.get('conversations', []))
                else: break
        
        todas_conversas.extend(conversas_time)
            
    return todas_conversas

# --- Busca de CSAT ---
# Regra: Tickets AVALIADOS no período (mesmo que tenham sido criados meses atrás)
def fetch_csat_data(start_ts, end_ts, progress_bar):
    url = "https://api.intercom.io/conversations/search"
    todas_conversas = []
    
    for i, t_id in enumerate(TEAM_IDS):
        # Buscamos por updated_at porque a avaliação é uma atualização
        payload = {
            "query": {
                "operator": "AND",
                "value": [
                    {"field": "updated_at", "operator": ">", "value": start_ts},
                    {"field": "updated_at", "operator": "<", "value": end_ts},
                    {"field": "team_assignee_id", "operator": "=", "value": t_id}
                ]
            },
            "pagination": {"per_page": 150}
        }
        
        r = requests.post(url, json=payload, headers=headers)
        if r.status_code != 200: continue
        
        data = r.json()
        total_time = data.get('total_count', 0)
        conversas_time = data.get('conversations', [])
        
        if total_time > 0:
            while data.get('pages', {}).get('next'):
                baixados = len(conversas_time)
                progress_bar.progress(0, text=f"⭐ CSAT (Time {t_id}): {baixados} de {total_time}...")
                
                payload['pagination']['starting_after'] = data['pages']['next']['starting_after']
                r = requests.post(url, json=payload, headers=headers)
                if r.status_code == 200:
                    data = r.json()
                    conversas_time.extend(data.get('conversations', []))
                else: break
        
        todas_conversas.extend(conversas_time)
            
    return todas_conversas

# ==========================================
# 2. INTERFACE
# ==========================================

st.title("📈 Relatório Unificado de Suporte")
st.markdown("Visão completa de **Volume, Produtividade e Qualidade (CSAT)**.")

with st.sidebar:
    st.header("⚙️ Configuração")
    with st.form("filtro_geral"):
        periodo = st.date_input(
            "📅 Período de Análise:",
            value=(datetime.now() - timedelta(days=7), datetime.now()), 
            format="DD/MM/YYYY"
        )
        st.write("")
        btn_gerar = st.form_submit_button("🔄 Gerar Relatório", type="primary", use_container_width=True)
    
    st.markdown("---")
    st.caption("🔗 **Acesso Rápido:**")
    st.markdown("🚀 [Painel Tempo Real (Operacional)](https://dashboardvisualpy.streamlit.app)")
    st.markdown("⭐ [Painel Focado em CSAT](https://dashboardcsatpy.streamlit.app)")
    st.info(f"ℹ️ **Conexão:** {len(TEAM_IDS)} Equipes monitoradas.")

if btn_gerar:
    # 1. Ajuste de Datas (Fuso Horário BR)
    ts_start, ts_end = 0, 0
    if isinstance(periodo, tuple):
        d_inicio = periodo[0]
        d_fim = periodo[1] if len(periodo) > 1 else periodo[0]
    else:
        d_inicio = d_fim = periodo

    dt_start = datetime.combine(d_inicio, dt_time.min).replace(tzinfo=FUSO_BR)
    dt_end = datetime.combine(d_fim, dt_time.max).replace(tzinfo=FUSO_BR)
    ts_start = int(dt_start.timestamp())
    ts_end = int(dt_end.timestamp())

    # 2. Execução (Buscas Separadas)
    progresso = st.progress(0, text="Iniciando conexão...")
    admins = get_admin_names()
    
    raw_volume = fetch_volume_data(ts_start, ts_end, progresso)
    raw_csat = fetch_csat_data(ts_start, ts_end, progresso)
    
    progresso.progress(1.0, text="Processando dados...")
    time.sleep(0.5)
    progresso.empty()

    tab_vol, tab_csat = st.tabs(["📊 Volume & Produtividade", "⭐ Qualidade (CSAT)"])

    # ==========================================
    # ABA 1: VOLUME
    # ==========================================
    with tab_vol:
        if raw_volume:
            lista_vol = []
            todas_tags = []
            outbound_count = 0 
            
            for c in raw_volume:
                # Filtro Inbound: Ignora conversas iniciadas pelo Admin
                source_author = c.get('source', {}).get('author', {}).get('type')
                if source_author == 'admin':
                    outbound_count += 1
                    continue 
                
                dt_criacao = datetime.fromtimestamp(c['created_at'], tz=FUSO_BR)
                aid = c.get('admin_assignee_id')
                nome_agente = admins.get(str(aid), "Sem Dono / Fila") if aid else "Sem Dono / Fila"
                
                tags_obj = c.get('tags', {})
                nomes_tags = [t['name'] for t in tags_obj.get('tags', [])]
                todas_tags.extend(nomes_tags)
                
                link_url = f"https://app.intercom.com/a/inbox/{APP_ID}/inbox/conversation/{c['id']}"

                lista_vol.append({
                    "DataIso": dt_criacao.date(),
                    "Hora": dt_criacao.hour,
                    "Data": dt_criacao.strftime("%d/%m %H:%M"),
                    "Agente": nome_agente,
                    "Tags": ", ".join(nomes_tags),
                    "Link": link_url,
                    "ID": c['id']
                })
            
            df_vol = pd.DataFrame(lista_vol)
            
            if not df_vol.empty:
                total = len(df_vol)
                qtd_dias = len(df_vol['DataIso'].unique())
                media_dia = total / qtd_dias if qtd_dias > 0 else 0
                
                c1, c2, c3 = st.columns(3)
                c1.metric("Tickets Recebidos (Inbound)", total)
                c2.metric("Média por Dia", f"{media_dia:.1f}")
                c3.metric("Agentes Ativos", df_vol[df_vol['Agente'] != "Sem Dono / Fila"]['Agente'].nunique())
                
                if outbound_count > 0:
                    st.caption(f"ℹ️ {outbound_count} conversas iniciadas por agentes (Outbound) ocultadas.")
                
                st.divider()

                # GRÁFICOS
                col_g1, col_g2 = st.columns(2)
                with col_g1:
                    st.subheader("📅 Volume por Dia")
                    vol_por_dia = df_vol.groupby('DataIso').size().reset_index(name='Tickets')
                    vol_por_dia['Data Formatada'] = vol_por_dia['DataIso'].apply(lambda x: x.strftime("%d/%m"))
                    fig_dias = px.bar(vol_por_dia, x='Data Formatada', y='Tickets', text='Tickets', color='Tickets', color_continuous_scale='Blues')
                    st.plotly_chart(fig_dias, use_container_width=True)
                    
                with col_g2:
                    st.subheader("⏰ Curva de Horário")
                    vol_por_hora = df_vol.groupby('Hora').size().reset_index(name='Volume')
                    fig_hora = px.area(vol_por_hora, x='Hora', y='Volume', markers=True)
                    fig_hora.update_xaxes(tickmode='linear', dtick=1, range=[0, 23])
                    st.plotly_chart(fig_hora, use_container_width=True)
                
                st.divider()

                c_tag, c_agente = st.columns(2)
                with c_tag:
                    st.subheader("🏷️ Top Tags")
                    if todas_tags:
                        contagem_tags = Counter(todas_tags)
                        df_tags = pd.DataFrame(contagem_tags.items(), columns=['Tag', 'Qtd']).sort_values('Qtd', ascending=False).head(10)
                        fig_tags = px.bar(df_tags, x='Qtd', y='Tag', orientation='h', text='Qtd', color='Qtd', color_continuous_scale='Viridis')
                        fig_tags.update_layout(yaxis={'categoryorder':'total ascending'})
                        st.plotly_chart(fig_tags, use_container_width=True)
                    else:
                        st.info("Nenhuma tag encontrada.")

                with c_agente:
                    st.subheader("🏆 Volume por Agente")
                    contagem_agente = df_vol['Agente'].value_counts().reset_index()
                    contagem_agente.columns = ['Agente', 'Tickets']
                    fig_agente = px.bar(contagem_agente, x='Tickets', y='Agente', orientation='h', text='Tickets', color='Tickets', color_continuous_scale='Greens')
                    fig_agente.update_layout(yaxis={'categoryorder':'total ascending'})
                    st.plotly_chart(fig_agente, use_container_width=True)

                st.divider()
                with st.expander("🔎 Ver Tabela de Volume"):
                    st.data_editor(
                        df_vol.sort_values(by=['DataIso', 'Hora'])[['Data', 'Agente', 'Tags', 'Link']],
                        column_config={"Link": st.column_config.LinkColumn("Abrir", display_text="Acessar")},
                        use_container_width=True, hide_index=True
                    )
            else:
                st.warning("Nenhum ticket Inbound encontrado.")
        else:
            st.warning("Nenhum ticket encontrado para Volume.")

    # ==========================================
    # ABA 2: CSAT
    # ==========================================
    with tab_csat:
        if raw_csat:
            stats = {}
            lista_detalhada_csat = [] 
            time_pos, time_neu, time_neg = 0, 0, 0
            
            for c in raw_csat:
                aid = str(c.get('admin_assignee_id'))
                if not aid or not c.get('conversation_rating'): continue
                
                rating_obj = c['conversation_rating']
                nota = rating_obj.get('rating')
                if nota is None: continue
                
                # AQUI É O PULO DO GATO: Filtra pela data da NOTA, não do ticket
                data_nota = rating_obj.get('created_at')
                if not data_nota: continue
                
                if not (ts_start <= data_nota <= ts_end): continue

                if aid not in stats: stats[aid] = {'pos':0, 'neu':0, 'neg':0, 'total':0}
                stats[aid]['total'] += 1
                
                emoji_nota = ""
                if nota >= 4:
                    stats[aid]['pos'] += 1; time_pos += 1; emoji_nota = "😍 Positiva"
                elif nota == 3:
                    stats[aid]['neu'] += 1; time_neu += 1; emoji_nota = "😐 Neutra"
                else:
                    stats[aid]['neg'] += 1; time_neg += 1; emoji_nota = "😡 Negativa"
                
                nome_agente = admins.get(aid, "Desconhecido")
                dt_evento = datetime.fromtimestamp(data_nota, tz=FUSO_BR).strftime("%d/%m %H:%M")
                tags_str = ", ".join([t['name'] for t in c.get('tags', {}).get('tags', [])])
                comentario = rating_obj.get('remark', '-')
                link_url = f"https://app.intercom.com/a/inbox/{APP_ID}/inbox/conversation/{c['id']}"
                
                lista_detalhada_csat.append({
                    "Data": dt_evento, "Agente": nome_agente, "Nota": nota,
                    "Tipo": emoji_nota, "Tags": tags_str, "Comentário": comentario, "Link": link_url
                })

            total_time = time_pos + time_neu + time_neg
            
            if total_time > 0:
                csat_real = (time_pos / total_time * 100)
                total_valid = time_pos + time_neg
                csat_adj = (time_pos / total_valid * 100) if total_valid > 0 else 0
                
                c1, c2, c3, c4, c5 = st.columns(5)
                c1.metric("CSAT Geral", f"{csat_real:.1f}%", f"{total_time} avaliações")
                c2.metric("CSAT Ajustado", f"{csat_adj:.1f}%", "Sem neutras")
                c3.metric("😍 Positivas", time_pos)
                c4.metric("😐 Neutras", time_neu)
                c5.metric("😡 Negativas", time_neg)
                
                st.divider()
                
                tabela_agentes = []
                for aid, s in stats.items():
                    nome = admins.get(aid, "Desconhecido")
                    valido = s['pos'] + s['neg']
                    adj = (s['pos'] / valido * 100) if valido > 0 else 0
                    real = (s['pos'] / s['total'] * 100) if s['total'] > 0 else 0
                    tabela_agentes.append({
                        "Agente": nome, "CSAT (Ajustado)": f"{adj:.1f}%", "CSAT (Real)": f"{real:.1f}%",
                        "Total": s['total'], "😍": s['pos'], "😐": s['neu'], "😡": s['neg']
                    })
                
                df_resumo = pd.DataFrame(tabela_agentes).sort_values("Total", ascending=False)
                st.subheader("🏆 Performance por Agente")
                st.dataframe(df_resumo, use_container_width=True, hide_index=True)
                
                st.divider()
                st.subheader("🔎 Detalhamento dos Tickets")
                
                df_detalhe = pd.DataFrame(lista_detalhada_csat)
                c_f1, c_f2 = st.columns(2)
                with c_f1: filtro_agentes = st.multiselect("Filtrar Agente:", df_detalhe['Agente'].unique())
                with c_f2: filtro_tipos = st.multiselect("Filtrar Tipo:", df_detalhe['Tipo'].unique())
                
                df_exibicao = df_detalhe.copy()
                if filtro_agentes: df_exibicao = df_exibicao[df_exibicao['Agente'].isin(filtro_agentes)]
                if filtro_tipos: df_exibicao = df_exibicao[df_exibicao['Tipo'].isin(filtro_tipos)]
                
                st.caption(f"Exibindo {len(df_exibicao)} tickets.")
                st.data_editor(
                    df_exibicao,
                    column_config={
                        "Link": st.column_config.LinkColumn("Ticket", display_text="Abrir"),
                        "Nota": st.column_config.NumberColumn("Nota", format="%d ⭐")
                    }, use_container_width=True, hide_index=True
                )
           else:
                st.warning("Nenhuma avaliação encontrada.")
        else:
            st.warning("Nenhum dado bruto de CSAT retornado.")

else:
    st.info("👈 Selecione as datas na barra lateral e clique em 'Gerar Relatório'.")
