import streamlit as st
import utils
import time
from datetime import datetime, time as dtime

st.set_page_config(page_title="Consulta de Atendimentos", page_icon="🔍", layout="wide")

# --- LOGIN SIMPLES (Opcional, se quiser proteger o acesso deles) ---
# Se não quiser senha para eles, pode apagar este bloco
if not utils.check_password():
    st.stop()

# --- BARRA LATERAL (Filtros) ---
with st.sidebar:
    st.title("Portal do Gerente")
    st.markdown("---")
    
    # Busca Inteligente (Nome ou ID)
    termo_busca = st.text_input("Buscar Cliente", placeholder="Nome da empresa ou ID...")
    
    # Filtro de Data (Apenas visual, o banco já traz o histórico)
    st.markdown("### Filtrar Período")
    hoje = datetime.now()
    data_ini = st.date_input("Início", hoje) # Data padrão hoje, mas eles mudam
    data_fim = st.date_input("Fim", hoje)
    
    st.info("💡 A busca consulta nossa base de dados histórica.")

# --- ÁREA PRINCIPAL ---
st.title("📂 Histórico de Conversas")

if termo_busca:
    with st.spinner(f"Buscando '{termo_busca}' no banco de dados..."):
        # Chama a função do utils que busca por ID ou NOME
        tickets = utils.carregar_tickets_mongo(termo_busca)
        
        # Filtro de Data Visual (Python)
        tickets_filtrados = []
        if tickets:
            ts_ini = int(datetime.combine(data_ini, dtime.min).timestamp())
            ts_fim = int(datetime.combine(data_fim, dtime.max).timestamp())
            
            for t in tickets:
                # Se estiver dentro da data selecionada
                if ts_ini <= t.get('updated_at', 0) <= ts_fim:
                    tickets_filtrados.append(t)
        
        # --- EXIBIÇÃO DOS RESULTADOS ---
        if not tickets:
            st.warning("Nenhum cliente encontrado com esse nome na base de dados.")
        elif not tickets_filtrados:
            st.warning(f"Cliente encontrado, mas sem tickets no período de {data_ini} a {data_fim}.")
        else:
            st.success(f"Encontramos {len(tickets_filtrados)} atendimentos.")
            
            for item in tickets_filtrados:
                with st.expander(f"📅 {datetime.fromtimestamp(item['created_at']).strftime('%d/%m/%Y')} | {item['autor_nome']} ({item['status']})"):
                    c1, c2 = st.columns([3, 1])
                    with c1:
                        st.write(f"**Cliente:** {item['cliente']}")
                        st.caption(f"Preview: {item['preview']}...")
                        
                        # Mostra Análise de IA se já tiver sido feita por você antes
                        if 'risco_churn' in item: # Se você salvou a analise da IA no banco
                            st.info(f"🤖 Análise IA: Risco {item['risco_churn'].upper()}")

                    with c2:
                        st.link_button("Ver no Intercom", item['link'])

else:
    st.info("👈 Digite o nome da empresa na barra lateral para começar.")
    
    # Dashboard rápido (Opcional)
    try:
        total = utils.contar_total_tickets_banco()
        st.markdown(f"--- \n📊 **Estatística da Base:** Temos **{total}** conversas arquivadas.")
    except:
        pass
