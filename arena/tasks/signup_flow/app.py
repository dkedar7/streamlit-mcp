import streamlit as st

st.title("Sign up")

st.text_input("Name", key="name")
st.selectbox("Plan", ["Free", "Pro", "Team"], key="plan")
st.slider("Years of experience", 0, 30, 0, key="experience")
st.checkbox("Subscribe to newsletter", key="subscribe")

if st.button("Create account"):
    st.session_state["created"] = True

if st.session_state.get("created"):
    st.subheader(f"Welcome, {st.session_state['name']}!")
