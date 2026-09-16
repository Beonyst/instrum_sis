import os

import searchengine
import nn


crawler = searchengine.Crawler()


print("Проверка поискового индекса...")

crawler.createindextables()


crawler.crawl(
    [
        "https://timetable.pallada.sibsau.ru/timetable/"
    ],
    depth=2
)


crawler.calculatepagerank()


searcher = searchengine.Searcher()


query = "расписание"


word_ids, url_ids = searcher.query(
    query
)


if not url_ids:

    print(
        "Нет результатов для обучения."
    )

    raise SystemExit


tables_created = nn.mynet.con.execute(
    """
    SELECT name
    FROM sqlite_master
    WHERE type = 'table'
      AND name = 'hiddennode'
    """
).fetchone()


if tables_created is None:

    nn.mynet.maketables()


before_training = nn.mynet.getresult(
    word_ids,
    url_ids
)


selected_url = url_ids[0]


print(
    "\nВыбранный пользователем URL:"
)

print(
    searcher.geturlname(
        selected_url
    )
)


nn.mynet.trainquery(
    word_ids,
    url_ids,
    selected_url
)


after_training = nn.mynet.getresult(
    word_ids,
    url_ids
)


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