import streamlit as st

def check_password():
    """
    Retorna `True` se o usuário tiver a senha correta.
    """

    # Verifica se a senha foi configurada nos secrets
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

    # Se já estiver logado, libera o acesso
    # O .get(..., False) garante que se a chave não existir, ele assume Falso sem dar erro
    if st.session_state.get("password_correct", False):
        return True

    # Se não estiver logado, mostra o campo de senha
    st.text_input(
        "🔒 Digite a senha de acesso:", 
        type="password", 
        on_change=password_entered, 
        key="password"
    )
    
    # Só mostramos o erro se a chave "password_correct" EXISTIR na memória.
    # Isso significa que o usuário já tentou digitar a senha e o callback 'password_entered' rodou.
    if "password_correct" in st.session_state and not st.session_state["password_correct"]:
        st.error("😕 Senha incorreta.")

    return False
    # Se a senha estiver errada (após tentativa), avisa
    if "password_correct" in st.session_state and st.session_state["password_correct"] is False:
        st.error("😕 Senha incorreta.")

    return False
