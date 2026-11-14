"""CVE dashboard: KPI, four Plotly figures, search, sorting, CSV export."""
from __future__ import annotations
import streamlit as st
from charts import build_figures
from data import apply_filters,get_metrics,normalize_filters


def render_dashboard(all_data, filters):
    st.title('🛡️ CVE Analytics')
    st.caption('Интерактивный анализ данных об уязвимостях за 2014–2026 годы')
    df=apply_filters(all_data,filters)
    with st.expander('Активные фильтры',expanded=False):
        st.json(normalize_filters(filters))
    if df.empty:
        st.warning('Нет записей по выбранным условиям. Измените фильтры в настройках.')
        return
    stats=get_metrics(df)
    k1,k2,k3,k4=st.columns(4)
    k1.metric('Всего записей',f"{stats['total']:,}")
    k2.metric('Средний CVSS',stats['avg_cvss'])
    k3.metric('Critical',f"{stats['critical']:,}")
    k4.metric('Затронуто узлов',f"{stats['affected']:,}")
    st.divider()
    figures=build_figures(df)
    l,r=st.columns(2)
    with l:
        st.plotly_chart(figures['trend'],use_container_width=True)
        st.plotly_chart(figures['attacks'],use_container_width=True)
    with r:
        st.plotly_chart(figures['vendors'],use_container_width=True)
        st.plotly_chart(figures['heatmap'],use_container_width=True)
    st.subheader('Исходные записи')
    query=st.text_input('Поиск по CVE ID, производителю или продукту',
                        placeholder='Например, CVE-2024 или Microsoft')
    view=df
    if query.strip():
        text=query.strip()
        mask=(df['cve_id'].str.contains(text,case=False,regex=False,na=False)
              |df['vendor'].str.contains(text,case=False,regex=False,na=False)
              |df['product'].str.contains(text,case=False,regex=False,na=False))
        view=df.loc[mask]
    st.caption(f'Найдено записей: {len(view):,}')
    st.dataframe(view,hide_index=True,use_container_width=True,height=420)
    st.download_button('Скачать отфильтрованные данные (CSV)',
                       view.to_csv(index=False).encode('utf-8-sig'),
                       'filtered_cve.csv','text/csv',key='export_csv')
