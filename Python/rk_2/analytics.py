from __future__ import annotations
import streamlit as st
from charts import build_figures
from data import apply_filters, get_metrics, normalize_filters

def render_dashboard(all_data, filters):
    st.title('🛡️ CVE Analytics')
    st.caption('Интерактивный анализ данных об уязвимостях за 2014–2026 годы')
    filtered_data = apply_filters(all_data, filters)
    with st.expander('Активные фильтры', expanded=False):
        st.json(normalize_filters(filters))
    if filtered_data.empty:
        st.warning('Нет записей по выбранным условиям. Измените фильтры в настройках.')
        return
    metrics = get_metrics(filtered_data)
    total_column, cvss_column, critical_column, hosts_column = st.columns(4)
    total_column.metric('Всего записей', f"{metrics['total']:,}")
    cvss_column.metric('Средний CVSS', metrics['avg_cvss'])
    critical_column.metric('Critical', f"{metrics['critical']:,}")
    hosts_column.metric('Затронуто узлов', f"{metrics['affected']:,}")
    st.divider()
    figures = build_figures(filtered_data)
    left_column, right_column = st.columns(2)
    with left_column:
        st.plotly_chart(figures['trend'], use_container_width=True)
        st.plotly_chart(figures['attacks'], use_container_width=True)
    with right_column:
        st.plotly_chart(figures['vendors'], use_container_width=True)
        st.plotly_chart(figures['heatmap'], use_container_width=True)
    st.subheader('Исходные записи')
    query = st.text_input('Поиск по CVE ID, производителю или продукту', placeholder='Например, CVE-2024 или Microsoft')
    visible_data = filtered_data
    if query.strip():
        text = query.strip()
        search_mask = filtered_data['cve_id'].str.contains(text, case=False, regex=False, na=False) | filtered_data['vendor'].str.contains(text, case=False, regex=False, na=False) | filtered_data['product'].str.contains(text, case=False, regex=False, na=False)
        visible_data = filtered_data.loc[search_mask]
    st.caption(f'Найдено записей: {len(visible_data):,}')
    st.dataframe(visible_data, hide_index=True, use_container_width=True, height=420)
    st.download_button('Скачать отфильтрованные данные (CSV)', visible_data.to_csv(index=False).encode('utf-8-sig'), 'filtered_cve.csv', 'text/csv', key='export_csv')
