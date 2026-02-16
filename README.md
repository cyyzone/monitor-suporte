# 🚀 Monitor Operacional Unificado (Intercom + Aircall)

> **Status:** Versão 2.0 (Em Produção)  
> **Responsável:** Jeny

## 📌 Sobre o Projeto
Este é um ecossistema de monitoramento em tempo real desenvolvido em **Python (Streamlit)** para centralizar a gestão da operação de suporte. 

O objetivo principal é eliminar a "cegueira operacional" e a necessidade de alternar entre múltiplas ferramentas (Intercom, Aircall, Slack), oferecendo uma visão única de **Texto (Tickets)** e **Voz (Telefonia)**.

O sistema atualiza automaticamente a cada 60 segundos e envia alertas proativos para a liderança.

---

## 🔥 Principais Funcionalidades

### 1. Painel Operacional (`dashboard_visual.py`)
* **Monitoramento Multi-Times:** Vigia as filas de espera de múltiplos departamentos (ex: Suporte, Financeiro) simultaneamente.
* **Integração de Voz (Aircall):** Cruza o e-mail do agente para contabilizar ligações atendidas/perdidas e disponibiliza o **link direto para ouvir a gravação** da chamada.
* **Visão de Produtividade:** Tabela unificada mostrando Tickets Abertos vs. Ligações Atendidas por agente.
* **Status em Tempo Real:** Indica quem está Online ou Ausente (Away).

### 2. Painel de Qualidade (`dashboard_csat.py`)
* Análise histórica de CSAT (Customer Satisfaction Score).
* Filtros por data e por agente para feedback individual.

### 3. Sistema de Alertas (Slack)
Um "robô vigia" que notifica no Slack quando:
* 🔥 Existe fila de espera (com link direto para o ticket e nome do time).
* ⚠️ Um agente está sobrecarregado (10+ tickets abertos).
* ⚡ Há um pico de demanda (3+ tickets em 30 minutos).
* 📉 A equipe online está abaixo da meta mínima.

---

## 🛠️ Stack Tecnológica

* **Linguagem:** Python 3.11+
* **Frontend:** Streamlit
* **APIs:** Intercom API (v2.9), Aircall API (v1)
* **Notificações:** Slack Webhooks
* **Manipulação de Dados:** Pandas

---

## ⚙️ Instalação e Configuração

### 1. Pré-requisitos
Certifique-se de ter o Python instalado. Clone o repositório e instale as dependências:

```bash
git clone [https://github.com/seu-usuario/monitor-suporte.git](https://github.com/seu-usuario/monitor-suporte.git)
cd monitor-suporte
pip install -r requirements.txt



## 🔐 Configuração (Secrets)

As credenciais não devem constar no código. Cria uma pasta `.streamlit` na raiz do projeto e um ficheiro `secrets.toml` com a seguinte estrutura:

```toml
# .streamlit/secrets.toml

# --- Acesso ao Painel ---
APP_PASSWORD = "sua_senha_de_acesso"

# --- API Intercom ---
INTERCOM_APP_ID = "seu_app_id"
INTERCOM_TOKEN = "seu_token_intercom"

# --- API Aircall (Novo v2.0) ---
AIRCALL_ID = "seu_api_id_aircall"
AIRCALL_TOKEN = "seu_api_token_aircall"

# --- Notificações ---
SLACK_WEBHOOK = "sua_url_do_webhook_slack"
