# 📊 Monitor de Suporte - Intercom

Este projeto reúne painéis (dashboards) para monitorar a equipe de Customer Success (CS) e Suporte utilizando a API do Intercom.

O objetivo é ter uma visão clara do **tempo real** (operacional), da **qualidade** (CSAT) e da **jornada de trabalho** (Status) dos agentes.

## 🚀 Painéis Disponíveis

O sistema é dividido em módulos para facilitar o uso:

### 1. ⚡ Monitor Operacional (`dashboard_visual.py`)
Focado em **tempo real**. 
* **Fila:** Mostra se há clientes aguardando atendimento.
* **Status:** Quem está Online 🟢 ou Ausente 🔴 agora.
* **Fluxo:** Volume de tickets do dia e dos últimos 30 minutos.
* **Alertas:** Avisa se um agente está sobrecarregado (muitos tickets abertos).

### 2. ⭐ Qualidade e CSAT (`dashboard_csat.py`)
Focado na **satisfação do cliente**.
* **CSAT Real vs. Ajustado:** Compara a nota considerando ou ignorando avaliações neutras.
* **Detalhamento:** Lista todas as avaliações com comentários e links diretos para os tickets.
* **Filtros:** Permite filtrar por agente específico.

### 3. 🕒 Ponto e Status (`dashboard_status.py`)
Focado na **gestão de tempo** e pausas.
* **Cálculo de Ausência:** Soma quanto tempo o agente ficou em modo "Away" (Ausente).
* **Histórico:** Mostra os horários exatos de saída e retorno (mesmo se a pausa começou no dia anterior).
* **Gráfico:** Visualização das horas de ausência por dia.

### 4. 📈 Volume Unificado (`dashboard_volume.py`)
Focado em **métricas de entrada**.
* **Inbound:** Quantos tickets novos entraram (separando suporte geral de leads).
* **Tags:** Quais os assuntos (tags) mais recorrentes.

---

## 🛠️ Como Configurar e Rodar

### Pré-requisitos
* Python instalado.
* Um **Token de Acesso** da API do Intercom.

### 1. Instalação
Baixe o projeto e instale as bibliotecas necessárias:

```bash
pip install -r requirements.txt

## 🛠️ Instalação e Configuração

### Pré-requisitos
* Python 3.11+
* Conta no Intercom com permissões de API.

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
