from __future__ import annotations
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

def build_figures(data: pd.DataFrame) -> dict:
    if data.empty:
        return {}
    yearly_counts = data.groupby('year').size().reset_index(name='Количество').sort_values('year')
    trend_figure = px.line(yearly_counts, x='year', y='Количество', markers=True, title='Динамика уязвимостей по годам')
    trend_figure.update_xaxes(dtick=1)
    attack_counts = data['attack_type'].value_counts().head(12).rename_axis('Тип атаки').reset_index(name='Количество')
    attacks_figure = px.bar(attack_counts, x='Количество', y='Тип атаки', orientation='h', title='Распределение типов атак')
    vendor_counts = data['vendor'].value_counts().head(10).rename_axis('Вендор').reset_index(name='Количество')
    vendors_figure = px.bar(vendor_counts, x='Количество', y='Вендор', orientation='h', title='Топ-10 вендоров')
    top_attacks = data['attack_type'].value_counts().head(12).index.tolist()
    top_sectors = data['target_sector'].value_counts().head(12).index.tolist()
    cross_table = pd.crosstab(data['attack_type'], data['target_sector']).reindex(index=top_attacks, columns=top_sectors, fill_value=0)
    heatmap_figure = go.Figure(data=go.Heatmap(z=cross_table.to_numpy(), x=top_sectors, y=top_attacks, colorscale='Blues', colorbar={'title': 'Записи'}, hovertemplate='Атака: %{y}<br>Отрасль: %{x}<br>Записей: %{z}<extra></extra>'))
    heatmap_figure.update_layout(title='Тепловая карта: тип атаки × отрасль', xaxis_title='Отрасль', yaxis_title='Тип атаки')
    return {'trend': trend_figure, 'attacks': attacks_figure, 'vendors': vendors_figure, 'heatmap': heatmap_figure}
