"""Pure Plotly figure builders: testable independently from Streamlit."""
from __future__ import annotations
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go


def build_figures(df: pd.DataFrame) -> dict:
    if df.empty:
        return {}
    trend=df.groupby('year').size().reset_index(name='Количество').sort_values('year')
    fig_trend=px.line(trend,x='year',y='Количество',markers=True,title='Динамика уязвимостей по годам')
    fig_trend.update_xaxes(dtick=1)
    attacks=df['attack_type'].value_counts().head(12).rename_axis('Тип атаки').reset_index(name='Количество')
    fig_attacks=px.bar(attacks,x='Количество',y='Тип атаки',orientation='h',title='Распределение типов атак')
    vendors=df['vendor'].value_counts().head(10).rename_axis('Вендор').reset_index(name='Количество')
    fig_vendors=px.bar(vendors,x='Количество',y='Вендор',orientation='h',title='Топ-10 вендоров')
    top_attacks=df['attack_type'].value_counts().head(12).index.tolist()
    top_sectors=df['target_sector'].value_counts().head(12).index.tolist()
    cross=pd.crosstab(df['attack_type'],df['target_sector']).reindex(
        index=top_attacks,columns=top_sectors,fill_value=0)
    fig_heatmap=go.Figure(data=go.Heatmap(
        z=cross.to_numpy(), x=top_sectors, y=top_attacks,
        colorscale='Blues',colorbar={'title':'Записи'},
        hovertemplate='Атака: %{y}<br>Отрасль: %{x}<br>Записей: %{z}<extra></extra>'))
    fig_heatmap.update_layout(title='Тепловая карта: тип атаки × отрасль',
                              xaxis_title='Отрасль',yaxis_title='Тип атаки')
    return {'trend':fig_trend,'attacks':fig_attacks,'vendors':fig_vendors,'heatmap':fig_heatmap}
