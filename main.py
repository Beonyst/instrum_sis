import os

import searchengine
import nn


# Имя базы данных поискового индекса
DATABASE_NAME = "searchindex.db"


# Проверяем, существует ли база данных
new_database = not os.path.exists(
    DATABASE_NAME
)


# Создаём поискового робота
crawler = searchengine.Crawler(
    DATABASE_NAME
)


# Если база создаётся впервые,
# создаём таблицы и индексируем сайт
if new_database:
    print("Создание поискового индекса...")

    crawler.createindextables()

    crawler.crawl(
        ["https://timetable.pallada.sibsau.ru/timetable/"],
        depth=2
    )


# Рассчитываем PageRank страниц
crawler.calculatepagerank()


# Создаём объект поисковой системы
searcher = searchengine.Searcher(
    DATABASE_NAME
)


# Выполняем поисковый запрос
query = "расписание"

word_ids, url_ids = searcher.query(
    query
)


# Если результатов нет, завершаем программу
if not url_ids:
    print("Нет результатов для обучения.")
    raise SystemExit


# Проверяем, созданы ли таблицы нейронной сети
tables_created = nn.mynet.con.execute(
    """
    SELECT name
    FROM sqlite_master
    WHERE type = 'table'
    AND name = 'hiddennode'
    """
).fetchone()


# При первом запуске создаём таблицы нейронной сети
if tables_created is None:
    nn.mynet.maketables()


# Получаем оценки страниц
# до обучения нейронной сети
before_training = nn.mynet.getresult(
    word_ids,
    url_ids
)


# Для демонстрации считаем,
# что пользователь выбрал первый результат
selected_url = url_ids[0]

print(
    "\nВыбранный пользователем URL:"
)

print(
    searcher.geturlname(
        selected_url
    )
)


# Обучаем нейронную сеть.
#
# Сеть должна увеличить оценку
# выбранной пользователем страницы
# и уменьшить относительные оценки остальных.
nn.mynet.trainquery(
    word_ids,
    url_ids,
    selected_url
)


# Повторно рассчитываем результаты
# после обучения
after_training = nn.mynet.getresult(
    word_ids,
    url_ids
)


# Выводим результаты до и после обучения
print(
    "\nРезультат работы нейронной сети:"
)

for index, url_id in enumerate(url_ids):
    url = searcher.geturlname(
        url_id
    )

    print(
        f"{url}\n"
        f"  До обучения: "
        f"{before_training[index]:.6f}\n"
        f"  После обучения: "
        f"{after_training[index]:.6f}\n"
    )