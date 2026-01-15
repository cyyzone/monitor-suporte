import streamlit as st
import pandas as pd
import time
import json
import os
from datetime import datetime, timezone, timedelta

# Importando suas ferramentas do utils.py
from utils import check_password, make_api_request, send_slack_alert 

# --- CONFIGURAÇÃO INICIAL ---
st.set_page_config(page_title="Monitor Limbo", page_icon="👻", layout="wide")

# Segurança
if not check_password():
    st.stop()

try:
    APP_ID = st.secrets["INTERCOM_APP_ID"]
except KeyError:
    st.error("❌ 'INTERCOM_APP_ID' não encontrado no secrets.")
    st.stop()

# --- FUNÇÃO DE BUSCA (MÉTODO GET / LISTA) ---
def get_global_unassigned():
    """
    Busca conversas 'Limbo Total':
    - Aberta
    - Sem Admin
    - Sem Time (Team Assignee ID deve ser nulo)
    """
    url = "https://api.intercom.io/conversations"
    
    # Parâmetros da API
    query_string = f"?sort=updated_at&order=desc&per_page=60"
    url_completa = url + query_string
    
    # Faz a requisição
    data = make_api_request("GET", url_completa)
    
    lista_limbo = []
    agora = datetime.now(timezone.utc)

    if data:
        conversas = data.get('conversations', [])
        
        for conv in conversas:
            # --- FILTRAGEM RIGOROSA ---
            
            # 1. Tem que estar ABERTA
            if conv.get('state') != 'open':
                continue
            
            # 2. Tem que estar SEM DONO (Admin)
            if conv.get('admin_assignee_id') is not None:
                continue

            # 3. Tem que estar SEM TIME (A regra que você pediu agora)
            if conv.get('team_assignee_id') is not None:
                continue

            # --- PREPARAÇÃO DOS DADOS ---
            ts_criacao = conv['created_at']
            ts_update = conv['updated_at']
            
            # Converte para objeto datetime
            dt_criacao_obj = datetime.fromtimestamp(ts_criacao, tz=timezone.utc)
            dt_update_obj = datetime.fromtimestamp(ts_update, tz=timezone.utc)

            # Cálculo de tempo de espera
            diferenca = agora - dt_criacao_obj
            if diferenca.days > 0:
                espera = f"{diferenca.days}d {diferenca.seconds//3600}h"
            else:
                espera = f"{diferenca.seconds//3600}h {(diferenca.seconds//60)%60}m"

            # Limpeza do texto
            body_text = conv.get('source', {}).get('body', '')
            preview_clean = str(body_text).replace("<p>", "").replace("</p>", " ").replace("<br>", " ")[:100]

            lista_limbo.append({
                'id': conv['id'],
                'created_at': dt_criacao_obj,
                'updated_at': dt_update_obj,
                'espera': espera,
                'link': f"https://app.intercom.com/a/inbox/{APP_ID}/inbox/conversation/{conv['id']}",
                'preview': preview_clean
            })
            
    return lista_limbo

# --- FUNÇÃO DE ALERTA ---
def processar_alertas(conversas):
    ARQUIVO_CONTROLE = "limbo_alert_log.json" 
    TEMPO_RESFRIAMENTO = 600
    agora = time.time()
    
    if not conversas:
        return

    ultimo_envio = 0
    if os.path.exists(ARQUIVO_CONTROLE):
        try:
            with open(ARQUIVO_CONTROLE, "r") as f:
                dados = json.load(f)
                ultimo_envio = dados.get("timestamp", 0)
        except:
            pass

    if (agora - ultimo_envio > TEMPO_RESFRIAMENTO):
        qtd = len(conversas)
        links = [f"<{c['link']}|#{c['id']}>" for c in conversas[:5]]
        lista_str = ", ".join(links)
        
        msg = (f"👻 *LIMBO TOTAL DETECTADO*\n"
               f"Existem *{qtd} conversas* sem time e sem dono!\n"
               f"Recentes: {lista_str}")
        
        send_slack_alert(msg)
        
        with open(ARQUIVO_CONTROLE, "w") as f:
            json.dump({"timestamp": agora}, f)
            
        st.toast(f"🔔 Alerta enviado ao Slack ({qtd} conversas)", icon="📨")

# --- O MOTOR VISUAL ---
@st.fragment(run_every=60)
def painel_em_tempo_real():
    st.title("👻 Monitor de Limbo (Sem Time)")
    
    # 1. Busca os dados
    conversas_limbo = get_global_unassigned()
    
    # 2. Processa alertas
    processar_alertas(conversas_limbo)
    
    # 3. Mostra na tela
    fuso_br = timezone(timedelta(hours=-3))
    hora_atual = datetime.now(fuso_br).strftime("%H:%M:%S")
    
    c1, c2 = st.columns([3, 1])
    c1.caption(f"Última verificação: {hora_atual}")
    if c2.button("🔄 Forçar Atualização"):
        st.rerun()

    st.markdown("---")

    if conversas_limbo:
        st.error(f"🔥 **ATENÇÃO:** Existem **{len(conversas_limbo)} conversas** totalmente sem atribuição!")
        
        df = pd.DataFrame(conversas_limbo)
        
        # Ordena visualmente pelas que foram atualizadas por último
        df = df.sort_values(by="updated_at", ascending=False)

        st.data_editor(
            df,
            column_config={
                "link": st.column_config.LinkColumn("Ticket", display_text="Abrir"),
                "created_at": st.column_config.DatetimeColumn("Criado em", format="DD/MM HH:mm"),
                "espera": st.column_config.TextColumn("Tempo Espera", width="small"),
                "preview": st.column_config.TextColumn("Resumo", width="large"),
                "id": st.column_config.NumberColumn("ID", format="%d")
            },
            
            column_order=["link", "espera", "preview", "created_at"],
            hide_index=True,
            use_container_width=True,
            key=f"tabela_limbo_{int(time.time())}"
        )
    else:
        st.success("✨ Tudo limpo! Nenhuma conversa perdida no limbo.")

# --- INÍCIO ---
painel_em_tempo_real()
