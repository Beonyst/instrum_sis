import re
import sqlite3 as sqlite
import urllib.request
from urllib.parse import urljoin

from bs4 import BeautifulSoup

import nn


# Слова, которые не несут полезной информации для поиска
IGNORE_WORDS = {
    "the",
    "of",
    "to",
    "and",
    "a",
    "in",
    "is",
    "it"
}


class Crawler:
    # Подключение к базе данных
    def __init__(self, dbname):
        self.con = sqlite.connect(dbname)

    # Закрытие подключения
    def __del__(self):
        if hasattr(self, "con"):
            self.con.close()

    # Сохранение изменений в базе
    def dbcommit(self):
        self.con.commit()

    # Получение идентификатора записи.
    # Если записи нет, она создаётся.
    def getentryid(self, table, field, value):
        result = self.con.execute(
            f"""
            SELECT rowid
            FROM {table}
            WHERE {field} = ?
            """,
            (value,)
        ).fetchone()

        if result is not None:
            return result[0]

        cursor = self.con.execute(
            f"""
            INSERT INTO {table}({field})
            VALUES (?)
            """,
            (value,)
        )

        return cursor.lastrowid

    # Добавление страницы в поисковый индекс
    def addtoindex(self, url, soup):
        # Если страница уже проиндексирована,
        # повторно её обрабатывать не нужно
        if self.isindexed(url):
            return

        print("Индексируется:", url)

        # Получаем обычный текст страницы
        text = self.gettextonly(soup)

        # Разбиваем текст на отдельные слова
        words = self.separatewords(text)

        # Получаем идентификатор страницы
        urlid = self.getentryid(
            "urllist",
            "url",
            url
        )

        # Добавляем все найденные слова в индекс
        for position, word in enumerate(words):
            if word in IGNORE_WORDS:
                continue

            wordid = self.getentryid(
                "wordlist",
                "word",
                word
            )

            # Запоминаем, где именно находится слово
            self.con.execute(
                """
                INSERT INTO wordlocation
                (urlid, wordid, location)
                VALUES (?, ?, ?)
                """,
                (urlid, wordid, position)
            )

    # Получение текста из HTML без тегов
    def gettextonly(self, soup):
        text = soup.string

        if text is not None:
            return str(text).strip()

        result = []

        for child in soup.contents:
            result.append(
                self.gettextonly(child)
            )

        return "\n".join(result)

    # Разбиение текста на отдельные слова
    def separatewords(self, text):
        splitter = re.compile(r"\W+")

        return [
            word.lower()
            for word in splitter.split(text)
            if word
        ]

    # Проверка, была ли страница уже проиндексирована
    def isindexed(self, url):
        result = self.con.execute(
            """
            SELECT rowid
            FROM urllist
            WHERE url = ?
            """,
            (url,)
        ).fetchone()

        if result is None:
            return False

        # Если для URL уже есть хотя бы одно слово,
        # значит страница была проиндексирована
        word = self.con.execute(
            """
            SELECT rowid
            FROM wordlocation
            WHERE urlid = ?
            """,
            (result[0],)
        ).fetchone()

        return word is not None

    # Сохранение информации о ссылке между страницами
    def addlinkref(self, url_from, url_to, link_text):
        words = self.separatewords(link_text)

        from_id = self.getentryid(
            "urllist",
            "url",
            url_from
        )

        to_id = self.getentryid(
            "urllist",
            "url",
            url_to
        )

        # Ссылка на саму себя не нужна
        if from_id == to_id:
            return

        cursor = self.con.execute(
            """
            INSERT INTO link(fromid, toid)
            VALUES (?, ?)
            """,
            (from_id, to_id)
        )

        link_id = cursor.lastrowid

        # Сохраняем слова, использованные в тексте ссылки
        for word in words:
            if word in IGNORE_WORDS:
                continue

            word_id = self.getentryid(
                "wordlist",
                "word",
                word
            )

            self.con.execute(
                """
                INSERT INTO linkwords(wordid, linkid)
                VALUES (?, ?)
                """,
                (word_id, link_id)
            )

    # Обход страниц сайта и создание поискового индекса
    def crawl(self, pages, depth=2):
        for _ in range(depth):
            new_pages = set()

            for page in pages:
                try:
                    request = urllib.request.Request(
                        page,
                        headers={
                            "User-Agent": "Mozilla/5.0"
                        }
                    )

                    connection = urllib.request.urlopen(
                        request,
                        timeout=10
                    )

                except Exception as error:
                    print(
                        "Не могу открыть",
                        page,
                        ":",
                        error
                    )
                    continue

                # Проверяем тип полученного содержимого
                content_type = (
                    connection.headers.get_content_type()
                )

                if content_type not in {
                    "text/html",
                    "application/xhtml+xml",
                    "text/plain"
                }:
                    print(
                        "Пропускаю",
                        page,
                        ":",
                        content_type
                    )
                    connection.close()
                    continue

                # Разбираем HTML-документ
                soup = BeautifulSoup(
                    connection.read(),
                    "html.parser"
                )

                connection.close()

                # Добавляем страницу в индекс
                self.addtoindex(
                    page,
                    soup
                )

                # Получаем все ссылки со страницы
                for link in soup("a"):
                    if "href" not in link.attrs:
                        continue

                    # Преобразуем относительную ссылку
                    # в полный URL
                    url = urljoin(
                        page,
                        link["href"]
                    )

                    # Не обрабатываем URL с кавычками
                    if "'" in url:
                        continue

                    # Удаляем якорь после #
                    url = url.split("#")[0]

                    # Добавляем только HTTP/HTTPS ссылки
                    if (
                        url.startswith("http")
                        and not self.isindexed(url)
                    ):
                        new_pages.add(url)

                    # Сохраняем связь между страницами
                    link_text = self.gettextonly(link)

                    self.addlinkref(
                        page,
                        url,
                        link_text
                    )

                self.dbcommit()

            pages = new_pages

    # Создание таблиц поискового индекса
    def createindextables(self):
        self.con.execute(
            "CREATE TABLE urllist(url)"
        )

        self.con.execute(
            "CREATE TABLE wordlist(word)"
        )

        self.con.execute(
            """
            CREATE TABLE wordlocation(
                urlid,
                wordid,
                location
            )
            """
        )

        self.con.execute(
            """
            CREATE TABLE link(
                fromid INTEGER,
                toid INTEGER
            )
            """
        )

        self.con.execute(
            """
            CREATE TABLE linkwords(
                wordid,
                linkid
            )
            """
        )

        # Индексы ускоряют поиск по базе
        self.con.execute(
            "CREATE INDEX wordidx ON wordlist(word)"
        )

        self.con.execute(
            "CREATE INDEX urlidx ON urllist(url)"
        )

        self.con.execute(
            "CREATE INDEX wordurlidx "
            "ON wordlocation(wordid)"
        )

        self.con.execute(
            "CREATE INDEX urltoidx "
            "ON link(toid)"
        )

        self.con.execute(
            "CREATE INDEX urlfromidx "
            "ON link(fromid)"
        )

        self.dbcommit()

    # Расчёт PageRank для всех страниц
    def calculatepagerank(self, iterations=20):
        # Удаляем старые результаты
        self.con.execute(
            "DROP TABLE IF EXISTS pagerank"
        )

        # Создаём таблицу PageRank
        self.con.execute(
            """
            CREATE TABLE pagerank(
                urlid PRIMARY KEY,
                score
            )
            """
        )

        # Начальное значение PageRank для каждой страницы
        self.con.execute(
            """
            INSERT INTO pagerank
            SELECT rowid, 1.0
            FROM urllist
            """
        )

        self.dbcommit()

        # Повторяем расчёт заданное количество раз
        for iteration in range(iterations):
            print(
                "Итерация PageRank:",
                iteration + 1
            )

            for (url_id,) in self.con.execute(
                "SELECT rowid FROM urllist"
            ):
                page_rank = 0.15

                # Получаем страницы,
                # которые ссылаются на текущую
                for (linker,) in self.con.execute(
                    """
                    SELECT DISTINCT fromid
                    FROM link
                    WHERE toid = ?
                    """,
                    (url_id,)
                ):
                    # PageRank страницы-источника
                    linking_rank = self.con.execute(
                        """
                        SELECT score
                        FROM pagerank
                        WHERE urlid = ?
                        """,
                        (linker,)
                    ).fetchone()[0]

                    # Количество ссылок
                    # на странице-источнике
                    linking_count = self.con.execute(
                        """
                        SELECT COUNT(*)
                        FROM link
                        WHERE fromid = ?
                        """,
                        (linker,)
                    ).fetchone()[0]

                    if linking_count > 0:
                        page_rank += (
                            0.85 *
                            linking_rank /
                            linking_count
                        )

                # Записываем новый PageRank
                self.con.execute(
                    """
                    UPDATE pagerank
                    SET score = ?
                    WHERE urlid = ?
                    """,
                    (page_rank, url_id)
                )

            self.dbcommit()


class Searcher:
    # Подключение к базе поискового индекса
    def __init__(self, dbname):
        self.con = sqlite.connect(dbname)

    # Закрытие подключения
    def __del__(self):
        if hasattr(self, "con"):
            self.con.close()

    # Получение URL и позиций слов,
    # соответствующих поисковому запросу
    def getmatchrows(self, query):
        words = query.split()

        if not words:
            return [], []

        word_ids = []
        tables = []
        conditions = []
        fields = []

        # Для каждого слова ищем его ID
        for index, word in enumerate(words):
            result = self.con.execute(
                """
                SELECT rowid
                FROM wordlist
                WHERE word = ?
                """,
                (word.lower(),)
            ).fetchone()

            if result is None:
                continue

            word_id = result[0]
            word_ids.append(word_id)

            table_name = f"w{len(word_ids) - 1}"

            tables.append(
                f"wordlocation {table_name}"
            )

            fields.append(
                f"{table_name}.urlid"
                if len(word_ids) == 1
                else f"{table_name}.location"
            )

            conditions.append(
                f"{table_name}.wordid = {word_id}"
            )

            # Все слова запроса должны находиться
            # на одной странице
            if len(word_ids) > 1:
                previous = (
                    f"w{len(word_ids) - 2}"
                )

                conditions.append(
                    f"{previous}.urlid = "
                    f"{table_name}.urlid"
                )

        if not word_ids:
            return [], []

        query_sql = (
            f"SELECT {', '.join(fields)} "
            f"FROM {', '.join(tables)} "
            f"WHERE {' AND '.join(conditions)}"
        )

        rows = list(
            self.con.execute(query_sql)
        )

        return rows, word_ids

    # Нормализация значений в диапазон от 0 до 1
    def normalizescores(self, scores, small_is_better=False):
        if not scores:
            return {}

        small_value = 0.00001

        if small_is_better:
            min_score = min(scores.values())

            return {
                url: min_score /
                max(small_value, score)
                for url, score in scores.items()
            }

        max_score = max(scores.values())

        if max_score == 0:
            max_score = small_value

        return {
            url: score / max_score
            for url, score in scores.items()
        }

    # Оценка по количеству совпадений слов
    def frequencyscore(self, rows):
        counts = {
            row[0]: 0
            for row in rows
        }

        for row in rows:
            counts[row[0]] += 1

        return self.normalizescores(counts)

    # Оценка по расположению слов на странице
    def locationscore(self, rows):
        locations = {
            row[0]: 1000000
            for row in rows
        }

        for row in rows:
            location = sum(row[1:])

            if location < locations[row[0]]:
                locations[row[0]] = location

        return self.normalizescores(
            locations,
            small_is_better=True
        )

    # Оценка по PageRank
    def pagerankscore(self, rows):
        pageranks = {}

        for row in rows:
            url_id = row[0]

            result = self.con.execute(
                """
                SELECT score
                FROM pagerank
                WHERE urlid = ?
                """,
                (url_id,)
            ).fetchone()

            if result is not None:
                pageranks[url_id] = result[0]

        return self.normalizescores(
            pageranks
        )

    # Получение общей оценки страниц
    def getscoredlist(self, rows):
        if not rows:
            return {}

        # Используем три критерия:
        # количество совпадений,
        # расположение слов,
        # PageRank
        scores = [
            self.frequencyscore(rows),
            self.locationscore(rows),
            self.pagerankscore(rows)
        ]

        total_scores = {
            row[0]: 0.0
            for row in rows
        }

        # Складываем оценки по всем критериям
        for score_list in scores:
            for url_id in total_scores:
                total_scores[url_id] += (
                    score_list.get(url_id, 0.0)
                )

        return total_scores

    # Получение URL по его идентификатору
    def geturlname(self, url_id):
        result = self.con.execute(
            """
            SELECT url
            FROM urllist
            WHERE rowid = ?
            """,
            (url_id,)
        ).fetchone()

        return result[0]

    # Выполнение поискового запроса
    def query(self, query):
        rows, word_ids = self.getmatchrows(query)

        if not rows:
            print("По запросу ничего не найдено.")
            return [], []

        scores = self.getscoredlist(rows)

        # Сортируем страницы
        # от самой высокой оценки к самой низкой
        ranked = sorted(
            scores.items(),
            key=lambda item: item[1],
            reverse=True
        )

        print("\nРезультаты поиска:")

        for score, url_id in [
            (score, url_id)
            for url_id, score in ranked[:10]
        ]:
            print(
                f"{score:.6f}\t"
                f"{self.geturlname(url_id)}"
            )

        # Возвращаем слова запроса
        # и идентификаторы найденных страниц
        return (
            word_ids,
            [
                url_id
                for url_id, _ in ranked[:10]
            ]
        )

    # Получение оценки страниц от нейронной сети
    def nnscore(self, rows, word_ids):
        # Получаем уникальные URL
        url_ids = list(
            dict.fromkeys(
                row[0] for row in rows
            )
        )

        # Получаем оценки нейронной сети
        nn_results = nn.mynet.getresult(
            word_ids,
            url_ids
        )

        scores = {
            url_ids[i]: nn_results[i]
            for i in range(len(url_ids))
        }

        return self.normalizescores(scores)


# Создание объекта поисковой системы