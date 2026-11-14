from __future__ import annotations
import streamlit as st
from data import YEARS, CATEGORICAL, default_filters, normalize_filters
NAMES = {'attack_type': 'Типы атак', 'severity': 'Критичность', 'attack_vector': 'Вектор атаки', 'attacker_country': 'Страна атакующего', 'target_sector': 'Отрасль-цель'}

def render_settings(all_data, store, user):
    st.title('⚙️ Настройки анализа')
    st.caption('Сохранённые настройки доступны после повторного входа в вашу учётную запись.')
    saved = normalize_filters(st.session_state.get('filters', default_filters()))
    with st.form('filter_form'):
        years = st.multiselect('Годы', YEARS, default=[x for x in saved.get('years', YEARS) if x in YEARS])
        chosen = {}
        left, right = st.columns(2)
        for index, field in enumerate(CATEGORICAL):
            choices = sorted(all_data[field].dropna().astype(str).unique().tolist()) if field in all_data.columns else []
            defaults = [x for x in saved.get(field, []) if x in choices]
            with left if index % 2 == 0 else right:
                chosen[field] = st.multiselect(NAMES[field], choices, default=defaults)
        cvss_threshold = st.slider('Минимальная оценка CVSS', 0.0, 10.0, float(saved.get('cvss_min', 0.0)), 0.1)
        only_with_exploit = st.checkbox('Только с доступным эксплойтом (Yes)', value=bool(saved.get('exploit_only', False)))
        only_exploited = st.checkbox('Только эксплуатированные (Exploited)', value=bool(saved.get('exploited_only', False)))
        save_requested = st.form_submit_button('Сохранить настройки', type='primary', key='settings_save')
    if save_requested:
        updated_settings = {'years': years, **chosen, 'cvss_min': cvss_threshold, 'exploit_only': only_with_exploit, 'exploited_only': only_exploited}
        try:
            store.save_settings(user['id'], updated_settings)
        except Exception as exc:
            st.error(f'Настройки не сохранены в базе: {error}')
        else:
            st.session_state.filters = updated_settings
            st.success('Настройки сохранены. Перейдите на страницу аналитики.')
    if st.button('Сбросить значения по умолчанию', key='settings_reset'):
        try:
            defaults = default_filters()
            store.save_settings(user['id'], defaults)
        except Exception as exc:
            st.error(f'Не удалось сбросить настройки: {error}')
        else:
            st.session_state.filters = defaults
            st.rerun()
