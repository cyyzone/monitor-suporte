import streamlit as st
import pandas as pd
import requests
from requests.auth import HTTPBasicAuth
from datetime import datetime, timezone, timedelta
import unicodedata # Biblioteca NATIVA do Python (não precisa instalar)
from utils import check_password, make_api_request

st.set_page_config(page_title="Relatório de Telefonia", page_icon="📞", layout="wide")

if not check_password():
    st.stop()

st.title("📞 Relatório de Telefonia e Metas")
st.markdown("Preencha a escala da semana, acompanhe o volume de ligações e veja quem bateu a meta.")

# Fuso horário de Brasília
FUSO_BR = timezone(timedelta(hours=-3))

# --- MAPEAMENTO AIRCALL ---
AGENTS_MAP = {
    "rhayslla.junca@produttivo.com.br": "5281911",
    "douglas.david@produttivo.com.br": "5586698",
    "aline.souza@produttivo.com.br": "5717251",
    "heloisa.atm.slv@produttivo.com.br": "7455039",
    "danielle.ghesini@produttivo.com.br": "7628368",
    "jenyffer.souza@produttivo.com.br": "8115775",
    "marcelo.misugi@produttivo.com.br": "8126602"
}

def formatar_segundos(segundos):
    if pd.isna(segundos) or segundos == 0:
        return "00:00"
    segundos = int(segundos)
    m, s = divmod(segundos, 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"

@st.cache_data(ttl=300, show_spinner=False)
def get_admin_details():
    url = "https://api.intercom.io/admins" 
    data = make_api_request("GET", url)
    dados = {}
    if data:
        for admin in data.get('admins', []):
            dados[str(admin['id'])] = admin['name']
    return dados

@st.cache_data(ttl=300, show_spinner=False)
def buscar_dados_aircall_detalhados(ts_inicio, ts_fim):
    if "AIRCALL_ID" not in st.secrets or "AIRCALL_TOKEN" not in st.secrets:
        st.error("Credenciais do Aircall não configuradas nos secrets.")
        return {}
        
    url = "https://api.aircall.io/v1/calls"
    auth = HTTPBasicAuth(st.secrets["AIRCALL_ID"], st.secrets["AIRCALL_TOKEN"])
    
    params = {
        "from": ts_inicio,
        "to": ts_fim,
        "order": "desc",
        "per_page": 50
    }
    
    stats_por_id = {
        adm_id: {
            "inbound": 0, "outbound": 0, "transferidas": 0, 
            "duracao_total": 0, "destinos": [], "detalhes": []
        } 
        for adm_id in AGENTS_MAP.values()
    }
    
    page = 1
    
    while True:
        params['page'] = page
        try:
            response = requests.get(url, auth=auth, params=params)
            if response.status_code != 200: break
                
            data = response.json()
            calls = data.get('calls', [])
            if not calls: break
                
            for call in calls:
                status = call.get('status')
                if status != 'done': continue 
                    
                user = call.get('user', {})
                user_email = user.get('email', '').lower() if user else ""
                
                transferred_by = call.get('transferred_by', {})
                transf_by_email = transferred_by.get('email', '').lower() if transferred_by else ""
                
                transferred_to = call.get('transferred_to', {})
                destino = "Desconhecido"
                if transferred_to:
                    if transferred_to.get('name'): destino = transferred_to.get('name')
                    elif transferred_to.get('email'): destino = transferred_to.get('email').split('@')[0]
                    elif transferred_to.get('number'): destino = transferred_to.get('number')
                
                direcao = call.get('direction', 'inbound') 
                duracao = call.get('duration', 0)
                numero_telefone = call.get('raw_digits', 'Desconhecido')
                link_gravacao = f"https://assets.aircall.io/calls/{call['id']}/recording"
                ts_ligacao = call.get('started_at', 0)
                
                if transf_by_email in AGENTS_MAP:
                    adm_id = AGENTS_MAP[transf_by_email]
                    stats_por_id[adm_id]["transferidas"] += 1
                    stats_por_id[adm_id]["destinos"].append(destino)
                    stats_por_id[adm_id]["detalhes"].append({
                        "Data_Timestamp": ts_ligacao, 
                        "Telefone": numero_telefone,
                        "Ação": "🔄 Transferiu",
                        "Direção": "Entrada (In)" if direcao == 'inbound' else "Saída (Out)",
                        "Duração": formatar_segundos(duracao),
                        "Destino": destino,
                        "Link": link_gravacao
                    })
                
                if user_email in AGENTS_MAP:
                    adm_id = AGENTS_MAP[user_email]
                    stats_por_id[adm_id]["duracao_total"] += duracao
                    
                    if direcao == 'inbound':
                        stats_por_id[adm_id]["inbound"] += 1
                        acao_str, dir_str = "📥 Recebeu", "Entrada (In)"
                    else:
                        stats_por_id[adm_id]["outbound"] += 1
                        acao_str, dir_str = "📤 Ligou", "Saída (Out)"

                    stats_por_id[adm_id]["detalhes"].append({
                        "Data_Timestamp": ts_ligacao, 
                        "Telefone": numero_telefone,
                        "Ação": acao_str,
                        "Direção": dir_str,
                        "Duração": formatar_segundos(duracao),
                        "Destino": "-",
                        "Link": link_gravacao
                    })

            if data.get('meta', {}).get('next_page_link'): page += 1
            else: break
        except Exception as e:
            print(f"Erro Aircall: {e}")
            break
            
    return stats_por_id


# =====================================================================
# 1. ÁREA DE CONFIGURAÇÃO (ESCALA E METAS)
# =====================================================================
st.markdown("---")
st.subheader("🗓️ 1. Configurar Escala e Metas")

c_meta, c_filtro, _ = st.columns([1, 1, 2])
with c_meta:
    meta_por_turno = st.number_input("🎯 Meta de ligações por Turno", min_value=1, value=15)
with c_filtro:
    datas = st.date_input("📅 Período de Análise", [datetime.today() - timedelta(days=7), datetime.today()])

st.caption("Preencha a escala abaixo com os primeiros nomes dos analistas (Ex: Aline, Heloisa). Use vírgula ou 'e' para separar os nomes.")

# Cria a tabela base da escala (vazia para preenchimento)
if "escala_df" not in st.session_state:
    st.session_state["escala_df"] = pd.DataFrame({
        "Dia": ["Segunda", "Terça", "Quarta", "Quinta", "Sexta"],
        "Manhã ☎️": ["", "", "", "", ""],
        "Tarde ☎️": ["", "", "", "", ""]
    })

# Exibe o grid interativo
escala_editada = st.data_editor(st.session_state["escala_df"], use_container_width=True, hide_index=True)

# Botão principal de ação
gerar_relatorio = st.button("🚀 Buscar Histórico e Calcular Metas", type="primary", use_container_width=True)

st.markdown("---")

if 'dados_busca' not in st.session_state:
    st.session_state['dados_busca'] = None

if gerar_relatorio:
    # Trava de segurança: Verifica se o usuário selecionou Início e Fim
    if len(datas) < 2:
        st.error("⚠️ Atenção: Por favor, selecione a data de INÍCIO e a data de FIM no calendário acima.")
    else:
        ts_start = int(datetime.combine(datas[0], datetime.min.time()).timestamp())
        ts_end = int(datetime.combine(datas[1], datetime.max.time()).timestamp())
        
        with st.spinner("Buscando histórico e analisando métricas..."):
            stats_aircall = buscar_dados_aircall_detalhados(ts_start, ts_end)
            admins = get_admin_details()
            st.session_state['dados_busca'] = (stats_aircall, admins, escala_editada)


# =====================================================================
# 2. ÁREA DE RESULTADOS (PROCESSAMENTO)
# =====================================================================
if st.session_state['dados_busca']:
    stats_aircall, admins, escala = st.session_state['dados_busca']
    
    # 2.1 LÓGICA DE LEITURA DA ESCALA
    turnos_calculados = {adm_id: 0 for adm_id in AGENTS_MAP.values()}
    
    def limpar_texto(texto):
        # Remove acentos com a biblioteca nativa do Python (unicodedata)
        texto_str = str(texto)
        texto_sem_acento = ''.join(c for c in unicodedata.normalize('NFD', texto_str) if unicodedata.category(c) != 'Mn')
        return texto_sem_acento.lower().replace(" e ", ",").split(",")

    # Varre a tabela de escala preenchida
    for _, row in escala.iterrows():
        nomes_turno = limpar_texto(row["Manhã ☎️"]) + limpar_texto(row["Tarde ☎️"])
        
        for nome_digitado in nomes_turno:
            nome_digitado = nome_digitado.strip()
            if not nome_digitado: continue
            
            for adm_id in AGENTS_MAP.values():
                nome_oficial = admins.get(adm_id, "").lower()
                nome_oficial_sem_acento = ''.join(c for c in unicodedata.normalize('NFD', nome_oficial) if unicodedata.category(c) != 'Mn')
                
                if nome_digitado in nome_oficial_sem_acento:
                    turnos_calculados[adm_id] += 1
                    break 
    
    # 2.2 PREPARAÇÃO DOS DADOS FINAIS
    tabela_dados = []
    
    for adm_id, stats in stats_aircall.items():
        nome = admins.get(adm_id, f"ID {adm_id}")
        inb = stats["inbound"]
        outb = stats["outbound"]
        total_atendidas = inb + outb
        turnos_agente = turnos_calculados[adm_id]
        
        media = (total_atendidas / turnos_agente) if turnos_agente > 0 else 0
        bateu_meta = "✅ Sim" if (media >= meta_por_turno and turnos_agente > 0) else ("❌ Não" if turnos_agente > 0 else "-")
            
        tabela_dados.append({
            "Agente": nome,
            "Turnos Escalados": turnos_agente,
            "Total Ligações": total_atendidas,
            "Média Alcançada (por turno)": f"{media:.1f}",
            "Bateu a Meta?": bateu_meta,
            "📥 Inbound": inb,
            "📤 Outbound": outb,
            "🔄 Transferidas": stats["transferidas"]
        })

    if tabela_dados:
        df_resultado = pd.DataFrame(tabela_dados)
        
        st.subheader("🏆 Resultado de Produtividade vs Escala")
        
        st.dataframe(
            df_resultado.sort_values(by="Total Ligações", ascending=False),
            use_container_width=True,
            hide_index=True
        )

        # 2.3 EXIBIÇÃO DOS DETALHES POR AGENTE
        st.markdown("---")
        st.subheader("🔎 Detalhamento de Ligações por Agente")
        
        for adm_id, stats in stats_aircall.items():
            total_interacoes = stats["inbound"] + stats["outbound"] + stats["transferidas"]
            
            if total_interacoes > 0:
                nome = admins.get(adm_id, f"ID {adm_id}")
                
                with st.expander(f"👤 {nome} (Total: {total_interacoes} interações)"):
                    detalhes = stats["detalhes"]
                    
                    for d in detalhes:
                        if d["Data_Timestamp"] > 0:
                            dt_obj = datetime.fromtimestamp(d["Data_Timestamp"], tz=FUSO_BR)
                            d["Data/Hora"] = dt_obj.strftime('%d/%m/%Y %H:%M:%S')
                        else:
                            d["Data/Hora"] = "Desconhecido"
                    
                    df_detalhes = pd.DataFrame(detalhes)
                    df_detalhes = df_detalhes.sort_values(by="Data_Timestamp", ascending=False)
                    df_detalhes = df_detalhes.drop(columns=["Data_Timestamp"])
                    
                    df_detalhes = df_detalhes[["Data/Hora", "Telefone", "Ação", "Direção", "Duração", "Destino", "Link"]]
                    
                    st.dataframe(
                        df_detalhes,
                        use_container_width=True,
                        hide_index=True,
                        column_config={
                            "Link": st.column_config.LinkColumn("Gravação", display_text="Ouvir Ligação")
                        }
                    )
        
    else:
        st.warning("Nenhuma ligação encontrada para o time neste período.")
