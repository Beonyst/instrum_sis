import re
import urllib.request
from urllib.parse import urljoin
import nn
import psycopg2 as pg
from bs4 import BeautifulSoup

from db_config import DATABASE_CONFIG


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


def get_connection():
    return pg.connect(**DATABASE_CONFIG)


class Crawler:

    def __init__(self, dbname=None):
        self.con = get_connection()

    def __del__(self):
        if hasattr(self, "con"):
            self.con.close()

    def dbcommit(self):
        self.con.commit()

    def getentryid(self, table, field, value):
        with self.con.cursor() as cur:
            cur.execute(
                f"""
                SELECT id
                FROM {table}
                WHERE {field} = %s
                """,
                (value,)
            )

            result = cur.fetchone()

            if result is not None:
                return result[0]

            cur.execute(
                f"""
                INSERT INTO {table}({field})
                VALUES (%s)
                RETURNING id
                """,
                (value,)
            )

            return cur.fetchone()[0]

    def addtoindex(self, url, soup):

        if self.isindexed(url):
            return

        print("Индексируется:", url)

        text = self.gettextonly(soup)
        words = self.separatewords(text)

        urlid = self.getentryid(
            "urllist",
            "url",
            url
        )

        for position, word in enumerate(words):

            if word in IGNORE_WORDS:
                continue

            wordid = self.getentryid(
                "wordlist",
                "word",
                word
            )

            with self.con.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO wordlocation
                    (urlid, wordid, location)
                    VALUES (%s, %s, %s)
                    """,
                    (urlid, wordid, position)
                )

    def gettextonly(self, soup):

        text = soup.string

        if text is not None:
            return str(text).strip()

        result = []

        for child in soup.contents:
            child_text = self.gettextonly(child)

            if child_text:
                result.append(child_text)

        return "\n".join(result)

    def separatewords(self, text):

        splitter = re.compile(r"\W+", re.UNICODE)

        return [
            word.lower()
            for word in splitter.split(text)
            if word
        ]

    def isindexed(self, url):

        with self.con.cursor() as cur:

            cur.execute(
                """
                SELECT id
                FROM urllist
                WHERE url = %s
                """,
                (url,)
            )

            result = cur.fetchone()

            if result is None:
                return False

            cur.execute(
                """
                SELECT id
                FROM wordlocation
                WHERE urlid = %s
                LIMIT 1
                """,
                (result[0],)
            )

            return cur.fetchone() is not None

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

        if from_id == to_id:
            return

        with self.con.cursor() as cur:

            cur.execute(
                """
                SELECT id
                FROM link
                WHERE fromid = %s
                  AND toid = %s
                """,
                (from_id, to_id)
            )

            existing_link = cur.fetchone()

            if existing_link is not None:
                return

            cur.execute(
                """
                INSERT INTO link(fromid, toid)
                VALUES (%s, %s)
                RETURNING id
                """,
                (from_id, to_id)
            )

            link_id = cur.fetchone()[0]

            for word in words:

                if word in IGNORE_WORDS:
                    continue

                word_id = self.getentryid(
                    "wordlist",
                    "word",
                    word
                )

                cur.execute(
                    """
                    INSERT INTO linkwords(wordid, linkid)
                    VALUES (%s, %s)
                    """,
                    (word_id, link_id)
                )

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

                soup = BeautifulSoup(
                    connection.read(),
                    "html.parser"
                )

                connection.close()

                self.addtoindex(
                    page,
                    soup
                )

                for link in soup("a"):

                    if "href" not in link.attrs:
                        continue

                    url = urljoin(
                        page,
                        link["href"]
                    )

                    if "'" in url:
                        continue

                    url = url.split("#")[0]

                    if (
                        url.startswith("http")
                        and not self.isindexed(url)
                    ):
                        new_pages.add(url)

                    link_text = self.gettextonly(link)

                    self.addlinkref(
                        page,
                        url,
                        link_text
                    )

                self.dbcommit()

            pages = new_pages

    def createindextables(self):

        with self.con.cursor() as cur:

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS urllist(
                    id SERIAL PRIMARY KEY,
                    url TEXT UNIQUE NOT NULL
                )
                """
            )

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS wordlist(
                    id SERIAL PRIMARY KEY,
                    word TEXT UNIQUE NOT NULL
                )
                """
            )

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS wordlocation(
                    id SERIAL PRIMARY KEY,
                    urlid INTEGER NOT NULL,
                    wordid INTEGER NOT NULL,
                    location INTEGER NOT NULL
                )
                """
            )

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS link(
                    id SERIAL PRIMARY KEY,
                    fromid INTEGER NOT NULL,
                    toid INTEGER NOT NULL
                )
                """
            )

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS linkwords(
                    id SERIAL PRIMARY KEY,
                    wordid INTEGER NOT NULL,
                    linkid INTEGER NOT NULL
                )
                """
            )

            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS wordidx
                ON wordlist(word)
                """
            )

            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS urlidx
                ON urllist(url)
                """
            )

            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS wordurlidx
                ON wordlocation(wordid)
                """
            )

            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS urltoidx
                ON link(toid)
                """
            )

            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS urlfromidx
                ON link(fromid)
                """
            )

        self.dbcommit()

    def calculatepagerank(self, iterations=20):

        with self.con.cursor() as cur:

            cur.execute(
                """
                DROP TABLE IF EXISTS pagerank
                """
            )

            cur.execute(
                """
                CREATE TABLE pagerank(
                    urlid INTEGER PRIMARY KEY,
                    score DOUBLE PRECISION
                )
                """
            )

            cur.execute(
                """
                INSERT INTO pagerank(urlid, score)
                SELECT id, 1.0
                FROM urllist
                """
            )

        self.dbcommit()

        for iteration in range(iterations):

            print(
                "Итерация PageRank:",
                iteration + 1
            )

            with self.con.cursor() as cur:

                cur.execute(
                    """
                    SELECT id
                    FROM urllist
                    """
                )

                url_ids = [
                    row[0]
                    for row in cur.fetchall()
                ]

                for url_id in url_ids:

                    page_rank = 0.15

                    cur.execute(
                        """
                        SELECT DISTINCT fromid
                        FROM link
                        WHERE toid = %s
                        """,
                        (url_id,)
                    )

                    linkers = cur.fetchall()

                    for (linker,) in linkers:

                        cur.execute(
                            """
                            SELECT score
                            FROM pagerank
                            WHERE urlid = %s
                            """,
                            (linker,)
                        )

                        linking_rank = cur.fetchone()

                        if linking_rank is None:
                            continue

                        linking_rank = linking_rank[0]

                        cur.execute(
                            """
                            SELECT COUNT(*)
                            FROM link
                            WHERE fromid = %s
                            """,
                            (linker,)
                        )

                        linking_count = cur.fetchone()[0]

                        if linking_count > 0:

                            page_rank += (
                                0.85
                                * linking_rank
                                / linking_count
                            )

                    cur.execute(
                        """
                        UPDATE pagerank
                        SET score = %s
                        WHERE urlid = %s
                        """,
                        (page_rank, url_id)
                    )

            self.dbcommit()


class Searcher:

    def __init__(self, dbname=None):
        self.con = get_connection()

    def __del__(self):
        if hasattr(self, "con"):
            self.con.close()

    def getmatchrows(self, query):

        words = query.split()

        if not words:
            return [], []

        word_ids = []
        tables = []
        conditions = []
        fields = []

        with self.con.cursor() as cur:

            for index, word in enumerate(words):

                cur.execute(
                    """
                    SELECT id
                    FROM wordlist
                    WHERE word = %s
                    """,
                    (word.lower(),)
                )

                result = cur.fetchone()

                if result is None:
                    continue

                word_id = result[0]

                word_ids.append(word_id)

                table_name = f"w{len(word_ids) - 1}"

                tables.append(
                    f"wordlocation {table_name}"
                )

                if len(word_ids) == 1:

                    fields.append(
                        f"{table_name}.urlid"
                    )

                else:

                    fields.append(
                        f"{table_name}.location"
                    )

                conditions.append(
                    f"{table_name}.wordid = {word_id}"
                )

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

        with self.con.cursor() as cur:

            cur.execute(query_sql)

            rows = list(
                cur.fetchall()
            )

        return rows, word_ids

    def normalizescores(
        self,
        scores,
        small_is_better=False
    ):

        if not scores:
            return {}

        small_value = 0.00001

        if small_is_better:

            min_score = min(
                scores.values()
            )

            return {
                url: min_score /
                max(small_value, score)
                for url, score in scores.items()
            }

        max_score = max(
            scores.values()
        )

        if max_score == 0:
            max_score = small_value

        return {
            url: score / max_score
            for url, score in scores.items()
        }

    def frequencyscore(self, rows):

        counts = {
            row[0]: 0
            for row in rows
        }

        for row in rows:
            counts[row[0]] += 1

        return self.normalizescores(
            counts
        )

    def locationscore(self, rows):

        locations = {
            row[0]: 1000000
            for row in rows
        }

        for row in rows:

            location = sum(
                row[1:]
            )

            if location < locations[row[0]]:
                locations[row[0]] = location

        return self.normalizescores(
            locations,
            small_is_better=True
        )

    def pagerankscore(self, rows):

        pageranks = {}

        for row in rows:

            url_id = row[0]

            with self.con.cursor() as cur:

                cur.execute(
                    """
                    SELECT score
                    FROM pagerank
                    WHERE urlid = %s
                    """,
                    (url_id,)
                )

                result = cur.fetchone()

            if result is not None:
                pageranks[url_id] = result[0]

        return self.normalizescores(
            pageranks
        )

    def getscoredlist(self, rows):

        if not rows:
            return {}

        scores = [
            self.frequencyscore(rows),
            self.locationscore(rows),
            self.pagerankscore(rows)
        ]

        total_scores = {
            row[0]: 0.0
            for row in rows
        }

        for score_list in scores:

            for url_id in total_scores:

                total_scores[url_id] += (
                    score_list.get(
                        url_id,
                        0.0
                    )
                )

        return total_scores

    def geturlname(self, url_id):

        with self.con.cursor() as cur:

            cur.execute(
                """
                SELECT url
                FROM urllist
                WHERE id = %s
                """,
                (url_id,)
            )

            result = cur.fetchone()

        if result is None:
            return None

        return result[0]

    def query(self, query):

        rows, word_ids = self.getmatchrows(
            query
        )

        if not rows:

            print(
                "По запросу ничего не найдено."
            )

            return [], []

        scores = self.getscoredlist(
            rows
        )

        ranked = sorted(
            scores.items(),
            key=lambda item: item[1],
            reverse=True
        )

        print(
            "\nРезультаты поиска:"
        )

        for url_id, score in ranked[:10]:

            print(
                f"{score:.6f}\t"
                f"{self.geturlname(url_id)}"
            )

        return (
            word_ids,
            [
                url_id
                for url_id, _ in ranked[:10]
            ]
        )

    def nnscore(self, rows, word_ids):

        url_ids = list(
            dict.fromkeys(
                row[0]
                for row in rows
            )
        )

        nn_results = nn.mynet.getresult(
            word_ids,
            url_ids
        )

        scores = {
            url_ids[i]: nn_results[i]
            for i in range(len(url_ids))
        }

        return self.normalizescores(
            scores
        )