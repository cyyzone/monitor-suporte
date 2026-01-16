# Monitor de Suporte Intercom 📊

Este projeto reúne dashboards desenvolvidos em **Python** e **Streamlit** para monitorizar a operação de suporte no Intercom. A aplicação divide-se em três módulos principais: monitorização operacional em tempo real, controlo de tickets sem atribuição ("limbo") e análise de qualidade (CSAT).

## 🚀 Módulos do Projeto

O sistema é composto por três painéis distintos:

### 1. Monitor Operacional (`dashboard_visual.py`)
Focado na gestão da equipa em tempo real.
* **Status dos Agentes:** Visualiza quem está Online ou Ausente (Away), com base no status do Intercom.
* **Alertas de Sobrecarga:** Sinaliza agentes com 5 ou mais tickets abertos.
* **Alta Demanda:** Identifica agentes que receberam 3 ou mais tickets nos últimos 30 minutos.
* **Fila de Espera:** Monitoriza tickets na fila e alerta sobre clientes a aguardar.
* **Integração com Slack:** Envia notificações automáticas em caso de anomalias.

### 2. Monitor Limbo (`monitor_limbo.py`)
Garante que nenhum cliente fica esquecido.
* **Deteção de "Limbo":** Lista conversas abertas sem qualquer atribuição (nem agente, nem equipa).
* **Cálculo de Espera:** Exibe o tempo de espera com conversão para o fuso horário local.
* **Alertas:** Notifica via Slack sobre conversas perdidas.

### 3. Painel de Qualidade - CSAT (`dashboard_csat.py`)
Para análise de métricas de satisfação.
* **Filtro por Período:** Seleção de datas personalizadas.
* **Métricas de CSAT:** Calcula o **CSAT Real** (todas as avaliações) e o **CSAT Ajustado** (ignora neutras).
* **Detalhamento:** Tabela de desempenho individual e lista de comentários.

## 🛠️ Instalação e Requisitos

Este projeto utiliza **Python** e requer as bibliotecas listadas em `requirements.txt`.

1.  **Clonar o repositório:**
    ```bash
    git clone https://teu-repositorio/monitor-suporte.git
    cd monitor-suporte
    ```

2.  **Instalar dependências:**
    Recomenda-se o uso de um ambiente virtual (venv).
    ```bash
    pip install -r requirements.txt
    ```

## 🔐 Configuração (Secrets)

As credenciais não devem constar no código. Cria uma pasta `.streamlit` na raiz do projeto e um ficheiro `secrets.toml` com a seguinte estrutura:

```toml
# .streamlit/secrets.toml

INTERCOM_APP_ID = "teu_app_id_aqui"
INTERCOM_TOKEN = "teu_token_de_acesso_aqui"
SLACK_WEBHOOK = "teu_url_do_webhook_slack"
APP_PASSWORD = "tua_senha_de_acesso_ao_dashboard"
