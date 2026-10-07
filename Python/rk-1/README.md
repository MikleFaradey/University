# РК 1 — HTTP-клиент и EDA SQL-инъекций

Работа выполнена по заданию rk-1: загрузка пяти групп данных из REST API с Basic Auth, валидация через Pydantic, объединение по id и разведочный анализ данных.

## Установка

~~~bash
python -m venv .venv
~~~

Windows:

~~~bash
.venv\Scripts\activate
pip install -r requirements.txt
~~~

Linux/macOS:

~~~bash
source .venv/bin/activate
pip install -r requirements.txt
~~~

## 1. Загрузка данных

~~~bash
python client.py
~~~

После успешного выполнения появится sql_injections_merged.csv.

## 2. EDA

~~~bash
jupyter notebook eda.ipynb
~~~

Далее выполнить Run All. Ноутбук содержит все 12 пунктов анализа из задания и автоматически печатает краткие выводы после каждого пункта.
