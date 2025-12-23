# 📊 Monitor de Suporte - CS

Painel de controle em tempo real para equipes de Customer Success (CS). Este dashboard conecta-se à API do Intercom para monitorar a fila de espera, o volume de tickets e a performance individual dos agentes.

O projeto foi construído em **Python** utilizando **Streamlit** para a visualização e **Pandas** para o tratamento de dados.

## 🚀 Funcionalidades

* **Monitoramento da Fila:** Alerta crítico visual quando existem clientes sem atribuição (fila de espera).
* **Status da Equipe:** Visualização rápida de quem está "Online" ou "Ausente" no Intercom.
* **Métricas em Tempo Real:**
    * Contagem de tickets abertos e pausados por agente.
    * Volume total do dia vs. Volume recente (últimos 30 minutos).
* **Alertas Visuais Automáticos:** Ícones que indicam sobrecarga ou picos de atendimento.
* **Histórico Recente:** Lista das últimas conversas atribuídas.
* **Auto-refresh:** O painel atualiza automaticamente a cada 60 segundos.

## 🛠️ Instalação e Configuração

### Pré-requisitos
* Python 3.11+
* Conta no Intercom com permissões de API.

### 1. Instalar Dependências

```bash
pip install -r requirements.txt

### 2. Configurar as Credenciais (Secrets)

O projeto utiliza o sistema de segredos do Streamlit. Você precisa criar um arquivo `.streamlit/secrets.toml` na raiz do projeto com as suas chaves do Intercom:

**Arquivo:** `.streamlit/secrets.toml`
```toml
INTERCOM_TOKEN = "seu_token_de_acesso_aqui"
INTERCOM_APP_ID = "seu_app_id_aqui"

### 3. Executar a Aplicação

```bash
streamlit run dashboard_visual.py

## 🐳 Executar com DevContainers

Este projeto inclui configuração para **DevContainers**. Se usar o VS Code:
1. Abra a pasta do projeto.
2. Clique em "Reopen in Container".
3. O ambiente será configurado e o servidor iniciará na porta `8501`.

## ℹ️ Legenda do Painel

O dashboard utiliza ícones para facilitar a leitura rápida da situação:

| Ícone | Significado | Regra do Código |
| :---: | :--- | :--- |
| 🟢 | **Online** | O agente está ativo no Intercom. |
| 🔴 | **Ausente** | O agente ativou o modo "Away". |
| ⚠️ | **Sobrecarga** | O agente tem **5 ou mais** tickets abertos simultaneamente. |
| ⚡ | **Alta Demanda** | O agente recebeu **3 ou mais** novos tickets nos últimos 30 minutos. |
| 🔥 | **CRÍTICO** | Existem clientes aguardando na fila sem agente atribuído. |

Feito por Jeny.
