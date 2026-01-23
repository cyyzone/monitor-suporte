import streamlit as st
import utils
import time
from datetime import datetime, timedelta, time as dtime

st.set_page_config(page_title="ADMIN - Sincronização", page_icon="⚙️", layout="wide")

# Senha de ADMIN (Pode ser diferente da dos gerentes se quiser)
if not utils.check_password():
    st.stop()

st.title("⚙️ Painel de Sincronização (ETL)")
st.warning("Área restrita. Utilize para atualizar o Banco de Dados MongoDB.")

# --- CONFIGURAÇÃO DA CARGA ---
with st.container(border=True):
    c1, c2 = st.columns(2)
    
    with c1:
        st.subheader("1. Período para Baixar")
        # Padrão: Ontem e Hoje
        dt_ini = st.date_input("De", datetime.now() - timedelta(days=1))
        dt_fim = st.date_input("Até", datetime.now())
    
    with c2:
        st.subheader("2. Filtro de Origem")
        modo = st.radio("Tipo de Carga", ["Empresa Específica", "Carga Geral (Todos os Tickets)"])
        
        id_empresa = None
        if modo == "Empresa Específica":
            id_input = st.text_input("ID ou Nome da Empresa")
            if id_input:
                # Função antiga de buscar ID na API (precisa estar no código ou importada)
                # Vou assumir que você manteve a lógica de busca de ID aqui
                pass 

    if st.button("🚀 INICIAR SINCRONIZAÇÃO", type="primary"):
        
        # LÓGICA DE LOOP PARA BAIXAR DA API
        # Aqui você usa aquela sua função 'carregar_tickets_por_periodo'
        # MAS ajustada para permitir busca sem ID de empresa se for "Carga Geral"
        
        st.info("Iniciando conexão com API Intercom...")
        progress = st.progress(0)
        status_txt = st.empty()
        
        # --- Adaptação da sua função de busca para o Admin ---
        # (Aqui entra a chamada da função carregar_tickets_por_periodo que já temos)
        # Se for Carga Geral, passamos id_empresa_intercom=None
        
        # Exemplo simulado da chamada:
        tickets_baixados, stats = carregar_tickets_por_periodo(
            dt_ini, dt_fim, 
            id_empresa_intercom=id_input if modo == "Empresa Específica" else None,
            _ui_progress=(progress, status_txt)
        )
        
        if tickets_baixados:
            status_txt.text("Salvando no MongoDB...")
            qtd = utils.salvar_lote_tickets_mongo(tickets_baixados)
            st.success(f"✅ Sucesso! {qtd} conversas salvas/atualizadas no banco.")
        else:
            st.warning("Nenhum ticket novo encontrado neste período.")

# --- VISUALIZAÇÃO DO BANCO (DEBUG) ---
st.divider()
st.subheader("Status do Banco de Dados")
total = utils.contar_total_tickets_banco()
st.metric("Total de Documentos no Mongo", total)
