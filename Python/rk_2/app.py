"""Entry point: streamlit run app.py"""
from __future__ import annotations
import os
from pathlib import Path
import streamlit as st
from auth import UserStore,AuthError
from data import YEARS,default_filters,normalize_filters,read_datasets
from settings import render_settings
from analytics import render_dashboard

ROOT=Path(__file__).resolve().parent
DATA=Path(os.environ.get('CVE_DATA_DIR',str(ROOT/'cve_datasets')))
DB=Path(os.environ.get('CVE_DB',str(ROOT/'users.sqlite3')))
st.set_page_config(page_title='CVE Analytics | ИУ8',page_icon='🛡️',layout='wide')

@st.cache_resource
def user_store(path:str): return UserStore(path)

@st.cache_data(show_spinner='Загрузка CSV-файлов…')
def load_years(folder:str,years:tuple[int,...], file_state:tuple):
    return read_datasets(folder,years)

def auth_page(store):
    st.title('🛡️ CVE Analytics')
    st.write('Аналитическая система исследования CVE-инцидентов, 2014–2026')
    login_tab,register_tab=st.tabs(['Вход','Регистрация'])
    with login_tab:
        with st.form('login_form'):
            login=st.text_input('Логин')
            password=st.text_input('Пароль',type='password')
            submit=st.form_submit_button('Войти',type='primary',key='login_submit')
        if submit:
            try:
                user=store.authenticate(login,password)
                st.session_state.user=user
                st.session_state.filters=normalize_filters(store.load_settings(user['id']))
                st.rerun()
            except AuthError as e: st.error(str(e))
    with register_tab:
        with st.form('registration_form'):
            username=st.text_input('Новый логин')
            email=st.text_input('E-mail')
            secret=st.text_input('Пароль (не менее 8 символов)',type='password')
            confirm=st.text_input('Повторите пароль',type='password')
            submit=st.form_submit_button('Зарегистрироваться',key='register_submit')
        if submit:
            try:
                store.register(username,email,secret,confirm)
                st.success('Регистрация завершена. Теперь войдите в систему.')
            except AuthError as e: st.error(str(e))


def main():
    store=user_store(str(DB))
    if 'user' not in st.session_state:
        auth_page(store)
        return
    user=st.session_state.user
    if 'filters' not in st.session_state:
        st.session_state.filters=normalize_filters(store.load_settings(user['id']))
    with st.sidebar:
        st.header('CVE Analytics')
        st.write(f"Пользователь: **{user['login']}**")
        page=st.radio('Навигация',['Аналитика','Настройки'],key='nav_page')
        if st.button('Выйти',use_container_width=True,key='logout'):
            st.session_state.clear()
            st.rerun()
    # Changes in the original CSV files invalidate the Streamlit cache automatically.
    file_state=tuple((year, (DATA/f'cyberattacks_cve_{year}.csv').stat().st_mtime_ns,
                      (DATA/f'cyberattacks_cve_{year}.csv').stat().st_size)
                     if (DATA/f'cyberattacks_cve_{year}.csv').is_file() else (year,None,None)
                     for year in YEARS)
    all_data,errors=load_years(str(DATA),tuple(YEARS),file_state)
    if errors:
        with st.expander(f'⚠️ Проблемы с файлами данных ({len(errors)})',expanded=all_data.empty):
            for e in errors: st.warning(e)
            st.code('python fetch_datasets.py',language='bash')
    # Настройки должны оставаться доступными даже при отсутствующих CSV.
    if page=='Настройки':
        if all_data.empty:
            st.info('Данные пока отсутствуют: можно выбрать годы и порог CVSS. Категории станут доступны после загрузки CSV.')
        render_settings(all_data,store,user)
    else:
        if all_data.empty:
            st.error('Не найдены пригодные данные. Скачайте CSV-файлы командой выше и обновите приложение.')
            return
        render_dashboard(all_data,st.session_state.filters)

if __name__=='__main__':main()
