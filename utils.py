import streamlit as st

def check_password():
    """
    Retorna `True` se o usuário tiver a senha correta.
    """
    
    # Se a senha não estiver configurada nos secrets, bloqueia por segurança
    if "APP_PASSWORD" not in st.secrets:
        st.error("ERRO: A senha da aplicação não foi configurada no secrets.toml")
        return False

    def password_entered():
        """Verifica se a senha digitada bate com a do secrets."""
        if st.session_state["password"] == st.secrets["APP_PASSWORD"]:
            st.session_state["password_correct"] = True
            del st.session_state["password"]  # Limpa a senha da memória
        else:
            st.session_state["password_correct"] = False

    # Verifica se já está logado na sessão
    if "password_correct" not in st.session_state:
        # Primeira vez abrindo a página, inicializa como falso
        st.session_state["password_correct"] = False

    # Se já estiver logado, libera o acesso
    if st.session_state["password_correct"]:
        return True

    # Se não estiver logado, mostra o campo de senha
    st.text_input(
        "🔒 Digite a senha de acesso:", 
        type="password", 
        on_change=password_entered, 
        key="password"
    )
    
    # Se a senha estiver errada (após tentativa), avisa
    if "password_correct" in st.session_state and st.session_state["password_correct"] is False:
        st.error("😕 Senha incorreta.")

    return False
