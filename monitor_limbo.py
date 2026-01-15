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

# Definição Global do Fuso Horário (Brasília)
FUSO_BR = timezone(timedelta(hours=-3))

# Segurança
if not check_password():
    st.stop()

try:
    APP_ID = st.secrets["INTERCOM_APP_ID"]
except KeyError:
    st.error("❌ 'INTERCOM_APP_ID' não encontrado no secrets.")
    st.stop()

# --- CAMINHO ABSOLUTO PARA O ARQUIVO DE LOG ---
PASTA_ATUAL = os.path.dirname(os.path.abspath(__file__))
ARQUIVO_CONTROLE = os.path.join(PASTA_ATUAL, "limbo_alert_log.json")

# --- FUNÇÃO DE BUSCA (MÉTODO GET) ---
def get_global_unassigned():
    """
    Busca conversas 'Limbo Total' e converte datas para BRT.
    """
    url = "https://api.intercom.io/conversations"
    
    # Busca as últimas 60 conversas (ordenadas por atualização)
    query_string = f"?sort=updated_at&order=desc&per_page=60"
    url_completa = url + query_string
    
    data = make_api_request("GET", url_completa)
    
    lista_limbo = []
    # Agora (em UTC) para cálculo matemático da diferença
    agora_utc = datetime.now(timezone.utc)

    if data:
        conversas = data.get('conversations', [])
        
        for conv in conversas:
            # --- FILTROS ---
            if conv.get('state') != 'open': continue
            if conv.get('admin_assignee_id') is not None: continue
            if conv.get('team_assignee_id') is not None: continue

            # --- TRATAMENTO DE DATA ---
            ts_criacao = conv['created_at']
            
            # 1. Cria o objeto data em UTC (padrão Intercom)
            dt_utc = datetime.fromtimestamp(ts_criacao, tz=timezone.utc)
            
            # 2. Converte para Brasília (para exibir na tabela)
            dt_br = dt_utc.astimezone(FUSO_BR)

            # 3. Calcula o tempo de espera (usando UTC para a matemática ficar certa)
            diferenca = agora_utc - dt_utc
            if diferenca.days > 0:
                espera = f"{diferenca.days}d {diferenca.seconds//3600}h"
            else:
                espera = f"{diferenca.seconds//3600}h {(diferenca.seconds//60)%60}m"

            # Limpeza do texto
            body_text = conv.get('source', {}).get('body', '')
            preview_clean = str(body_text).replace("<p>", "").replace("</p>", " ").replace("<br>", " ")[:100]

            lista_limbo.append({
                'id': conv['id'],
                'created_at_br': dt_br, # Coluna nova com horário corrigido
                'updated_at_utc': conv['updated_at'], # Mantemos o original p/ ordenação interna
                'espera': espera,
                'link': f"https://app.intercom.com/a/inbox/{APP_ID}/inbox/conversation/{conv['id']}",
                'preview': preview_clean
            })
            
    return lista_limbo

# --- FUNÇÃO DE ALERTA (COM CAMINHO SEGURO) ---
def processar_alertas(conversas):
    TEMPO_RESFRIAMENTO = 600 # 10 minutos
    agora = time.time()
    
    if not conversas:
        return

    # 1. Leitura do Arquivo (Persistência)
    ultimo_envio_arquivo = 0
    if os.path.exists(ARQUIVO_CONTROLE):
        try:
            with open(ARQUIVO_CONTROLE, "r") as f:
                dados = json.load(f)
                ultimo_envio_arquivo = dados.get("timestamp", 0)
        except:
            pass

    # 2. Leitura da Memória (Session State)
    if "ultimo_slack_limbo" not in st.session_state:
        st.session_state["ultimo_slack_limbo"] = 0
    ultimo_envio_ram = st.session_state["ultimo_slack_limbo"]

    # Pega o mais recente dos dois
    ultimo_envio_real = max(ultimo_envio_arquivo, ultimo_envio_ram)
    tempo_passado = agora - ultimo_envio_real
    
    # Lógica de Envio
    if tempo_passado < TEMPO_RESFRIAMENTO:
        restante = int(TEMPO_RESFRIAMENTO - tempo_passado)
        st.info(f"❄️ Alerta em resfriamento: próximo envio permitido em {restante}s")
    else:
        # Envia Alerta
        qtd = len(conversas)
        links = [f"<{c['link']}|#{c['id']}>" for c in conversas[:5]]
        lista_str = ", ".join(links)
        
        msg = (f"👻 *LIMBO TOTAL DETECTADO*\n"
               f"Existem *{qtd} conversas* sem time e sem dono!\n"
               f"Recentes: {lista_str}")
        
        send_slack_alert(msg)
        
        # Atualiza a memória e o arquivo
        st.session_state["ultimo_slack_limbo"] = agora
        try:
            with open(ARQUIVO_CONTROLE, "w") as f:
                json.dump({"timestamp": agora}, f)
        except Exception as e:
            print(f"Erro ao salvar log: {e}")
            
        st.toast(f"🔔 Alerta enviado ao Slack ({qtd} conversas)", icon="📨")

# --- O MOTOR VISUAL ---
@st.fragment(run_every=60)
def painel_em_tempo_real():
    st.title("👻 Monitor de Limbo (Sem Time)")
    
    conversas_limbo = get_global_unassigned()
    
    processar_alertas(conversas_limbo)
    
    hora_atual = datetime.now(FUSO_BR).strftime("%H:%M:%S")
    
    c1, c2 = st.columns([3, 1])
    c1.caption(f"Última verificação: {hora_atual} (Horário de Brasília)")
    if c2.button("🔄 Forçar Atualização"):
        st.rerun()

    st.markdown("---")

    if conversas_limbo:
        st.error(f"🔥 **ATENÇÃO:** Existem **{len(conversas_limbo)} conversas** totalmente sem atribuição!")
        
        df = pd.DataFrame(conversas_limbo)
        # Ordena usando o timestamp UTC (mais preciso), mas mostra o BRT
        df = df.sort_values(by="updated_at_utc", ascending=False)

        st.data_editor(
            df,
            column_config={
                "link": st.column_config.LinkColumn("Ticket", display_text="Abrir"),
                # Agora usamos a coluna 'created_at_br' que já convertemos
                "created_at_br": st.column_config.DatetimeColumn("Criado em", format="DD/MM HH:mm"),
                "espera": st.column_config.TextColumn("Tempo Espera", width="small"),
                "preview": st.column_config.TextColumn("Resumo", width="large"),
                "id": st.column_config.NumberColumn("ID", format="%d")
            },
            column_order=["link", "espera", "preview", "created_at_br"],
            hide_index=True,
            use_container_width=True,
            key=f"tabela_limbo_{int(time.time())}"
        )
    else:
        st.success("✨ Tudo limpo! Nenhuma conversa perdida no limbo.")

# --- INÍCIO ---
painel_em_tempo_real()
