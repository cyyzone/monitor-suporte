# 📊 Monitor de Suporte - CS (Intercom)

Este projeto é uma suite de monitoramento para equipes de Customer Success, dividida em dois painéis estratégicos: **Operacional** (Tempo Real) e **Qualidade** (CSAT Analítico).

O objetivo é fornecer visibilidade imediata sobre a fila e produtividade, além de uma análise profunda da satisfação do cliente, consumindo a API do Intercom.

## 🚀 Módulos do Projeto

O sistema foi separado em dois dashboards para garantir performance e foco:

### 1. 🚀 Dashboard Operacional (`dashboard_operacional.py`)
Focado na **velocidade**. É leve e atualiza automaticamente a cada 60 segundos. Ideal para ficar na TV da sala.
* **Monitoramento de Fila:** Alerta visual crítico para clientes aguardando atendimento.
* **Status em Tempo Real:** Quem está Online vs. Ausente (Away).
* **Métricas de Fluxo:** Volume do dia e Volume recente (últimos 30 min) para identificar picos de demanda.
* **Alertas de Sobrecarga:** Identifica agentes com muitos tickets abertos simultaneamente.

### 2. ⭐ Dashboard de Qualidade (`dashboard_csat.py`)
Focado na **análise**. Processa o histórico completo do mês atual, buscando tickets antigos que receberam avaliação recente.
* **CSAT Global (Time):** Cálculo padrão de mercado (considera avaliações Neutras).
* **CSAT Individual (Ajustado):** Cálculo justo para o agente (ignora avaliações Neutras).
* **Detalhamento:** Tabela com contagem de notas Positivas (4-5), Neutras (3) e Negativas (1-2).
* **Busca Profunda:** Varre conversas atualizadas no mês para garantir que nenhuma nota seja perdida.

---

## 🛠️ Instalação e Configuração

### Pré-requisitos
* Python 3.11+
* Conta no Intercom com permissões de API.

### 1. Instalar Dependências

```bash
pip install -r requirements.txt

### 1. Instalar Dependências

```bash
pip install -r requirements.txt
```
### 2. Configurar as Credenciais (Secrets)

O projeto utiliza o sistema de segredos do Streamlit. Você precisa criar um arquivo `.streamlit/secrets.toml` na raiz do projeto com as suas chaves do Intercom:

**Arquivo:** `.streamlit/secrets.toml`
```toml
INTERCOM_TOKEN = "seu_token_de_acesso_aqui"
INTERCOM_APP_ID = "seu_app_id_aqui"
```
### 3. Executar a Aplicação

```bash
streamlit run dashboard_visual.py
```
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
